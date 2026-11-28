"""Score stage of a LoCoMo system or read run with the registered scorer (scorers.yaml).

    uv run python -m grace.cli.locomo_score --run <system RUN_DIR> --experiment E007 \\
        --run-root "$PROJECT_ROOT/runs/E007/artifacts/<worker>"

Reads the run's `predictions.jsonl` and `resolved-config.yaml` (benchmark, split, schedule,
histories), loads the read tasks, messages and gold of the same development split through
`load_split` (manifest checks), aligns them (`eval/analysis/metrics/align.py`: every read
answered, nothing cited from after the read) and applies the registered LoCoMo metrics that need no
judge: `f1` (categories 1-4, strata by category) and `f1-adversarial` (category 5), each with its
registered population, annotation and invalid-output policy, through
`answer.locomo_score` and `record.aggregate`. Writes a new `score` run directory with `run.json`,
`resolved-config.yaml`, `run.log`, `metrics.json` (one `MetricRecord` per metric and stratum) and
`scores.jsonl` (the value of every read). Development splits only.
"""

from __future__ import annotations

import argparse
import importlib
import json
import shlex
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.eval.analysis.metrics.align import align, gold_index, read_jsonl
from grace.eval.analysis.metrics.record import MetricRecord, aggregate, write_metrics
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.runner.harness import rundir

SCORERS = REPO_ROOT / "configs" / "common" / "scorers.yaml"
SLUG = "locomo"


def registered_metrics() -> list[dict]:
    """The LoCoMo metrics of the registry that are scored by rule (no judge)."""
    registry = yaml.safe_load(SCORERS.read_text(encoding="utf-8"))["benchmarks"][SLUG]
    return [m for m in registry["metrics"] if "judge" not in m]


def _scorer(path: str):
    module, name = path.split(":")
    return getattr(importlib.import_module(module), name)


def score(aligned, gold, metric: dict) -> tuple[dict, dict, dict]:
    """Per-read values, outputs and categories of one metric's population."""
    population = metric["population"]["include"]
    fn = _scorer(metric["code"])
    values, outputs, labels = {}, {}, {}
    for rid, a in aligned.items():
        g = gold[a.read_task["task_id"]]
        label = g["labels"][population["label"]]
        if label not in population["in"]:
            continue
        outputs[rid], labels[rid] = a.output, label
        values[rid] = (None if a.output == "invalid"
                       else fn(int(g["labels"]["category"]), a.output,
                               a.prediction["prediction"], g["reference"]))
    return values, outputs, labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run", type=Path, required=True,
                        help="completed system or read RUN_DIR")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args(argv)

    system = json.loads((args.run / "run.json").read_text(encoding="utf-8"))
    if system["status"] != "completed" or system["stage"] not in ("system", "read"):
        parser.error(f"{system['run_id']}: not a completed system or read run")
    resolved = yaml.safe_load((args.run / "resolved-config.yaml").read_text(encoding="utf-8"))
    if resolved["benchmark"] != SLUG:
        parser.error(f"{system['run_id']}: benchmark {resolved['benchmark']!r}, not {SLUG}")
    split = resolved["split"]
    if load_config(SLUG).splits[split].kind != "development":
        parser.error("development splits only")
    if not str(args.run_root.resolve()).startswith(str(shared_dir("runs_root").resolve())):
        parser.error("--run-root must be under runs_root")

    run_dir = rundir.create(args.run_root, args.experiment)
    metrics_spec = registered_metrics()
    out = {"stage": "score", "experiment": args.experiment, "system_run": system["run_id"],
           "benchmark": SLUG, "split": split, "schedule": resolved["read_tasks"],
           "metrics": metrics_spec}
    (run_dir / "resolved-config.yaml").write_text(yaml.safe_dump(out, sort_keys=False),
                                                  encoding="utf-8")
    code = rundir.code_state()
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": args.experiment, "stage": "score",
        "upstream": [{"run_id": system["run_id"], "stage": system["stage"],
                      "path": args.run.resolve().as_posix(),
                      "run_json_sha256": rundir.file_sha256(args.run / "run.json")}],
        "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": "configs/common/scorers.yaml",
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": system["data"],
        "project_root": project_root().as_posix(), "seed": system["seed"],
        "command": " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment("cpu"), "held_out_access": "none"})
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    n = 0
    try:
        records = load_split(SLUG, split)
        histories = set(resolved["histories"])
        if resolved["read_tasks"] != "read_tasks.jsonl":
            raise ValueError(f"schedule {resolved['read_tasks']!r}: native schedule only")
        tasks = [t.to_record() for t in records.read_tasks if t.history_id in histories]
        messages = [m.to_record() for m in records.messages if m.history_id in histories]
        gold_rows = [g.to_record() for g in records.gold if g.history_id in histories]
        predictions = read_jsonl(args.run / "predictions.jsonl")
        aligned = align(tasks, messages, gold_rows, predictions)
        rows, per_read = [], defaultdict(dict)
        for m in metrics_spec:
            gold = gold_index(gold_rows, str(m["annotation"]))
            values, outputs, labels = score(aligned, gold, m)
            for rid, v in values.items():
                per_read[rid][m["name"]] = v
            groups = [(None, list(values))]
            for label in m.get("strata") or []:
                for value in sorted(set(labels.values())):
                    groups.append((f"{label}={value}",
                                   [r for r in values if labels[r] == value]))
            for stratum, rids in groups:
                t = aggregate({r: values[r] for r in rids}, {r: outputs[r] for r in rids},
                              m["invalid_policy"])
                rows.append(MetricRecord(
                    benchmark=SLUG, split=split, schedule=resolved["read_tasks"],
                    annotation=str(m["annotation"]), metric=m["name"],
                    direction=m["direction"], stratum=stratum, seed=system["seed"],
                    value=t.value, n_total=t.n_total, n_scored=t.n_scored,
                    n_invalid=t.n_invalid, n_unknown=t.n_unknown,
                    n_judge_invalid=t.n_judge_invalid, invalid_policy=m["invalid_policy"],
                    scorer=f"{SLUG}/{m['name']}", evaluator_version=code.sha))
        write_metrics(run_dir / "metrics.json", rows)
        with (run_dir / "scores.jsonl").open("x", encoding="utf-8") as f:
            for rid, a in aligned.items():
                f.write(json.dumps({"read_id": rid, "output": a.output, **per_read[rid]},
                                   sort_keys=True) + "\n")
        n = len(aligned)
        log.write(f"{n} reads scored\n")
        for r in rows:
            log.write(f"{r.metric} {r.stratum or 'all'}: {r.value} ({r.n_scored}/{r.n_total})\n")
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        log.write(f"{type(exc).__name__}: {exc}\n")
        log.close()
        run.finish(n, f"{type(exc).__name__}: {exc}")
        raise
    log.close()
    run.finish(n)
    print(f"{run_dir} {run.data['status']}")
    return 0 if run.data["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
