"""Cost reports and curves from run directories (task T030; plan 8.1 to 8.3).

    python -m grace.cli.cost.report ledger RUN_DIR [--json OUT.json]
    python -m grace.cli.cost.report amortise --out DIR --run LABEL=RUN_DIR ... \
        [--ledger computed|logical|gpu_seconds | --price C] [--seed N] [--baseline LABEL]
    python -m grace.cli.cost.report payback --out DIR --system LABEL=RUN_DIR ... \
        --full-history RUN_DIR [--uncached RUN_DIR] [--steps 20]
    python -m grace.cli.cost.report quality --out DIR --score LABEL=SCORE_RUN_DIR ... \
        --metric NAME [--annotation NAME] [--ledger computed]
    python -m grace.cli.cost.report success --out DIR --run LABEL=RUN_DIR:JUDGE_RUN_DIR ... \
        [--judge NAME] [--ledger computed]

`ledger` prints the three ledgers per category, checks that the per-read charges reconcile with
the per-call totals (exit 1 if not), and lists embedding, latency, timings and tool calls apart.
The other commands write CSV tables, PNG figures and `inputs.json` (the run IDs, paths and
`run.json` checksums they read) into `--out`, a new directory under the runs root
(`configs/common/paths.yaml`); they never write into an input run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from grace.config.paths import shared_dir
from grace.eval.analysis.metrics.cost import amortisation as am
from grace.eval.analysis.metrics.cost import plots
from grace.eval.analysis.metrics.cost.ledger import LedgerError, RunCost, load_run, summary
from grace.eval.runner.harness import rundir


def labelled(value: str) -> tuple[str, Path]:
    label, sep, path = value.partition("=")
    if not sep or not label or not path:
        raise argparse.ArgumentTypeError(f"expected LABEL=PATH, got {value!r}")
    return label, Path(path)


def out_dir(path: Path, runs_root: Path | None = None) -> Path:
    """Create the output directory exclusively; it must lie under the runs root."""
    root = (runs_root or shared_dir("runs_root")).resolve()
    resolved = Path(path).resolve()
    if resolved != root and root not in resolved.parents:
        raise SystemExit(f"--out {resolved} is not under the runs root {root}")
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def write_inputs(out: Path, command: str, runs: dict[str, RunCost]) -> None:
    code = rundir.code_state()
    record = {"command": command, "code_sha": code.sha, "code_dirty": code.dirty,
              "inputs": []}
    for label, run in runs.items():
        chain = [run, *run.upstream]
        for item in chain:
            run_json = item.run_dir / "run.json"
            record["inputs"].append({
                "label": label, "run_id": item.run_id, "stage": item.run.get("stage"),
                "status": item.run.get("status"), "path": item.run_dir.resolve().as_posix(),
                "run_json_sha256": hashlib.sha256(run_json.read_bytes()).hexdigest()})
    (out / "inputs.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def _dump(out: Path, name: str, data) -> None:
    with (out / name).open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _require_completed(runs: dict[str, RunCost], allow_failed: bool) -> None:
    for label, run in runs.items():
        for item in (run, *run.upstream):
            if item.run.get("status") != "completed" and not allow_failed:
                raise SystemExit(f"{label}: run {item.run_id} is {item.run.get('status')}; "
                                 "pass --allow-failed to include it")


# ---------------------------------------------------------------------------------------------


def cmd_ledger(args) -> int:
    try:
        report = summary(load_run(args.run))
    except LedgerError as exc:
        print(f"does not reconcile: {exc}")
        return 1
    header = f"{'category':<11} {'calls':>6} {'failed':>6} {'logical':>12} {'computed':>12} " \
             f"{'gpu_s':>10} {'gpu_null':>8}"
    print(f"run {report['run_id']}  reads {report['n_reads']}  upstream {report['upstream']}")
    print(header)
    for category, row in [*report["ledgers"].items(), ("system", report["system"])]:
        print(f"{category:<11} {row['calls']:>6} {row['failed_calls']:>6} {row['logical']:>12} "
              f"{row['computed']:>12} {row['gpu_seconds']:>10.3f} {row['gpu_null']:>8}")
    print(f"reconciled with per-call totals: {sorted(report['reconciliation'])}; "
          f"W after the last read: {report['unassigned_w']['logical']} logical tokens")
    sep = report["separate"]
    print(f"embedding: {sep['embedding']}; tool calls: {sep['tool_calls']}")
    print(f"read model latency ms: {sep['read_model_latency_ms']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


def cmd_amortise(args, command: str) -> int:
    runs = {label: load_run(path) for label, path in args.run}
    _require_completed(runs, args.allow_failed)
    out = out_dir(args.out)
    write_inputs(out, command, runs)
    curves = [curve for label, run in runs.items()
              for curve in am.cumulative(run, label, ledger=args.ledger, c=args.price,
                                         seed=args.seed)]
    rows = [(c.label, c.history_id, c.ledger, c.order, m, value)
            for c in curves for m, value in enumerate(c.points, start=1)]
    plots.write_csv(out / "cumulative.csv",
                    ("label", "history_id", "ledger", "order", "reads", "cumulative"), rows)
    crossings = []
    if args.baseline:
        for curve in curves:
            if curve.label == args.baseline:
                continue
            base = next((b for b in curves if b.label == args.baseline
                         and b.history_id == curve.history_id), None)
            if base is not None:
                crossings.append({"label": curve.label, "baseline": args.baseline,
                                  "history_id": curve.history_id,
                                  "crossing_reads": am.crossing(curve, base)})
        _dump(out, "crossings.json", crossings)
    unit = curves[0].ledger if curves else args.ledger
    plots.cumulative_figure(curves, out / "cumulative.png", unit=unit)
    print(f"wrote {out}")
    for item in crossings:
        print(item)
    return 0


def cmd_payback(args, command: str) -> int:
    systems = {label: load_run(path) for label, path in args.system}
    full = load_run(args.full_history)
    runs = {**systems, "full-history": full}
    uncached = load_run(args.uncached) if args.uncached else None
    if uncached is not None:
        runs["full-history-uncached"] = uncached
    _require_completed(runs, args.allow_failed)
    out = out_dir(args.out)
    write_inputs(out, command, runs)
    row = am.full_history_row(full)
    marks = {}
    if row["token_cache_ratio"] is not None:
        marks["c (tokens)"] = row["token_cache_ratio"]
    rows = {"cached": row}
    if uncached is not None:
        rows["uncached"] = am.full_history_row(uncached)
        gpu = am.gpu_cache_ratio(full, uncached)
        rows["gpu_cache_ratio"] = gpu
        if gpu["value"] is not None:
            marks["c (GPU s, upper)"] = gpu["value"]
    _dump(out, "full-history-row.json", rows)
    cs = sorted(set(am.grid(args.steps)) | set(marks.values()))
    series = {label: am.payback_curve(run, full, cs) for label, run in systems.items()}
    table = [(label, p.c, p.w, p.system_per_read, p.baseline_per_read, p.delta, p.m_star)
             for label, points in series.items() for p in points]
    plots.write_csv(out / "payback.csv", ("label", "c", "W", "system_per_read",
                                          "full_history_per_read", "delta", "m_star"), table)
    _dump(out, "payback-measured-c.json",
          {label: [p.to_dict() for p in points if p.c in marks.values()]
           for label, points in series.items()} | {"marks": marks})
    plots.payback_figure(series, marks, out / "payback.png")
    print(f"wrote {out}")
    print(json.dumps(rows, indent=2))
    return 0


def _metric(score_dir: Path, metric: str, annotation: str | None) -> dict:
    data = json.loads((score_dir / "metrics.json").read_text(encoding="utf-8"))["metrics"]
    found = [m for m in data if m["metric"] == metric and m["stratum"] is None
             and (annotation is None or m["annotation"] == annotation)]
    if len(found) != 1:
        raise SystemExit(f"{score_dir}: {len(found)} records of metric {metric!r} "
                         f"(annotation {annotation!r}, whole population); need exactly one")
    return found[0]


def _scored_run(score_dir: Path) -> Path:
    run = json.loads((score_dir / "run.json").read_text(encoding="utf-8"))
    systems = [u for u in run["upstream"] if u["stage"] in ("system", "read")]
    if len(systems) != 1:
        raise SystemExit(f"{score_dir}: score run has no single system or read upstream")
    return Path(systems[0]["path"])


def cmd_quality(args, command: str) -> int:
    scored = {label: (path, load_run(_scored_run(path))) for label, path in args.score}
    runs = {label: run for label, (_, run) in scored.items()}
    _require_completed(runs, args.allow_failed)
    out = out_dir(args.out)
    write_inputs(out, command, runs)
    points = []
    for label, (path, run) in scored.items():
        record = _metric(path, args.metric, args.annotation)
        per_read = am.mean_cost_per_read(run)
        points.append({"label": label, "value": record["value"], "n_scored": record["n_scored"],
                       "tokens": per_read[args.ledger], **{f"mean_{k}": v
                                                           for k, v in per_read.items()}})
    plots.write_csv(out / "quality.csv", ("label", "metric", "value", "n_scored",
                                          "mean_logical", "mean_computed", "mean_gpu_seconds"),
                    [(p["label"], args.metric, p["value"], p["n_scored"], p["mean_logical"],
                      p["mean_computed"], p["mean_gpu_seconds"]) for p in points])
    plots.quality_figure([p for p in points if p["value"] is not None], out / "quality.png",
                         metric=args.metric, unit=args.ledger)
    print(f"wrote {out}")
    return 0


def cmd_success(args, command: str) -> int:
    pairs = {}
    for label, spec in args.run:
        system, sep, judge = str(spec).partition(":")
        if not sep:
            raise SystemExit(f"{label}: expected RUN_DIR:JUDGE_RUN_DIR")
        pairs[label] = (load_run(Path(system)), Path(judge))
    runs = {label: run for label, (run, _) in pairs.items()}
    _require_completed(runs, args.allow_failed)
    out = out_dir(args.out)
    write_inputs(out, command, runs)
    rows = []
    for label, (run, judge_dir) in pairs.items():
        judgements = [json.loads(line) for line in
                      (judge_dir / "judgements.jsonl").read_text(encoding="utf-8").splitlines()
                      if line.strip()]
        success = am.success_from_judgements(judgements, args.judge)
        rows.append({"label": label, "judge_run": judge_dir.name,
                     **am.cost_per_success(run, success)})
    _dump(out, "cost-per-success.json", rows)
    plots.write_csv(out / "cost-per-success.csv",
                    ("label", "n_reads", "n_success", "success_rate", "ledger", "total",
                     "cost_per_success"),
                    [(r["label"], r["n_reads"], r["n_success"], r["success_rate"], ledger,
                      r["total"][ledger], r["cost_per_success"][ledger])
                     for r in rows for ledger in am.LEDGERS])
    plots.success_figure(rows, out / "cost-per-success.png", ledger=args.ledger)
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = " ".join(["python -m grace.cli.cost.report", *argv])
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ledger", help="three ledgers of one run, reconciled with its calls")
    p.add_argument("run", type=Path)
    p.add_argument("--json", type=Path, default=None)

    def common(p):
        p.add_argument("--out", type=Path, required=True,
                       help="new directory under the runs root")
        p.add_argument("--allow-failed", action="store_true",
                       help="include runs that are not completed (development only)")

    p = sub.add_parser("amortise", help="cumulative cost over reads")
    common(p)
    p.add_argument("--run", type=labelled, action="append", required=True)
    p.add_argument("--ledger", choices=am.LEDGERS, default="computed")
    p.add_argument("--price", type=float, default=None, help="price tokens at cache ratio C")
    p.add_argument("--seed", type=int, default=None,
                   help="draw the read order with this seed (default: the measured run order)")
    p.add_argument("--baseline", default=None, help="label to report crossing points against")

    p = sub.add_parser("payback", help="M* over the cache ratio, measured c marked")
    common(p)
    p.add_argument("--system", type=labelled, action="append", required=True)
    p.add_argument("--full-history", type=Path, required=True,
                   help="full-history run measured with prefix caching")
    p.add_argument("--uncached", type=Path, default=None,
                   help="the same reads on a server without prefix caching")
    p.add_argument("--steps", type=int, default=20)

    p = sub.add_parser("quality", help="quality against mean tokens per read")
    common(p)
    p.add_argument("--score", type=labelled, action="append", required=True)
    p.add_argument("--metric", required=True)
    p.add_argument("--annotation", default=None)
    p.add_argument("--ledger", choices=am.LEDGERS, default="computed")

    p = sub.add_parser("success", help="cost per successful task")
    common(p)
    p.add_argument("--run", type=labelled, action="append", required=True,
                   help="LABEL=SYSTEM_RUN_DIR:JUDGE_RUN_DIR")
    p.add_argument("--judge", default=None, help="judge config name in judgements.jsonl")
    p.add_argument("--ledger", choices=am.LEDGERS, default="computed")

    args = parser.parse_args(argv)
    if args.command == "ledger":
        return cmd_ledger(args)
    if args.command == "amortise" and args.price is not None and args.ledger != "computed":
        parser.error("give --price or --ledger, not both")
    handler = {"amortise": cmd_amortise, "payback": cmd_payback, "quality": cmd_quality,
               "success": cmd_success}[args.command]
    return handler(args, command)


if __name__ == "__main__":
    raise SystemExit(main())
