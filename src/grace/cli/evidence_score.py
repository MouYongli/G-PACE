"""Score stage: evidence in the working context of a system or read run (E013 metrics).

    uv run python -m grace.cli.evidence_score --run <system or read RUN_DIR> --experiment E013 \\
        --run-root "$PROJECT_ROOT/runs/E013/artifacts/<worker>"

Reads the run's `predictions.jsonl`, `resolved-config.yaml`, `traces/read.jsonl`,
`contexts.jsonl` and `calls.jsonl`, loads the read tasks, messages and gold of the same
development split through `load_split` (manifest checks), aligns them
(`eval/analysis/metrics/align.py`) and computes the metrics of
`eval/analysis/metrics/evidence.py`: full evidence hit (strict and lenient), evidence hit,
evidence recall and unsupported answers, overall and per stratum (LoCoMo `category`,
LongMemEval-S `question_type`), plus the mean context and answer-prompt tokens. These metrics are
not registered in `configs/common/scorers.yaml` (no answer scorer); their definitions are the
module's and the scorer name is `<benchmark>/evidence/<metric>`. Writes a new `score` run
directory with `run.json`, `resolved-config.yaml`, `run.log`, `metrics.json` (one `MetricRecord`
per metric and stratum), `tokens.json` and `scores.jsonl`. Development splits only.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

import yaml

from grace.config.paths import project_root, shared_dir
from grace.eval.analysis.metrics import evidence
from grace.eval.analysis.metrics.align import align, read_jsonl
from grace.eval.analysis.metrics.record import MetricRecord, aggregate, write_metrics
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.runner.harness import rundir

STRATA = {"locomo": "category", "longmemeval-s": "question_type"}
POLICY = "exclude_and_report"


def score_rows(aligned, gold: dict, traces: dict, contexts: dict, prompt: dict, label: str | None):
    """Per-read values, outputs and stratum labels of the scored reads; the excluded read IDs."""
    values, outputs, labels, excluded = {}, {}, {}, []
    for rid, a in aligned.items():
        g = gold[a.read_task["task_id"]]
        v = evidence.read_values(a.prediction, g, traces.get(rid))
        if v is None:
            excluded.append(rid)
            continue
        v["context_tokens"] = contexts[rid]["tokens"]
        v["prompt_tokens"] = prompt.get(rid)
        values[rid], outputs[rid] = v, a.output
        labels[rid] = None if label is None else str(g["labels"].get(label))
    return values, outputs, labels, excluded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run", type=Path, required=True, help="completed system or read run")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args(argv)

    system = json.loads((args.run / "run.json").read_text(encoding="utf-8"))
    if system["status"] != "completed" or system["stage"] not in ("system", "read"):
        parser.error(f"{system['run_id']}: not a completed system or read run")
    resolved = yaml.safe_load((args.run / "resolved-config.yaml").read_text(encoding="utf-8"))
    slug, split = resolved["benchmark"], resolved["split"]
    if load_config(slug).splits[split].kind != "development":
        parser.error("development splits only")
    if not str(args.run_root.resolve()).startswith(str(shared_dir("runs_root").resolve())):
        parser.error("--run-root must be under runs_root")

    run_dir = rundir.create(args.run_root, args.experiment)
    label = STRATA.get(slug)
    out = {"stage": "score", "experiment": args.experiment, "upstream_run": system["run_id"],
           "benchmark": slug, "split": split, "schedule": resolved["read_tasks"],
           "scorer": "grace.cli.evidence_score", "metrics": list(evidence.RATES),
           "tokens": list(evidence.TOKENS), "strata": label, "invalid_policy": POLICY}
    (run_dir / "resolved-config.yaml").write_text(yaml.safe_dump(out, sort_keys=False),
                                                  encoding="utf-8")
    code = rundir.code_state()
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": args.experiment, "stage": "score",
        "upstream": [{"run_id": system["run_id"], "stage": system["stage"],
                      "path": args.run.resolve().as_posix(),
                      "run_json_sha256": rundir.file_sha256(args.run / "run.json")}],
        "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": "src/grace/eval/analysis/metrics/evidence.py",
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": system["data"],
        "project_root": project_root().as_posix(), "seed": system["seed"],
        "command": " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment("cpu"), "held_out_access": "none"})
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    n = 0
    try:
        records = load_split(slug, split)
        histories = set(resolved["histories"])
        tasks = [t.to_record() for t in records.read_tasks if t.history_id in histories]
        messages = [m.to_record() for m in records.messages if m.history_id in histories]
        gold_rows = [g.to_record() for g in records.gold if g.history_id in histories]
        annotations = sorted({g["annotation"] for g in gold_rows})
        if len(annotations) != 1:
            raise ValueError(f"expected one gold annotation, found {annotations}")
        gold = {g["task_id"]: g for g in gold_rows}
        aligned = align(tasks, messages, gold_rows, read_jsonl(args.run / "predictions.jsonl"))
        traces = {t["read_id"]: t for t in read_jsonl(args.run / "traces" / "read.jsonl")}
        contexts = {c["read_id"]: c for c in read_jsonl(args.run / "contexts.jsonl")}
        prompt = evidence.answer_prompt_tokens(read_jsonl(args.run / "calls.jsonl"))
        values, outputs, labels, excluded = score_rows(aligned, gold, traces, contexts, prompt,
                                                       label)
        groups = [(None, list(values))]
        if label is not None:
            for value in sorted({v for v in labels.values()}):
                groups.append((f"{label}={value}", [r for r in values if labels[r] == value]))
        rows, tokens = [], {}
        for stratum, rids in groups:
            for metric in evidence.RATES:
                t = aggregate({r: values[r][metric] for r in rids},
                              {r: outputs[r] for r in rids}, POLICY)
                rows.append(MetricRecord(
                    benchmark=slug, split=split, schedule=resolved["read_tasks"],
                    annotation=annotations[0], metric=metric,
                    direction="lower" if metric == "unsupported_answer" else "higher",
                    stratum=stratum, seed=system["seed"], value=t.value, n_total=t.n_total,
                    n_scored=t.n_scored, n_invalid=t.n_invalid, n_unknown=t.n_unknown,
                    n_judge_invalid=0, invalid_policy=POLICY,
                    scorer=f"{slug}/evidence/{metric}", evaluator_version=code.sha))
            valid = [r for r in rids if outputs[r] != "invalid"]
            tokens[stratum or "all"] = {
                "n": len(valid),
                **{k: evidence.mean(values[r][k] for r in valid if values[r][k] is not None)
                   for k in evidence.TOKENS}}
        tokens["n_excluded_no_gold_evidence"] = len(excluded)
        write_metrics(run_dir / "metrics.json", rows)
        (run_dir / "tokens.json").write_text(json.dumps(tokens, indent=2) + "\n",
                                             encoding="utf-8")
        with (run_dir / "scores.jsonl").open("x", encoding="utf-8") as f:
            for rid in aligned:
                row = {"read_id": rid, "output": aligned[rid].output,
                       "excluded": rid in excluded, **values.get(rid, {})}
                f.write(json.dumps(row, sort_keys=True) + "\n")
        n = len(aligned)
        log.write(f"{n} reads, {len(excluded)} without gold evidence\n")
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
    raise SystemExit(main())
