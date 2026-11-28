"""GraceEngine: the one place that wires memory -> pipeline -> views (structure.md, D013; T026).

GRACE implements `context.api.ContextEngine` like every baseline, so the harness drives it through
the interface only. This module fixes the order of the steps; every step is a component handed in
at construction (`Components`), so a variant is a different component chosen by its engine config
(`configs/engines/*.yaml`), never a branch here (structure.md, "A variant replaces a component").

Write path (`write(message)`), plan 5.1-5.4:

1. `pipeline/update/` (T022): the `Updater` appends the message to the log (`memory/history/`) and
   extracts every complete unit into the claim graph (`memory/graph/`), one change set per
   committed version.
2. The message is indexed for the text channels (`memory/index/`: BM25, and dense when the
   retrieval config enables it; embedding calls go through the model port and are booked to W).
3. Views (`views/`, T018/T019): every committed change set goes to the staleness strategy (marks,
   eager maintenance) and resident views are materialised from the template families.

Read path (`read(task, budget)`), plan 5.3-5.6:

1. A read inside an open extraction unit flushes it first (write cost, trigger `read`).
2. `pipeline/query/` (T023): the planner turns the request into a plan (rule templates, then the
   planner LLM, one repair); the plan runs on the graph at the read version.
3. Views: the staleness strategy checks and repairs resident views (lazy rebuilds are booked to
   W); a resident view whose bound query equals the plan's query is a view hit, and its sentences
   are verified state. Without a hit, the query answers themselves are the state items.
4. `pipeline/retrieval/` (T025): routing and fusion over BM25, dense and the graph channel (the
   plan's query result).
5. `pipeline/assembly/` (T026): demand from the plan's variables, constraints from the read
   (version, the query's valid-time window and known-version cut-off), selection within the
   budget. A pending query expansion is served here, once: the open variables are planned and
   retrieved as one restricted query, and the assembler runs again with `retrieval_used=True`.

One extra retrieval per read (plan 5.6). The assembler's query expansion and the answering LLM's
`retrieve` output share one counter. The read trace carries `retrieval_used`; when it is True the
harness resolves a `retrieve` output as `unknown` and never calls `further_retrieval`; called
anyway, it retrieves nothing and returns the read's context.

Construction. `GraceEngine(components)` takes the components directly (tests, probes, oracles,
T027 variants built in code). The harness builds it from an engine config through the component
registry (`config/registry.py`) with `GraceEngine.from_port(model, **params)`, where `model` is
the harness's model port (`count_tokens`, `embed`, and `client`, the `grace.llm.ChatClient` of
the run, used by the planner and LLM rendering, and by the writer unless the port also has a
`writer_client`: the engine config's `writer_model`, E007 main configuration). Without a `client`
(the fake backend of tests and dry runs) the writer extracts nothing and the planner uses its rule
templates only.

Config params (`configs/engines/grace.yaml`): `writer`, `planner`, `retrieval`, `assembly`,
`views` (paths of the component configs, relative to the repository; `views: null` gives the empty
view component), `staleness` (strategy name and options of `views/staleness/`), `fragment`
(sizes of the vocabulary fragment shown to the planner).

Variants (T027). A config may replace components by name through `components` (resolved
lazily by `config/registry.py`, so this module imports no variant): `views` replaces the view
component factory (`views/serialise.py`, template serialisation), `extension` adds a per-history
extension (`Extension` below gives the interface and the defaults that change nothing): the
updater's `deferred` resolution log (`pipeline/update/deferred.py`, query-time resolution), the
extractor (`pipeline/update/slots.py`, the slot table of ablation B), the graph a read queries,
extra state facts for the assembler, and its own save and restore. Each factory is called with
the writer config, the chat client and the view config, plus its options from the config.

Traces. Every read returns `ReadTrace` with the fused candidates, the evidence shown, view hits,
staleness decisions, every call ID (flush, planner, view maintenance, embeddings), `utilisation`,
`expansions_used` and `retrieval_used`; `last_assembly` keeps the full assembly record of the
latest read for probes. Every write returns the write trace with stale marks and the change set of
the latest version it committed (see "Open issue" in the T026 log on several versions per write).
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from grace.config import registry
from grace.config.paths import REPO_ROOT
from grace.context import api
from grace.context.memory.graph.entries import Entity
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import load_vocabulary
from grace.context.memory.history.log import MessageLog
from grace.context.memory.index.bm25 import BM25Index
from grace.context.memory.index.chunking import chunk_message
from grace.context.memory.index.dense import DenseIndex
from grace.context.pipeline.assembly.assemble import Assembler, Assembly, AssemblyConfig
from grace.context.pipeline.assembly.demand import demand_of
from grace.context.pipeline.assembly.filter import Constraints
from grace.context.pipeline.assembly.items import Item, answer_items, message_item
from grace.context.pipeline.query.grammar import to_text
from grace.context.pipeline.query.ir import State
from grace.context.pipeline.query.planner import (
    Plan,
    Planner,
    PlannerConfig,
    PlanningContext,
    run_plan,
)
from grace.context.pipeline.query.rules import EntityInfo, PredicateInfo
from grace.context.pipeline.retrieval.retrieve import RetrievalConfig, Retriever
from grace.context.pipeline.retrieval.text import BM25Channel, DenseChannel
from grace.context.pipeline.update.extract import Extractor, NullExtractor
from grace.context.pipeline.update.updater import Updater, WriterConfig, llm_writer
from grace.context.views.render import LLMRenderer, TemplateRenderer
from grace.context.views.staleness import make_strategy
from grace.context.views.store import ViewStore
from grace.context.views.template_families import ViewConfig, load_view_config
from grace.llm.prompts import load_pinned

PROMPT_REGISTRY = REPO_ROOT / "configs" / "common" / "prompts.yaml"
SPEAKER_KIND = "speaker"
_WORD = re.compile(r"[a-z0-9]+")
_CAMEL = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
_DECISION = {"advance": ("fresh", "reuse"), "citation_repair": ("citation_stale", "patch"),
             "local_rebuild": ("answer_stale", "rebuild"),
             "full_rebuild": ("answer_stale", "rebuild")}

# embed(texts, trigger, history_id, version, read_id) -> (vectors, call IDs)
Embed = Callable[[Sequence[str], str, str, int, str | None],
                 tuple[list[list[float]], list[str]]]


# ---------------------------------------------------------------------------------------------
# Components


def _words(text: str) -> set[str]:
    split = " ".join(_CAMEL.findall(text)) or text
    return {w for w in _WORD.findall(split.lower()) if len(w) > 2}


@dataclass(frozen=True)
class VocabularyFragment:
    """The vocabulary fragment shown to the planner for one read (plan 5.6, "Query planning").

    The predicates used in the graph at the read version, ranked by word overlap with the
    request (camel case split), then by use; the entities ranked the same way by their IDs and
    labels, then by frequency; every speaker. At most `max_predicates` and `max_entities`.
    """

    max_predicates: int = 30
    max_entities: int = 30

    def select(self, request: str, store: ClaimStore, version: int, exclusive: Callable[[str],
               bool]) -> tuple[tuple[PredicateInfo, ...], tuple[EntityInfo, ...],
                               tuple[str, ...]]:
        state = store.state(min(version, store.head))
        q = _words(request)
        uses: Counter = Counter(c.predicate for c in state.claims.values())
        counts: Counter = Counter()
        for c in state.claims.values():
            counts[c.subject] += 1
            if isinstance(c.object, Entity):
                counts[c.object.id] += 1
        labels = state.entity_labels()
        speakers = tuple(dict.fromkeys(a.speaker for a in sorted(
            state.attributions.values(), key=lambda a: (a.version, a.attribution_id))))
        preds = sorted(uses, key=lambda p: (-len(q & _words(p)), -uses[p], p))
        predicates = tuple(PredicateInfo(p, exclusive(p)) for p in preds[:self.max_predicates])

        def names(e: str) -> tuple[str, ...]:
            label = labels.get(e)
            return (label,) if label and label != e else (e,)

        others = [e for e in counts if e not in speakers]
        ranked = sorted(others, key=lambda e: (-len(q & (_words(e) | _words(names(e)[0]))),
                                               -counts[e], e))
        entities = tuple([EntityInfo(s, names(s), SPEAKER_KIND) for s in speakers]
                         + [EntityInfo(e, names(e)) for e in ranked[:self.max_entities]])
        return predicates, entities, speakers


class Views:
    """The view component: resident view store plus a staleness strategy (T018, T019)."""

    def __init__(self, store: ViewStore, strategy_name: str, **options: Any):
        self.store = store
        self.strategy_name = strategy_name
        self.options = dict(options)
        self.strategy = make_strategy(strategy_name, store, **options)

    def on_commit(self, changeset, graph: ClaimStore) -> tuple[list[api.StaleMark], list[str]]:
        record = self.strategy.write(changeset, graph)
        calls = [c for e in record.maintenance for c in e.call_ids]
        start = len(self.store.events)
        self.store.materialise(graph, changeset.version)
        calls += [c for e in self.store.events[start:] for c in e.call_ids]
        marks = [api.StaleMark(m.view_id, self.strategy_name,
                               m.level if m.level in api.STALE_LEVELS else "unknown")
                 for m in record.marks]
        return marks, calls

    def on_read(self, graph: ClaimStore, version: int, read_id: str
                ) -> tuple[list[api.StalenessDecision], list[str]]:
        record = self.strategy.read(graph, version, read_id=read_id)
        decisions, calls = [], []
        for check in record.checks:
            calls += list(check.call_ids)
            if check.action in _DECISION:
                decision, action = _DECISION[check.action]
                decisions.append(api.StalenessDecision(check.view_id, self.strategy_name,
                                                       decision, action))
        return decisions, calls

    def hit(self, plan: Plan):
        """The resident view whose bound query is the plan's query, or None."""
        if not plan.view_eligible:
            return None
        text = to_text(plan.query)
        for view in self.store.views():
            if to_text(view.query) == text:
                return view
        return None

    def save(self, directory: Path) -> list[Path]:
        return self.store.save(directory)

    def restore(self, directory: Path, graph: ClaimStore) -> None:
        self.store = ViewStore.restore(directory, self.store.history_id, self.store.renderer,
                                       config=self.store.config, families=self.store.families,
                                       vocabulary=self.store.vocabulary)
        self.strategy = make_strategy(self.strategy_name, self.store, **self.options)
        self.strategy.prime(graph.changesets())


class NoViews:
    """The empty view component ("no views" variant): no marks, no decisions, no hits."""

    def on_commit(self, changeset, graph):
        return [], []

    def on_read(self, graph, version, read_id):
        return [], []

    def hit(self, plan):
        return None

    def save(self, directory: Path) -> list[Path]:
        return []

    def restore(self, directory: Path, graph: ClaimStore) -> None:
        pass


class Extension:
    """Per-history hooks of a variant; these defaults leave GRACE unchanged. A variant's
    extension (registered in `config/registry.py`) provides the same attributes."""

    deferred = None  # a `deferred.ResolutionLog`: the updater commits no supersession

    def extractor(self, default: Extractor) -> Extractor:
        return default

    def read_graph(self, store: ClaimStore, version: int) -> ClaimStore:
        """The graph the read path queries at `version` (default: the stored graph)."""
        return store

    def state_facts(self, task: api.ReadTask, request: str) -> list:
        """Extra state items: objects with `item_id`, `text`, `evidence_ids`, `version`, `valid`
        and optionally `retired` (the version from which the fact is superseded)."""
        return []

    def save(self, directory: Path) -> list[Path]:
        return []

    def restore(self, directory: Path) -> None:
        pass


def _no_extension(history: api.HistoryInfo) -> Extension:
    return Extension()


@dataclass
class Components:
    """Everything GraceEngine composes; `views(history, vocabulary)` builds the view component
    of one history and `extractor(history)` its writer."""

    count: Callable[[str], int]
    extractor: Callable[[api.HistoryInfo], Extractor]
    planner: Planner
    retrieval: RetrievalConfig
    assembly: AssemblyConfig
    views: Callable[[api.HistoryInfo, Any], Views | NoViews]
    writer: WriterConfig = field(default_factory=WriterConfig)
    fragment: VocabularyFragment = field(default_factory=VocabularyFragment)
    embed: Embed | None = None
    counter_name: str = "unnamed"
    no_client: bool = False  # built without a chat client (dry run; see `from_port`)
    extension: Callable[[api.HistoryInfo], Any] = _no_extension


# ---------------------------------------------------------------------------------------------
# The engine


@dataclass
class _ReadState:
    plan: Plan
    items: list[Item]
    candidates: list[api.Candidate]
    call_ids: list[str]
    decisions: list[api.StalenessDecision]
    hits: list[str]
    constraints: Constraints
    assembly: Assembly
    graph: ClaimStore


class GraceEngine(api.ContextEngine):
    """GRACE (plan section 5); see the module docstring."""

    kind = "grace"

    def __init__(self, components: Components):
        self.c = components
        self.history: api.HistoryInfo | None = None
        self.log: MessageLog | None = None
        self.store: ClaimStore | None = None
        self.updater: Updater | None = None
        self.bm25 = BM25Index(components.retrieval.bm25.get("k1", 1.5),
                              components.retrieval.bm25.get("b", 0.75))
        self.dense = DenseIndex() if self._dense_on() else None
        self.views: Views | NoViews | None = None
        self.extension: Any = None
        self._reads: dict[str, _ReadState] = {}
        self.last_assembly: Assembly | None = None

    # -- construction from a config ------------------------------------------------------------

    @staticmethod
    def _configs(writer: str | None, planner: str | None, views: str | None,
                 seed: int | None) -> tuple[WriterConfig, PlannerConfig, ViewConfig | None]:
        """The writer, planner and view configs with the run's seed in every decoding."""
        writer_config = WriterConfig.load(REPO_ROOT / writer) if writer else WriterConfig.load()
        planner_config = (PlannerConfig.load(REPO_ROOT / planner) if planner
                          else PlannerConfig.load())
        view_config = load_view_config(REPO_ROOT / views) if views else None
        if seed is not None:
            writer_config = replace(writer_config, decoding={**writer_config.decoding,
                                                             "seed": seed})
            planner_config = replace(planner_config, decoding={**planner_config.decoding,
                                                               "seed": seed})
            if view_config is not None:
                view_config = replace(view_config, rendering=replace(
                    view_config.rendering,
                    decoding={**view_config.rendering.decoding, "seed": seed}))
        return writer_config, planner_config, view_config

    @classmethod
    def resolved_settings(cls, params: Mapping[str, Any], seed: int | None, *,
                          allow_no_client: bool = False) -> dict[str, Any]:
        """What the engine's own model calls use, for the run's resolved config: the decoding
        (with seed) of the writer, the planner and view rendering, and whether the engine ran
        without a chat client (a dry run: no extraction, rule-only planner, template views)."""
        writer, planner, views = cls._configs(params.get("writer"), params.get("planner"),
                                              params.get("views", "configs/views/default.yaml"),
                                              seed)
        return {"writer_decoding": dict(writer.decoding),
                "planner_decoding": dict(planner.decoding),
                "rendering": ({"mode": views.rendering.mode,
                               "decoding": dict(views.rendering.decoding)}
                              if views is not None else None),
                "allow_no_client": allow_no_client}

    @classmethod
    def from_port(cls, model: Any, *, writer: str | None = None, planner: str | None = None,
                  retrieval: str = "configs/retrieval/default.yaml",
                  assembly: str = "configs/assembly/default.yaml",
                  views: str | None = "configs/views/default.yaml",
                  staleness: Mapping[str, Any] | None = None,
                  fragment: Mapping[str, int] | None = None,
                  components: Mapping[str, Mapping[str, Any]] | None = None,
                  allow_no_client: bool = False) -> GraceEngine:
        """Build from the harness's model port and the params of an engine config.

        The writer, the planner and LLM rendering need the run's chat client (`model.client`);
        without it construction fails unless `allow_no_client` is set (dry runs and tests only;
        the harness records the flag in the resolved config). The client is wrapped so that every
        prompt the engine sends is also recorded in the port's `observed` list (gold-sentinel
        audit), and the run's seed (`model.decoding["seed"]`) is put into every decoding."""
        client = getattr(model, "client", None)
        if client is None and not allow_no_client:
            raise ValueError("GraceEngine needs the run's chat client (model.client) for the "
                             "writer and the planner; allow_no_client=True is for dry runs only")
        if client is not None:
            client = ObservedClient(client, getattr(model, "observe", None))
        # The writer's own client when the run's port has one (engine config `writer_model`);
        # the planner and LLM rendering stay on the run's client.
        writer_client = getattr(model, "writer_client", None)
        writer_client = (ObservedClient(writer_client, getattr(model, "observe", None))
                         if writer_client is not None and client is not None else client)
        seed = (getattr(model, "decoding", None) or {}).get("seed")
        writer_config, planner_config, view_config = cls._configs(writer, planner, views, seed)
        staleness = dict(staleness or {"strategy": "push_confirm", "local_filters": True})
        strategy = staleness.pop("strategy")
        no_client = client is None

        def make_views(history: api.HistoryInfo, vocabulary) -> Views | NoViews:
            if view_config is None:
                return NoViews()
            return Views(ViewStore(history.history_id, _renderer(view_config, client),
                                   config=view_config, vocabulary=vocabulary),
                         strategy, **staleness)

        def make_extractor(history: api.HistoryInfo) -> Extractor:
            if client is None:
                return NullExtractor()
            return llm_writer(writer_config, writer_client, history)

        extension = _no_extension
        for slot, spec in (components or {}).items():
            spec = dict(spec)
            factory = registry.load_component(spec.pop("factory"))
            # an extension replaces or extends the writer side (slot writer, deferred
            # resolution): it gets the writer's client; a views factory gets the run's
            built = factory(writer=writer_config,
                            client=writer_client if slot == "extension" else client,
                            view_config=view_config, **spec)
            if slot == "views":
                make_views = built
            elif slot == "extension":
                extension = built
            else:
                raise ValueError(f"unknown component slot {slot!r}; expected views or extension")

        embed = None
        if hasattr(model, "embed"):
            def embed(texts, trigger, history_id, version, read_id):
                result = model.embed(list(texts), _Tag("embed", trigger, history_id, version,
                                                       read_id))
                return [list(v) for v in result.vectors], list(result.call_ids)
        return cls(Components(
            count=model.count_tokens, extractor=make_extractor,
            planner=Planner(planner_config, client),
            retrieval=RetrievalConfig.load(REPO_ROOT / retrieval),
            assembly=AssemblyConfig.load(REPO_ROOT / assembly), views=make_views,
            writer=writer_config, fragment=VocabularyFragment(**dict(fragment or {})),
            embed=embed, counter_name=getattr(model, "model", "model port"),
            no_client=no_client, extension=extension))

    # -- life cycle ----------------------------------------------------------------------------

    def open(self, history: api.HistoryInfo) -> None:
        if self.history is not None:
            raise RuntimeError("engine already holds a history; use one instance per history")
        self.history = history
        self.log = MessageLog(history.history_id)
        self.store = ClaimStore(history.history_id)
        self.extension = self.c.extension(history)
        self._make_updater(history)
        self.views = self.c.views(history, self.updater.vocabulary.current)

    def _make_updater(self, history: api.HistoryInfo) -> None:
        self.updater = Updater(history, self.log, self.store,
                               self.extension.extractor(self.c.extractor(history)),
                               self.c.writer, vocabulary=load_vocabulary(),
                               deferred=self.extension.deferred)

    @property
    def version(self) -> int:
        return self.log.head if self.log is not None else 0

    def write(self, message: api.Message) -> api.WriteResult:
        history = self._history()
        if message.history_id != history.history_id:
            raise ValueError(f"message of history {message.history_id!r} written to "
                             f"{history.history_id!r}")
        if message.version != self.version + 1:
            raise ValueError(f"expected version {self.version + 1}, got {message.version}")
        start = time.perf_counter()
        results = self.updater.write(message)
        timings = {"update": (time.perf_counter() - start) * 1000}
        call_ids = [c for r in results for c in r.call_ids]
        start = time.perf_counter()
        call_ids += self._index(message)
        timings["index"] = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        marks, view_calls, changeset = self._commit_views(results)
        timings["views"] = (time.perf_counter() - start) * 1000
        trace = api.WriteTrace(history.history_id, message.version, (message.message_id,),
                               tuple(call_ids + view_calls), tuple(marks), timings)
        return api.WriteResult(trace, changeset)

    def read(self, task: api.ReadTask, budget_tokens: int | None) -> api.ReadResult:
        self._check_task(task)
        start = time.perf_counter()
        timings: dict[str, float] = {}
        call_ids: list[str] = []
        flushed = self.updater.flush(task.version, task.read_id)
        call_ids += [c for r in flushed for c in r.call_ids]
        marks_calls = self._commit_views(flushed)[1]
        call_ids += marks_calls
        timings["flush"] = (time.perf_counter() - start) * 1000

        t = time.perf_counter()
        graph = self.extension.read_graph(self.store, task.version)
        request = _request(task)
        plan, result = self._plan(task, request, graph)
        call_ids += list(plan.call_ids)
        timings["query"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        decisions, view_calls = self.views.on_read(graph, task.version, task.read_id)
        call_ids += view_calls
        state_items, hits = self._state_items(task, plan, result, graph)
        state_items += self._facts(task, request, len(state_items) + 1)
        timings["views"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        text_items, candidates, embed_calls = self._retrieve(task, request, result,
                                                             len(state_items) + 1)
        call_ids += embed_calls
        timings["retrieval"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        items = state_items + text_items
        constraints = _constraints(task, plan)
        demand = demand_of(request, plan.variables)
        assembler = self._assembler()
        # No assembler query for a fallback plan: it would re-query the request (E013 diagnosis).
        assembly = assembler.assemble(task, demand, items, budget_tokens, constraints,
                                      query_expansion=plan.route != "fallback")
        if assembly.pending is not None:
            extra_plan, extra_result = self._plan(task, assembly.pending.query, graph)
            call_ids += list(extra_plan.call_ids)
            more_state, _ = self._state_items(task, extra_plan, extra_result, graph, prefix="x")
            more_text, more_cands, more_calls = self._retrieve(
                task, assembly.pending.query, extra_result, len(items) + len(more_state) + 1)
            call_ids += more_calls
            items = items + more_state + more_text
            candidates += more_cands
            assembly = assembler.assemble(task, demand, items, budget_tokens, constraints,
                                          expansions_used=assembly.expansions_used,
                                          retrieval_used=True)
        timings["assembly"] = (time.perf_counter() - t) * 1000
        self._reads[task.read_id] = _ReadState(plan, items, candidates, call_ids, decisions,
                                               hits, constraints, assembly, graph)
        return self._result(task, assembly, candidates, call_ids, decisions, hits, timings,
                            further=False)

    def further_retrieval(self, task: api.ReadTask, request: str,
                          budget_tokens: int | None) -> api.ReadResult:
        self._check_task(task)
        state = self._reads.get(task.read_id)
        if state is None:
            raise RuntimeError(f"further_retrieval of {task.read_id} before its read")
        if state.assembly.retrieval_used:
            # The read's one extra retrieval is spent (plan 5.6): nothing more is retrieved; the
            # context of the read is returned unchanged (the harness does not call this then).
            return self._result(task, state.assembly, state.candidates, [],
                                state.decisions, state.hits, {}, further=True)
        start = time.perf_counter()
        call_ids: list[str] = []  # only the calls of this step; the read's are in its trace
        extra_plan, extra_result = self._plan(task, request, state.graph)
        call_ids += list(extra_plan.call_ids)
        more_state, _ = self._state_items(task, extra_plan, extra_result, state.graph,
                                          prefix="r")
        more_text, more_cands, more_calls = self._retrieve(task, request, extra_result, 1)
        call_ids += more_calls
        items = more_state + more_text + [i for i in state.items if i.item_id not in
                                          {m.item_id for m in more_state + more_text}]
        assembly = self._assembler().assemble(
            task, demand_of(_request(task), state.plan.variables), items, budget_tokens,
            state.constraints, expansions_used=state.assembly.expansions_used,
            retrieval_used=True)
        timings = {"further_retrieval": (time.perf_counter() - start) * 1000}
        return self._result(task, assembly, more_cands + state.candidates, call_ids,
                            state.decisions, state.hits, timings, further=True)

    def end_read(self, task: api.ReadTask) -> None:
        self._reads.pop(task.read_id, None)

    def save(self, directory: Path) -> list[Path]:
        directory = Path(directory)
        files = [self.log.save(directory / "log"), *self.store.save(directory / "store"),
                 self.updater.save(directory / "writer")]
        files += self.views.save(directory / "views")
        files += self.extension.save(directory / "extension")
        if self.dense is not None:
            path = directory / "dense.json"
            path.write_text(json.dumps({"chunks": [c.chunk_id for c in self.dense.chunks],
                                        "vectors": self.dense.vectors()}), encoding="utf-8")
            files.append(path)
        meta = directory / "engine.json"
        meta.write_text(json.dumps({"kind": self.kind, "history": self.history.to_record(),
                                    "version": self.version}, sort_keys=True), encoding="utf-8")
        return [*files, meta]

    def restore(self, directory: Path) -> None:
        if self.history is not None:
            raise RuntimeError("restore needs a fresh engine")
        directory = Path(directory)
        meta = json.loads((directory / "engine.json").read_text(encoding="utf-8"))
        if meta["kind"] != self.kind:
            raise ValueError(f"snapshot of {meta['kind']!r} cannot restore {self.kind!r}")
        history = api.HistoryInfo.from_record(meta["history"])
        self.history = history
        self.log = MessageLog.restore(directory / "log", history.history_id)
        self.store = ClaimStore.restore(directory / "store")
        self.extension = self.c.extension(history)
        if (directory / "extension").exists():
            self.extension.restore(directory / "extension")
        self._make_updater(history)
        self.updater.restore_state(directory / "writer")
        self.views = self.c.views(history, self.updater.vocabulary.current)
        if (directory / "views").exists():
            self.views.restore(directory / "views", self.store)
        vectors = {}
        if self.dense is not None:
            saved = json.loads((directory / "dense.json").read_text(encoding="utf-8"))
            vectors = dict(zip(saved["chunks"], saved["vectors"], strict=True))
        for message in self.log.messages():
            for chunk in chunk_message(message):
                self.bm25.add(chunk)
                if self.dense is not None:
                    self.dense.add(chunk, vectors[chunk.chunk_id])

    # -- steps ---------------------------------------------------------------------------------

    def _dense_on(self) -> bool:
        return "dense" in self.c.retrieval.channels

    def _index(self, message: api.Message) -> list[str]:
        chunks = chunk_message(message)
        for chunk in chunks:
            self.bm25.add(chunk)
        if self.dense is None:
            return []
        if self.c.embed is None:
            raise RuntimeError("the retrieval config enables dense, but no embedder is given")
        vectors, call_ids = self.c.embed([c.text for c in chunks], "write",
                                         message.history_id, message.version, None)
        for chunk, vector in zip(chunks, vectors, strict=True):
            self.dense.add(chunk, vector)
        return call_ids

    def _commit_views(self, results) -> tuple[list[api.StaleMark], list[str], Mapping | None]:
        marks: list[api.StaleMark] = []
        calls: list[str] = []
        last = None
        for result in results:
            for changeset in result.changesets:
                m, c = self.views.on_commit(changeset, self.store)
                marks += m
                calls += c
                last = changeset
        return marks, calls, (last.to_record() if last is not None else None)

    def _plan(self, task: api.ReadTask, request: str, graph: ClaimStore):
        last = None
        for m in reversed(self.log.messages(task.version)):
            when = _message_time(m, self.history)
            if when:
                last = when[:10]
                break
        predicates, entities, speakers = self.c.fragment.select(
            request, graph, task.version, self._exclusive)
        ctx = PlanningContext(task.history_id, task.read_id, task.version, request,
                              task.asked_at[:10] if task.asked_at else last, predicates,
                              entities, speakers, task.kind)
        plan = self.c.planner.plan(ctx)
        return run_plan(plan, graph, task.version, self._version_date)

    def _facts(self, task: api.ReadTask, request: str, rank_start: int) -> list[Item]:
        """State facts of the extension (e.g. slot values) as state items."""
        return [Item(f.item_id, "claim", f.text, tuple(f.evidence_ids), version=f.version,
                     retired=getattr(f, "retired", None), valid=f.valid, rank=rank_start + i)
                for i, f in enumerate(self.extension.state_facts(task, request))]

    def _state_items(self, task, plan: Plan, result, graph: ClaimStore, prefix: str = "q"
                     ) -> tuple[list[Item], list[str]]:
        view = self.views.hit(plan)
        if view is not None:
            covers = frozenset(view.columns)
            items = [Item(f"{view.view_id}#{i}", "view", s.text, tuple(s.evidence), (),
                          version=view.cutoff, rank=i + 1, covers=covers)
                     for i, s in enumerate(view.sentences) if s.text and s.evidence]
            return items, [view.view_id]
        if result is None:
            return [], []
        state = graph.state(task.version)
        versions = {m.message_id: m.version for m in self.log.messages(task.version)}

        def stamp(entry: str) -> int | None:
            e = state.claims.get(entry) or state.attributions.get(entry)
            return e.version if e is not None else None

        def retired(claim: str) -> int | None:
            ends = [s.version for s in state.supersessions_of(claim)]
            return min(ends) if ends else None
        return answer_items(result, prefix=f"{task.read_id}:{prefix}", version_of=versions.get,
                            stamp_of=stamp, retired_of=retired), []

    def _retrieve(self, task, query: str, graph_result, rank_start: int):
        config = self.c.retrieval
        dense, calls = None, []
        if self.dense is not None:
            def embed_query(text: str) -> list[float]:
                vectors, ids = self.c.embed([text], "read", task.history_id, task.version,
                                            task.read_id)
                calls.extend(ids)
                return vectors[0]
            dense = DenseChannel(self.dense, embed_query, config.dense.get("query_instruction"))
        retriever = Retriever(config, bm25=BM25Channel(self.bm25) if "bm25" in config.channels
                              else None, dense=dense)
        versions = {m.message_id: m.version for m in self.log.messages(task.version)}
        result = retriever.retrieve(query, task.version, graph_result=graph_result,
                                    version_of=versions.get)
        items = [message_item(self.log.by_id(c.evidence_id, task.version),
                              rank=rank_start + i, history=self.history)
                 for i, c in enumerate(result.fused)]
        return items, result.trace_candidates(), calls

    def _assembler(self) -> Assembler:
        return Assembler(self.c.assembly, self.c.count, log=self.log, history=self.history,
                         counter_name=self.c.counter_name)

    def _result(self, task, assembly: Assembly, candidates, call_ids, decisions, hits, timings,
                *, further: bool) -> api.ReadResult:
        self.last_assembly = assembly
        context = assembly.context
        shown = {f.fragment_id.split("#")[0] for f in context.fragments}
        trace = api.read_trace(context, candidates=candidates, further_retrieval=further,
                               call_ids=list(dict.fromkeys(call_ids)), timings_ms=timings,
                               view_hits=[h for h in hits if h in shown],
                               staleness_decisions=decisions,
                               retrieval_used=assembly.retrieval_used,
                               expansions_used=assembly.expansions_used)
        return api.ReadResult(context, trace)

    def _exclusive(self, predicate: str) -> bool:
        predicates = self.updater.vocabulary.current.predicates
        return predicates[predicate].exclusive if predicate in predicates else False

    def _version_date(self, version: int) -> str | None:
        if not 1 <= version <= self.log.head:
            return None
        return _message_time(self.log.get(version), self.history)

    def _check_task(self, task: api.ReadTask) -> None:
        history = self._history()
        if task.history_id != history.history_id:
            raise ValueError(f"read of history {task.history_id!r} sent to "
                             f"{history.history_id!r}")
        api.check_read(self, task)

    def _history(self) -> api.HistoryInfo:
        if self.history is None:
            raise RuntimeError("open() or restore() first")
        return self.history


# ---------------------------------------------------------------------------------------------
# Helpers


class ObservedClient:
    """A `grace.llm` chat client whose prompts are also handed to `observe` (the harness port's
    record of every text sent to a model, audited by the gold-sentinel test); every other
    attribute is the wrapped client's."""

    def __init__(self, client: Any, observe: Callable[[Sequence[str]], None] | None):
        self._client, self._observe = client, observe

    def chat(self, messages, context, **kwargs):
        if self._observe is not None:
            self._observe([m["content"] for m in messages])
        return self._client.chat(messages, context, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


@dataclass(frozen=True)
class _Tag:
    """The call tag the harness's model port expects (fields of its `CallTag`)."""

    call_type: str
    trigger: str
    history_id: str | None
    version: int | None
    read_id: str | None = None


def _renderer(config: ViewConfig, client):
    if config.rendering.mode != "llm" or client is None:
        return TemplateRenderer()
    return LLMRenderer(client, load_pinned(config.rendering.prompt, PROMPT_REGISTRY),
                       dict(config.rendering.decoding),
                       max_rows_per_call=config.rendering.max_rows_per_call)


def _message_time(message: api.Message, history: api.HistoryInfo | None) -> str | None:
    if message.timestamp or history is None:
        return message.timestamp
    segment = history.segment(message.segment_id)
    return segment.timestamp if segment else None


def _request(task: api.ReadTask) -> str:
    if task.kind == "question":
        return task.question
    return f"State request: report the current state for {task.state_schema}"


def _constraints(task: api.ReadTask, plan: Plan) -> Constraints:
    """Read constraints: the read version; the plan's valid-time window; `current_only` unless
    the query reads an earlier knowledge version (`AT known=r0`, r0 < version) or historical
    state, so time-travel reads are not dropped as retired."""
    query = plan.query
    current = True
    if query is not None:
        at = query.at
        if (at.known is not None and at.known < task.version) or at.state != State.CURRENT:
            current = False
    window = (plan.window.start, plan.window.end) if plan.window is not None else None
    return Constraints(version=task.version, valid=window, current_only=current)


__all__ = ["Components", "Extension", "GraceEngine", "NoViews", "Views", "VocabularyFragment"]
