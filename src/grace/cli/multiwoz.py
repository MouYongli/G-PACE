"""MultiWOZ state prediction and scoring (task T028; plan 6.5).

Development split only: every command loads benchmark records through `load_split`, which refuses
held-out splits until the T033 preregistration tag exists. No later turn is read and no gold state
is fed back: trackers see the visible messages up to the read's version only.

Commands (each one run of the Experiment-run contract under
`$PROJECT_ROOT/runs/T028/artifacts/<worker>/T028/<run-id>/`):

    # system stage: ReacTOD on the shared Qwen3-8B server
    uv run python -m grace.cli.multiwoz reactod --base-url http://localhost:8252/v1 \
        [--sample 100 --sample-seed 28] [--workers 16]
    # ingest stage: slot rows, one extraction call per message
    uv run python -m grace.cli.multiwoz rows --base-url http://localhost:8252/v1 [...]
    # read stage: project the rows of one ingest run under a policy (no model call)
    uv run python -m grace.cli.multiwoz project --upstream <ingest run dir> --policy overwrite
    # score stage: one prediction file (or the shards of one system) against 2.4, 2.2, 2.1 and
    # the derived offer-turn gold
    uv run python -m grace.cli.multiwoz score --upstream <run dir> [<run dir> ...]

`--sample N` takes a seeded subset of the development dialogues (sorted IDs, `random.Random(seed)`),
reported in `resolved-config.yaml`; scoring then uses exactly the read tasks of those dialogues.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shlex
import sys
import traceback
from collections import defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import project_root, shared_dir
from grace.context import api
from grace.eval.analysis.metrics import dst
from grace.eval.analysis.metrics.align import align, read_jsonl
from grace.eval.analysis.metrics.record import MetricRecord, aggregate, write_metrics
from grace.eval.datasets.benchmarks import multiwoz, multiwoz_derived
from grace.eval.datasets.benchmarks import multiwoz_offers as mo
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.engines.baselines import multiwoz as mw
from grace.eval.engines.baselines.multiwoz_reactod import K_MAX, ReacTOD
from grace.eval.runner.harness import rundir
from grace.eval.runner.harness.drive import DEFAULT_MODEL, ClientSettings
from grace.eval.runner.harness.inputs import HistoryInputs, Inputs, load_dev
from grace.eval.runner.harness.models import FakeBackend, RecordingModel
from grace.eval.runner.harness.outputs import Prediction
from grace.llm.records import CallLedger

EXPERIMENT = "T028"
BENCHMARK = "multiwoz"
ANNOTATIONS = ("2.4", "2.2", "2.1")
SLOTS = frozenset(multiwoz.SLOTS)
BOOTSTRAP = 10_000


# ---------------------------------------------------------------------------------------------
# Shared run plumbing


def default_parent() -> Path:
    return shared_dir("runs_root") / EXPERIMENT / "artifacts" / "w01-T028"


def sample_ids(ids: Sequence[str], n: int | None, seed: int) -> list[str]:
    ids = sorted(ids)
    if n is None or n >= len(ids):
        return ids
    return sorted(random.Random(seed).sample(ids, n))


def slot_specs(inputs: Inputs) -> list[mw.SlotSpec]:
    """The 30 official slots with 2.2 descriptions and enumerations (manifest checked by
    load_split before this is read)."""
    path = inputs.path.parent / "2.2" / "schema.json"
    return mw.slot_kinds(json.loads(path.read_text(encoding="utf-8")), SLOTS)


def data_fields(inputs: Inputs) -> list[dict[str, Any]]:
    data = [{"benchmark": inputs.benchmark, "version": inputs.data_version,
             "manifest_sha256": inputs.manifest_sha256, "split": inputs.split,
             "path": inputs.path.resolve().as_posix()}]
    data += [{"benchmark": inputs.benchmark, "version": v, "manifest_sha256": sha,
              "split": inputs.split, "path": (inputs.path.parent / v).resolve().as_posix()}
             for v, sha in inputs.extra_manifests]
    return data


def upstream_field(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "run.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["status"] != "completed":
        raise ValueError(f"upstream {run_dir} is {data['status']}, not completed")
    return {"run_id": data["run_id"], "stage": data["stage"],
            "path": Path(run_dir).resolve().as_posix(),
            "run_json_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class Run:
    """One run directory: resolved config, run.json life cycle, log."""

    def __init__(self, parent: Path, stage: str, resolved: dict[str, Any], data: list[dict],
                 upstream: list[dict], seed: int, device: str, command: str):
        self.dir = rundir.create(parent, EXPERIMENT)
        (self.dir / "resolved-config.yaml").write_text(
            yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True), encoding="utf-8")
        code = rundir.code_state()
        self.run = rundir.RunJson(self.dir, {
            "run_id": self.dir.name, "experiment": EXPERIMENT, "stage": stage,
            "upstream": upstream, "code_sha": code.sha, "code_dirty": code.dirty,
            "config_path": "src/grace/cli/multiwoz.py",
            "config_sha256": rundir.file_sha256(self.dir / "resolved-config.yaml"),
            "resources_sha256": rundir.resources_sha256(), "data": data,
            "project_root": project_root().as_posix(), "seed": seed, "command": command,
            "environment": rundir.environment(device)})
        self.log = (self.dir / "run.log").open("a", encoding="utf-8")

    def write_jsonl(self, name: str, rows: list[dict]) -> None:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def finish(self, n: int, failure: str | None = None) -> None:
        self.log.write(f"done: {n} records, failure={failure}\n")
        self.log.close()
        self.run.finish(n, failure)


def model_factory(args, seed: int) -> tuple[Callable[[CallLedger], Any], dict, str]:
    if args.backend == "fake":
        backend = FakeBackend()
        return (lambda ledger: RecordingModel(backend, ledger, max_attempts=2),
                {"label": backend.model}, backend.device)
    settings = ClientSettings(args.base_url, args.model_config)
    return (settings.factory({}, seed), settings.model_info(),
            "cpu (model on the serving endpoint)")


def load_inputs(args) -> Inputs:
    if args.sample is None:
        return load_dev(BENCHMARK, args.split)
    config = load_config(BENCHMARK)
    spec = config.splits[args.split]
    ids = mo.split_ids(config.source_dir(project_root(), "2.4"), spec.history_list_file)
    return load_dev(BENCHMARK, args.split, None, sample_ids(ids, args.sample, args.sample_seed))


def prediction(task: api.ReadTask, out: mw.StateOutput) -> Prediction:
    metadata: dict[str, Any] = {"current_choice": out.current_choice}
    if out.trace:
        metadata["trace"] = dict(out.trace)
    return Prediction(benchmark=task.benchmark, split=task.split, history_id=task.history_id,
                      read_id=task.read_id, task_id=task.task_id, version=task.version,
                      output=out.output, prediction=out.state if out.output == "state" else None,
                      cited_ids=[], context_ids=[], further_retrieval=False,
                      raw_output=out.raw_output, metadata=metadata)


def parallel(items: Sequence[HistoryInputs], work: Callable[[HistoryInputs], Any],
             workers: int, log) -> list[Any]:
    results: list[Any] = [None] * len(items)

    def one(index: int):
        results[index] = work(items[index])
        log.write(f"{items[index].history.history_id}: {len(items[index].reads)} reads\n")
        log.flush()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for future in [pool.submit(one, i) for i in range(len(items))]:
            future.result()
    return results


# ---------------------------------------------------------------------------------------------
# reactod (system) and rows (ingest)


def cmd_reactod(args, command: str) -> int:
    inputs = load_inputs(args)
    specs = slot_specs(inputs)
    make, info, device = model_factory(args, args.seed)
    resolved = {"stage": "system", "system": "reactod", "benchmark": BENCHMARK,
                "split": inputs.split, "read_tasks": inputs.schedule,
                "histories": [h.history.history_id for h in inputs.histories],
                "sample": args.sample, "sample_seed": args.sample_seed, "k_max": K_MAX,
                "model": info, "workers": args.workers, "slots": sorted(SLOTS)}
    run = Run(args.out or default_parent(), "system", resolved, data_fields(inputs), [],
              args.seed, device, command)
    ledger = CallLedger(run.dir / "calls.jsonl", run.dir.name)
    ledger.path.touch()
    try:
        model = make(ledger)

        def work(item: HistoryInputs):
            tracker = ReacTOD(model, specs)
            preds, reads = [], list(item.reads)
            for message in item.messages:
                tracker.observe(message)
                while reads and reads[0].version == message.version:
                    preds.append(prediction(reads[0], tracker.predict(reads.pop(0))))
            return preds, tracker.turns
        results = parallel(inputs.histories, work, args.workers, run.log)
        preds = [p.to_record() for ps, _ in results for p in ps]
        run.write_jsonl("predictions.jsonl", preds)
        run.write_jsonl("traces/read.jsonl", [t for _, ts in results for t in ts])
        failure = None if len(preds) == inputs.n_reads else \
            f"record count: {len(preds)} predictions, {inputs.n_reads} read tasks"
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        run.log.write(traceback.format_exc())
        run.finish(0, f"{type(exc).__name__}: {exc}")
        raise
    run.finish(len(preds), failure)
    print(f"{run.dir.name}: {run.run.data['status']} ({len(preds)} reads) -> {run.dir}")
    return 0 if failure is None else 1


def cmd_rows(args, command: str) -> int:
    inputs = load_inputs(args)
    specs = slot_specs(inputs)
    make, info, device = model_factory(args, args.seed)
    resolved = {"stage": "ingest", "system": "slot-rows", "benchmark": BENCHMARK,
                "split": inputs.split, "read_tasks": inputs.schedule,
                "histories": [h.history.history_id for h in inputs.histories],
                "sample": args.sample, "sample_seed": args.sample_seed, "model": info,
                "prompt": "extract-slots", "context_messages": 1, "workers": args.workers,
                "functions": list(mw.FUNCTIONS), "slots": sorted(SLOTS)}
    run = Run(args.out or default_parent(), "ingest", resolved, data_fields(inputs), [],
              args.seed, device, command)
    ledger = CallLedger(run.dir / "calls.jsonl", run.dir.name)
    ledger.path.touch()
    try:
        model = make(ledger)

        def work(item: HistoryInputs):
            extractor = mw.SlotRowExtractor(model, specs)
            traces = []
            for message in item.messages:
                rows, call_ids = extractor.observe(message)
                traces.append({"history_id": message.history_id, "version": message.version,
                               "message_ids": [message.message_id], "call_ids": call_ids,
                               "stale_marks": [], "timings_ms": {},
                               "rows": [r.to_record() for r in rows]})
            return item.history.history_id, extractor.rows, traces, extractor.failed_messages
        results = parallel(inputs.histories, work, args.workers, run.log)
        run.write_jsonl("traces/write.jsonl", [t for _, _, ts, _ in results for t in ts])
        snapshot = run.dir / "snapshot"
        snapshot.mkdir()
        manifest = []
        for hid, rows, _, failed in results:
            name = f"{hid.removesuffix('.json')}.rows.json"
            path = snapshot / name
            path.write_text(json.dumps({"history_id": hid, "rows": [r.to_record() for r in rows],
                                        "failed_messages": failed}, ensure_ascii=False),
                            encoding="utf-8")
            n_messages = next(len(h.messages) for h in inputs.histories
                              if h.history.history_id == hid)
            manifest.append({"history_id": hid, "version": n_messages,
                             "files": [{"path": name, "sha256": rundir.file_sha256(path)}]})
        (snapshot / "manifest.json").write_text(json.dumps({"histories": manifest}, indent=1),
                                                encoding="utf-8")
        n_messages = sum(len(h.messages) for h in inputs.histories)
        failed = sum(len(f) for *_, f in results)
        run.log.write(f"messages: {n_messages}, failed extractions: {failed}\n")
    except Exception as exc:  # noqa: BLE001
        run.log.write(traceback.format_exc())
        run.finish(0, f"{type(exc).__name__}: {exc}")
        raise
    run.finish(n_messages)
    print(f"{run.dir.name}: {run.run.data['status']} ({n_messages} messages, {failed} failed "
          f"extractions) -> {run.dir}")
    return 0


# ---------------------------------------------------------------------------------------------
# project (read)


def cmd_project(args, command: str) -> int:
    upstream = Path(args.upstream)
    up = upstream_field(upstream)
    if up["stage"] != "ingest":
        raise SystemExit("project needs exactly one ingest run as upstream")
    up_config = yaml.safe_load((upstream / "resolved-config.yaml").read_text(encoding="utf-8"))
    inputs = load_dev(BENCHMARK, up_config["split"], None, up_config["histories"])
    resolved = {"stage": "read", "system": f"slot-rows/{args.policy}", "policy": args.policy,
                "benchmark": BENCHMARK, "split": inputs.split, "read_tasks": inputs.schedule,
                "histories": up_config["histories"], "sample": up_config.get("sample"),
                "sample_seed": up_config.get("sample_seed"), "upstream_run": up["run_id"]}
    run = Run(args.out or default_parent(), "read", resolved, data_fields(inputs), [up],
              0, "cpu", command)
    for name in ("calls.jsonl",):
        (run.dir / name).touch()
    try:
        manifest = json.loads((upstream / "snapshot" / "manifest.json").read_text())
        files = {h["history_id"]: h["files"][0] for h in manifest["histories"]}
        preds = []
        for item in inputs.histories:
            entry = files[item.history.history_id]
            path = upstream / "snapshot" / entry["path"]
            if rundir.file_sha256(path) != entry["sha256"]:
                raise ValueError(f"snapshot checksum differs: {path}")
            rows = [mw.SlotRow(**r) for r in json.loads(path.read_text())["rows"]]
            for task in item.reads:
                preds.append(prediction(task, mw.predict_from_rows(rows, task, args.policy,
                                                                   SLOTS)).to_record())
        run.write_jsonl("predictions.jsonl", preds)
        failure = None if len(preds) == inputs.n_reads else "record count differs"
    except Exception as exc:  # noqa: BLE001
        run.log.write(traceback.format_exc())
        run.finish(0, f"{type(exc).__name__}: {exc}")
        raise
    run.finish(len(preds), failure)
    print(f"{run.dir.name}: {run.run.data['status']} ({len(preds)} reads, {args.policy}) -> "
          f"{run.dir}")
    return 0 if failure is None else 1


# ---------------------------------------------------------------------------------------------
# score


def bootstrap(values_by_cluster: dict[str, list[float]], seed: int = 0,
              resamples: int = BOOTSTRAP) -> tuple[float, float] | None:
    """95% percentile interval of the micro mean, resampling clusters (dialogues)."""
    clusters = [(sum(v), len(v)) for v in values_by_cluster.values() if v]
    if not clusters:
        return None
    rng = random.Random(seed)
    n = len(clusters)
    means = []
    for _ in range(resamples):
        total = count = 0
        for _ in range(n):
            s, c = clusters[rng.randrange(n)]
            total += s
            count += c
        means.append(total / count)
    means.sort()
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def lenient(a: str, b: str) -> bool:
    """T006 rule `values_match`: the comparison of the PRIMARY offer-turn values."""
    return mo.values_match(a, b)


def lenient_jga(pred: dict | None, gold: dict, alternatives: dict | None = None) -> float:
    p, g = dst.normalise_state(pred), dst.normalise_state(gold)
    if p.keys() != g.keys():
        return 0.0
    for slot, value in g.items():
        options = [value, *(alternatives or {}).get(slot, [])]
        if not any(p[slot] == o or lenient(p[slot], o) for o in options):
            return 0.0
    return 1.0


def score_values(aligned, gold_by_ann, derived) -> dict[str, dict[str, Any]]:
    """metric -> {"values": read/item key -> value, "clusters": key -> dialogue, outputs}."""
    out: dict[str, dict[str, Any]] = {}

    def put(metric, key, value, cluster, output):
        m = out.setdefault(metric, {"values": {}, "cluster": {}, "outputs": {}})
        m["values"][key], m["cluster"][key], m["outputs"][key] = value, cluster, output

    for rid, a in aligned.items():
        pred, output = a.prediction["prediction"], a.prediction["output"]
        state = pred if output == "state" else None
        hid = a.read_task["history_id"]
        for ann in ANNOTATIONS:
            gold = gold_by_ann[ann][a.read_task["task_id"]]
            ref = gold["reference"]
            alts = (gold.get("metadata") or {}).get("alternatives")
            put(f"jga|{ann}", rid, dst.joint_goal(state, ref), hid, output)
            put(f"slot-f1|{ann}", rid, dst.slot_f1(state, ref), hid, output)
            put(f"jga-lenient|{ann}", rid, lenient_jga(state, ref, alts), hid, output)
        item = derived.get(a.read_task["task_id"])
        if item is None:
            continue
        choices = (a.prediction.get("metadata") or {}).get("current_choice")
        ref = item["reference"]
        label = item["labels"]["response"]
        for i, r in enumerate(ref["retention"]):
            key = f"{rid}#r{i}"
            # primary: T006 values_match; sensitivity: exact match after normalise_state
            for name, match in (("retained", lenient), ("retained-exact", None)):
                value = dst.retained(state, r, match)
                put(f"{name}|{ANN_D}", key, value, hid, output)
                put(f"{name}|{ANN_D}|response={label}", key, value, hid, output)
                put(f"{name}|{ANN_D}|conflict={str(r['conflict']).lower()}", key, value, hid,
                    output)
        for i, p in enumerate(ref["paired"]):
            key = f"{rid}#p{i}"
            choice = dst.current_choice(state, choices, p["domain"], p["entity_slot"])
            conflict = {s: p["originals"][s] for s in p["conflict_slots"]}
            for suffix, match in (("", lenient), ("-exact", None)):
                value = dst.paired_correct(state, choices, p, p["originals"], match)
                put(f"paired_correct{suffix}|{ANN_D}", key, value, hid, output)
                put(f"paired_correct{suffix}|{ANN_D}|domain={p['domain']}", key, value, hid,
                    output)
                put(f"paired_correct{suffix}|{ANN_D}|response={p['response']}", key, value,
                    hid, output)
                put(f"choice_correct{suffix}|{ANN_D}", key,
                    dst.choice_correct(choice, p, match), hid, output)
                if conflict:
                    put(f"paired_correct_conflict{suffix}|{ANN_D}", key,
                        dst.paired_correct(state, choices, p, conflict, match), hid, output)
    return out


ANN_D = multiwoz_derived.ANNOTATION


def cmd_score(args, command: str) -> int:
    runs = [Path(p) for p in args.upstream]
    ups = [upstream_field(r) for r in runs]
    stages = {u["stage"] for u in ups}
    if not stages <= {"system", "read"}:
        raise SystemExit(f"score needs system or read runs, got {sorted(stages)}")
    predictions, histories, splits, seeds = [], [], set(), set()
    for r in runs:
        config = yaml.safe_load((r / "resolved-config.yaml").read_text(encoding="utf-8"))
        histories += config["histories"]
        splits.add(config["split"])
        seeds.add(json.loads((r / "run.json").read_text())["seed"])
        predictions += read_jsonl(r / "predictions.jsonl")
    if len(splits) != 1 or len(set(histories)) != len(histories):
        raise SystemExit("upstream runs must share one split and partition the dialogues")
    split = splits.pop()
    records = load_split(BENCHMARK, split)
    wanted = set(histories)
    tasks = [t.to_record() for t in records.schedules["read_tasks.jsonl"]
             if t.history_id in wanted]
    messages = [m.to_record() for m in records.messages if m.history_id in wanted]
    gold = [g.to_record() for g in records.gold if g.history_id in wanted]
    aligned = align(tasks, messages, gold, predictions)
    gold_by_ann = {ann: {g["task_id"]: g for g in gold if g["annotation"] == ann}
                   for ann in ANNOTATIONS}
    config = load_config(BENCHMARK)
    root = project_root()
    sources = {v: config.source_dir(root, v) for v in config.manifests()}
    dialogues, _ = mo.load_dialogues(sources, sorted(wanted),
                                     config.options["split_dirs_22"][split], keep_text=False)
    derived_gold = multiwoz_derived.derive_all(dialogues, BENCHMARK, split)
    derived = {g.task_id: g.to_record() for g in derived_gold}
    inputs = load_dev(BENCHMARK, split, None, sorted(wanted))
    resolved = {"stage": "score", "benchmark": BENCHMARK, "split": split,
                "upstream_runs": [u["run_id"] for u in ups], "annotations": list(ANNOTATIONS),
                "derived_annotation": ANN_D, "bootstrap_resamples": BOOTSTRAP,
                "n_dialogues": len(wanted), "derived_summary":
                    multiwoz_derived.summary(derived_gold)}
    run = Run(args.out or default_parent(), "score", resolved, data_fields(inputs), ups,
              seeds.pop() if len(seeds) == 1 else 0, "cpu", command)
    (run.dir / "calls.jsonl").touch()
    code = run.run.data["code_sha"]
    try:
        run.write_jsonl("derived-gold.jsonl", list(derived.values()))
        values = score_values(aligned, gold_by_ann, derived)
        records_out, summary = [], {}
        for metric, m in sorted(values.items()):
            name, annotation, *stratum = metric.split("|")
            tally = aggregate(m["values"], m["outputs"], "count_as_wrong")
            by_cluster: dict[str, list[float]] = defaultdict(list)
            for key, value in m["values"].items():
                by_cluster[m["cluster"][key]].append(
                    0.0 if m["outputs"][key] == "invalid" else value)
            interval = (bootstrap(by_cluster)
                        if not stratum or stratum[0].startswith("conflict=") else None)
            records_out.append(MetricRecord(
                benchmark=BENCHMARK, split=split, schedule="read_tasks.jsonl",
                annotation=annotation, metric=name, direction="higher",
                stratum=stratum[0] if stratum else None, seed=run.run.data["seed"],
                value=tally.value, n_total=tally.n_total, n_scored=tally.n_scored,
                n_invalid=tally.n_invalid, n_unknown=tally.n_unknown, n_judge_invalid=0,
                invalid_policy="count_as_wrong", scorer=f"{BENCHMARK}/{name}",
                evaluator_version=code))
            summary[metric] = {"value": tally.value, "n": tally.n_total,
                               "n_invalid": tally.n_invalid, "ci95": interval,
                               "clusters": len(by_cluster)}
        write_metrics(run.dir / "metrics.json", records_out)
        (run.dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n",
                                              encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        run.log.write(traceback.format_exc())
        run.finish(0, f"{type(exc).__name__}: {exc}")
        raise
    run.finish(len(aligned))
    for metric in ("jga|2.4", "jga|2.2", "jga|2.1", "jga-lenient|2.1", f"retained|{ANN_D}",
                   f"retained|{ANN_D}|conflict=true", f"choice_correct|{ANN_D}",
                   f"paired_correct|{ANN_D}", f"paired_correct_conflict|{ANN_D}",
                   f"retained-exact|{ANN_D}", f"choice_correct-exact|{ANN_D}",
                   f"paired_correct-exact|{ANN_D}", f"paired_correct_conflict-exact|{ANN_D}"):
        s = summary.get(metric)
        if s:
            ci = s["ci95"]
            print(f"{metric}: {s['value']:.4f} (n={s['n']}, invalid={s['n_invalid']}, "
                  f"95% CI {ci[0]:.4f}-{ci[1]:.4f})" if ci else f"{metric}: {s['value']}")
    print(f"{run.dir.name}: {run.run.data['status']} -> {run.dir}")
    return 0


# ---------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("reactod", "rows"):
        p = sub.add_parser(name)
        p.add_argument("--split", default="dev")
        p.add_argument("--sample", type=int, default=None)
        p.add_argument("--sample-seed", type=int, default=28)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--workers", type=int, default=16)
        p.add_argument("--backend", choices=["client", "fake"], default="client")
        p.add_argument("--base-url", default="http://localhost:8252/v1")
        p.add_argument("--model-config", type=Path, default=DEFAULT_MODEL)
        p.add_argument("--out", type=Path, default=None)
    p = sub.add_parser("project")
    p.add_argument("--upstream", required=True)
    p.add_argument("--policy", choices=mw.POLICIES, required=True)
    p.add_argument("--out", type=Path, default=None)
    p = sub.add_parser("score")
    p.add_argument("--upstream", nargs="+", required=True)
    p.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    command = shlex.join([sys.executable, "-m", "grace.cli.multiwoz",
                          *(argv if argv is not None else sys.argv[1:])])
    if getattr(args, "out", None) is not None:
        args.out = Path(args.out)
    handler = {"reactod": cmd_reactod, "rows": cmd_rows, "project": cmd_project,
               "score": cmd_score}[args.command]
    return handler(args, command)


if __name__ == "__main__":
    raise SystemExit(main())
