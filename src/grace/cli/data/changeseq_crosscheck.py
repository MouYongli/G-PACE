"""Cross-check the change-sequence invalidation truth against the T017 compiler (T015, item 3).

    uv run python -m grace.cli.data.changeseq_crosscheck \\
        "$PROJECT_ROOT/runs/T015/artifacts/<dataset-run-id>" \\
        --out "$PROJECT_ROOT/runs/T015/artifacts/<run-id>"

The generator computes (ans, wit, ev) of every view binding at every version from the event log,
without the query compiler (`eval/datasets/changeseq/invalidation.py`, design
docs/research/change-sequences.md section 6.4). This entry point compiles each view template to
the T017 IR, executes it on the stored gold graph at every version (`context/pipeline/query/`,
read-time re-query) and compares the result with the generator's `reference.jsonl`; the answer and
citation staleness derived from the compiled results is compared with `labels.jsonl`.

**Why here.** `eval/datasets/changeseq/` must never import `context/pipeline/query/` (D013); the
check needs both, and of the packages allowed to import both (`cli/`, `eval/runner/probes/`,
`eval/engines/oracles/`) only `cli/` is in T015's write scope. The IR templates below are the
cross-check's encoding of the six templates of design section 6.2; the system's own view
templates belong to T018 (`context/views/template_families.py`) and should move or be checked
against these when that task lands.

**Two graphs.** The attribution constraint `[u, f]` requires by default report mode own,
positive polarity and not derived (T017, F1 closed; docs/research/query-ir.md), as the design's
V1-V3 do (change-sequences.md 6.2), so the full gold graph is compared directly. The check still
runs twice:

- `full`: the gold graph as stored; this is the acceptance comparison;
- `own-positive`: the same change sets with every non-own, negative or derived attribution
  removed, except attributions that license a supersession (they only sit on claims that are no
  longer current). On this graph the attribution default has nothing to filter, so it is a
  control: a disagreement on `full` that disappears on `own-positive` is *explained* by the
  handling of report mode, polarity or derivation (a regression of the F1 default), and one
  that stays is a compiler, IR-template or reference-function fault.

Witnesses are compared raw; the V3 count witness is one union witness on both sides
(plan 3.4, user decision of 2026-11-25), and raw V3 witness differences are also counted
separately.

The node the run belongs to (`task` in run.json) is `--task`, by default the node directory of
`--out` (`runs_root/<NODE>/...`), so that reruns by another node are labelled with that node.

Writes `run.json`, `summary.json`, `mismatches.jsonl` and `queries.txt` into a new directory under
runs_root. Refuses a dirty worktree unless `--allow-dirty`, and any sequence not in the
development split. CPU only, no model calls.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import traceback
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from grace.config.paths import project_root, shared_dir
from grace.context.memory.graph.entries import (
    CommunicativeFunction,
    Entity,
    Polarity,
    ReportMode,
    Value,
)
from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.query.compile import CompiledQuery, compile_query
from grace.context.pipeline.query.execute import execute
from grace.context.pipeline.query.grammar import to_text
from grace.context.pipeline.query.ir import (
    AttributionConstraint,
    Bound,
    ClaimPattern,
    CountDistinct,
    Filter,
    Latest,
    LatestKey,
    NotExists,
    Op,
    Predicate,
    Query,
    ValidBound,
    Var,
)
from grace.context.pipeline.query.result import QueryResult
from grace.eval.datasets.changeseq.generate import world_of
from grace.eval.datasets.changeseq.invalidation import Binding, World
from grace.eval.datasets.changeseq.template_families import load_family
from grace.eval.runner.harness.rundir import (
    code_state,
    environment,
    file_sha256,
    resources_sha256,
    utc_now,
)

GRAPHS = ("full", "own-positive")
# "No valid end" (V2): an open end is later than every time (query-ir.md, "Filters"), so a claim
# passes `end(?c) > MAX_DATE` exactly when it has no end. The fragment has no direct "unset" test.
MAX_DATE = Value("9999-12-31", "date")

OBJ, T, Q, V, C = Var("o"), Var("t"), Var("q"), Var("v"), Var("c")
INFORM, REQUEST = CommunicativeFunction.INFORM, CommunicativeFunction.REQUEST
OFFER, ACCEPT, REJECT = (CommunicativeFunction.OFFER, CommunicativeFunction.ACCEPT,
                         CommunicativeFunction.REJECT)


def _att(speaker: str, function: CommunicativeFunction | None) -> AttributionConstraint:
    return AttributionConstraint(Entity(speaker), function)


# ---------------------------------------------------------------------------------------------
# IR templates of the six views (design section 6.2)


def view_query(b: Binding, world: World) -> Query:
    """The IR of binding `b`. Deviations from the design table forced by the fragment:

    - V1-V3, V4: the design's "own, positive, not derived" is the default of `[u, f]` (F1,
      closed in T017), so the templates write `[u, f]` only; the `own-positive` graph is a
      control for that default (module docstring).
    - V2: "no valid end" is `end(?c) > 9999-12-31`; LATEST BY version keys on the later of the
      claim's and the attribution's version, the design on the claim's (equal when |K| <= 1).
    - V4: `?q in Cons(k)` cannot be written (predicate variables cannot be filtered); the
      pattern leaves `?q` open, which equals the design when the user requests nothing but the
      task's constraints (true of the grammar; a violation would show as a mismatch).
    - V5: the design has two NOT EXISTS (accept, reject); the fragment allows one, so it is one
      NOT EXISTS over `[user, _]`, and it ranges over claims with the same (k, sel, o), not the
      same claim node. Both equal the design when users attach no other function to choice
      claims and every item is offered once per task (true of the grammar).
    """
    if b.template in ("V1", "V2", "V3"):
        auth = _att(world.authority[b.predicate], INFORM)
        pattern = ClaimPattern(Entity(b.subject), b.predicate, OBJ, attribution=auth, label=C)
        if b.template == "V1":
            return Query((OBJ,), (pattern,))
        if b.template == "V3":
            return Query((), (pattern,), count=CountDistinct(OBJ))
        return Query((OBJ,), (pattern,), filters=(Filter(ValidBound(C, Bound.END), Op.GT,
                                                       MAX_DATE),),
                     latest=Latest(C, LatestKey.VERSION))
    k, sel = Entity(b.subject), world.choice_predicate
    if b.template == "V4":
        return Query((Q, V), (ClaimPattern(k, Q, V, attribution=_att("user", REQUEST)),))
    if b.template == "V5":
        return Query((OBJ,), (ClaimPattern(k, sel, OBJ, attribution=_att("assistant", OFFER)),),
                     negation=NotExists(ClaimPattern(k, sel, OBJ, attribution=_att("user", None))))
    if b.template == "V6":
        arr = world.catalogue_predicate
        return Query(
            (OBJ, T),
            (ClaimPattern(k, sel, OBJ, attribution=_att("user", ACCEPT), label=C),
             ClaimPattern(OBJ, arr, T, attribution=_att("assistant", INFORM))),
            negation=NotExists(ClaimPattern(k, sel, OBJ, attribution=_att("user", REJECT))),
            latest=Latest(C, LatestKey.VERSION))
    raise ValueError(f"unknown template {b.template}")


# ---------------------------------------------------------------------------------------------
# Results in the generator's canonical form


def _plain(value) -> Any:
    if isinstance(value, Entity):
        return value.id
    if isinstance(value, Predicate):
        return value.name
    if value.datatype == "integer":
        return int(value.lexical)
    return value.lexical


def canonical(result: QueryResult) -> dict[str, Any]:
    """`QueryResult` -> {"ans", "wit", "ev"} as `invalidation.ViewValue.canonical` writes it."""
    def answer(values):
        plain = [_plain(v) for v in values]
        return plain[0] if len(plain) == 1 else plain

    wit = sorted([answer(a.values), sorted(sorted((*w.claims, *w.attributions))
                                           for w in a.witnesses)] for a in result.answers)
    return {"ans": sorted(answer(a.values) for a in result.answers), "wit": wit,
            "ev": sorted({e for a in result.answers for e in a.evidence})}


# ---------------------------------------------------------------------------------------------
# Graphs


def own_positive(store: ClaimStore) -> ClaimStore:
    """The store's change sets without the attributions `[u, f]` cannot exclude (see above)."""
    licences = {s.attribution_id for cs in store.changesets() for s in cs.supersessions}
    out = ClaimStore(store.history_id, store.mode)
    for cs in store.changesets():
        keep = tuple(a for a in cs.attributions if a.attribution_id in licences or (
            a.report_mode is ReportMode.OWN and a.polarity is Polarity.POSITIVE
            and not a.derived))
        out.commit(replace(cs, attributions=keep))
    return out


def reserialised(store: ClaimStore, mode: str) -> ClaimStore:
    if store.mode == mode:
        return store
    out = ClaimStore(store.history_id, mode)
    for cs in store.changesets():
        out.commit(cs)
    return out


# ---------------------------------------------------------------------------------------------
# The check


def stale_labels(values: Sequence[Mapping[str, Any]]) -> list[tuple[bool, bool]]:
    """(answer_stale, citation_stale) at t = 1..N from the canonical values at t = 0..N."""
    out = []
    for before, after in zip(values, values[1:], strict=False):
        answer = before["ans"] != after["ans"]
        out.append((answer, not answer and (before["wit"], before["ev"]) != (after["wit"],
                                                                              after["ev"])))
    return out


@dataclass
class SequenceCheck:
    """Comparison of one sequence on one graph."""

    sequence_id: str
    graph: str
    versions: int
    bindings: int = 0
    by_template: Counter = field(default_factory=Counter)    # (binding, version) pairs checked
    value_mismatch: Counter = field(default_factory=Counter)
    component: Counter = field(default_factory=Counter)      # "V2/wit": first part that differs
    v3_raw_witness_mismatch: int = 0
    label_mismatch: Counter = field(default_factory=Counter)
    mismatches: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {"sequence_id": self.sequence_id, "graph": self.graph, "versions": self.versions,
                "bindings": self.bindings, "checked": dict(self.by_template),
                "value_mismatch": dict(self.value_mismatch), "component": dict(self.component),
                "v3_raw_witness_mismatch": self.v3_raw_witness_mismatch,
                "label_mismatch": dict(self.label_mismatch)}


def check_sequence(store: ClaimStore, bindings: Sequence[Binding], world: World,
                   reference: Mapping[str, Sequence[Mapping[str, Any]]],
                   labels: Mapping[tuple[str, int], tuple[bool, bool]],
                   *, sequence_id: str, graph: str,
                   template: Callable[[Binding, World], Query] = view_query) -> SequenceCheck:
    """Execute every binding's compiled IR at t = 0..N and compare with the reference values
    (`GoldStaleness.values`) and the per-message labels ((binding, t) -> (answer, citation))."""
    n = len(next(iter(reference.values()))) - 1
    out = SequenceCheck(sequence_id, graph, n, len(bindings))
    for b in bindings:
        compiled = compile_query(template(b, world), store.mode)
        got = [canonical(execute(compiled, store, t)) for t in range(n + 1)]
        want = list(reference[b.binding_id])
        if b.template == "V3":
            out.v3_raw_witness_mismatch += sum(g["wit"] != w["wit"] for g, w in zip(
                got, want, strict=True))
        out.by_template[b.template] += n + 1
        for t, (g, w) in enumerate(zip(got, want, strict=True)):
            if g != w:
                out.value_mismatch[b.template] += 1
                part = next(k for k in ("ans", "wit", "ev") if g[k] != w[k])
                out.component[f"{b.template}/{part}"] += 1
                out.mismatches.append({"sequence_id": sequence_id, "graph": graph,
                                       "binding_id": b.binding_id, "version": t,
                                       "reference": w, "compiled": g})
        for t, derived in enumerate(stale_labels(got), start=1):
            if derived != labels[(b.binding_id, t)]:
                out.label_mismatch[b.template] += 1
                out.mismatches.append({"sequence_id": sequence_id, "graph": graph,
                                       "binding_id": b.binding_id, "version": t,
                                       "label": list(labels[(b.binding_id, t)]),
                                       "compiled_label": list(derived)})
    return out


def explain(full: SequenceCheck, projected: SequenceCheck) -> tuple[int, int]:
    """(explained, unexplained) value mismatches on `full`: explained when the `own-positive`
    graph agrees with the reference at the same binding and version."""
    left = {(m["binding_id"], m["version"]) for m in projected.mismatches if "compiled" in m}
    rows = [m for m in full.mismatches if "compiled" in m]
    unexplained = sum((m["binding_id"], m["version"]) in left for m in rows)
    return len(rows) - unexplained, unexplained


# ---------------------------------------------------------------------------------------------
# Reading a generated dataset


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@dataclass
class StoredSequence:
    sequence_id: str
    split: str
    world: World
    store: ClaimStore
    bindings: list[Binding]
    reference: dict[str, list[dict[str, Any]]]
    labels: dict[tuple[str, int], tuple[bool, bool]]


def load_sequence(directory: Path) -> StoredSequence:
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    n = meta["world"]["n_messages"]
    bindings = [Binding(r["template"], r["subject"], r["predicate"])
                for r in _jsonl(directory / "bindings.jsonl")]
    changes: dict[str, dict[int, dict[str, Any]]] = {b.binding_id: {} for b in bindings}
    for r in _jsonl(directory / "reference.jsonl"):
        changes[r["binding_id"]][r["version"]] = {k: r[k] for k in ("ans", "wit", "ev")}
    reference = {}
    for b in bindings:
        values, current = [], None
        for t in range(n + 1):
            current = changes[b.binding_id].get(t, current)
            if current is None:
                raise ValueError(f"{directory}: no reference value for {b.binding_id} at 0")
            values.append(current)
        reference[b.binding_id] = values
    labels = {(r["binding_id"], r["version"]): (r["answer_stale"], r["citation_stale"])
              for r in _jsonl(directory / "labels.jsonl")}
    return StoredSequence(meta["sequence_id"], meta["split"], world_of(load_family(
        meta["family"])), ClaimStore.restore(directory / "graph"), bindings, reference, labels)


def queries_text(bindings: Sequence[Binding], world: World, mode: str) -> str:
    """The IR (text form) and compiled main SPARQL of one binding per template."""
    seen, parts = set(), []
    for b in bindings:
        if b.template in seen:
            continue
        seen.add(b.template)
        compiled: CompiledQuery = compile_query(view_query(b, world), mode)
        parts.append(f"# {b.binding_id}\n{to_text(view_query(b, world))}\n\n"
                     f"## main ({mode})\n{compiled.main}\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------------------------
# Entry point


NODE = re.compile(r"[TE]\d{3}")


def node_of(out: Path, runs: Path) -> str | None:
    """The node directory of a run directory `runs_root/<NODE>/...`, if it names a node."""
    first = out.relative_to(runs).parts[0]
    return first if NODE.fullmatch(first) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dataset_run", type=Path,
                        help="run directory written by grace.cli.data.changeseq")
    parser.add_argument("--out", type=Path, required=True, help="new directory under runs_root")
    parser.add_argument("--modes", nargs="+", default=["rdf11"], choices=["rdf11", "rdf12"],
                        help="claim serialisations to execute on")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--task", help="node of this run (T<NNN> or E<NNN>); default: the node "
                        "directory of --out")
    args = parser.parse_args(argv)
    runs = shared_dir("runs_root").resolve()
    out, upstream = args.out.resolve(), args.dataset_run.resolve()
    if runs not in out.parents:
        parser.error(f"--out must lie under {runs}")
    task = args.task or node_of(out, runs)
    if task is None or not NODE.fullmatch(task):
        parser.error("cannot tell the node from --out; pass --task T<NNN> or E<NNN>")
    if out.exists():
        parser.error(f"{out} exists; a run directory is created exclusively")
    up_run = json.loads((upstream / "run.json").read_text(encoding="utf-8"))
    if up_run.get("status") != "completed":
        parser.error(f"upstream run {upstream.name} is not completed")
    code = code_state()
    if code.dirty and not args.allow_dirty:
        parser.error("the worktree has uncommitted changes; commit first or pass --allow-dirty")
    dataset_dir = upstream / "dataset"
    manifest = file_sha256(dataset_dir / "MANIFEST.sha256")
    if manifest != up_run.get("manifest_sha256"):
        parser.error(f"dataset manifest {manifest} differs from the upstream run.json")
    out.mkdir(parents=True)
    run = {
        "run_id": out.name, "task": task, "stage": "check", "upstream": [up_run["run_id"]],
        "status": "running", "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": up_run["config_path"], "config_sha256": up_run["config_sha256"],
        "resources_sha256": resources_sha256(), "seed": up_run["seed"],
        "data": [{"dataset_run": up_run["run_id"], "manifest_sha256": manifest,
                  "generator_code_sha": up_run["code_sha"]}],
        "project_root": str(project_root()),
        "command": shlex.join([sys.executable, "-m", "grace.cli.data.changeseq_crosscheck",
                               *(argv if argv is not None else sys.argv[1:])]),
        "environment": environment("cpu"), "started_at": utc_now(), "finished_at": None,
        "graphs": list(GRAPHS), "modes": args.modes, "model_calls": 0,
        "held_out_access": "none",
    }

    def save() -> None:
        (out / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    save()
    try:
        summary = run_check(dataset_dir, out, args.modes)
    except Exception:
        run.update(status="failed", finished_at=utc_now(), error=traceback.format_exc())
        save()
        raise
    run.update(status="completed", finished_at=utc_now(), result=summary["totals"])
    save()
    print(json.dumps({"run_id": run["run_id"], **summary["totals"]}, indent=2))
    return 0


def run_check(dataset_dir: Path, out: Path, modes: Sequence[str]) -> dict[str, Any]:
    dataset = json.loads((dataset_dir / "dataset.json").read_text(encoding="utf-8"))
    per_sequence, totals = [], Counter()
    by_graph: dict[str, dict[str, Counter]] = {}
    with (out / "mismatches.jsonl").open("w", encoding="utf-8") as handle:
        for entry in dataset["sequences"]:
            seq = load_sequence(dataset_dir / entry["path"])
            if seq.split != "development":
                raise ValueError(f"{seq.sequence_id} is in split {seq.split!r}; development only")
            if not per_sequence:
                (out / "queries.txt").write_text(queries_text(seq.bindings, seq.world, "rdf11"),
                                                 encoding="utf-8")
            for mode in modes:
                base = reserialised(seq.store, mode)
                checks = {}
                for graph, store in (("full", base), ("own-positive", own_positive(base))):
                    c = check_sequence(store, seq.bindings, seq.world, seq.reference, seq.labels,
                                       sequence_id=seq.sequence_id, graph=graph)
                    checks[graph] = c
                    for m in c.mismatches:
                        handle.write(json.dumps({"mode": mode, **m}, sort_keys=True) + "\n")
                    agg = by_graph.setdefault(f"{mode}/{graph}", {
                        "checked": Counter(), "value_mismatch": Counter(), "component": Counter(),
                        "label_mismatch": Counter(), "v3_raw_witness_mismatch": Counter()})
                    agg["checked"].update(c.by_template)
                    agg["value_mismatch"].update(c.value_mismatch)
                    agg["component"].update(c.component)
                    agg["label_mismatch"].update(c.label_mismatch)
                    agg["v3_raw_witness_mismatch"]["V3"] += c.v3_raw_witness_mismatch
                explained, unexplained = explain(checks["full"], checks["own-positive"])
                totals["explained_full_mismatches"] += explained
                totals["unexplained_full_mismatches"] += unexplained
                per_sequence.append({"mode": mode, **checks["full"].summary(),
                                     "explained": explained, "unexplained": unexplained,
                                     "own_positive": checks["own-positive"].summary()})
            totals["sequences"] += 1
    for key, agg in by_graph.items():
        totals[f"{key}/checked"] = sum(agg["checked"].values())
        totals[f"{key}/value_mismatch"] = sum(agg["value_mismatch"].values())
        totals[f"{key}/label_mismatch"] = sum(agg["label_mismatch"].values())
    summary = {"totals": dict(totals),
               "by_graph": {k: {name: dict(c) for name, c in v.items()}
                            for k, v in by_graph.items()},
               "sequences": per_sequence}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    return summary


if __name__ == "__main__":
    sys.exit(main())
