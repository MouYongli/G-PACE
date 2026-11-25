"""Generate, check and write change sequences and their dataset manifest (design section 9).

`generate_sequence` runs the whole pipeline for one sequence and refuses to return a sequence that
fails any check:

- the event log satisfies G1-G8 (`events.check_log`);
- every macro realises its intended change type on its focus binding;
- the type / outcome cross-table of design section 4.2 holds for every (message, binding);
- the gold graph commits to a T014 store and conforms to the T014 SHACL shapes (`gold.py`);
- the views re-evaluated on the gold graph at every version agree with the event-log reference
  (`regraph.py`, T015 acceptance item 3);
- every rendered message passes the renderer's output checks.

`write_sequence` writes one directory per sequence; `build_dataset` writes a set of sequences from
a dataset config with `dataset.json` and `MANIFEST.sha256`. Only `messages.jsonl` and the question
texts are visible to systems; every other file is gold.

- `messages.jsonl`: message ID, version, episode, speaker, timestamp, text;
- `events.jsonl`: the event log (primitive events per message, macro ID, intended type, focus
  binding, render cue);
- `graph/`: the gold claim graph as a T014 store snapshot (`store.json`, `changesets.jsonl` with
  the version-stamped entries, `graph.nt`);
- `bindings.jsonl`, `reference.jsonl`: every binding; canonical (ans, wit, ev) and fingerprints at
  each version where they change;
- `labels.jsonl`: answer-stale, citation-stale, change type and C7 sub-kinds per (message,
  binding);
- `schedules/<name>.jsonl`: the questions of one read schedule with gold answers, witnesses and
  labels;
- `meta.json`: family, split, cell, seeds, generator SHA, renderer, counts, checks, checksums;
- `render_log.jsonl`: attempts, check failures and fallbacks per message.

`dataset.json` records the renderer (for the model renderer: model, exact snapshot, tokenizer pins,
prompt and its hash, decoding and serving flags) and the render statistics per family: messages,
attempts, fallbacks, fallback rate and whether it exceeds the grammar's `fallback_rate_limit`.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grace.context.memory.graph.store import ClaimStore
from grace.eval.datasets.changeseq import gold as gold_graph
from grace.eval.datasets.changeseq import regraph
from grace.eval.datasets.changeseq.events import check_log
from grace.eval.datasets.changeseq.generate import PlannedSequence, plan_sequence
from grace.eval.datasets.changeseq.invalidation import (
    DerivedState,
    GoldStaleness,
    check_invariants,
    gold_staleness,
)
from grace.eval.datasets.changeseq.render import RenderOutcome, TemplateRenderer, render_messages
from grace.eval.datasets.changeseq.schedule import Schedule, build_schedules
from grace.eval.datasets.changeseq.template_families import (
    CellConfig,
    FamilyError,
    grammar,
    load_family,
    load_split,
)

ROLE = {"user": "user", "assistant": "agent"}
# Version of the generator's output conventions, recorded in meta.json and dataset.json so that
# datasets of different conventions are told apart. 2: the V3 count witness is one union witness
# (plan 3.4), not one witness set per member; the model renderer of D006 exists.
GENERATOR_VERSION = "changeseq-generator-2"


class GenerationError(RuntimeError):
    """A generated sequence failed one of the checks; the message lists the failures."""


@dataclass
class SequenceBundle:
    plan: PlannedSequence
    gold: GoldStaleness
    store: ClaimStore
    rendered: RenderOutcome
    schedules: list[Schedule]
    checks: dict[str, Any]
    renderer: dict[str, Any]


def sequence_seed(master_seed: int | str, sequence_id: str) -> int:
    return int(hashlib.sha256(f"{master_seed}:{sequence_id}".encode()).hexdigest(), 16) % 2**31


def focus_mismatches(plan: PlannedSequence, gold: GoldStaleness) -> list[str]:
    kinds = {(x["version"], x["binding_id"]): x["change_type"] for x in gold.labels}
    out = []
    for r in plan.log:
        if r.macro and kinds[(r.version, r.macro.focus)] != r.macro.intended_type:
            out.append(f"t={r.version} {r.macro.name} on {r.macro.focus}: intended "
                       f"{r.macro.intended_type}, realised {kinds[(r.version, r.macro.focus)]}")
    return out


def generate_sequence(family_id: str, cell: CellConfig, seed: int, sequence_id: str,
                      renderer=None, validate: str = "graph") -> SequenceBundle:
    renderer = renderer or TemplateRenderer()
    family = load_family(family_id)
    plan = plan_sequence(family, cell, seed, sequence_id)
    world = plan.world
    exclusive = {p for p in family.predicate_names() if family.is_exclusive(p)}
    failures: dict[str, list[str]] = {
        "well_formedness": check_log(plan.log, world.authority, exclusive,
                                     world.catalogue_predicate, world.choice_predicate)}
    gold = gold_staleness(plan.log, world, plan.bindings())
    failures["focus_types"] = focus_mismatches(plan, gold)
    failures["invariants"] = check_invariants(gold)
    try:
        store = gold_graph.build_store(plan.log, sequence_id, validate=validate)
        failures["gold_graph"] = []
    except gold_graph.GoldGraphError as exc:
        raise GenerationError(f"{sequence_id}: {exc}") from exc
    failures["graph_reevaluation"] = regraph.disagreements(store, plan.bindings(), world,
                                                           gold.values)
    rendered = render_messages(plan.log, family, renderer, sequence_id, seed)
    failures["render_checks"] = [f"t={x['version']}: {x['final_failures']}"
                                 for x in rendered.log if x["final_failures"]]
    if any(failures.values()):
        detail = "; ".join(f"{k}: {len(v)} (e.g. {v[:3]})" for k, v in failures.items() if v)
        raise GenerationError(f"{sequence_id}: {detail}")
    schedules = build_schedules(plan, gold, DerivedState(plan.log, world), renderer)
    checks = {k: "passed" for k in failures}
    checks["gold_graph"] = f"passed (SHACL, {validate})"
    return SequenceBundle(plan, gold, store, rendered, schedules, checks, describe(renderer))


TEMPLATE_RECORD = {"name": "template-v1", "kind": "template", "snapshot": None,
                   "note": "deterministic development/test renderer; not the paper's renderer"}


def describe(renderer) -> dict[str, Any]:
    """Renderer record of `meta.json` and `dataset.json`."""
    if renderer.kind == "template":
        return {**TEMPLATE_RECORD, "name": renderer.name}
    return renderer.describe()


def _jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sequence(bundle: SequenceBundle, out_dir: Path, *, split: str, code_sha: str,
                   master_seed: int | str) -> dict[str, Any]:
    """Write one sequence directory; return its `meta.json` content."""
    plan = bundle.plan
    out_dir.mkdir(parents=True, exist_ok=False)
    _jsonl(out_dir / "messages.jsonl", (
        {"message_id": m.record.message_id, "version": m.record.version,
         "episode": m.record.episode, "speaker": m.record.speaker, "role": ROLE[m.record.speaker],
         "timestamp": m.record.timestamp, "text": m.text} for m in bundle.rendered.messages))
    _jsonl(out_dir / "events.jsonl", (r.to_record() for r in plan.log))
    bundle.store.save(out_dir / "graph")
    _jsonl(out_dir / "bindings.jsonl", (b.to_record() for b in plan.bindings()))
    _jsonl(out_dir / "reference.jsonl", bundle.gold.reference_records())
    _jsonl(out_dir / "labels.jsonl", bundle.gold.labels)
    (out_dir / "schedules").mkdir()
    for sched in bundle.schedules:
        _jsonl(out_dir / "schedules" / f"{sched.name}.jsonl", sched.questions)
    _jsonl(out_dir / "render_log.jsonl", bundle.rendered.log)
    realised_types = Counter(x["change_type"] for x in bundle.gold.labels)
    outcomes = Counter((x["change_type"], "answer" if x["answer_stale"] else
                        "citation" if x["citation_stale"] else "neither")
                       for x in bundle.gold.labels)
    meta = {
        "sequence_id": plan.sequence_id, "family": plan.family.family_id, "split": split,
        "cell": plan.cell.to_record(), "master_seed": master_seed, "seed": plan.seed,
        "generator": {"code_sha": code_sha, "grammar": grammar().version,
                      "version": GENERATOR_VERSION},
        "renderer": bundle.renderer,
        "world": {"companion": plan.companion, "tasks": dict(plan.tasks),
                  "setup_length": plan.setup_length, "n_messages": len(plan.log),
                  "n_episodes": len({r.episode for r in plan.log})},
        "macros": {"planned": plan.planned, "realised": plan.realised,
                   "unrealised": plan.unrealised,
                   "by_name": dict(Counter(r.macro.name for r in plan.log if r.macro))},
        "labels": {"change_types": dict(realised_types),
                   "type_outcome": {f"{k}/{o}": n for (k, o), n in sorted(outcomes.items())}},
        "schedules": {s.name: {"points": s.points, **s.counts()} for s in bundle.schedules},
        "primary_schedule": plan.cell.primary,
        "render": {"fallback_rate": bundle.rendered.fallback_rate,
                   "check_failures": bundle.rendered.check_failures},
        "checks": bundle.checks,
    }
    files = sorted(p for p in out_dir.rglob("*") if p.is_file())
    meta["checksums"] = {p.relative_to(out_dir).as_posix(): sha256_file(p) for p in files}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8")
    return meta


@dataclass(frozen=True)
class DatasetConfig:
    """`configs/changeseq/<name>.yaml`: which sequences to generate."""

    dataset: str
    seed: int
    cells: tuple[tuple[CellConfig, int], ...]     # (cell, sequences per cell)
    allow_held_out: bool = False
    # "template-v1", or a mapping {kind: model, model_config, prompt, workers}
    renderer: Any = "template-v1"

    @property
    def renderer_kind(self) -> str:
        return "template" if self.renderer == "template-v1" else "model"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DatasetConfig:
        unknown = sorted(set(raw) - {"dataset", "seed", "cells", "allow_held_out", "renderer",
                                     "note"})
        if unknown:
            raise FamilyError(f"dataset config: unknown keys {unknown}")
        renderer = raw.get("renderer", "template-v1")
        if renderer != "template-v1":
            if not isinstance(renderer, Mapping) or renderer.get("kind") != "model":
                raise FamilyError("renderer: template-v1 or a mapping with kind: model")
            extra = sorted(set(renderer) - {"kind", "model_config", "prompt", "workers"})
            if extra:
                raise FamilyError(f"renderer: unknown keys {extra}")
        cells = []
        for spec in raw["cells"]:
            spec = dict(spec)
            families = spec.pop("families")
            n = int(spec.pop("sequences_per_family"))
            densities = spec.pop("density", [10])
            for family in families:
                for rho in densities:
                    cells.append((CellConfig.from_record({"family": family, "density": rho,
                                                          **spec}), n))
        return cls(raw["dataset"], int(raw["seed"]), tuple(cells),
                   bool(raw.get("allow_held_out", False)), renderer)

    def sequence_ids(self) -> list[tuple[str, CellConfig]]:
        out = []
        for cell, n in self.cells:
            for i in range(n):
                out.append((f"{cell.family}-rho{cell.density:g}-L{cell.length}-{i:03d}", cell))
        return out


def render_stats(entries: list[dict[str, Any]], logs: Mapping[str, list[dict[str, Any]]]
                 ) -> dict[str, dict[str, Any]]:
    """Attempts and fallbacks per family (design section 7)."""
    limit = grammar().fallback_rate_limit
    out: dict[str, dict[str, Any]] = {}
    for e in entries:
        s = out.setdefault(e["family"], {"messages": 0, "attempts": 0, "fallbacks": 0,
                                         "retried": 0})
        for row in logs[e["sequence_id"]]:
            s["messages"] += 1
            s["attempts"] += len(row["attempts"])
            s["fallbacks"] += int(row["fallback"])
            s["retried"] += int(len(row["attempts"]) > 1)
    for s in out.values():
        s["fallback_rate"] = s["fallbacks"] / s["messages"] if s["messages"] else 0.0
        s["over_limit"] = s["fallback_rate"] > limit
        s["limit"] = limit
    return dict(sorted(out.items()))


def build_dataset(config: DatasetConfig, out_dir: Path, code_sha: str, renderer=None,
                  workers: int = 1) -> dict[str, Any]:
    """Generate every sequence of `config` into `out_dir` (must not exist) with the manifest.

    `renderer` defaults to the template renderer. With `workers > 1` sequences are generated in
    parallel threads (messages of one sequence stay sequential, since each sees the six before
    it); the output does not depend on the number of workers except through the model server."""
    split = load_split()
    renderer = renderer or TemplateRenderer()
    jobs = []
    for sequence_id, cell in config.sequence_ids():
        which = split.split_of(cell.family)
        if which == "held-out" and not config.allow_held_out:
            raise FamilyError(f"{cell.family} is a held-out family; set allow_held_out to "
                              f"generate it")
        jobs.append((sequence_id, cell, which, sequence_seed(config.seed, sequence_id)))
    out_dir.mkdir(parents=True, exist_ok=False)

    def run(job):
        sequence_id, cell, _, seed = job
        return generate_sequence(cell.family, cell, seed, sequence_id, renderer=renderer)

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            bundles = list(pool.map(run, jobs))
    else:
        bundles = [run(job) for job in jobs]
    entries, logs = [], {}
    for (sequence_id, cell, which, seed), bundle in zip(jobs, bundles, strict=True):
        meta = write_sequence(bundle, out_dir / "sequences" / sequence_id, split=which,
                              code_sha=code_sha, master_seed=config.seed)
        logs[sequence_id] = bundle.rendered.log
        entries.append({"sequence_id": sequence_id, "family": cell.family, "split": which,
                        "path": f"sequences/{sequence_id}", "seed": seed,
                        "n_messages": meta["world"]["n_messages"],
                        "primary_schedule": meta["primary_schedule"]})
    dataset = {"dataset": config.dataset, "benchmark": "change-seq", "seed": config.seed,
               "generator": {"code_sha": code_sha, "grammar": grammar().version,
                             "version": GENERATOR_VERSION},
               "renderer": describe(renderer), "render": render_stats(entries, logs),
               "sequences": entries}
    (out_dir / "dataset.json").write_text(json.dumps(dataset, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8")
    write_manifest(out_dir)
    return dataset


def write_manifest(directory: Path) -> str:
    """Write `MANIFEST.sha256` (`<sha256>  <relative path>` per file); return its SHA-256."""
    lines = [f"{sha256_file(p)}  {p.relative_to(directory).as_posix()}\n"
             for p in sorted(directory.rglob("*"))
             if p.is_file() and p.name != "MANIFEST.sha256"]
    manifest = directory / "MANIFEST.sha256"
    manifest.write_text("".join(lines), encoding="utf-8")
    return sha256_file(manifest)
