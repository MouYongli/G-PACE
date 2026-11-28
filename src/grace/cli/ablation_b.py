"""E011, ablation B: attribution guard x representation x time, with the single arms (plan 7.3, B).

    uv run python -m grace.cli.ablation_b system --config configs/experiments/E011-ablation-b-\
attribution-guard.yaml --arm graph-guard-bi --benchmark multiwoz --shard 0/8 \\
        --base-url http://localhost:8252/v1 --embed-url http://localhost:8251/v1 \\
        --writer-url http://localhost:8253/v1
    uv run python -m grace.cli.ablation_b score --config <config> --benchmark multiwoz \\
        --system <shard run dir> [<shard run dir> ...]
    uv run python -m grace.cli.ablation_b compare --config <config> --benchmark multiwoz \\
        --arm graph-guard-bi=<score run dir> --arm tagged=<score run dir> ... --out <dir>

- `system` (stage `system`): one arm (an engine config of the experiment config) on one shard of
  the benchmark's population, through the common harness (`runner/harness/drive.run_system`).
  MultiWOZ: the seeded dialogue subset and only its offer-turn reads (the config's `population`);
  change-seq: every sequence of the inline development config, native schedule.
- `score` (stage `score`): the per-item values of every E011 metric over the population, from the
  predictions of one arm (its shards) or of an external run that covers the population; writes
  `scores.jsonl` (metric, key, value, cluster, output), `summary.json` (value, n, cluster-bootstrap
  95% interval) and `metrics.json`.
- `compare` (not a run): the config's contrasts as paired differences with 95% cluster-bootstrap
  intervals (`eval/analysis/metrics/changeseq.paired_bootstrap`, D002), and the share of the guard
  gain that the tag obtains, written with the checksum of every input run.json to
  `<out>/summary.json`.

Development data only; selection of the MultiWOZ reads uses the derived offer-turn gold of the
development split, which never reaches an engine.
"""

from __future__ import annotations

import argparse
import json
import random
import shlex
import sys
import traceback
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.eval.analysis.metrics import changeseq as csm
from grace.eval.analysis.metrics import dst
from grace.eval.analysis.metrics.align import align, read_jsonl
from grace.eval.analysis.metrics.record import MetricRecord, aggregate, write_metrics
from grace.eval.datasets.benchmarks import multiwoz_derived
from grace.eval.datasets.benchmarks import multiwoz_offers as mo
from grace.eval.datasets.benchmarks.base import BenchmarkConfig, load_config
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.runner.harness import drive, rundir
from grace.eval.runner.harness.drive import ClientSettings

EXPERIMENT = "E011"
BENCHMARKS = ("multiwoz", "change-seq")
RESAMPLES = 10_000
ANN_D = multiwoz_derived.ANNOTATION
MW_ANNOTATIONS = ("2.4", "2.2", "2.1")


def default_root() -> Path:
    return shared_dir("runs_root") / EXPERIMENT / "artifacts" / "w01-E011"


def load_experiment(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for key in ("experiment", "seed", "models", "arms", "benchmarks", "contrasts"):
        if key not in config:
            raise ValueError(f"{path}: missing {key!r}")
    if config["experiment"] != EXPERIMENT:
        raise ValueError(f"{path}: experiment is {config['experiment']!r}")
    return config


def repo_relative(path: Path) -> str:
    return drive.repo_relative(Path(path))


# ---------------------------------------------------------------------------------------------
# Populations


def mw_derived(history_ids: Sequence[str] | None = None, split: str = "dev") -> dict[str, dict]:
    """task_id -> derived offer-turn gold record (2.4-current-choice) of the development split."""
    records = load_split("multiwoz", split)
    ids = sorted(history_ids) if history_ids is not None else sorted(
        {m.history_id for m in records.messages})
    config = load_config("multiwoz")
    root = project_root()
    sources = {v: config.source_dir(root, v) for v in config.manifests()}
    dialogues, _ = mo.load_dialogues(sources, ids, config.options["split_dirs_22"][split],
                                     keep_text=False)
    return {g.task_id: g.to_record()
            for g in multiwoz_derived.derive_all(dialogues, "multiwoz", split)}


def mw_population(spec: Mapping[str, Any], split: str = "dev",
                  derived: Mapping[str, dict] | None = None) -> tuple[list[str], list[str]]:
    """(dialogue IDs, offer-turn task IDs) of the seeded subset (config `population`)."""
    derived = derived if derived is not None else mw_derived(None, split)
    pool = sorted({g["history_id"] for g in derived.values() if g["reference"]["paired"]})
    n = int(spec["sample"])
    if n > len(pool):
        raise ValueError(f"sample {n} exceeds the pool of {len(pool)} dialogues")
    chosen = sorted(random.Random(int(spec["sample_seed"])).sample(pool, n))
    wanted = set(chosen)
    tasks = sorted(t for t, g in derived.items() if g["history_id"] in wanted)
    return chosen, tasks


def cs_config(config: Mapping[str, Any]) -> BenchmarkConfig:
    spec = config["benchmarks"]["change-seq"]
    bc = BenchmarkConfig.from_dict(spec["config"])
    if bc.splits[spec["split"]].kind != "development":
        raise ValueError("E011 reads development splits only")
    return bc


def shard(items: Sequence[str], spec: str | None) -> list[str]:
    if not spec:
        return list(items)
    i, n = (int(x) for x in spec.split("/"))
    if not 0 <= i < n:
        raise ValueError(f"bad shard {spec!r}")
    return [x for k, x in enumerate(items) if k % n == i]


# ---------------------------------------------------------------------------------------------
# system


def cmd_system(args, config: Mapping[str, Any], command: str) -> int:
    arm = config["arms"].get(args.arm)
    if arm is None:
        raise SystemExit(f"unknown arm {args.arm!r}; one of {sorted(config['arms'])}")
    spec = config["benchmarks"][args.benchmark]
    client = ClientSettings(args.base_url, REPO_ROOT / config["models"]["answer"], args.embed_url,
                            writer_url=args.writer_url)
    common = dict(engine_config=REPO_ROOT / arm["engine"], budget=int(spec["budget"]),
                  experiment=EXPERIMENT, run_root=args.out_root or default_root(),
                  split=spec["split"], seed=int(config["seed"]), client=client, command=command)
    if args.benchmark == "multiwoz":
        histories, tasks = mw_population(spec["population"], spec["split"])
        histories = shard(histories, args.shard)
        keep = {h for h in histories}
        tasks = [t for t in tasks if t.split(":", 1)[0] in keep]
        result = drive.run_system(benchmark="multiwoz", history_ids=histories, task_ids=tasks,
                                  **common)
    else:
        bc = cs_config(config)
        histories = shard(list(bc.splits[spec["split"]].histories), args.shard)
        result = drive.run_system(benchmark="change-seq", schedule=spec.get("schedule"),
                                  history_ids=histories, benchmark_config=bc, **common)
    print(f"{result.run_id}: {result.status} ({result.n_reads} reads, arm {args.arm}"
          f"{', label ' + args.label if args.label else ''}) -> {result.run_dir}")
    if args.label:
        (result.run_dir / "E011-label.txt").write_text(f"{args.arm} {args.label}\n",
                                                        encoding="utf-8")
    return 0 if result.status == "completed" else 1


# ---------------------------------------------------------------------------------------------
# score


def _upstream(run_dir: Path) -> dict[str, Any]:
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if run.get("status") != "completed":
        raise ValueError(f"{run_dir.name}: upstream run is {run.get('status')!r}")
    if run.get("stage") not in ("system", "read"):
        raise ValueError(f"{run_dir.name}: stage {run.get('stage')!r}, expected system or read")
    return {"run_id": run["run_id"], "stage": run["stage"], "path": run_dir.as_posix(),
            "run_json_sha256": rundir.file_sha256(run_dir / "run.json"), "seed": run["seed"]}


def _predictions(runs: Sequence[Path], wanted_tasks: set[str]) -> list[dict]:
    """Predictions of the population tasks (runs may cover more); every task exactly once."""
    out, seen = [], set()
    for r in runs:
        for p in read_jsonl(r / "predictions.jsonl"):
            if p["task_id"] in wanted_tasks:
                if p["task_id"] in seen:
                    raise ValueError(f"task {p['task_id']} predicted twice")
                seen.add(p["task_id"])
                out.append(p)
    missing = wanted_tasks - seen
    if missing:
        raise ValueError(f"{len(missing)} population tasks have no prediction, e.g. "
                         f"{sorted(missing)[:3]}")
    return out


def _match(a: str, b: str) -> bool:
    a, b = " ".join(a.lower().split()), " ".join(b.lower().split())
    return a == b or mo.values_match(a, b)


def mw_values(aligned: Mapping[str, Any], gold_by_ann: Mapping[str, Mapping[str, dict]],
              derived: Mapping[str, dict]) -> list[dict[str, Any]]:
    """Per-item values of the MultiWOZ metrics (the T028 definitions, lenient values_match as the
    registered primary) plus `offer_overwrite` and the non-train paired stratum."""
    from grace.cli.multiwoz import score_values  # the T028 scorer, unchanged

    values = score_values(aligned, gold_by_ann, derived)
    rows = []
    for metric, m in values.items():
        name, _, rest = metric.partition("|")
        if "-exact" in name or name.startswith(("slot-f1", "jga-lenient")):
            continue
        if name == "jga" and rest != "2.4":
            continue
        stratum = rest.split("|", 1)[1] if "|" in rest else None
        if stratum and not stratum.startswith(("conflict=", "domain=")):
            continue
        label = name if stratum is None else f"{name}|{stratum}"
        for key, value in m["values"].items():
            output = m["outputs"][key]
            rows.append({"metric": label, "key": key, "value": 0.0 if output == "invalid"
                         else value, "cluster": m["cluster"][key], "output": output})
            if name == "paired_correct" and stratum and stratum.startswith("domain=") \
                    and stratum != "domain=train":
                rows.append({**rows[-1], "metric": "paired_correct|domain!=train"})
    for rid, a in aligned.items():
        item = derived.get(a.read_task["task_id"])
        if item is None:
            continue
        pred = dst.normalise_state(a.prediction["prediction"]
                                   if a.prediction["output"] == "state" else None)
        for i, r in enumerate(item["reference"]["retention"]):
            if not r["conflict"]:
                continue
            value = pred.get(r["slot"])
            over = (value is not None and not _match(value, r["original"])
                    and any(_match(value, o) for o in r["offered"]))
            rows.append({"metric": "offer_overwrite|conflict=true", "key": f"{rid}#r{i}",
                         "value": 1.0 if over else 0.0, "cluster": a.read_task["history_id"],
                         "output": a.prediction["output"]})
    return [r for r in rows if not r["metric"].startswith("paired_correct|domain=")]


def score_multiwoz(config, runs: Sequence[Path]) -> tuple[list[dict], list[dict], str]:
    spec = config["benchmarks"]["multiwoz"]
    split = spec["split"]
    derived_all = mw_derived(None, split)
    histories, tasks = mw_population(spec["population"], split, derived_all)
    wanted = set(tasks)
    predictions = _predictions(runs, wanted)
    records = load_split("multiwoz", split)
    hset = set(histories)
    read_tasks = [t.to_record() for t in records.schedules["read_tasks.jsonl"]
                  if t.task_id in wanted]
    messages = [m.to_record() for m in records.messages if m.history_id in hset]
    gold = [g.to_record() for g in records.gold if g.task_id in wanted]
    aligned = align(read_tasks, messages, gold, predictions)
    gold_by_ann = {ann: {g["task_id"]: g for g in gold if g["annotation"] == ann}
                   for ann in MW_ANNOTATIONS}
    derived = {t: derived_all[t] for t in tasks}
    data = [{"benchmark": "multiwoz", "version": records.version if hasattr(records, "version")
             else None, "split": split}]
    return mw_values(aligned, gold_by_ann, derived), data, "read_tasks.jsonl"


def cs_values(scored: Sequence[csm.Scored], gold: Sequence[dict], predictions: Sequence[dict],
              population: Sequence[str], strata: Sequence[str]) -> list[dict[str, Any]]:
    labels = {g["task_id"]: g for g in gold if g["annotation"] == "generator"}
    preds = {p["read_id"]: p for p in predictions}
    rows = []
    for s in scored:
        g = labels[s.task_id]
        base = {"key": s.read_id, "value": s.value, "output": s.output,
                "cluster": s.family, "sequence": s.history_id}
        if s.question_type in population:
            rows.append({**base, "metric": "set-match"})
            for label in strata:
                value = g["labels"].get(label) if label != "change_type" else s.change_type
                if label == "question_type":
                    value = s.question_type
                if value is not None:
                    rows.append({**base, "metric": f"set-match|{label}={value}"})
        else:
            rows.append({**base, "metric": "set-match-historical"})
            for label in ("question_type", "pair_kind"):
                value = g["labels"].get(label)
                if value is not None:
                    rows.append({**base, "metric": f"set-match-historical|{label}={value}"})
        outdated = [x for item in g["metadata"].get("outdated_text") or []
                    for x in csm.item_strings(g["labels"]["template"], item)]
        if outdated and not g["labels"].get("premise_outdated"):
            p = preds[s.read_id]
            text = csm.tokens(csm.prediction_text(p["prediction"])) \
                if p["output"] in ("answer", "state") else ()
            stale = any(csm.mentions(text, x) for x in outdated if csm.tokens(x))
            rows.append({**base, "metric": "stale_value_use", "value": 1.0 if stale else 0.0})
    return rows


def score_changeseq(config, runs: Sequence[Path]) -> tuple[list[dict], list[dict], str]:
    spec = config["benchmarks"]["change-seq"]
    bc = cs_config(config)
    records = load_split("change-seq", spec["split"], config=bc)
    schedule = f"read_tasks.{spec['schedule']}.jsonl" if spec.get("schedule") else \
        "read_tasks.jsonl"
    tasks = [t.to_record() for t in records.schedules[schedule]]
    wanted = {t["task_id"] for t in tasks}
    predictions = _predictions(runs, wanted)
    messages = [m.to_record() for m in records.messages]
    gold = [g.to_record() for g in records.gold]
    scoring = spec["scoring"]
    scored = csm.score_reads(tasks, messages, gold, predictions,
                             annotation=scoring["annotation"])
    data = [{"benchmark": bc.benchmark, "version": bc.version,
             "manifest_sha256": bc.manifest_sha256, "split": spec["split"],
             "path": bc.source_dir(project_root()).resolve().as_posix()}]
    return cs_values(scored, gold, predictions, scoring["population"], scoring["strata"]), data, \
        schedule


def summarise(rows: Sequence[dict], cluster_key: str = "cluster") -> dict[str, Any]:
    by_metric: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_metric[r["metric"]].append(r)
    out = {}
    for metric, rs in sorted(by_metric.items()):
        values = {r["key"]: r["value"] for r in rs}
        clusters = {r["key"]: r[cluster_key] for r in rs}
        boot = csm.cluster_bootstrap(values, clusters, resamples=RESAMPLES, seed=0)
        out[metric] = {"value": boot["mean"], "n": boot["n_reads"], "ci95": boot["ci95"],
                       "clusters": boot["n_clusters"],
                       "n_invalid": sum(r["output"] == "invalid" for r in rs)}
    return out


def cmd_score(args, config, config_path: Path, command: str) -> int:
    runs = [Path(p).resolve() for p in args.system]
    ups = [_upstream(r) for r in runs]
    code = rundir.code_state()
    run_dir = rundir.create(args.out_root or default_root(), EXPERIMENT)
    resolved = {"stage": "score", "experiment": EXPERIMENT, "benchmark": args.benchmark,
                "benchmark_spec": {k: v for k, v in config["benchmarks"][args.benchmark].items()
                                   if k != "config"},
                "upstream_runs": [u["run_id"] for u in ups],
                "experiment_config": repo_relative(config_path), "bootstrap_resamples": RESAMPLES}
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True), encoding="utf-8")
    seeds = {u["seed"] for u in ups}
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": EXPERIMENT, "stage": "score",
        "upstream": [{k: u[k] for k in ("run_id", "stage", "path", "run_json_sha256")}
                     for u in ups],
        "code_sha": code.sha, "code_dirty": code.dirty, "config_path": repo_relative(config_path),
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": [],
        "project_root": project_root().as_posix(), "seed": seeds.pop() if len(seeds) == 1 else 0,
        "command": command, "environment": rundir.environment("cpu")})
    (run_dir / "calls.jsonl").touch()
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    try:
        if args.benchmark == "multiwoz":
            rows, data, schedule = score_multiwoz(config, runs)
            data = json.loads((runs[0] / "run.json").read_text())["data"]
        else:
            rows, data, schedule = score_changeseq(config, runs)
        run.data["data"] = data
        with (run_dir / "scores.jsonl").open("x", encoding="utf-8") as handle:
            for r in rows:
                handle.write(json.dumps(r, sort_keys=True) + "\n")
        summary = summarise(rows)
        if args.benchmark == "change-seq":
            summary["_by_sequence"] = summarise(rows, "sequence")
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n",
                                              encoding="utf-8")
        records = []
        for metric in summary:
            if metric.startswith("_"):
                continue
            name, _, stratum = metric.partition("|")
            rs = [r for r in rows if r["metric"] == metric]
            tally = aggregate({r["key"]: r["value"] for r in rs},
                              {r["key"]: r["output"] for r in rs}, "count_as_wrong")
            records.append(MetricRecord(
                benchmark=args.benchmark, split=config["benchmarks"][args.benchmark]["split"],
                schedule=schedule, annotation=ANN_D if args.benchmark == "multiwoz"
                and name != "jga" else ("2.4" if name == "jga" else "generator"),
                metric=name, direction="lower" if name in ("offer_overwrite", "stale_value_use")
                else "higher", stratum=stratum or None, seed=run.data["seed"],
                value=tally.value, n_total=tally.n_total, n_scored=tally.n_scored,
                n_invalid=tally.n_invalid, n_unknown=tally.n_unknown, n_judge_invalid=0,
                invalid_policy="count_as_wrong", scorer=f"{args.benchmark}/{name}",
                evaluator_version=code.sha))
        write_metrics(run_dir / "metrics.json", records)
        log.write(f"scored {len(rows)} item values from {[u['run_id'] for u in ups]}\n")
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        log.write(traceback.format_exc())
        log.close()
        run.finish(0, f"{type(exc).__name__}: {exc}")
        raise
    log.close()
    run.finish(len(rows))
    primary = "paired_correct" if args.benchmark == "multiwoz" else "set-match"
    s = summary[primary]
    print(f"{run_dir.name}: {primary} {s['value']:.4f} (n={s['n']}, 95% CI "
          f"{s['ci95'][0]:.4f}-{s['ci95'][1]:.4f}) -> {run_dir}")
    return 0


# ---------------------------------------------------------------------------------------------
# compare


def _scores(score_dir: Path) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in read_jsonl(score_dir / "scores.jsonl"):
        out[r["metric"]][r["key"]] = r
    return out


def guard_share(tag_a, tag_b, guard_a, guard_b, clusters: Mapping[str, str],
                resamples: int = RESAMPLES, seed: int = 0) -> dict[str, Any]:
    """share = (tag_a - tag_b) / (guard_a - guard_b) on the same items, with a percentile interval
    from one cluster bootstrap that draws the same clusters for all four arms."""
    keys = sorted(set(tag_a) & set(tag_b) & set(guard_a) & set(guard_b))
    groups: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        groups[clusters[k]].append(k)
    names = sorted(groups)

    def sums(arm):
        return {c: sum(arm[k] for k in groups[c]) for c in names}
    ta, tb, ga, gb = sums(tag_a), sums(tag_b), sums(guard_a), sums(guard_b)

    def share(draw):
        g = sum(ga[c] - gb[c] for c in draw)
        return None if g == 0 else sum(ta[c] - tb[c] for c in draw) / g
    point = share(names)
    rng = random.Random(seed)
    stats = [s for s in (share([rng.choice(names) for _ in names]) for _ in range(resamples))
             if s is not None]
    stats.sort()
    ci = ([csm._quantile(stats, 0.025), csm._quantile(stats, 0.975)] if stats else None)
    n = len(keys)
    return {"share": point, "ci95": ci, "n": n, "tag_gain": sum(ta.values()) / n - sum(
        tb.values()) / n, "guard_gain": sum(ga.values()) / n - sum(gb.values()) / n,
        "undefined_resamples": resamples - len(stats)}


def cmd_compare(args, config, config_path: Path) -> int:
    runs = shared_dir("runs_root").resolve()
    out = Path(args.out).resolve()
    if runs not in out.parents:
        raise SystemExit(f"--out must lie under {runs}")
    out.mkdir(parents=True, exist_ok=False)
    arms = dict(a.split("=", 1) for a in args.arm)
    scores = {name: _scores(Path(d)) for name, d in arms.items()}
    metrics = (["paired_correct", "retained", "choice_correct", "paired_correct|domain!=train",
                "paired_correct_conflict", "retained|conflict=true", "jga",
                "offer_overwrite|conflict=true"] if args.benchmark == "multiwoz" else
               ["set-match", "set-match|change_type=C5", "set-match-historical",
                "set-match-historical|pair_kind=differing",
                "set-match-historical|pair_kind=control", "stale_value_use"])
    summary: dict[str, Any] = {"benchmark": args.benchmark,
                               "experiment_config": repo_relative(config_path),
                               "inputs": {}, "arms": {}, "contrasts": {}, "guard_share": {}}
    for name, d in arms.items():
        path = Path(d).resolve()
        summary["inputs"][name] = {"path": path.as_posix(),
                                   "run_json_sha256": rundir.file_sha256(path / "run.json")}
        summary["arms"][name] = {m: v for m, v in json.loads(
            (path / "summary.json").read_text()).items() if m in metrics}
    for label, (a, b) in config["contrasts"].items():
        if a not in scores or b not in scores:
            continue
        summary["contrasts"][label] = {}
        for metric in metrics:
            va, vb = scores[a].get(metric), scores[b].get(metric)
            if not va or not vb or set(va) != set(vb):
                continue
            clusters = {k: r["cluster"] for k, r in va.items()}
            res = csm.paired_bootstrap({k: r["value"] for k, r in va.items()},
                                       {k: r["value"] for k, r in vb.items()}, clusters,
                                       resamples=RESAMPLES, seed=0)
            res.pop("per_cluster", None)
            res.pop("leave_one_cluster_out", None)
            summary["contrasts"][label][metric] = res
    needed = ("tagged", "rrf", "graph-guard-bi", "graph-noguard-bi")
    if all(n in scores for n in needed):
        for metric in metrics:
            vs = [scores[n].get(metric) for n in needed]
            if not all(vs):
                continue
            clusters = {k: r["cluster"] for k, r in vs[0].items()}
            summary["guard_share"][metric] = guard_share(
                *({k: r["value"] for k, r in v.items()} for v in vs), clusters)
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"compare -> {out / 'summary.json'}")
    return 0


# ---------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    system = sub.add_parser("system", help="one arm on one shard (stage system)")
    system.add_argument("--arm", required=True)
    system.add_argument("--shard", default=None, help="i/n: every n-th history from the i-th")
    system.add_argument("--base-url", required=True)
    system.add_argument("--embed-url", default=None)
    system.add_argument("--writer-url", default=None)
    system.add_argument("--label", default=None, help="e.g. `rerun` (writer-variance run)")
    score = sub.add_parser("score", help="score one arm (stage score)")
    score.add_argument("--system", nargs="+", required=True, help="run dirs (shards of one arm)")
    comp = sub.add_parser("compare", help="paired contrasts over score runs (not a run)")
    comp.add_argument("--arm", action="append", required=True, help="<name>=<score run dir>")
    comp.add_argument("--out", type=Path, required=True)
    for p in (system, score, comp):
        p.add_argument("--config", type=Path, required=True)
        p.add_argument("--benchmark", choices=BENCHMARKS, required=True)
    for p in (system, score):
        p.add_argument("--out-root", type=Path, default=None,
                       help="parent of E011/<run-id>/ (default runs/E011/artifacts/w01-E011)")
    args = parser.parse_args(argv)
    config = load_experiment(args.config)
    command = shlex.join([sys.executable, "-m", "grace.cli.ablation_b",
                          *(argv if argv is not None else sys.argv[1:])])
    if args.command == "system":
        return cmd_system(args, config, command)
    if args.command == "score":
        return cmd_score(args, config, args.config, command)
    return cmd_compare(args, config, args.config)


if __name__ == "__main__":
    sys.exit(main())
