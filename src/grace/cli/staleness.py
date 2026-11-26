"""E002, rough natural staleness distribution (plan 6.5): extraction and measurement.

    uv run python -m grace.cli.staleness extract \\
        --config configs/experiments/E002-rough-staleness-distribution.yaml --benchmark locomo \\
        --base-url http://127.0.0.1:8121/v1 [--base-url ...]
    uv run python -m grace.cli.staleness measure \\
        --config configs/experiments/E002-rough-staleness-distribution.yaml \\
        --upstream <extract run dir>

- `extract` (stage `ingest`): every message of the benchmark's development split is read by one
  extraction call (`grace.eval.runner.probes.natural_extract`; prompt `extract-claims-rough`,
  the model pin of the config, every call through `grace.llm.client.ChatClient`). Histories run in
  parallel, the messages of one history in version order. Several `--base-url` values spread
  histories over servers of the same model. Writes the contract's `calls.jsonl`,
  `changesets.jsonl`, `traces/write.jsonl` and `snapshot/` (the claim graph of every history,
  committed through `ClaimStore`, which checks every change set), plus `extractions.jsonl` (raw
  output, parse status and mapping notes per message) and `vocabulary.jsonl` (the run-local
  predicate table per history). `n_records`: messages.
- `measure` (stage `probe`, CPU only, upstream: one completed `extract` run): replays the change
  sets and re-queries the template views after every message
  (`grace.eval.runner.probes.natural_staleness`). Writes `events.jsonl` (one record per stale,
  typed or marked (message, view) pair), `histories.jsonl` (counters per history),
  `distribution.json` (totals, `grace.eval.analysis.metrics.natural_staleness`) and
  `audit-sample.tsv` (typed staleness events drawn for a later human audit). `n_records`:
  messages.

Development splits only.
"""

from __future__ import annotations

import argparse
import json
import random
import shlex
import sys
import threading
import traceback
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import load_vocabulary
from grace.context.views.template_families import load_view_config
from grace.eval.analysis.metrics.natural_staleness import TYPES, summarise
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.runner.harness import drive, rundir
from grace.eval.runner.probes import natural_extract as nx
from grace.eval.runner.probes import natural_staleness as ns
from grace.llm.client import ChatClient, Endpoint, LLMCallFailed
from grace.llm.prompts import load_pinned
from grace.llm.records import CallContext, CallLedger
from grace.llm.tokens import HFTokenCounter, TokenizerPin, locate_snapshot

EXPERIMENT = "E002"
WORKER = "manager"
KEYS = ("experiment", "seed", "benchmarks", "extraction", "views", "measurement",
        "decision_rule", "audit_sample")
PROMPTS = REPO_ROOT / "configs" / "common" / "prompts.yaml"
MAX_FAILED_SHARE = 0.02     # an extraction run with more failed calls than this is `failed`


def load_experiment(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if missing := [k for k in KEYS if k not in config]:
        raise ValueError(f"{path}: missing keys {missing}")
    if config["experiment"] != EXPERIMENT:
        raise ValueError(f"{path}: experiment must be {EXPERIMENT}")
    return config


def run_root() -> Path:
    return shared_dir("runs_root") / EXPERIMENT / "artifacts" / WORKER


def write_jsonl(handle, record: Mapping[str, Any]) -> None:
    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def load_records(config: Mapping[str, Any], benchmark: str):
    spec = config["benchmarks"][benchmark]
    bc = load_config(benchmark)
    if bc.splits[spec["split"]].kind != "development":
        raise ValueError("E002 reads development splits only")
    records = load_split(benchmark, spec["split"], config=bc)
    data = [{"benchmark": benchmark, "version": bc.version,
             "manifest_sha256": bc.manifest_sha256, "split": spec["split"],
             "path": bc.source_dir(project_root()).resolve().as_posix()}]
    by_history: dict[str, list] = defaultdict(list)
    for m in records.messages:
        by_history[m.history_id].append(m)
    for messages in by_history.values():
        messages.sort(key=lambda m: m.version)
        if [m.version for m in messages] != list(range(1, len(messages) + 1)):
            raise ValueError(f"{messages[0].history_id}: message versions are not 1..N")
    return records, by_history, data


def speakers_of(messages: Sequence) -> list[str]:
    return list(dict.fromkeys(m.speaker for m in messages if m.speaker))


def participants(spec: Mapping[str, Any], messages: Sequence) -> str:
    if spec["roles"] is not None:
        return spec["participants"]
    a, b = speakers_of(messages)
    return spec["participants"].format(a=a, b=b)


def start_run(config_path: Path, resolved: Mapping[str, Any], stage: str, data, seed: int,
              device: str, upstream: list[dict[str, Any]], command: str | None):
    code = rundir.code_state()
    run_dir = rundir.create(run_root(), EXPERIMENT)
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(dict(resolved), sort_keys=True, allow_unicode=True), encoding="utf-8")
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": EXPERIMENT, "stage": stage, "upstream": upstream,
        "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": drive.repo_relative(config_path),
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": data,
        "project_root": project_root().as_posix(), "seed": seed,
        "command": command or " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment(device)})
    return run_dir, run


# ---------------------------------------------------------------------------------------------
# extract (stage ingest)


def extract(config_path: Path, benchmark: str, base_urls: Sequence[str], *,
            histories: Sequence[str] | None = None, workers: int | None = None,
            serving: Mapping[str, Any] | None = None, command: str | None = None) -> Path:
    config = load_experiment(config_path)
    spec, ex = config["benchmarks"][benchmark], config["extraction"]
    records, by_history, data = load_records(config, benchmark)
    chosen = [h for h in records.histories if histories is None or h.history_id in histories]
    if histories is not None and len(chosen) != len(set(histories)):
        raise ValueError(f"unknown histories in {histories}")
    model_path = REPO_ROOT / ex["model_config"]
    model = yaml.safe_load(model_path.read_text(encoding="utf-8"))
    pin = TokenizerPin.from_file(model_path)
    counter = HFTokenCounter(pin, locate_snapshot(pin))
    prompt = load_pinned(ex["prompt"], PROMPTS)
    seed_vocabulary = load_vocabulary()
    settings = nx.Settings(**{k: ex[k] for k in (
        "message_chars", "earlier_messages", "earlier_chars", "max_claims", "max_predicates",
        "recent_versions")})
    workers = workers or int(ex["workers"])
    resolved = {"stage": "ingest", "experiment": EXPERIMENT,
                "config": drive.repo_relative(config_path), "benchmark": benchmark,
                "split": spec["split"], "histories": [h.history_id for h in chosen],
                "partial": histories is not None, "participants": spec["participants"],
                "roles": spec["roles"], "extraction": {**ex, "workers": workers},
                "settings": vars(settings), "prompt_sha256": prompt.sha256,
                "seed_vocabulary": seed_vocabulary.version,
                "model": {"model_config": ex["model_config"], "served_name": model["served_name"],
                          "label": f"{pin.hf_repo}@{pin.revision}", "thinking": model["thinking"],
                          "base_urls": list(base_urls), "serving": dict(serving or {})}}
    run_dir, run = start_run(config_path, resolved, "ingest", data, int(config["seed"]),
                             "cpu (model on the serving endpoints)", [], command)
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    ledger = CallLedger(run_dir / "calls.jsonl", run_dir.name)
    ledger.path.touch()
    clients = [ChatClient(Endpoint.for_model(pin, url, model["served_name"]), ledger, counter,
                          max_attempts=int(ex["max_attempts"])) for url in base_urls]
    decoding = dict(ex["decoding"])
    lock = threading.Lock()
    progress = Counter()
    n_messages = sum(len(by_history[h.history_id]) for h in chosen)

    def say(text: str) -> None:
        with lock:
            log.write(f"{rundir.utc_now()} {text}\n")
            log.flush()

    def make_chat(client: ChatClient, history_id: str):
        def chat(messages, version: int):
            context = CallContext("extract", "write", history_id, None, version)
            try:
                result = client.chat(messages, context, prompt_sha256=prompt.sha256,
                                     decoding=decoding)
            except LLMCallFailed as exc:
                return None, "failed", str(exc), [r.call_id for r in exc.records]
            return (result.text, result.status, result.error,
                    [r.call_id for r in result.records])
        return chat

    def on_message(history_id: str, version: int, status: str) -> None:
        with lock:
            progress[status] += 1
            done = sum(progress.values())
            if progress["failed"] > max(50, MAX_FAILED_SHARE * n_messages):
                raise RuntimeError(f"{progress['failed']} failed extraction calls; aborting")
        if done % 500 == 0:
            say(f"{done}/{n_messages} messages; status {dict(progress)}")

    def one(i: int, history):
        messages = by_history[history.history_id]
        result = nx.extract_history(
            history, messages, make_chat(clients[i % len(clients)], history.history_id), prompt,
            seed_vocabulary, participants=participants(spec, messages), settings=settings,
            on_message=on_message)
        store = ClaimStore(history.history_id)
        for cs in result.changesets:
            store.commit(cs)
        files = store.save(run_dir / "snapshot" / history.history_id)
        return result, store.head, files

    failure, n = None, 0
    manifest = []
    try:
        (run_dir / "traces").mkdir()
        with (run_dir / "changesets.jsonl").open("w", encoding="utf-8") as cfile, \
                (run_dir / "extractions.jsonl").open("w", encoding="utf-8") as xfile, \
                (run_dir / "traces" / "write.jsonl").open("w", encoding="utf-8") as tfile, \
                (run_dir / "vocabulary.jsonl").open("w", encoding="utf-8") as vfile, \
                ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(one, i, h): h.history_id for i, h in enumerate(chosen)}
            for future in as_completed(futures):
                result, head, files = future.result()
                for cs in result.changesets:
                    cfile.write(cs.to_json() + "\n")
                for record in result.records:
                    write_jsonl(xfile, record)
                for record in result.traces:
                    write_jsonl(tfile, record)
                write_jsonl(vfile, {"history_id": result.history_id,
                                    "predicates": result.vocabulary})
                for handle in (cfile, xfile, tfile, vfile):
                    handle.flush()
                n += len(result.changesets)
                manifest.append({"history_id": result.history_id, "version": head, "files": [
                    {"path": Path(f).relative_to(run_dir / "snapshot").as_posix(),
                     "sha256": rundir.file_sha256(Path(f))} for f in files]})
                say(f"history {result.history_id} done: {len(result.changesets)} messages, "
                    f"status {dict(result.status)}")
        (run_dir / "snapshot" / "manifest.json").write_text(json.dumps(
            {"histories": sorted(manifest, key=lambda h: h["history_id"])}, indent=2) + "\n",
            encoding="utf-8")
        if n != n_messages:
            failure = f"{n} of {n_messages} messages extracted"
        elif progress["failed"] > MAX_FAILED_SHARE * n_messages:
            failure = f"{progress['failed']} failed calls exceed {MAX_FAILED_SHARE:.0%}"
        say(f"finished: {n} messages, status {dict(progress)}")
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure
        failure = f"{type(exc).__name__}: {exc}"
        log.write(traceback.format_exc())
    finally:
        log.close()
        if failure is None and histories is not None:
            failure = "partial: a subset of histories (smoke test, not a formal run)"
        run.finish(n, failure)
    return run_dir


# ---------------------------------------------------------------------------------------------
# measure (stage probe)


def _measure_one(args: dict[str, Any]) -> dict[str, Any]:
    """Process-pool worker: replay one history; plain data in and out."""
    views = args["views"]
    base = load_view_config(REPO_ROOT / views["base_config"])
    base = replace(base, instantiation_threshold=int(views["instantiation_threshold"]),
                   state_speaker=views["state_speaker"],
                   choice_predicate=views["choice_predicate"])
    changesets = [ChangeSet.from_record(r) for r in args["changesets"]]
    changesets.sort(key=lambda cs: cs.version)
    vocabulary = ns.vocabulary_from(args["vocabulary"], f"E002-{args['history_id']}")
    orients = ns.orientations(speakers_of(args["messages"]), args["roles"])
    result = ns.measure_history(args["history_id"], changesets, args["messages"], vocabulary,
                                base, orients, benchmark=args["benchmark"],
                                full_check=args["full_check"])
    return {"events": result.events,
            "history": {"benchmark": args["benchmark"], "messages": len(args["messages"]),
                        "orientations": [vars(o) | {"families": list(o.families)}
                                         for o in orients], **result.summary()}}


def audit_sample(events: Sequence[Mapping[str, Any]], per_type: int, seed: int
                 ) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out = []
    for t in TYPES:
        typed = sorted((e for e in events if e["type"] == t and e["outcome"] != "none"),
                       key=lambda e: (e["history_id"], e["version"], e["view_id"],
                                      e["orientation"]))
        out += rng.sample(typed, min(per_type, len(typed)))
    return out


def measure(config_path: Path, upstream_dir: Path, *, processes: int | None = None,
            command: str | None = None) -> Path:
    config = load_experiment(config_path)
    upstream_dir = Path(upstream_dir).resolve()
    up = json.loads((upstream_dir / "run.json").read_text(encoding="utf-8"))
    if up["status"] != "completed" or up["stage"] != "ingest" or up["experiment"] != EXPERIMENT:
        raise ValueError(f"{upstream_dir}: upstream must be a completed E002 ingest run")
    up_config = yaml.safe_load((upstream_dir / "resolved-config.yaml").read_text("utf-8"))
    benchmark = up_config["benchmark"]
    spec = config["benchmarks"][benchmark]
    records, by_history, data = load_records(config, benchmark)
    histories = up_config["histories"]
    changesets: dict[str, list[dict]] = defaultdict(list)
    with (upstream_dir / "changesets.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            changesets[record["history_id"]].append(record)
    vocabularies = {}
    with (upstream_dir / "vocabulary.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            vocabularies[record["history_id"]] = record["predicates"]
    full_check = bool(config["measurement"]["full_check"][benchmark])
    processes = processes or int(config["measurement"]["processes"])
    resolved = {"stage": "probe", "experiment": EXPERIMENT,
                "config": drive.repo_relative(config_path), "benchmark": benchmark,
                "split": spec["split"], "histories": histories, "roles": spec["roles"],
                "views": config["views"], "full_check": full_check, "processes": processes,
                "strategies": {k: {"strategy": s, **o} for k, (s, o) in ns.STRATEGIES.items()},
                "decision_rule": config["decision_rule"], "audit_sample": config["audit_sample"]}
    upstream = [{"run_id": up["run_id"], "stage": "ingest", "path": upstream_dir.as_posix(),
                 "run_json_sha256": rundir.file_sha256(upstream_dir / "run.json")}]
    run_dir, run = start_run(config_path, resolved, "probe", data, int(config["seed"]), "cpu",
                             upstream, command)
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    failure, n = None, 0
    try:
        (run_dir / "calls.jsonl").touch()
        (run_dir / "traces").mkdir()
        jobs = [{"history_id": h, "benchmark": benchmark, "messages": by_history[h],
                 "changesets": changesets[h], "vocabulary": vocabularies[h],
                 "roles": spec["roles"], "views": config["views"], "full_check": full_check}
                for h in histories]
        events, summaries = [], []
        with ProcessPoolExecutor(max_workers=processes) as pool, \
                (run_dir / "events.jsonl").open("w", encoding="utf-8") as efile, \
                (run_dir / "histories.jsonl").open("w", encoding="utf-8") as hfile:
            futures = [pool.submit(_measure_one, job) for job in jobs]
            for future in as_completed(futures):
                out = future.result()
                for e in out["events"]:
                    write_jsonl(efile, e)
                write_jsonl(hfile, out["history"])
                events += out["events"]
                summaries.append(out["history"])
                n += out["history"]["messages"]
                log.write(f"{rundir.utc_now()} {out['history']['history_id']}: "
                          f"{len(out['events'])} events in {out['history']['seconds']} s\n")
                log.flush()
        messages = {benchmark: sum(h["messages"] for h in summaries)}
        distribution = summarise(events, summaries, messages, config["decision_rule"])
        (run_dir / "distribution.json").write_text(
            json.dumps(distribution, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sample = audit_sample(events, int(config["audit_sample"]["per_type"]),
                              int(config["audit_sample"]["seed"]))
        texts = {(m.history_id, m.version): m for m in records.messages}
        with (run_dir / "audit-sample.tsv").open("w", encoding="utf-8") as handle:
            handle.write("history_id\tversion\tmessage_id\tspeaker\tview_id\torientation\ttype"
                         "\toutcome\tmessage\tlabel_correct\n")
            for e in sample:
                m = texts[(e["history_id"], e["version"])]
                text = " ".join(m.text.split())[:500]
                handle.write("\t".join(str(x) for x in (
                    e["history_id"], e["version"], e["message_id"], e["speaker"], e["view_id"],
                    e["orientation"], e["type"], e["outcome"], text, "")) + "\n")
        expected = sum(len(by_history[h]) for h in histories)
        violations = distribution[benchmark]["soundness_violations"]
        if n != expected:
            failure = f"{n} of {expected} messages measured"
        elif violations:
            failure = f"{violations} soundness violations of the candidate filter"
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure
        failure = f"{type(exc).__name__}: {exc}"
        log.write(traceback.format_exc())
    finally:
        log.close()
        run.finish(n, failure)
    return run_dir


# ---------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="grace.cli.staleness", description=__doc__.split(
        "\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("extract", help="stage ingest: one extraction call per message")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--benchmark", required=True)
    p.add_argument("--base-url", action="append", required=True)
    p.add_argument("--history", action="append", help="subset (smoke test; run is `failed`)")
    p.add_argument("--workers", type=int)
    p.add_argument("--serving", type=json.loads, default={},
                   help="server settings to record, as JSON (GPU, vLLM version, arguments)")
    m = sub.add_parser("measure", help="stage probe: replay and type every change")
    m.add_argument("--config", type=Path, required=True)
    m.add_argument("--upstream", type=Path, required=True)
    m.add_argument("--processes", type=int)
    args = parser.parse_args(argv)
    command = " ".join(shlex.quote(a) for a in ["python", "-m", "grace.cli.staleness",
                                                *(argv if argv is not None else sys.argv[1:])])
    if args.command == "extract":
        run_dir = extract(args.config, args.benchmark, args.base_url, histories=args.history,
                          workers=args.workers, serving=args.serving, command=command)
    else:
        run_dir = measure(args.config, args.upstream, processes=args.processes, command=command)
    status = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    print(f"{run_dir}: {status['status']}" + (f" ({status['failure']})"
                                             if status["failure"] else ""))
    return 0 if status["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
