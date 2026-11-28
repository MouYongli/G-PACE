"""The `ingest` and `read` stages of end-of-history reading (contracts.md, "Experiment run",
"Stages and upstream runs").

Under end-of-history reading, ingestion and reading are separate stages, so that one `ingest` run
serves several `read` runs (the budget levels, the read-side ablations):

- `run_ingest` writes every message of each history into a fresh engine, calls `finish()` (the
  end-of-history step), and saves the engine state into `snapshot/<history_id>/`. It writes
  `calls.jsonl`, `traces/write.jsonl`, `changesets.jsonl` and `snapshot/` with
  `snapshot/manifest.json` (per history: last committed version, every file with its SHA-256).
  `n_records` is the number of messages written.
- `run_read` names exactly one completed `ingest` run as its upstream. For every history it copies
  the snapshot into its own directory (`cache/restore/<history_id>/`, checked against the
  manifest and removed once the history is answered), restores a fresh engine from it, and
  answers the history's read tasks at the run's budget. It writes `calls.jsonl`,
  `predictions.jsonl`, `contexts.jsonl` and `traces/read.jsonl`; `n_records` is the number of
  reads. Every read must be at the snapshot version (end-of-history reading); a read at an earlier
  version needs a `system` run. A read that commits write-side work (a flush, a `finish()` step)
  fails the run: the snapshot was then incomplete.

Write side and read side. A `read` run refuses an upstream whose engine was built differently on
the write side (`write_side`, `incompatibilities`):

- Every engine: `engine`, `writer_model` and `engine_llm` must be equal.
- GRACE (`engine: grace`): the writer config (`params.writer`) and the writer-side extension
  (`params.components.extension`: slot table, query-time resolution) must be equal, and so must
  the content (SHA-256) of the writer config and the writer model config. Resident views are
  maintained at write time and saved in the snapshot: a read engine with resident views (`views`
  not null and no `components.views` replacement) needs the same `views` and `staleness` params
  (and views config content) as the ingest engine. A read engine whose retrieval config enables
  the dense channel needs an ingest engine that built the dense index with the same embedding
  model. Free on the read side: `planner`, `retrieval` (other than the dense requirement),
  `assembly` (selection, fill, open items, ...), `fragment`, a view source that reads the graph at
  read time (`components.views: serialised-views`, or `views: null`), the budget, `description`
  and `prefix_caching`.
- Any other engine (the baselines) declares no read side: its whole `params` and `embedding` must
  be equal.

The ingest run records its write side in `resolved-config.yaml` (`write_side`); the read run
compares its own engine config against it and records the result.

Histories run one after another, or in `workers` threads (one engine per history; the model
clients and the call ledger are shared and thread-safe). A history's write steps or reads are
appended to the run files when the history is done, so records of one history are contiguous.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import threading
import traceback
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT
from grace.context import api
from grace.context.pipeline.retrieval.retrieve import RetrievalConfig
from grace.eval.datasets.benchmarks.base import BenchmarkConfig
from grace.eval.engines.baselines.base import message_time
from grace.eval.runner.harness import rundir
from grace.eval.runner.harness.drive import (
    ClientSettings,
    answer_read,
    budgets,
    build_engine,
    engine_settings,
    load_engine_config,
    load_inputs,
    models_for,
    repo_relative,
    start_run,
)
from grace.eval.runner.harness.inputs import HistoryInputs, Inputs
from grace.eval.runner.harness.models import Backend
from grace.eval.runner.harness.outputs import RunWriter
from grace.llm.records import CallLedger

SNAPSHOT = "snapshot"
MANIFEST = "manifest.json"
GRACE = "grace"
DEFAULT_VIEWS = "configs/views/default.yaml"     # GraceEngine.from_port defaults
DEFAULT_RETRIEVAL = "configs/retrieval/default.yaml"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")


# ---------------------------------------------------------------------------------------------
# Write side of an engine config


def _file_sha(path: str | None) -> str | None:
    return rundir.file_sha256(REPO_ROOT / path) if path else None


def _dense_on(params: dict[str, Any]) -> bool:
    return "dense" in RetrievalConfig.load(
        REPO_ROOT / params.get("retrieval", DEFAULT_RETRIEVAL)).channels


def write_side(config: dict[str, Any]) -> dict[str, Any]:
    """What an engine config fixes on the write side (module docstring); JSON-able."""
    side: dict[str, Any] = {"engine": config["engine"],
                            "writer_model": config.get("writer_model"),
                            "engine_llm": config.get("engine_llm")}
    files = {"writer_model": _file_sha(config.get("writer_model"))}
    if config["engine"] != GRACE:
        side.update(params=config["params"], embedding=config.get("embedding"), files=files)
        return side
    params = config["params"]
    components = dict(params.get("components") or {})
    views = params.get("views", DEFAULT_VIEWS)
    resident = views is not None and "views" not in components
    side["writer"] = params.get("writer")
    side["extension"] = components.get("extension")
    side["resident_views"] = ({"views": views, "staleness": params.get("staleness")}
                              if resident else None)
    side["dense"] = config.get("embedding") if _dense_on(params) else None
    files["writer"] = _file_sha(params.get("writer"))
    if resident:
        files["views"] = _file_sha(views)
    side["files"] = files
    return side


def incompatibilities(ingest: dict[str, Any], read: dict[str, Any]) -> list[str]:
    """Why a read engine with write side `read` cannot restore a snapshot of an ingest engine
    with write side `ingest` (both from `write_side`); empty when it can."""
    problems = []

    def differ(key: str, a: Any, b: Any) -> None:
        if a != b:
            problems.append(f"{key}: ingest {a!r}, read {b!r}")
    for key in ("engine", "writer_model", "engine_llm"):
        differ(key, ingest.get(key), read.get(key))
    differ("files.writer_model", ingest["files"].get("writer_model"),
           read["files"].get("writer_model"))
    if problems or read["engine"] != GRACE:
        for key in ("params", "embedding"):
            if read["engine"] != GRACE:
                differ(key, ingest.get(key), read.get(key))
        return problems
    differ("writer", ingest.get("writer"), read.get("writer"))
    differ("files.writer", ingest["files"].get("writer"), read["files"].get("writer"))
    differ("extension", ingest.get("extension"), read.get("extension"))
    if read.get("resident_views") is not None:
        differ("resident_views", ingest.get("resident_views"), read["resident_views"])
        differ("files.views", ingest["files"].get("views"), read["files"].get("views"))
    if read.get("dense") is not None:
        differ("dense (embedding of the dense index)", ingest.get("dense"), read["dense"])
    return problems


# ---------------------------------------------------------------------------------------------
# Shared machinery


@dataclass
class StageRun:
    run_dir: Path
    run_id: str
    status: str
    failure: str | None
    n_records: int


def _each(items: Iterable[HistoryInputs], work: Callable[[HistoryInputs], Any],
          done: Callable[[HistoryInputs, Any], None], workers: int) -> None:
    """`work` per history (in `workers` threads), then `done` with its result (serialised)."""
    items = list(items)
    if workers <= 1:
        for item in items:
            done(item, work(item))
        return
    lock = threading.Lock()

    def job(item):
        result = work(item)
        with lock:
            done(item, result)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(job, item) for item in items]
        finished, _ = wait(futures, return_when=FIRST_EXCEPTION)
        failed = [f for f in finished if f.exception() is not None]
        if failed:
            for f in futures:
                f.cancel()
            raise failed[0].exception()


def _history_dir(history_id: str) -> str:
    if not SAFE_ID.fullmatch(history_id):
        raise ValueError(f"history_id {history_id!r} cannot name a snapshot directory")
    return history_id


def _files_of(directory: Path, root: Path) -> list[dict[str, str]]:
    out = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symbolic link in a snapshot: {path}")
        if path.is_file():
            out.append({"path": path.relative_to(root).as_posix(),
                        "sha256": rundir.file_sha256(path)})
    return out


def _finish(run: rundir.RunJson, log, n: int, failure: str | None) -> None:
    log.write(f"done: {n} records\n" if failure is None else f"failure: {failure}\n")
    log.close()
    run.finish(n, failure)


# ---------------------------------------------------------------------------------------------
# Ingest stage


def run_ingest(*, engine_config: Path, experiment: str, run_root: Path,
               records: Path | None = None, benchmark: str | None = None, split: str = "dev",
               seed: int = 0, history_ids: list[str] | None = None,
               backend_factory: Callable[[bool], Backend] | None = None,
               client: ClientSettings | None = None, code: rundir.CodeState | None = None,
               command: str | None = None, on_model: Callable[[Any], None] | None = None,
               benchmark_config: BenchmarkConfig | None = None, workers: int = 1) -> StageRun:
    """One `ingest` run: every message of every history, `finish()`, and the snapshot."""
    config = load_engine_config(engine_config)
    inputs = load_inputs(records, benchmark, split, None, history_ids, benchmark_config)
    code = code or rundir.code_state()
    models = models_for(config, seed, client, backend_factory)
    run_dir = rundir.create(run_root, experiment)
    config_path = repo_relative(engine_config)
    resolved = {"stage": "ingest", "experiment": experiment, "engine_config": config_path,
                "engine": config, "write_side": write_side(config),
                "benchmark": inputs.benchmark, "split": inputs.split,
                "records": repo_relative(records) if records is not None else None,
                "histories": [h.history.history_id for h in inputs.histories],
                "seed": seed, "model": models.info, "max_attempts": 2, "workers": workers}
    if (settings := engine_settings(config, seed, client is None)) is not None:
        resolved["engine_settings"] = settings
    run = start_run(run_dir, experiment=experiment, stage="ingest", upstream=[],
                    resolved=resolved, config_path=config_path, inputs=inputs, seed=seed,
                    command=command, code=code, device=models.device)
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    ledger = CallLedger(run_dir / "calls.jsonl", run_dir.name)
    ledger.path.touch()
    snapshot = run_dir / SNAPSHOT
    snapshot.mkdir()
    n_messages = sum(len(h.messages) for h in inputs.histories)
    entries: dict[str, dict[str, Any]] = {}
    written = 0
    try:
        model, engine_model = models.build(ledger)
        if on_model:
            on_model(model)
        writer = RunWriter(run_dir, RunWriter.INGEST_FILES)

        def work(item: HistoryInputs):
            history_id = item.history.history_id
            engine = build_engine(config, engine_model, allow_no_client=client is None)
            engine.open(item.history)
            steps = [engine.write(m) for m in item.messages]
            steps += list(engine.finish())
            if engine.version != len(item.messages):
                raise RuntimeError(f"{history_id}: engine at version {engine.version} after "
                                   f"{len(item.messages)} messages")
            directory = snapshot / _history_dir(history_id)
            directory.mkdir()
            saved = {Path(p).resolve() for p in engine.save(directory)}
            files = _files_of(directory, snapshot)
            missing = saved - {(snapshot / f["path"]).resolve() for f in files}
            if missing:
                raise RuntimeError(f"{history_id}: save() reported files outside its directory")
            return steps, {"history_id": history_id, "version": engine.version, "files": files}

        def done(item: HistoryInputs, result) -> None:
            nonlocal written
            steps, entry = result
            for step in steps:
                writer.write(step)
            entries[entry["history_id"]] = entry
            written += len(item.messages)
            log.write(f"{entry['history_id']}: {len(item.messages)} messages, version "
                      f"{entry['version']}, {len(entry['files'])} snapshot files\n")
            log.flush()

        _each(inputs.histories, work, done, workers)
        manifest = {"histories": [entries[h.history.history_id] for h in inputs.histories]}
        (snapshot / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False)
                                         + "\n", encoding="utf-8")
        failure = None
        if written != n_messages:
            failure = f"record count: {written} messages written, {n_messages} in the inputs"
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        log.write(traceback.format_exc())
        _finish(run, log, written, f"{type(exc).__name__}: {exc}")
        raise
    log.write(f"{len(ledger.records)} model calls\n")
    _finish(run, log, written, failure)
    return StageRun(run_dir, run_dir.name, run.data["status"], run.data["failure"], written)


# ---------------------------------------------------------------------------------------------
# Read stage


def load_upstream(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """run.json, resolved config and snapshot manifest of a completed ingest run."""
    path = Path(path)
    run = json.loads((path / "run.json").read_text(encoding="utf-8"))
    if run.get("stage") != "ingest":
        raise ValueError(f"{run.get('run_id')}: upstream of a read run must be an ingest run, "
                         f"not {run.get('stage')!r}")
    if run.get("status") != "completed":
        raise ValueError(f"{run['run_id']}: upstream run is {run.get('status')!r}, "
                         "not completed")
    resolved = yaml.safe_load((path / "resolved-config.yaml").read_text(encoding="utf-8"))
    manifest = json.loads((path / SNAPSHOT / MANIFEST).read_text(encoding="utf-8"))
    return run, resolved, manifest


def _same_data(upstream: list[dict[str, Any]], ours: list[dict[str, Any]]) -> bool:
    def key(entries):
        return sorted((d["benchmark"], d["version"], d["manifest_sha256"], d["split"])
                      for d in entries)
    return key(upstream) == key(ours)


def restore_copy(upstream: Path, entry: dict[str, Any], target: Path) -> None:
    """Copy one history's snapshot files into `target`, checking every SHA-256."""
    prefix = _history_dir(entry["history_id"]) + "/"
    for f in entry["files"]:
        if not f["path"].startswith(prefix) or ".." in Path(f["path"]).parts:
            raise ValueError(f"manifest path {f['path']!r} outside {prefix}")
        source = upstream / SNAPSHOT / f["path"]
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise ValueError(f"snapshot file {f['path']} does not match the manifest")
        destination = target / f["path"][len(prefix):]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def run_read(*, engine_config: Path, upstream: Path, budget: int | None, experiment: str,
             run_root: Path, schedule: str | None = None, seed: int = 0,
             history_ids: list[str] | None = None,
             backend_factory: Callable[[bool], Backend] | None = None,
             client: ClientSettings | None = None, code: rundir.CodeState | None = None,
             command: str | None = None, on_model: Callable[[Any], None] | None = None,
             benchmark_config: BenchmarkConfig | None = None, workers: int = 1) -> StageRun:
    """One `read` run from the snapshot of one completed `ingest` run (module docstring).

    The benchmark records (fixture directory or development split) are those of the upstream
    run; `history_ids` limits the run to some of its histories."""
    upstream = Path(upstream).resolve()
    up_run, up_resolved, manifest = load_upstream(upstream)
    config = load_engine_config(engine_config)
    problems = incompatibilities(up_resolved["write_side"], write_side(config))
    if problems:
        raise ValueError(f"{up_run['run_id']}: the ingest engine differs on the write side: "
                         + "; ".join(problems))
    entries = {e["history_id"]: e for e in manifest["histories"]}
    history_ids = history_ids or list(up_resolved["histories"])
    unknown = sorted(set(history_ids) - entries.keys())
    if unknown:
        raise ValueError(f"histories not in the upstream snapshot: {unknown}")
    records = REPO_ROOT / up_resolved["records"] if up_resolved.get("records") else None
    inputs: Inputs = load_inputs(records, None if records else up_resolved["benchmark"],
                                 up_resolved["split"], schedule, history_ids, benchmark_config)
    code = code or rundir.code_state()
    # The read side never calls the writer: build the port without the writer's endpoint.
    read_config = {k: v for k, v in config.items() if k != "writer_model"}
    models = models_for(read_config, seed, client, backend_factory)
    max_tokens = int(budgets()["answer"]["output_reserve_tokens"])
    run_dir = rundir.create(run_root, experiment)
    config_path = repo_relative(engine_config)
    resolved = {"stage": "read", "experiment": experiment, "engine_config": config_path,
                "engine": config, "write_side": write_side(config),
                "upstream_ingest": {"run_id": up_run["run_id"], "code_sha": up_run["code_sha"],
                                    "engine_config": up_resolved["engine_config"],
                                    "manifest_sha256": rundir.file_sha256(
                                        upstream / SNAPSHOT / MANIFEST)},
                "benchmark": inputs.benchmark, "split": inputs.split,
                "read_tasks": inputs.schedule,
                "histories": [h.history.history_id for h in inputs.histories],
                "budget_tokens": budget, "seed": seed, "model": models.info,
                "answer_max_tokens": max_tokens, "max_attempts": 2, "workers": workers}
    if (settings := engine_settings(config, seed, client is None)) is not None:
        resolved["engine_settings"] = settings
    up_entry = {"run_id": up_run["run_id"], "stage": "ingest", "path": upstream.as_posix(),
                "run_json_sha256": rundir.file_sha256(upstream / "run.json")}
    run = start_run(run_dir, experiment=experiment, stage="read", upstream=[up_entry],
                    resolved=resolved, config_path=config_path, inputs=inputs, seed=seed,
                    command=command, code=code, device=models.device)
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    if up_run["code_sha"] != code.sha:
        log.write(f"note: upstream code {up_run['code_sha']}, this run {code.sha}\n")
    ledger = CallLedger(run_dir / "calls.jsonl", run_dir.name)
    ledger.path.touch()
    answered = 0
    try:
        if not _same_data(up_run["data"], run.data["data"]):
            raise ValueError("benchmark data differ from the upstream ingest run's")
        model, engine_model = models.build(ledger)
        if on_model:
            on_model(model)
        writer = RunWriter(run_dir, RunWriter.READ_FILES)

        def work(item: HistoryInputs):
            history_id = item.history.history_id
            entry = entries[history_id]
            target = run_dir / "cache" / "restore" / _history_dir(history_id)
            target.mkdir(parents=True)
            restore_copy(upstream, entry, target)
            engine: api.ContextEngine = build_engine(config, engine_model,
                                                     allow_no_client=client is None)
            engine.restore(target)
            last = item.messages[-1]
            if engine.version != entry["version"] or engine.version != last.version:
                raise RuntimeError(f"{history_id}: restored version {engine.version}, manifest "
                                   f"{entry['version']}, last message {last.version}")
            visible = {m.message_id for m in item.messages}
            out = []
            for task in item.reads:
                if task.version != engine.version:
                    raise ValueError(f"{task.read_id} reads version {task.version}, not the end "
                                     f"of the history ({engine.version}): use a system run")
                result, prediction = answer_read(engine, task, budget, model, visible,
                                                 message_time(last, item.history), max_tokens)
                if result.writes:
                    raise RuntimeError(f"{task.read_id}: the read committed write-side work; "
                                       "the snapshot was not complete")
                out.append((prediction, result.context, result.trace))
            if engine.finish():
                raise RuntimeError(f"{history_id}: finish() after restore committed work")
            shutil.rmtree(target)
            return out

        def done(item: HistoryInputs, out) -> None:
            nonlocal answered
            for prediction, context, trace in out:
                writer.read(prediction, context, trace)
            answered += len(out)
            log.write(f"{item.history.history_id}: {len(out)} reads\n")
            log.flush()

        _each(inputs.histories, work, done, workers)
        failure = None
        if answered != inputs.n_reads or writer.counts["predictions.jsonl"] != inputs.n_reads:
            failure = f"record count: {answered} answered, {inputs.n_reads} read tasks"
        restore = run_dir / "cache" / "restore"
        if restore.exists() and not any(restore.iterdir()):
            restore.rmdir()
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        log.write(traceback.format_exc())
        _finish(run, log, answered, f"{type(exc).__name__}: {exc}")
        raise
    log.write(f"{len(ledger.records)} model calls\n")
    _finish(run, log, answered, failure)
    return StageRun(run_dir, run_dir.name, run.data["status"], run.data["failure"], answered)


def add_stage_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--stage", choices=["system", "ingest", "read"], default="system",
                        help="system (default), ingest (writes and snapshot) or read (from the "
                             "snapshot of --upstream)")
    parser.add_argument("--upstream", type=Path, default=None,
                        help="read stage: the directory of one completed ingest run")
    parser.add_argument("--workers", type=int, default=1,
                        help="ingest and read stages: histories processed in parallel")
