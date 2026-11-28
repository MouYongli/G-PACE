"""E010, ablation C on extracted graphs: which view content source serves the answering LLM best,
and how often standing views serve a read at all.

    uv run python -m grace.cli.ablation_c_extracted read --arm llm-src --budget 1024 \\
        --base-url <8B url> --embed-url <embedding url> --writer-url <32B url>
    uv run python -m grace.cli.ablation_c_extracted system --target change-seq --arm llm-src \\
        --budget 1024 --base-url ... --embed-url ... --writer-url ...
    uv run python -m grace.cli.ablation_c_extracted score --system <change-seq system run dir>
    uv run python -m grace.cli.locomo_score --run <locomo read/system run> --experiment E010 \\
        --run-root <runs_root>/E010/artifacts/w01-E010
    uv run python -m grace.cli.ablation_c_extracted compare --target locomo --budget 1024 \\
        --arm template-src=<score run dir> ... --out <new dir under runs_root>

Config: `configs/experiments/E010-ablation-c-extracted.yaml` (`--config`). The view arms are GRACE
engine configs whose view slot is a read-time content source (`context/views/readtime.py`).

- `read` (stage `read`): one view arm on LoCoMo from the snapshot of the target's shared ingest
  run (`stages.run_read`).
- `system` (stage `system`): one arm with per-turn reading on the controlled sequences (the
  target's histories, inline benchmark config as E005), or the `raw` arm on LoCoMo (a baseline
  has no GRACE read side, so it runs as a system run of end-of-history reads).
- Both write, besides the contract's files, `views/presentations.jsonl`: one record per
  presentation of a query result by the arm's content source (`readtime.EVENT_SINK`; written when
  the stage has returned).
- `score` (stage `score`): set match of a change-seq system run (`ablation_c.run_score`).
- `compare` (not a run): per arm accuracy with cluster-bootstrap intervals, paired differences
  of the configured pairs, view hit rates, rendering-check counts, wrong citations, rendering
  cost and context use; written with the checksum of every input run.json to
  `<out>/summary.json`.

Development data only.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from grace.cli import ablation_c
from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.context.views import readtime
from grace.eval.analysis.metrics import changeseq as metric
from grace.eval.analysis.metrics.align import read_jsonl
from grace.eval.datasets.benchmarks.base import BenchmarkConfig
from grace.eval.runner.harness import drive, rundir, stages
from grace.eval.runner.harness.drive import ClientSettings
from grace.llm.records import read_calls

EXPERIMENT = "E010"
CONFIG = REPO_ROOT / "configs" / "experiments" / "E010-ablation-c-extracted.yaml"
EVENTS_FILE = "views/presentations.jsonl"


def run_root() -> Path:
    return shared_dir("runs_root") / EXPERIMENT / "artifacts" / "w01-E010"


def load_experiment(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for key in ("experiment", "seed", "models", "arms", "budgets", "targets", "comparison"):
        if key not in config:
            raise ValueError(f"{path}: missing {key!r}")
    if config["experiment"] != EXPERIMENT:
        raise ValueError(f"{path}: experiment is {config['experiment']!r}")
    return config


def _client(args, config) -> ClientSettings | None:
    if not args.base_url:
        return None
    return ClientSettings(args.base_url, REPO_ROOT / config["models"]["answer"], args.embed_url,
                          writer_url=args.writer_url)


class Collector:
    """Receives the presentation records of one stage run (`readtime.EVENT_SINK`)."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def __enter__(self) -> Collector:
        readtime.EVENT_SINK = self.records.append
        return self

    def __exit__(self, *exc) -> None:
        readtime.EVENT_SINK = None

    def write(self, run_dir: Path) -> None:
        path = Path(run_dir) / EVENTS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            for r in sorted(self.records, key=lambda r: (r["history_id"], r["version"],
                                                         r["read_id"])):
                handle.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def _engine(config: Mapping[str, Any], arm: str) -> Path:
    if arm not in config["arms"]:
        raise ValueError(f"unknown arm {arm!r}; arms are {sorted(config['arms'])}")
    return REPO_ROOT / config["arms"][arm]["engine"]


def run_read(config, arm: str, budget: int, client, *, history_ids=None, workers: int = 1,
             out_root: Path | None = None, backend_factory=None):
    target = config["targets"]["locomo"]
    with Collector() as collector:
        result = stages.run_read(engine_config=_engine(config, arm),
                                 upstream=project_root() / target["ingest_run"], budget=budget,
                                 experiment=EXPERIMENT, run_root=out_root or run_root(),
                                 seed=int(config["seed"]), history_ids=history_ids,
                                 client=client, workers=workers,
                                 backend_factory=backend_factory,
                                 command=shlex.join(sys.argv))
    collector.write(result.run_dir)
    return result


def run_system(config, target_name: str, arm: str, budget: int, client, *, history_ids=None,
               out_root: Path | None = None, backend_factory=None):
    target = config["targets"][target_name]
    kwargs: dict[str, Any] = {"benchmark": target["benchmark"], "split": target["split"]}
    if "config" in target:
        kwargs["benchmark_config"] = BenchmarkConfig.from_dict(target["config"])
    histories = history_ids or target.get("histories")
    with Collector() as collector:
        result = drive.run_system(engine_config=_engine(config, arm), budget=budget,
                                  experiment=EXPERIMENT, run_root=out_root or run_root(),
                                  seed=int(config["seed"]), history_ids=histories,
                                  client=client, backend_factory=backend_factory,
                                  command=shlex.join(sys.argv), **kwargs)
    collector.write(result.run_dir)
    return result


def score_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """The change-seq target in the shape `ablation_c.run_score` reads."""
    t = config["targets"]["change-seq"]
    return {"benchmark": {"config": t["config"], "split": t["split"]},
            "scoring": t["scoring"], "population": t["population"]}


# ---------------------------------------------------------------------------------------------
# Comparison (not a run)


def _completed(run_dir: Path, stages_: Sequence[str]) -> dict[str, Any]:
    run = json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))
    if run.get("status") != "completed" or run.get("stage") not in stages_:
        raise ValueError(f"{run_dir}: {run.get('stage')} run is {run.get('status')!r}")
    return run


def view_stats(run_dir: Path) -> dict[str, Any]:
    """View hits, state lines, presentations, rendering checks, wrong citations and rendering
    cost of one system or read run, plus per-read flags for the paired strata."""
    run_dir = Path(run_dir)
    traces = read_jsonl(run_dir / "traces" / "read.jsonl")
    contexts = {c["read_id"]: c for c in read_jsonl(run_dir / "contexts.jsonl")}
    predictions = {p["read_id"]: p for p in read_jsonl(run_dir / "predictions.jsonl")}
    events = (read_jsonl(run_dir / EVENTS_FILE) if (run_dir / EVENTS_FILE).exists() else [])
    calls = read_calls(run_dir / "calls.jsonl")
    n = len(traces)
    per_read: dict[str, dict[str, bool]] = {}
    hit_any = hit_only = state_any = 0
    for t in traces:
        frags = contexts[t["read_id"]]["fragments"]
        state = [f for f in frags if f["kind"] in ("view", "claim")]
        hit = bool(t["view_hits"])
        only = hit and bool(frags) and all(f["kind"] == "view" and
                                           f["fragment_id"].split("#")[0] in t["view_hits"]
                                           for f in frags)
        hit_any += hit
        hit_only += only
        state_any += bool(state)
        per_read[t["read_id"]] = {"state_lines": bool(state), "view_hit": hit}
    # Answer citations outside the working context (fabricated or misread IDs).
    cited = wrong = 0
    for rid, p in predictions.items():
        shown = {e.split("#")[0] for f in contexts[rid]["fragments"] for e in f["evidence_ids"]}
        for c in p.get("cited_ids") or []:
            cited += 1
            wrong += c not in shown
    render = [c for c in calls if c.call_type == "render"]
    presented = [e for e in events if e["status"] == "presented"]
    llm_ok = sum(e.get("llm_sentences", 0) for e in presented)
    failed = sum(e.get("failed_sentences", 0) for e in presented)
    units = sum(e.get("units", 0) for e in presented)
    fallback = sum(e.get("fallback_units", 0) for e in presented)
    rw_sources = sum(e.get("rewrite_sources", 0) for e in presented)
    rw_wrong = sum(e.get("wrong_citations", 0) for e in presented)
    hits = [e for e in presented if e.get("view_id")]
    no_hit = [e for e in presented if not e.get("view_id")]
    return {
        "reads": n,
        "view_hit_rate": {"hit_any": hit_any / n if n else None,
                          "hit_only": hit_only / n if n else None,
                          "reads_hit_any": hit_any, "reads_hit_only": hit_only},
        "state_lines": {"reads": state_any, "rate": state_any / n if n else None},
        "presentations": {
            "events": len(events), "presented": len(presented),
            "skipped": len(events) - len(presented),
            "reads_with_plan_query": len({e["read_id"] for e in events}),
            "view_eligible": sum(e["view_eligible"] for e in presented),
            "hits": len(hits), "hit_families": dict(Counter(e["family"] for e in hits)),
            "no_hit_with_near_binding": sum(bool(e.get("near")) for e in no_hit),
            "no_hit_eligible_with_near_binding": sum(bool(e.get("near")) and e["view_eligible"]
                                                     for e in no_hit),
            # Why a near binding missed: its bound query differs from the plan's query only in
            # variable names, also in attribution constraints, or in more (readtime.near_class).
            "no_hit_near_class": dict(Counter(e.get("near_class") or "no_near_binding"
                                              for e in no_hit)),
            "no_hit_near_class_eligible": dict(Counter(e.get("near_class") or "no_near_binding"
                                                       for e in no_hit if e["view_eligible"])),
            "reads_hit_if_variable_names_ignored": len({e["read_id"] for e in no_hit
                                                        if e["view_eligible"] and
                                                        e.get("near_class") == "variable_names"}),
            "reads_hit_if_variables_and_attribution_ignored": len(
                {e["read_id"] for e in no_hit if e["view_eligible"]
                 and e.get("near_class") in ("variable_names", "attribution")}),
            "candidate_bindings_mean": (mean(e.get("candidates", 0) for e in presented)
                                        if presented else None),
            "rows_mean": mean(e["rows"] for e in presented) if presented else None,
            "empty_results": sum(e["rows"] == 0 for e in presented)},
        "rendering_check": {
            "units_rendered": units, "llm_sentences": llm_ok, "failed_sentences": failed,
            "fallback_units": fallback,
            "sentence_failure_rate": failed / (llm_ok + failed) if llm_ok + failed else None,
            "unit_fallback_rate": fallback / units if units else None,
            "rewrite_sentences": sum(e.get("rewrite_sentences", 0) for e in presented),
            "rewrite_dropped_sentences": sum(e.get("dropped_sentences", 0) for e in presented),
            "rewrite_rows_stated": sum(e.get("rows_stated", 0) for e in presented),
            "rewrite_calls_failed": sum(e.get("rewrite_calls_failed", 0) for e in presented)},
        "wrong_citations": {
            "rewrite_sources": rw_sources, "rewrite_wrong": rw_wrong,
            "rewrite_wrong_rate": rw_wrong / rw_sources if rw_sources else None,
            "answer_citations": cited, "answer_citations_outside_context": wrong,
            "answer_outside_rate": wrong / cited if cited else None},
        "rendering_cost": {
            "calls": len(render), "status": dict(Counter(c.status for c in render)),
            "category": dict(Counter(c.category for c in render)),
            "input_tokens": sum(c.input_tokens for c in render),
            "output_tokens": sum(c.output_tokens for c in render),
            "cached_input_tokens": sum(c.cached_input_tokens for c in render),
            "per_read_tokens": (sum(c.input_tokens + c.output_tokens for c in render) / n
                                if n else None)},
        "context_tokens_mean": mean(c["tokens"] for c in contexts.values()) if contexts else None,
    }, per_read


def _values(target: str, score_dir: Path, population: Mapping[str, Any] | None
            ) -> tuple[dict[str, float], dict[str, str], dict[str, str], list[dict]]:
    """Per-read values, clusters and strata labels of one score run."""
    rows = read_jsonl(Path(score_dir) / "scores.jsonl")
    if target == "locomo":
        rows = [r for r in rows if "f1" in r]  # categories 1-4 (registered f1 population)
        values = {r["read_id"]: (r["f1"] if r["f1"] is not None else 0.0) for r in rows}
        clusters = {r["read_id"]: r["read_id"].split(":")[0] for r in rows}
        return values, clusters, {}, rows
    included = [r for r in rows if r["question_type"] in population["include_types"]]
    values = {r["read_id"]: r["value"] for r in included}
    clusters = {r["read_id"]: r["family"] for r in included}
    qtype = {r["read_id"]: r["question_type"] for r in rows}
    return values, clusters, qtype, rows


def compare(config: Mapping[str, Any], target: str, budget: int,
            score_dirs: Mapping[str, Path], out: Path) -> dict[str, Any]:
    boot = config["comparison"]["bootstrap"]
    population = config["targets"][target].get("population")
    inputs, values, clusters, arms, flags = {}, {}, {}, {}, {}
    qtypes: dict[str, str] = {}
    for arm, score_dir in score_dirs.items():
        score_dir = Path(score_dir).resolve()
        run = _completed(score_dir, ["score"])
        up = Path(run["upstream"][0]["path"])
        system = _completed(up, ["system", "read"])
        resolved = yaml.safe_load((up / "resolved-config.yaml").read_text("utf-8"))
        if resolved["budget_tokens"] != budget:
            raise ValueError(f"{arm}: {system['run_id']} has budget {resolved['budget_tokens']}")
        inputs[arm] = {"score_run": run["run_id"], "upstream_run": system["run_id"],
                       "upstream_stage": system["stage"],
                       "engine_config": resolved.get("engine_config"),
                       "score_run_json_sha256": rundir.file_sha256(score_dir / "run.json"),
                       "upstream_run_json_sha256": rundir.file_sha256(up / "run.json"),
                       "code_sha": system["code_sha"], "code_dirty": system["code_dirty"]}
        v, c, q, rows = _values(target, score_dir, population)
        values[arm], clusters[arm] = v, c
        qtypes.update(q)
        stats, per_read = view_stats(up)
        flags[arm] = per_read
        acc = metric.cluster_bootstrap(v, c, resamples=boot["resamples"], seed=boot["seed"])
        by_read = metric.cluster_bootstrap(v, {r: r for r in v}, resamples=boot["resamples"],
                                           seed=boot["seed"])
        arms[arm] = {"accuracy": acc, "accuracy_read_interval": by_read["ci95"],
                     "n_reads": len(v),
                     "outputs": dict(Counter(r.get("output") for r in rows)), **stats}
        if target == "change-seq":
            arms[arm]["by_question_type"] = _by(v, qtypes)
            hist = [r for r in rows if r["question_type"] in population["descriptive_types"]]
            arms[arm]["historical_descriptive"] = {
                "n_reads": len(hist),
                "accuracy": mean(r["value"] for r in hist) if hist else None}
    pairs = {}
    names = [tuple(config["comparison"]["primary"]),
             *[tuple(p) for p in config["comparison"]["secondary"]]]
    unit_main = boot["cluster_unit"][target]
    for a, b in names:
        if a not in values or b not in values:
            continue
        common = sorted(set(values[a]) & set(values[b]))
        va = {r: values[a][r] for r in common}
        vb = {r: values[b][r] for r in common}
        cl = {r: clusters[a][r] for r in common}
        entry = {unit_main: metric.paired_bootstrap(va, vb, cl, resamples=boot["resamples"],
                                                    seed=boot["seed"]),
                 "read": _slim(metric.paired_bootstrap(va, vb, {r: r for r in common},
                                                       resamples=boot["resamples"],
                                                       seed=boot["seed"]))}
        # Reads where either arm showed presented state lines: the only reads where the content
        # source can matter (descriptive stratum).
        sub = [r for r in common if flags[a].get(r, {}).get("state_lines")
               or flags[b].get(r, {}).get("state_lines")]
        if sub:
            entry["reads_with_state_lines"] = {
                "n_reads": len(sub), "a": mean(va[r] for r in sub), "b": mean(vb[r] for r in sub),
                "difference": mean(va[r] - vb[r] for r in sub),
                "read_interval": _slim(metric.paired_bootstrap(
                    {r: va[r] for r in sub}, {r: vb[r] for r in sub}, {r: r for r in sub},
                    resamples=boot["resamples"], seed=boot["seed"]))}
        if target == "change-seq":
            entry["by_question_type"] = {
                q: {"n_reads": len(ids), "difference": mean(va[r] - vb[r] for r in ids)}
                for q in population["include_types"]
                if (ids := [r for r in common if qtypes.get(r) == q])}
        pairs[f"{a} - {b}"] = entry
    summary = {"experiment": EXPERIMENT, "target": target, "budget_tokens": budget,
               "inputs": inputs, "arms": arms, "paired": pairs, "bootstrap": boot,
               "population": population}
    out.mkdir(parents=True, exist_ok=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    return summary


def _slim(paired: dict[str, Any]) -> dict[str, Any]:
    """A read-level paired bootstrap without its per-read cluster tables."""
    return {k: v for k, v in paired.items() if k not in ("per_cluster", "leave_one_cluster_out")}


def _by(values: Mapping[str, float], labels: Mapping[str, str]) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    for r, v in values.items():
        groups[labels[r]].append(v)
    return {k: {"n_reads": len(g), "accuracy": mean(g)} for k, g in sorted(groups.items())}


# ---------------------------------------------------------------------------------------------
# Entry point


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def served(p):
        p.add_argument("--config", type=Path, default=CONFIG)
        p.add_argument("--arm", required=True)
        p.add_argument("--budget", type=int, required=True)
        p.add_argument("--base-url", default=None, help="answering/planner/rendering endpoint; "
                       "omitted: the fake backend (no number from it is real)")
        p.add_argument("--embed-url", default=None)
        p.add_argument("--writer-url", default=None)
        p.add_argument("--history", action="append", default=None)
        p.add_argument("--run-root", type=Path, default=None)
    read = sub.add_parser("read", help="one view arm on LoCoMo from the shared ingest run")
    served(read)
    read.add_argument("--workers", type=int, default=1)
    system = sub.add_parser("system", help="one arm as a system run")
    served(system)
    system.add_argument("--target", required=True, choices=["change-seq", "locomo"])
    score = sub.add_parser("score", help="set match of a change-seq system run")
    score.add_argument("--config", type=Path, default=CONFIG)
    score.add_argument("--system", type=Path, required=True)
    score.add_argument("--run-root", type=Path, default=None)
    comp = sub.add_parser("compare", help="paired comparison over score runs (not a run)")
    comp.add_argument("--config", type=Path, default=CONFIG)
    comp.add_argument("--target", required=True, choices=["change-seq", "locomo"])
    comp.add_argument("--budget", type=int, required=True)
    comp.add_argument("--arm", action="append", required=True, help="<arm>=<score run dir>")
    comp.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    config = load_experiment(args.config)
    if args.command == "read":
        result = run_read(config, args.arm, args.budget, _client(args, config),
                          history_ids=args.history, workers=args.workers,
                          out_root=args.run_root)
    elif args.command == "system":
        result = run_system(config, args.target, args.arm, args.budget, _client(args, config),
                            history_ids=args.history, out_root=args.run_root)
    elif args.command == "score":
        run_dir = ablation_c.run_score(score_config(config), args.config, args.system,
                                       command=shlex.join(sys.argv),
                                       out_root=args.run_root or run_root(),
                                       experiment=EXPERIMENT)
        print(f"{run_dir.name}: score -> {run_dir}")
        return 0
    else:
        arms = dict(a.split("=", 1) for a in args.arm)
        summary = compare(config, args.target, args.budget,
                          {k: Path(v) for k, v in arms.items()}, args.out)
        print(json.dumps({a: {"accuracy": s["accuracy"].get("mean"),
                              "hit_any": s["view_hit_rate"]["hit_any"]}
                          for a, s in summary["arms"].items()}, indent=2))
        return 0
    print(f"{result.run_id}: {result.status} -> {result.run_dir}")
    if result.failure:
        print(f"failure: {result.failure}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
