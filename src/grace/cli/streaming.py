"""LoCoMo evidence-anchored streaming (task T031; plan 6.5): answer consistency of a system run.

The system run itself is an ordinary harness run on the streaming schedule:

    uv run python -m grace.eval.runner.harness.drive --engine configs/engines/grace.yaml \\
        --benchmark locomo --split dev --schedule streaming --history conv-26 --state-probe \\
        --backend client --base-url <chat endpoint> --embed-url <embedding endpoint> \\
        --experiment T031 --run-root "$PROJECT_ROOT/runs/T031/artifacts/<worker>"

`consistency` scores the v(q) and N answers of one completed streaming system run against the same
gold (`grace.eval.analysis.metrics.streaming`). It copies the records it scores against (streaming
read tasks of the run's histories and tasks, messages, gold) into `<out>/records/`, so the analysis
reads run-directory files only, and writes `<out>/pairs.jsonl` and `<out>/consistency.json`. It is
an unregistered analysis (no scorer of `configs/common/scorers.yaml`), not a `score` run:

    uv run python -m grace.cli.streaming consistency --run <system RUN_DIR> --out <new dir>

Development splits only; `--out` must be a new directory under runs_root.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT, shared_dir
from grace.eval.analysis.metrics import streaming as metric
from grace.eval.analysis.metrics.align import align, read_jsonl
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.locomo import STREAMING_SCHEDULE
from grace.eval.datasets.benchmarks.locomo_read_points import load_committed
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.runner.harness.rundir import code_state, file_sha256

SLUG = "locomo"


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def copy_records(run_dir: Path, resolved: dict[str, Any], out: Path) -> dict[str, Any]:
    """Write the records the run is scored against into `out/records/`; return data provenance."""
    if resolved.get("benchmark") != SLUG or resolved.get("read_tasks") != STREAMING_SCHEDULE:
        raise SystemExit(f"{run_dir}: not a LoCoMo streaming run (benchmark "
                         f"{resolved.get('benchmark')!r}, schedule {resolved.get('read_tasks')!r})")
    split = resolved["split"]
    config = load_config(SLUG)
    if config.splits[split].kind != "development":
        raise SystemExit(f"{SLUG}/{split} refused: development splits only")
    records = load_split(SLUG, split)
    histories = set(resolved["histories"])
    tasks = set(resolved["task_ids"]) if "task_ids" in resolved else None
    reads = [t.to_record() for t in records.schedules[STREAMING_SCHEDULE]
             if t.history_id in histories and (tasks is None or t.task_id in tasks)]
    task_ids = {r["task_id"] for r in reads}
    directory = out / "records"
    directory.mkdir(parents=True)
    write_jsonl(directory / STREAMING_SCHEDULE, reads)
    write_jsonl(directory / "histories.jsonl",
                (h.to_record() for h in records.histories if h.history_id in histories))
    write_jsonl(directory / "messages.jsonl",
                (m.to_record() for m in records.messages if m.history_id in histories))
    write_jsonl(directory / "gold.jsonl",
                (g.to_record() for g in records.gold if g.task_id in task_ids))
    read_points = config.options["streaming_read_points"]
    committed = load_committed(REPO_ROOT / read_points)
    separate = sorted(t for t in committed.get("reported_separately") or {}
                      if t in task_ids)
    (directory / "reported_separately.json").write_text(json.dumps(separate, indent=1) + "\n",
                                                        encoding="utf-8")
    return {"benchmark": SLUG, "split": split, "version": config.version,
            "manifest_sha256": config.manifest_sha256, "read_points": read_points}


def consistency(run_dir: Path, out: Path) -> dict[str, Any]:
    run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if run_json.get("status") != "completed":
        raise SystemExit(f"{run_dir}: run status {run_json.get('status')!r}, not completed")
    resolved = yaml.safe_load((run_dir / "resolved-config.yaml").read_text(encoding="utf-8"))
    out.mkdir(parents=True)
    data = copy_records(run_dir, resolved, out)
    records = out / "records"
    reads = read_jsonl(records / STREAMING_SCHEDULE)
    gold_rows = read_jsonl(records / "gold.jsonl")
    aligned = align(reads, read_jsonl(records / "messages.jsonl"), gold_rows,
                    read_jsonl(run_dir / "predictions.jsonl"))
    gold = {g["task_id"]: g for g in gold_rows}
    n_messages = {h["history_id"]: h["n_messages"]
                  for h in read_jsonl(records / "histories.jsonl")}
    separate = json.loads((records / "reported_separately.json").read_text(encoding="utf-8"))
    rows = metric.pair_rows(aligned, gold, n_messages, separate)
    write_jsonl(out / "pairs.jsonl", rows)
    code = code_state()
    result = {"analysis": "T031 streaming consistency (unregistered)",
              "system_run": {"run_id": run_json["run_id"], "path": run_dir.resolve().as_posix(),
                             "run_json_sha256": file_sha256(run_dir / "run.json"),
                             "engine_config": resolved.get("engine_config")},
              "code_sha": code.sha, "code_dirty": code.dirty, "data": data,
              "summary": metric.summarize(rows)}
    (out / "consistency.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cons = sub.add_parser("consistency", help="score v(q) and N answers of a streaming run")
    cons.add_argument("--run", type=Path, required=True, help="completed system RUN_DIR")
    cons.add_argument("--out", type=Path, required=True, help="new directory under runs_root")
    args = parser.parse_args(argv)
    runs = shared_dir("runs_root").resolve()
    out = args.out.resolve()
    if runs not in out.parents:
        parser.error(f"--out must lie under {runs}")
    if out.exists():
        parser.error(f"{out} exists; every invocation writes a new directory")
    result = consistency(args.run, out)
    print(json.dumps(result["summary"]["all"], indent=1))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
