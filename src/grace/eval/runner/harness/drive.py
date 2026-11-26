"""Drive a ContextEngine over histories by their read schedule; the `system` stage of a run.

For every history: a fresh engine is opened, messages are written in version order, and after
message r every read task with `version` r is answered on that snapshot, each independently, before
message r+1 is written (contracts.md, "Read task"). The harness passes only visible records to the
engine and to the answering model; gold data is never handed on.

Inputs come from a development split through `load_split` (`--benchmark`, `--split`), or from a
synthetic fixture directory (`--records`, tests and CI only). Model calls go through `grace.llm`
(`--backend client`: the OpenAI-compatible server at `--base-url`, the model pin of
`--model-config`, embeddings from `--embed-url`), or through the deterministic fake
(`--backend fake`, the default; no network, no score from it is real).

An engine config MAY name a second model for the engine's own chat calls (`engine_llm`, T034:
Graphiti's native-backbone row). With `--backend client` the engine is then built on an
`EngineLLMModel`: its chat calls go to that endpoint, whose URL, deployment and key come from the
environment variables the config names (never from the repository), while its embeddings, its
token counting and the answering step stay on the run's model. The fake backend ignores it.

    uv run python -m grace.eval.runner.harness.drive --engine configs/engines/bm25.yaml \
        --benchmark locomo --split dev --history conv-26 --budget full --backend client \
        --base-url http://127.0.0.1:8061/v1 --embed-url http://127.0.0.1:8062/v1
"""

from __future__ import annotations

import argparse
import functools
import os
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
from grace.eval.datasets.benchmarks.base import BenchmarkConfig
from grace.eval.engines.baselines.base import message_time
from grace.eval.engines.baselines.registry import ENGINES
from grace.eval.runner.harness import rundir
from grace.eval.runner.harness.answer import answer
from grace.eval.runner.harness.inputs import Inputs, load_dev, load_fixture
from grace.eval.runner.harness.models import (
    Backend,
    ClientModel,
    EngineLLMModel,
    FakeBackend,
    RecordingModel,
)
from grace.eval.runner.harness.outputs import Prediction, RunWriter
from grace.llm.client import ChatClient, Endpoint
from grace.llm.embeddings import EmbeddingClient
from grace.llm.records import CallLedger
from grace.llm.tokens import HFTokenCounter, TokenizerJsonCounter, TokenizerPin, locate_snapshot

BUDGETS = REPO_ROOT / "configs" / "common" / "budgets.yaml"
DEFAULT_MODEL = REPO_ROOT / "configs" / "models" / "qwen3-8b.yaml"
ENGINE_KEYS = {"engine", "description", "params", "prefix_caching", "embedding", "engine_llm"}
# `engine_llm`: the engine's own chat model. Required keys, then descriptive ones.
ENGINE_LLM_REQUIRED = {"label", "base_url_env", "deployment_env", "api_key_env", "tokenizer",
                       "decoding"}
ENGINE_LLM_KEYS = ENGINE_LLM_REQUIRED | {"auth_header", "input_tokens", "transport_attempts",
                                        "backoff_s", "provider", "model", "version", "deployment"}


def load_engine_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    unknown = set(config) - ENGINE_KEYS
    if unknown or config.get("engine") not in ENGINES:
        raise ValueError(f"{path}: bad engine config (unknown keys {sorted(unknown)}, "
                         f"engine {config.get('engine')!r} not in {sorted(ENGINES)})")
    if "engine_llm" in config:
        spec = config["engine_llm"]
        keys = set(spec) if isinstance(spec, dict) else set()
        if keys - ENGINE_LLM_KEYS or ENGINE_LLM_REQUIRED - keys:
            raise ValueError(f"{path}: engine_llm needs {sorted(ENGINE_LLM_REQUIRED)} and allows "
                             f"{sorted(ENGINE_LLM_KEYS - ENGINE_LLM_REQUIRED)}; got {sorted(keys)}")
    config.setdefault("params", {})
    config.setdefault("prefix_caching", False)
    return config


def build_engine(config: dict[str, Any], model) -> api.ContextEngine:
    return ENGINES[config["engine"]](model, **config["params"])


def budgets() -> dict[str, Any]:
    return yaml.safe_load(BUDGETS.read_text(encoding="utf-8"))


def repo_relative(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


# ---------------------------------------------------------------------------------------------
# Real model client


@functools.cache
def _counter(model_config: Path) -> HFTokenCounter:
    pin = TokenizerPin.from_file(model_config)
    return HFTokenCounter(pin, locate_snapshot(pin))


@dataclass(frozen=True)
class ClientSettings:
    """Where the served models are; recorded in resolved-config.yaml."""

    base_url: str
    model_config: Path = DEFAULT_MODEL
    embed_url: str | None = None
    serving: dict[str, Any] | None = None  # server settings to record (e.g. prefix caching)

    def model_info(self) -> dict[str, Any]:
        config = yaml.safe_load(Path(self.model_config).read_text(encoding="utf-8"))
        info = {"model_config": repo_relative(self.model_config),
                "served_name": config["served_name"],
                "label": f"{config['hf_repo']}@{config['revision']}",
                "thinking": config["thinking"], "decoding": config["decoding"],
                "base_url": self.base_url, "embed_url": self.embed_url}
        if self.serving is not None:
            info["serving"] = dict(self.serving)
        return info

    def factory(self, engine_config: dict[str, Any], seed: int
                ) -> Callable[[CallLedger], ClientModel]:
        config = yaml.safe_load(Path(self.model_config).read_text(encoding="utf-8"))
        attempts = int(budgets()["pipeline"]["transport_attempts"])

        def make(ledger: CallLedger) -> ClientModel:
            counter = _counter(Path(self.model_config))
            endpoint = Endpoint.for_model(counter.pin, self.base_url, config["served_name"])
            client = ChatClient(endpoint, ledger, counter, max_attempts=attempts)
            embedder = None
            if "embedding" in engine_config:
                if not self.embed_url:
                    raise ValueError("this engine embeds: pass --embed-url")
                emb = engine_config["embedding"]
                embedder = EmbeddingClient(
                    Endpoint(base_url=self.embed_url, served_model=emb["served_name"],
                             model_label=f"{emb['hf_repo']}@{emb['revision']}"),
                    ledger, counter.count_text, max_attempts=attempts)
            decoding = {**config["decoding"], "seed": seed}
            return ClientModel(client, counter, decoding=decoding, embedder=embedder)
        return make

    def engine_factory(self, engine_config: dict[str, Any], seed: int
                       ) -> Callable[[CallLedger, ClientModel], EngineLLMModel] | None:
        """The engine's port when its config names its own chat model (`engine_llm`), else None
        (the engine shares the run's model)."""
        spec = engine_config.get("engine_llm")
        if spec is None:
            return None
        # A hosted API limits requests per minute: the config may allow more transport attempts
        # and a longer back-off (doubling per attempt) than the local servers need.
        attempts = int(spec.get("transport_attempts",
                                budgets()["pipeline"]["transport_attempts"]))
        backoff = float(spec.get("backoff_s", 1.0))

        def make(ledger: CallLedger, base: ClientModel) -> EngineLLMModel:
            counter = TokenizerJsonCounter.from_pin(spec["tokenizer"])
            client = ChatClient(engine_llm_endpoint(spec), ledger, counter, max_attempts=attempts,
                                backoff_s=backoff)
            decoding = {**spec["decoding"], "seed": seed}
            return EngineLLMModel(ClientModel(client, counter, decoding=decoding), base)
        return make


def engine_llm_endpoint(spec: dict[str, Any]) -> Endpoint:
    """Endpoint of an engine's own chat model. Its URL and deployment are read from the
    environment variables the config names, so neither is written to the repository or the run
    directory; the key is read by the client at call time."""
    names = (spec["base_url_env"], spec["deployment_env"], spec["api_key_env"])
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"engine_llm: environment variables not set: {', '.join(missing)}")
    return Endpoint(base_url=os.environ[spec["base_url_env"]],
                    served_model=os.environ[spec["deployment_env"]], model_label=spec["label"],
                    api_key_env=spec["api_key_env"], auth_header=spec.get("auth_header", "bearer"),
                    input_tokens=spec.get("input_tokens", "local"))


# ---------------------------------------------------------------------------------------------
# System stage


@dataclass
class SystemRun:
    run_dir: Path
    run_id: str
    status: str
    failure: str | None
    n_reads: int


def drive_history(engine: api.ContextEngine, item, budget: int | None, model,
                  writer: RunWriter, max_tokens: int | None = None) -> int:
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
            result = answer(engine, task, budget, model, visible,
                            asked_at=message_time(message, item.history), max_tokens=max_tokens)
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


def run_system(*, engine_config: Path, budget: int | None, experiment: str, run_root: Path,
               records: Path | None = None, benchmark: str | None = None, split: str = "dev",
               schedule: str | None = None, seed: int = 0,
               history_ids: list[str] | None = None,
               backend_factory: Callable[[bool], Backend] | None = None,
               client: ClientSettings | None = None,
               code: rundir.CodeState | None = None, command: str | None = None,
               on_model: Callable[[Any], None] | None = None,
               engine_wrapper: Callable[[api.ContextEngine], api.ContextEngine] | None = None,
               benchmark_config: BenchmarkConfig | None = None,
               ) -> SystemRun:
    """One `system` stage run of one engine config on one benchmark split and budget.

    Exactly one of `records` (fixture directory) and `benchmark` (development split) is given;
    `client` selects the real model path, otherwise `backend_factory` (default: the fake)."""
    if (records is None) == (benchmark is None):
        raise ValueError("give exactly one of records (fixtures) and benchmark (development data)")
    if client is not None and backend_factory is not None:
        raise ValueError("give at most one of client and backend_factory")
    config = load_engine_config(engine_config)
    inputs: Inputs = (load_fixture(records, schedule, history_ids) if records is not None
                      else load_dev(benchmark, split, schedule, history_ids,
                                    config=benchmark_config))
    code = code or rundir.code_state()
    max_tokens = int(budgets()["answer"]["output_reserve_tokens"])
    make_engine_model = None
    if client is not None:
        make_model = client.factory(config, seed)
        make_engine_model = client.engine_factory(config, seed)
        model_info, device = client.model_info(), "cpu (model on the serving endpoint)"
    else:
        backend = (backend_factory or (lambda caching: FakeBackend(prefix_caching=caching)))(
            config["prefix_caching"])
        attempts = 2

        def make_model(ledger):
            return RecordingModel(backend, ledger, max_attempts=attempts)
        model_info, device = {"label": backend.model}, backend.device
    run_dir = rundir.create(run_root, experiment)
    run_id = run_dir.name
    config_path = repo_relative(engine_config)
    resolved = {"stage": "system", "experiment": experiment, "engine_config": config_path,
                "engine": config, "benchmark": inputs.benchmark, "split": inputs.split,
                "read_tasks": inputs.schedule, "histories": [h.history.history_id
                                                             for h in inputs.histories],
                "budget_tokens": budget, "seed": seed, "model": model_info,
                "answer_max_tokens": max_tokens, "max_attempts": 2}
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True), encoding="utf-8")
    data = [{"benchmark": inputs.benchmark, "version": inputs.data_version,
             "manifest_sha256": inputs.manifest_sha256, "split": inputs.split,
             "path": inputs.path.resolve().as_posix()}]
    data += [{"benchmark": inputs.benchmark, "version": version, "manifest_sha256": sha,
              "split": inputs.split, "path": (inputs.path.parent / version).resolve().as_posix()}
             for version, sha in inputs.extra_manifests]
    run = rundir.RunJson(run_dir, {
        "run_id": run_id, "experiment": experiment, "stage": "system", "upstream": [],
        "code_sha": code.sha, "code_dirty": code.dirty, "config_path": config_path,
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": data,
        "project_root": project_root().as_posix(), "seed": seed,
        "command": command or " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment(device)})
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    ledger = CallLedger(run_dir / "calls.jsonl", run_id)
    ledger.path.touch()
    answered, failure = 0, None
    try:
        model = make_model(ledger)
        engine_model = make_engine_model(ledger, model) if make_engine_model else model
        if on_model:
            on_model(model)
        writer = RunWriter(run_dir)
        for item in inputs.histories:
            engine = build_engine(config, engine_model)
            if engine_wrapper:
                engine = engine_wrapper(engine)
            answered += drive_history(engine, item, budget, model, writer, max_tokens)
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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--benchmark", help="benchmark slug; its development split is loaded "
                                            "through load_split")
    source.add_argument("--records", type=Path,
                        help="synthetic fixture directory (split 'fixture' only)")
    parser.add_argument("--split", default="dev", help="development split (default: dev)")
    parser.add_argument("--schedule", default=None, help="read-task schedule (default: native)")
    parser.add_argument("--budget", default="full", help="memory budget in tokens, or 'full'")
    parser.add_argument("--experiment", default="T003", help="T<NNN> or E<NNN>")
    parser.add_argument("--run-root", type=Path, default=None,
                        help="parent of <experiment>/<run-id>/ (default: runs/T003/artifacts/"
                             "manager under PROJECT_ROOT)")
    parser.add_argument("--history", action="append", default=None, help="limit to histories")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--backend", choices=["fake", "client"], default="fake")
    parser.add_argument("--base-url", default=None, help="chat endpoint, e.g. "
                                                         "http://127.0.0.1:8061/v1")
    parser.add_argument("--embed-url", default=None, help="embedding endpoint (dense, rrf)")
    parser.add_argument("--model-config", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args(argv)
    budget = None if args.budget == "full" else int(args.budget)
    run_root = args.run_root or shared_dir("runs_root") / "T003" / "artifacts" / "manager"
    client = None
    if args.backend == "client":
        if not args.base_url:
            parser.error("--backend client needs --base-url")
        client = ClientSettings(args.base_url, args.model_config, args.embed_url)
    result = run_system(engine_config=args.engine, records=args.records,
                        benchmark=args.benchmark, split=args.split, budget=budget,
                        experiment=args.experiment, run_root=run_root, schedule=args.schedule,
                        seed=args.seed, history_ids=args.history, client=client)
    print(f"{result.run_id}: {result.status} ({result.n_reads} reads) -> {result.run_dir}")
    if result.failure:
        print(f"failure: {result.failure}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
