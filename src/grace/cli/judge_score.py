"""Score stage of a system or read run with its registered judged metrics
(configs/common/scorers.yaml) and one judge run of it.

    uv run python -m grace.cli.judge_score --run <system or read RUN_DIR> \\
        --judge-run <judge RUN_DIR of that run> --run-root "$PROJECT_ROOT/runs/E012/artifacts/<w>"

Reads the run's `predictions.jsonl` and `resolved-config.yaml` (benchmark, split, schedule,
histories) and the judge run's `judgements.jsonl`, loads the read tasks, messages and gold of the
same development split through `load_split` (manifest checks), aligns them
(`eval/analysis/metrics/align.py`) and applies every registered metric of the benchmark whose
`judge` is the judge run's judge (`answer.judged_values`: `answer` reads take the verdict, a judge
verdict `invalid` leaves the denominator as `n_judge_invalid`, `unknown` is correct exactly on the
registered abstention tasks, `invalid` predictions follow the invalid-output policy). Writes a new
`score` run with `run.json`, `resolved-config.yaml`, `run.log`, `metrics.json` and `scores.jsonl`
(the value of every read). The experiment is the upstream run's unless `--experiment` is given.
Development splits only.
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
from grace.eval.analysis.judging.judge import read_judgements
from grace.eval.analysis.metrics.align import align, gold_index, read_jsonl
from grace.eval.analysis.metrics.record import MetricRecord, aggregate, write_metrics
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.runner.harness import rundir

SCORERS = REPO_ROOT / "configs" / "common" / "scorers.yaml"


def judged_metrics(benchmark: str, judge: str) -> list[dict]:
    """The registered metrics of `benchmark` judged by the judge config `judge`."""
    registry = yaml.safe_load(SCORERS.read_text(encoding="utf-8"))["benchmarks"][benchmark]
    return [m for m in registry["metrics"] if m.get("judge") == judge]


def _scorer(path: str):
    module, name = path.split(":")
    return getattr(importlib.import_module(module), name)


def in_population(labels: dict, population: dict) -> bool:
    include = population.get("include")
    return include is None or labels.get(include["label"]) in include["in"]


def score(aligned, gold: dict, verdicts: dict[str, str], metric: dict):
    """Per-read values, outputs, stratum labels and judge-invalid reads of one metric."""
    outputs, abstention, rows = {}, {}, {}
    rule = metric.get("abstention")
    for rid, a in aligned.items():
        g = gold.get(a.read_task["task_id"])
        if g is None or not in_population(g["labels"], metric["population"]):
            continue
        outputs[rid], rows[rid] = a.output, g["labels"]
        abstention[rid] = rule is not None and g["labels"].get(rule["label"]) == rule["value"]
    values, judge_invalid = _scorer(metric["code"])(verdicts, outputs, abstention)
    return values, outputs, rows, judge_invalid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run", type=Path, required=True, help="completed system or read RUN_DIR")
    parser.add_argument("--judge-run", type=Path, required=True,
                        help="completed judge RUN_DIR whose upstream is --run")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--experiment", default=None)
    args = parser.parse_args(argv)

    system = json.loads((args.run / "run.json").read_text(encoding="utf-8"))
    if system["status"] != "completed" or system["stage"] not in ("system", "read"):
        parser.error(f"{system['run_id']}: not a completed system or read run")
    judge_run = json.loads((args.judge_run / "run.json").read_text(encoding="utf-8"))
    if judge_run["status"] != "completed" or judge_run["stage"] != "judge":
        parser.error(f"{judge_run['run_id']}: not a completed judge run")
    up = judge_run["upstream"][0]
    if up["run_id"] != system["run_id"] or \
            up["run_json_sha256"] != rundir.file_sha256(args.run / "run.json"):
        parser.error(f"{judge_run['run_id']} did not judge {system['run_id']} as it is now")
    judge_cfg = yaml.safe_load((args.judge_run / "resolved-config.yaml").read_text("utf-8"))
    judge_name = judge_cfg["judge"]
    resolved = yaml.safe_load((args.run / "resolved-config.yaml").read_text(encoding="utf-8"))
    slug, split = resolved["benchmark"], resolved["split"]
    if load_config(slug).splits[split].kind != "development":
        parser.error("development splits only")
    if not str(args.run_root.resolve()).startswith(str(shared_dir("runs_root").resolve())):
        parser.error("--run-root must be under runs_root")
    metrics_spec = judged_metrics(slug, judge_name)
    if not metrics_spec:
        parser.error(f"{slug}: no registered metric is judged by {judge_name!r}")

    experiment = args.experiment or system["experiment"]
    run_dir = rundir.create(args.run_root, experiment)
    out = {"stage": "score", "experiment": experiment, "system_run": system["run_id"],
           "judge_run": judge_run["run_id"], "judge": judge_name,
           "judge_config_sha256": judge_cfg.get("judge_config_sha256"), "benchmark": slug,
           "split": split, "schedule": resolved["read_tasks"], "metrics": metrics_spec}
    (run_dir / "resolved-config.yaml").write_text(yaml.safe_dump(out, sort_keys=False),
                                                  encoding="utf-8")
    code = rundir.code_state()
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": experiment, "stage": "score",
        "upstream": [{"run_id": r["run_id"], "stage": r["stage"], "path": p.resolve().as_posix(),
                      "run_json_sha256": rundir.file_sha256(p / "run.json")}
                     for r, p in ((system, args.run), (judge_run, args.judge_run))],
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
        if resolved["read_tasks"] != "read_tasks.jsonl":
            raise ValueError(f"schedule {resolved['read_tasks']!r}: native schedule only")
        records = load_split(slug, split)
        histories = set(resolved["histories"])
        tasks = [t.to_record() for t in records.read_tasks if t.history_id in histories]
        messages = [m.to_record() for m in records.messages if m.history_id in histories]
        gold_rows = [g.to_record() for g in records.gold if g.history_id in histories]
        aligned = align(tasks, messages, gold_rows, read_jsonl(args.run / "predictions.jsonl"))
        judgements = read_judgements(args.judge_run / "judgements.jsonl", judge_name)
        verdicts = {rid: j.verdict for rid, j in judgements.items()}
        rows, per_read = [], defaultdict(dict)
        for m in metrics_spec:
            gold = gold_index(gold_rows, str(m["annotation"]))
            for rid, j in judgements.items():
                if j.annotation != str(m["annotation"]):
                    raise ValueError(f"{rid}: judged against annotation {j.annotation}, metric "
                                     f"{m['name']} scores {m['annotation']}")
            values, outputs, labels, judge_invalid = score(aligned, gold, verdicts, m)
            for rid, v in values.items():
                per_read[rid][m["name"]] = v
            groups = [(None, list(values))]
            for label in m.get("strata") or []:
                for value in sorted({str(labels[r].get(label)) for r in values}):
                    groups.append((f"{label}={value}",
                                   [r for r in values if str(labels[r].get(label)) == value]))
            for stratum, rids in groups:
                t = aggregate({r: values[r] for r in rids}, {r: outputs[r] for r in rids},
                              m["invalid_policy"], judge_invalid & frozenset(rids))
                rows.append(MetricRecord(
                    benchmark=slug, split=split, schedule=resolved["read_tasks"],
                    annotation=str(m["annotation"]), metric=m["name"],
                    direction=m["direction"], stratum=stratum, seed=system["seed"],
                    value=t.value, n_total=t.n_total, n_scored=t.n_scored,
                    n_invalid=t.n_invalid, n_unknown=t.n_unknown,
                    n_judge_invalid=t.n_judge_invalid, invalid_policy=m["invalid_policy"],
                    scorer=f"{slug}/{m['name']}", evaluator_version=code.sha))
        write_metrics(run_dir / "metrics.json", rows)
        with (run_dir / "scores.jsonl").open("x", encoding="utf-8") as f:
            for rid, a in aligned.items():
                f.write(json.dumps({"read_id": rid, "output": a.output,
                                    "verdict": verdicts.get(rid), **per_read[rid]},
                                   sort_keys=True) + "\n")
        n = len(aligned)
        log.write(f"{n} reads scored\n")
        for r in rows:
            log.write(f"{r.metric} {r.stratum or 'all'}: {r.value} ({r.n_scored}/{r.n_total}, "
                      f"judge invalid {r.n_judge_invalid})\n")
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
