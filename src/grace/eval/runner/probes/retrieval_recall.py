"""T025: evidence recall of the retrieval channels, routing and fusion on development data.

For every read task of a development split the probe

1. indexes the history's messages up to the end (BM25 and dense; chunks are messages, so every
   candidate is one unified evidence ID, a `message_id`), and searches at the read's version, so
   only messages `<= version` can be returned;
2. on a benchmark with a claim graph (`graph: gold`, the change sequences), plans the question
   with the T023 planner (rule templates, then the planner LLM when one is configured), runs the
   plan on the sequence's stored gold graph at the read version and maps the evidence of the
   answers to graph candidates (`context/pipeline/retrieval/graph.py`); without a graph the graph
   channel is unavailable;
3. keeps every channel's ranking up to `depth` and evaluates every condition of the experiment
   config (channel set, routing, fusion) at every cut-off with `total` set to that cut-off, by the
   same `Retriever` code GRACE uses, so a switched-off channel leaves the number of candidates
   unchanged.

The probe sees only visible records (question, version, messages) and, for the change sequences,
the gold claim graph that stands in for a perfect writer; it never sees gold evidence. Recall is
computed afterwards from the files of the run directory by `eval/analysis/metrics/retrieval.py`.

Model calls: message and query embeddings (call type `embed`, category `embedding`) and planner
calls (`plan`, `repair`), all through `grace.llm` and recorded in `calls.jsonl`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.index.bm25 import BM25Index
from grace.context.memory.index.chunking import chunk_message
from grace.context.memory.index.dense import DenseIndex
from grace.context.pipeline.query.planner import Planner, PlanningContext, run_plan
from grace.context.pipeline.query.rules import EntityInfo, PredicateInfo
from grace.context.pipeline.retrieval.candidates import CHANNELS, RetrievalCandidate
from grace.context.pipeline.retrieval.graph import graph_candidates
from grace.context.pipeline.retrieval.retrieve import RetrievalConfig, Retriever
from grace.context.pipeline.retrieval.text import BM25Channel, DenseChannel
from grace.llm.records import CallContext

# embed(texts, context) -> vectors in input order (wired to grace.llm.embeddings.EmbeddingClient)
Embed = Callable[[Sequence[str], CallContext], list[list[float]]]
SPEAKERS = ("user", "assistant")


@dataclass(frozen=True)
class Condition:
    name: str
    channels: tuple[str, ...]
    routing: str = "all"
    fusion: str = "rrf"
    backfill: bool = True

    @classmethod
    def from_dict(cls, name: str, raw: Mapping[str, Any]) -> Condition:
        if unknown := sorted(set(raw) - {"channels", "routing", "fusion", "backfill"}):
            raise ValueError(f"condition {name}: unknown keys {unknown}")
        return cls(name, tuple(raw["channels"]), raw.get("routing", "all"),
                   raw.get("fusion", "rrf"), bool(raw.get("backfill", True)))

    def config(self, base: RetrievalConfig, cutoff: int) -> RetrievalConfig:
        return replace(base, total=cutoff, depth=cutoff, channels=self.channels,
                       routing=self.routing, fusion=self.fusion, backfill=self.backfill)


# ---------------------------------------------------------------------------------------------
# Gold graphs of the change sequences (the graph channel's input; a perfect-writer stand-in)


@dataclass(frozen=True)
class GoldGraph:
    store: ClaimStore
    predicates: tuple[PredicateInfo, ...]
    entities: tuple[EntityInfo, ...]
    speakers: tuple[str, ...] = SPEAKERS


def _verb(ask: str) -> str | None:
    m = re.match(r"^(?:which|what|where)(?: [\w ]+?)? do I (.+?)\?$", ask, re.IGNORECASE)
    return m.group(1) if m else None


def changeseq_vocabulary(family, world: Mapping[str, Any]
                         ) -> tuple[tuple[PredicateInfo, ...], tuple[EntityInfo, ...]]:
    """The vocabulary fragment and entity table a GRACE read of a change sequence would show.

    The same construction as the T023 development check (`tests/integration/planner_dev.py`,
    `changeseq_vocabulary`), from the family definition and the sequence's `meta.json` world:
    predicate names, nouns and question verbs; people, task names and item labels. No answer is in
    it.
    """
    from grace.eval.datasets.changeseq.template_families import grammar

    preds = []
    for sp in (family.multi, family.exclusive):
        aliases = tuple(x for x in (sp.noun, _verb(sp.forms.get("ask_first", ""))) if x)
        preds.append(PredicateInfo(sp.predicate, sp.exclusive, aliases))
    for c in family.task.constraints:
        preds.append(PredicateInfo(c.predicate, family.is_exclusive(c.predicate),
                                   description=f"a requirement of the {family.task.noun}"))
    cat = family.task.catalogue
    preds.append(PredicateInfo(cat.predicate, True, (cat.noun,),
                               description="property of an option, stated by the assistant"))
    choice = grammar().choice_predicate
    preds.append(PredicateInfo(choice, False, ("option", "selected option"),
                               description=f"an option for a {family.task.noun}; offered, "
                                           "accepted or rejected"))
    ents = [EntityInfo("user", ("I", "me", "my"), "speaker"),
            EntityInfo("assistant", ("you",), "speaker"),
            EntityInfo(world["companion"], (world["companion"],), "person")]
    for k, name in sorted(world["tasks"].items()):
        ents.append(EntityInfo(k, (name, name.removeprefix("the ")), family.task.noun))
    for item_id, label in family.task.items:
        ents.append(EntityInfo(item_id, (label,), "option"))
    return tuple(preds), tuple(ents)


def load_gold_graphs(source_dir: Path, history_ids: Iterable[str]) -> dict[str, GoldGraph]:
    """Gold claim graph and vocabulary fragment of every named development sequence."""
    from grace.eval.datasets.changeseq.template_families import load_family

    dataset = json.loads((source_dir / "dataset.json").read_text(encoding="utf-8"))
    paths = {s["sequence_id"]: source_dir / s["path"] for s in dataset["sequences"]}
    out = {}
    for sid in history_ids:
        seq_dir = paths[sid]
        meta = json.loads((seq_dir / "meta.json").read_text(encoding="utf-8"))
        if meta["split"] != "development":
            raise ValueError(f"{sid} is in split {meta['split']!r}; development only")
        preds, ents = changeseq_vocabulary(load_family(meta["family"]), meta["world"])
        out[sid] = GoldGraph(ClaimStore.restore(seq_dir / "graph"), preds, ents)
    return out


# ---------------------------------------------------------------------------------------------
# One history


def _ranking_record(cands: Sequence[RetrievalCandidate]) -> list[list[Any]]:
    return [[c.evidence_id, round(c.score, 6)] for c in cands]


def _embed_messages(messages, embed: Embed, batch: int, history_id: str) -> DenseIndex:
    index = DenseIndex()
    chunks = [c for m in messages for c in chunk_message(m)]
    for start in range(0, len(chunks), batch):
        part = chunks[start:start + batch]
        context = CallContext("embed", "write", history_id, None, part[-1].version)
        vectors = embed([c.text for c in part], context)
        for chunk, vector in zip(part, vectors, strict=True):
            index.add(chunk, vector)
    return index


def probe_history(history_id: str, messages: Sequence, tasks: Sequence, *,
                  base: RetrievalConfig, conditions: Sequence[Condition],
                  cutoffs: Sequence[int], depth: int, embed: Embed | None, embed_batch: int,
                  graph: GoldGraph | None = None, planner: Planner | None = None,
                  benchmark: str) -> list[dict[str, Any]]:
    """One record per read task: channel rankings, plan, and the fused IDs of every condition."""
    messages = sorted(messages, key=lambda m: m.version)
    needs_dense = any("dense" in c.channels for c in conditions)
    bm25_index = BM25Index(base.bm25.get("k1", 1.5), base.bm25.get("b", 0.75))
    for m in messages:
        for chunk in chunk_message(m):
            bm25_index.add(chunk)
    bm25 = BM25Channel(bm25_index)
    dense = None
    if needs_dense:
        if embed is None:
            raise ValueError("a condition uses the dense channel but no embedder is configured")
        dense_index = _embed_messages(messages, embed, embed_batch, history_id)
    version_of = {m.message_id: m.version for m in messages}
    dates = {m.version: m.timestamp for m in messages}
    rows = []
    for task in tasks:
        query = task.question
        if needs_dense:
            def embed_query(text, task=task):
                context = CallContext("embed", "read", task.history_id, task.read_id,
                                      task.version)
                return embed([text], context)[0]
            dense = DenseChannel(dense_index, embed_query, base.dense.get("query_instruction"))
        rankings: dict[str, tuple[RetrievalCandidate, ...]] = {
            "bm25": tuple(bm25.search(query, task.version, depth))}
        if dense is not None:
            rankings["dense"] = tuple(dense.search(query, task.version, depth))
        plan_record, result = None, None
        if graph is not None and planner is not None:
            last = max((m.timestamp for m in messages if m.version <= task.version
                        and m.timestamp), default=None)
            ctx = PlanningContext.from_task(task, predicates=graph.predicates,
                                            entities=graph.entities, speakers=graph.speakers,
                                            last_message_date=last[:10] if last else None)
            plan = planner.plan(ctx)
            plan, result = run_plan(plan, graph.store, task.version, dates.get)
            plan_record = plan.to_record()
            plan_record["answers"] = None if result is None else len(result.answers)
            rankings["graph"] = tuple(graph_candidates(result, depth, version_of.get))
        graph_result = result if "graph" in rankings and result is not None else None
        out_conditions: dict[str, dict[str, Any]] = {}
        for cond in conditions:
            if "graph" in cond.channels and set(cond.channels) == {"graph"} and graph is None:
                continue
            per_cutoff = {}
            for cutoff in cutoffs:
                config = cond.config(base, cutoff)
                retriever = Retriever(config, bm25=bm25 if "bm25" in config.channels else None,
                                      dense=dense if "dense" in config.channels else None)
                res = retriever.retrieve(query, task.version, graph_result=graph_result,
                                         version_of=version_of.get, rankings=rankings)
                per_cutoff[str(cutoff)] = {"ids": list(res.evidence_ids),
                                           "route": res.route.to_record(),
                                           "backfilled": list(res.backfilled)}
            out_conditions[cond.name] = per_cutoff
        rows.append({
            "benchmark": benchmark, "split": task.split, "history_id": task.history_id,
            "read_id": task.read_id, "task_id": task.task_id, "version": task.version,
            "graph_available": graph_result is not None, "plan": plan_record,
            "rankings": {ch: _ranking_record(rankings[ch]) for ch in CHANNELS
                         if ch in rankings},
            "conditions": out_conditions})
    return rows
