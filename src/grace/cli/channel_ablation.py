"""E012 (ablation D, retrieval channels): evidence and answer metrics per arm (stage `score`).

    uv run python -m grace.cli.channel_ablation --experiment E012 \\
        --run-root "$PROJECT_ROOT/runs/E012/artifacts/<worker>" \\
        --arm full=<read RUN_DIR> --arm no-bm25=<read RUN_DIR> ... \\
        [--score full=<score RUN_DIR> ...] [--reference full]

Every arm is a completed `read` (or `system`) run of the same benchmark, split, histories and
budget. Gold comes from the development split through `load_split` (manifest checks); the read
runs contribute only their own files (`predictions.jsonl`, `contexts.jsonl`, `traces/read.jsonl`,
`calls.jsonl`). Per read and arm:

- `fused_recall`: share of the gold evidence messages among the fused candidates;
- `strict_recall`, `full_hit`: share of the gold evidence shown as raw text (`included_ids`), and
  whether all of it is;
- `path_recall`: share of the gold evidence the context rests on, raw text or cited by a state
  item (the union of the trace's `provenance`; "lenient recall" of contracts.md);
- `graph_candidates` (the graph channel returned at least one candidate), `state_shown` (the
  context holds a claim or view fragment), `unknown` (the answer output is `unknown`);
- `read_tokens` (planning and other read-side calls, category U) and `answer_tokens` (A);
- `f1`, when a LoCoMo score run of the arm is given (`scores.jsonl`, registered F1 of categories
  1-4; category 5 is scored by `f1-adversarial` and has no `f1`).

Aggregates are means over reads, overall and per stratum (LoCoMo `category`, LongMemEval
`question_type`). Against `--reference`, each metric also gets the paired mean difference with a
95% bootstrap interval over reads (seed 0, 2,000 resamples; reads, not histories, are resampled:
development diagnostics, not a formal test). `unique` counts, for the reference arm, the gold
evidence messages among the fused candidates that exactly one channel ranked (within its depth):
what each channel contributes that the others do not, at the candidate level.

Writes a new score run with `run.json`, `resolved-config.yaml`, `run.log`, `channels.json` and
`per_read.jsonl`. Development splits only.
"""

from __future__ import annotations

import argparse
import json
import random
import shlex
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from grace.config.paths import project_root, shared_dir
from grace.eval.analysis.metrics.align import read_jsonl
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.runner.harness import rundir

STRATA = ("category", "question_type")
METRICS = ("f1", "unknown", "fused_recall", "strict_recall", "full_hit", "path_recall",
           "graph_candidates", "state_shown", "read_tokens", "answer_tokens")
SAME = ("benchmark", "split", "histories", "budget_tokens", "read_tasks")


def _pairs(values: list[str], flag: str) -> dict[str, Path]:
    out = {}
    for v in values or []:
        name, sep, path = v.partition("=")
        if not sep or not name or name in out:
            raise SystemExit(f"{flag} {v!r}: expected a unique NAME=RUN_DIR")
        out[name] = Path(path)
    return out


def _share(gold: set[str], shown: set[str]) -> float | None:
    return len(gold & shown) / len(gold) if gold else None


def read_metrics(run: Path, gold: dict[str, dict], scores: Path | None) -> dict[str, dict]:
    """Per-read metrics of one arm, keyed by read ID."""
    traces = {t["read_id"]: t for t in read_jsonl(run / "traces" / "read.jsonl")}
    contexts = {c["read_id"]: c for c in read_jsonl(run / "contexts.jsonl")}
    tokens: dict[str, Counter] = defaultdict(Counter)
    for call in read_jsonl(run / "calls.jsonl"):
        if call.get("read_id"):
            tokens[call["read_id"]][call["category"]] += (call.get("input_tokens") or 0) + \
                (call.get("output_tokens") or 0)
    f1 = {}
    if scores is not None:
        f1 = {s["read_id"]: s.get("f1") for s in read_jsonl(scores / "scores.jsonl")}
    out = {}
    for p in read_jsonl(run / "predictions.jsonl"):
        rid = p["read_id"]
        g, t = gold[p["task_id"]], traces[rid]
        evidence = set(g["evidence_ids"] or ())
        fused = {c["id"] for c in t["candidates"] if c["channel"] == "fused"}
        path = {e for ids in t["provenance"].values() for e in ids}
        kinds = {f["kind"] for f in contexts[rid]["fragments"]}
        strict = _share(evidence, set(t["included_ids"]))
        out[rid] = {
            "task_id": p["task_id"],
            "stratum": next((str(g["labels"][k]) for k in STRATA if k in g["labels"]), None),
            "f1": f1.get(rid),
            "unknown": float(p["output"] == "unknown"),
            "fused_recall": _share(evidence, fused),
            "strict_recall": strict,
            "full_hit": None if strict is None else float(strict == 1.0),
            "path_recall": _share(evidence, path),
            "graph_candidates": float(any(c["channel"] == "graph" for c in t["candidates"])),
            "state_shown": float(bool(kinds & {"claim", "view"})),
            "read_tokens": float(tokens[rid]["U"]),
            "answer_tokens": float(tokens[rid]["A"]),
            "_channels": {ch: {c["id"] for c in t["candidates"] if c["channel"] == ch}
                          for ch in ("bm25", "dense", "graph")},
            "_fused": fused, "_evidence": evidence,
        }
    return out


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def aggregate(rows: dict[str, dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {"all": list(rows.values())}
    for r in rows.values():
        if r["stratum"] is not None:
            groups.setdefault(f"stratum={r['stratum']}", []).append(r)
    return {name: {"n": len(rs), **{m: _mean(r[m] for r in rs) for m in METRICS}}
            for name, rs in sorted(groups.items())}


def paired(arm: dict[str, dict], ref: dict[str, dict], seed: int = 0, n_boot: int = 2000
           ) -> dict[str, dict]:
    """Paired mean difference arm - reference per metric and stratum, with a bootstrap CI."""
    rng = random.Random(seed)
    out: dict[str, dict] = {}
    groups: dict[str, list[str]] = {"all": sorted(arm)}
    for rid in sorted(arm):
        if arm[rid]["stratum"] is not None:
            groups.setdefault(f"stratum={arm[rid]['stratum']}", []).append(rid)
    for name, rids in sorted(groups.items()):
        out[name] = {}
        for m in METRICS:
            d = [arm[r][m] - ref[r][m] for r in rids
                 if arm[r][m] is not None and ref[r][m] is not None]
            if not d:
                continue
            boots = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(n_boot))
            out[name][m] = {"diff": sum(d) / len(d), "ci95": [boots[int(0.025 * n_boot)],
                                                               boots[int(0.975 * n_boot) - 1]],
                            "worse": sum(x < 0 for x in d), "better": sum(x > 0 for x in d),
                            "n": len(d)}
    return out


def unique(rows: dict[str, dict]) -> dict[str, dict]:
    """Gold evidence among the fused candidates, by the set of channels that ranked it."""
    out: dict[str, Counter] = defaultdict(Counter)
    for r in rows.values():
        for e in r["_evidence"] & r["_fused"]:
            by = tuple(ch for ch, ids in r["_channels"].items() if e in ids)
            key = f"only_{by[0]}" if len(by) == 1 else "+".join(by) or "none"
            out["all"][key] += 1
            if r["stratum"] is not None:
                out[f"stratum={r['stratum']}"][key] += 1
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--arm", action="append", required=True, help="NAME=read RUN_DIR")
    parser.add_argument("--score", action="append", default=[], help="NAME=score RUN_DIR")
    parser.add_argument("--reference", default=None, help="arm the others are paired against")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args(argv)
    arms, scores = _pairs(args.arm, "--arm"), _pairs(args.score, "--score")
    reference = args.reference or next(iter(arms))
    if reference not in arms or set(scores) - set(arms):
        parser.error("--reference and every --score must name an --arm")
    if not str(args.run_root.resolve()).startswith(str(shared_dir("runs_root").resolve())):
        parser.error("--run-root must be under runs_root")

    runs, resolved = {}, {}
    for name, path in arms.items():
        runs[name] = json.loads((path / "run.json").read_text(encoding="utf-8"))
        resolved[name] = yaml.safe_load((path / "resolved-config.yaml").read_text("utf-8"))
        if runs[name]["status"] != "completed" or runs[name]["stage"] not in ("read", "system"):
            parser.error(f"{name}: {runs[name]['run_id']} is not a completed read or system run")
    first = resolved[reference]
    for name, r in resolved.items():
        if (diff := [k for k in SAME if r.get(k) != first.get(k)]):
            parser.error(f"{name}: differs from {reference} in {diff}")
    for name, path in scores.items():
        s = json.loads((path / "run.json").read_text(encoding="utf-8"))
        if s["status"] != "completed" or s["upstream"][0]["run_id"] != runs[name]["run_id"]:
            parser.error(f"{name}: {s['run_id']} is not a completed score of {name}'s run")
    slug, split = first["benchmark"], first["split"]
    if load_config(slug).splits[split].kind != "development":
        parser.error("development splits only")

    run_dir = rundir.create(args.run_root, args.experiment)
    config = {"stage": "score", "experiment": args.experiment, "benchmark": slug, "split": split,
              "budget_tokens": first["budget_tokens"], "reference": reference,
              "arms": {n: {"run_id": runs[n]["run_id"], "engine_config": runs[n]["config_path"],
                           "score_run": (json.loads((scores[n] / "run.json").read_text(
                               encoding="utf-8"))["run_id"] if n in scores else None)}
                       for n in arms},
              "metrics": list(METRICS), "bootstrap": {"seed": 0, "resamples": 2000}}
    (run_dir / "resolved-config.yaml").write_text(yaml.safe_dump(config, sort_keys=False),
                                                  encoding="utf-8")
    code = rundir.code_state()
    upstream = [{"run_id": runs[n]["run_id"], "stage": runs[n]["stage"],
                 "path": arms[n].resolve().as_posix(),
                 "run_json_sha256": rundir.file_sha256(arms[n] / "run.json")} for n in arms]
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": args.experiment, "stage": "score",
        "upstream": upstream, "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": "src/grace/cli/channel_ablation.py",
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": runs[reference]["data"],
        "project_root": project_root().as_posix(), "seed": 0,
        "command": " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment("cpu"), "held_out_access": "none"})
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    n = 0
    try:
        records = load_split(slug, split)
        histories = set(first["histories"])
        gold = {g.task_id: g.to_record() for g in records.gold if g.history_id in histories}
        rows = {name: read_metrics(path, gold, scores.get(name)) for name, path in arms.items()}
        for name, r in rows.items():
            if set(r) != set(rows[reference]):
                raise ValueError(f"{name}: read IDs differ from {reference}")
        result = {"reference": reference, "unique_reference": unique(rows[reference]),
                  "arms": {name: {"run_id": runs[name]["run_id"], "aggregate": aggregate(r),
                                  "vs_reference": (paired(r, rows[reference])
                                                   if name != reference else None)}
                           for name, r in rows.items()}}
        (run_dir / "channels.json").write_text(json.dumps(result, indent=1, sort_keys=True),
                                               encoding="utf-8")
        with (run_dir / "per_read.jsonl").open("x", encoding="utf-8") as f:
            for name, r in rows.items():
                for rid in sorted(r):
                    f.write(json.dumps({"arm": name, "read_id": rid,
                                        **{k: v for k, v in r[rid].items()
                                           if not k.startswith("_")}}, sort_keys=True) + "\n")
        n = len(rows[reference])
        log.write(f"{len(arms)} arms x {n} reads\n")
        for name, r in result["arms"].items():
            a = r["aggregate"]["all"]
            log.write(f"{name}: " + " ".join(
                f"{m}={a[m]:.3f}" for m in METRICS if a[m] is not None) + "\n")
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
