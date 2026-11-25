"""Drive a ContextEngine over histories by their read schedule; the `system` stage of a run.

For every history: a fresh engine is opened, messages are written in version order, and after
message r every read task with `version` r is answered on that snapshot, each independently, before
message r+1 is written (contracts.md, "Read task"). The harness passes only visible records to the
engine and to the answering model; gold data is never loaded here.

Usage (deterministic fake model; the real backend arrives with T004's `llm/client.py`):

    uv run python -m grace.eval.runner.harness.drive --engine configs/engines/bm25.yaml \
        --records tests/fixtures/benchmarks/locomo --budget 512 --experiment T003
"""

from __future__ import annotations

import argparse
import shlex
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.context import api
from grace.eval.engines.baselines.registry import ENGINES
from grace.eval.runner.harness import rundir
from grace.eval.runner.harness.answer import answer
from grace.eval.runner.harness.inputs import Inputs, load
from grace.eval.runner.harness.ledger import CallLedger
from grace.eval.runner.harness.models import Backend, FakeBackend, RecordingModel
from grace.eval.runner.harness.outputs import Prediction, RunWriter


def load_engine_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    unknown = set(config) - {"engine", "description", "params", "prefix_caching"}
    if unknown or config.get("engine") not in ENGINES:
        raise ValueError(f"{path}: bad engine config (unknown keys {sorted(unknown)}, "
                         f"engine {config.get('engine')!r} not in {sorted(ENGINES)})")
    config.setdefault("params", {})
    config.setdefault("prefix_caching", False)
    return config


def build_engine(config: dict[str, Any], model) -> api.ContextEngine:
    return ENGINES[config["engine"]](model, **config["params"])


@dataclass
class SystemRun:
    run_dir: Path
    run_id: str
    status: str
    failure: str | None
    n_reads: int


def drive_history(engine: api.ContextEngine, item, budget: int | None, model: RecordingModel,
                  writer: RunWriter) -> int:
    """Ingest one history and answer its reads; return the number of reads answered."""
    engine.open(item.history)
    reads = list(item.reads)
    visible: set[str] = set()
    answered = 0
    for message in item.messages:
        writer.write(engine.write(message))
        visible.add(message.message_id)
        while reads and reads[0].version == message.version:
            task = reads.pop(0)
            result = answer(engine, task, budget, model, visible)
            engine.end_read(task)
            metadata = {"dropped_citations": result.dropped_citations} \
                if result.dropped_citations else {}
            prediction = Prediction(
                benchmark=task.benchmark, split=task.split, history_id=task.history_id,
                read_id=task.read_id, task_id=task.task_id, version=task.version,
                output=result.output, prediction=result.prediction, cited_ids=result.cited_ids,
                context_ids=result.context.context_ids,
                further_retrieval=result.trace.further_retrieval, raw_output=result.raw_output,
                metadata=metadata)
            writer.read(prediction, result.context, result.trace)
            answered += 1
    if reads:
        raise RuntimeError(f"{len(reads)} reads of {item.history.history_id} were not reached")
    return answered


def run_system(*, engine_config: Path, records: Path, budget: int | None, experiment: str,
               run_root: Path, schedule: str | None = None, seed: int = 0,
               data_version: str | None = None, history_ids: list[str] | None = None,
               backend_factory: Callable[[bool], Backend] | None = None,
               code: rundir.CodeState | None = None, command: str | None = None,
               on_model: Callable[[RecordingModel], None] | None = None,
               engine_wrapper: Callable[[api.ContextEngine], api.ContextEngine] | None = None,
               ) -> SystemRun:
    """One `system` stage run of one engine config on one benchmark split and budget."""
    config = load_engine_config(engine_config)
    inputs: Inputs = load(records, schedule, history_ids)
    if data_version is None:
        if inputs.split != "fixture":
            raise ValueError("--data-version is required outside fixtures")
        data_version = "fixture"
    code = code or rundir.code_state()
    backend = (backend_factory or (lambda caching: FakeBackend(prefix_caching=caching)))(
        config["prefix_caching"])
    run_dir = rundir.create(run_root, experiment)
    run_id = run_dir.name
    try:
        config_path = engine_config.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        config_path = engine_config.resolve().as_posix()
    resolved = {"stage": "system", "experiment": experiment, "engine_config": config_path,
                "engine": config, "benchmark": inputs.benchmark, "split": inputs.split,
                "read_tasks": inputs.files[-1], "histories": [h.history.history_id
                                                              for h in inputs.histories],
                "budget_tokens": budget, "seed": seed, "model": backend.model,
                "max_attempts": 2}
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True), encoding="utf-8")
    run = rundir.RunJson(run_dir, {
        "run_id": run_id, "experiment": experiment, "stage": "system", "upstream": [],
        "code_sha": code.sha, "code_dirty": code.dirty, "config_path": config_path,
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(),
        "data": [{"benchmark": inputs.benchmark, "version": data_version,
                  "manifest_sha256": inputs.manifest_sha256(), "split": inputs.split,
                  "path": inputs.directory.resolve().as_posix()}],
        "project_root": project_root().as_posix(), "seed": seed,
        "command": command or " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment(backend.device)})
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    ledger = CallLedger(run_dir / "calls.jsonl", run_id)
    ledger.path.touch()
    model = RecordingModel(backend, ledger, max_attempts=resolved["max_attempts"])
    if on_model:
        on_model(model)
    writer = RunWriter(run_dir)
    answered, failure = 0, None
    try:
        for item in inputs.histories:
            engine = build_engine(config, model)
            if engine_wrapper:
                engine = engine_wrapper(engine)
            answered += drive_history(engine, item, budget, model, writer)
            log.write(f"{item.history.history_id}: {len(item.messages)} messages, "
                      f"{len(item.reads)} reads\n")
        if answered != inputs.n_reads or writer.counts["predictions.jsonl"] != inputs.n_reads:
            failure = f"record count: {answered} answered, {inputs.n_reads} read tasks"
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        failure = f"{type(exc).__name__}: {exc}"
        log.write(traceback.format_exc())
        run.finish(answered, failure)
        log.close()
        raise
    log.write(f"done: {answered} reads, {len(ledger.records)} model calls\n")
    log.close()
    run.finish(answered, failure)
    return SystemRun(run_dir, run_id, run.data["status"], run.data["failure"], answered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engine", type=Path, required=True, help="configs/engines/<name>.yaml")
    parser.add_argument("--records", type=Path, required=True,
                        help="directory with histories.jsonl, messages.jsonl, read_tasks*.jsonl")
    parser.add_argument("--schedule", default=None, help="read-task schedule (default: native)")
    parser.add_argument("--budget", default="full", help="memory budget in tokens, or 'full'")
    parser.add_argument("--experiment", default="T003", help="T<NNN> or E<NNN>")
    parser.add_argument("--run-root", type=Path, default=None,
                        help="parent of <experiment>/<run-id>/ (default: runs/T003/artifacts/"
                             "manager under PROJECT_ROOT)")
    parser.add_argument("--history", action="append", default=None, help="limit to histories")
    parser.add_argument("--data-version", default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--backend", choices=["fake"], default="fake",
                        help="only the deterministic fake until T004 provides llm/client.py")
    args = parser.parse_args(argv)
    budget = None if args.budget == "full" else int(args.budget)
    run_root = args.run_root or shared_dir("runs_root") / "T003" / "artifacts" / "manager"
    result = run_system(engine_config=args.engine, records=args.records, budget=budget,
                        experiment=args.experiment, run_root=run_root, schedule=args.schedule,
                        seed=args.seed, data_version=args.data_version,
                        history_ids=args.history)
    print(f"{result.run_id}: {result.status} ({result.n_reads} reads) -> {result.run_dir}")
    if result.failure:
        print(f"failure: {result.failure}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
