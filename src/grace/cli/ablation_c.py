"""E005, ablation C on gold graphs: template serialisation against LLM rendering of the same rows.

    uv run python -m grace.cli.ablation_c system \\
        --config configs/experiments/E005-ablation-c-gold.yaml --arm llm --budget 1024 \\
        --base-url http://127.0.0.1:8106/v1
    uv run python -m grace.cli.ablation_c score --config <config> --system <system run dir>
    uv run python -m grace.cli.ablation_c compare --config <config> --budget 1024 \\
        --arm template=<score run dir> --arm llm=<score run dir> --arm raw=<score run dir>

- `system` (stage `system`): one arm at one display budget on every development sequence. The
  view arms (`template`, `llm`) answer from the resident views of the sequence's gold bindings,
  built by the frozen view code (`context/views/`) on the stored gold graph with surface entity
  labels (the gold-graph oracle of this experiment; structure.md, "Question answering on gold
  graphs"). At the first read of every read version each view is re-queried and repaired
  (`ViewStore.maintain`, confirm=True; rendering booked to W with trigger `read`). The working
  context holds one fragment per view, taken in an order fixed per read (sha256 of read ID and
  view ID, the same for both view arms) while it fits the budget. The `raw` arm is the harness's
  raw-text engine (`configs/engines/full-history.yaml`) at the same budget: the newest messages
  that fit. Answering is the shared harness step (`runner/harness/answer.py`). Besides the
  contract's files a view run writes `views/view_events.jsonl` (every maintenance event: units
  rendered, sentences kept, rendering-check counts, call IDs).
- `score` (stage `score`): normalised set match (`eval/analysis/metrics/changeseq.py`) of one
  system run; writes the split's records under `records/` (gold reaches the analysis as files),
  `scores.jsonl` (one value per read) and `metrics.json`.
- `compare` (not a run): paired differences with cluster-bootstrap intervals (D002), accuracy per
  arm, the render-check failure rate and write-side rendering tokens of the view runs, written
  with the checksum of every input run.json to `<out>/summary.json`.

Development data only; the oracle reads gold graphs of development sequences only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
import time
import traceback
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.context import api
from grace.context.memory.graph.entries import Entity
from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.query.result import QueryResult, scope_note
from grace.context.views.render import LLMRenderer, Renderer, TemplateRenderer
from grace.context.views.store import ViewStore
from grace.context.views.template_families import ViewConfig, load_view_config
from grace.context.views.view import Binding, View
from grace.eval.analysis.metrics import changeseq as metric
from grace.eval.analysis.metrics.align import read_jsonl
from grace.eval.analysis.metrics.record import write_metrics
from grace.eval.datasets.benchmarks.base import BenchmarkConfig, write_records
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.datasets.changeseq.template_families import load_family
from grace.eval.engines.baselines.base import BaselineEngine, CallTag, Packer, pinned_prompt
from grace.eval.runner.harness import drive, rundir
from grace.eval.runner.harness.drive import ClientSettings, drive_history
from grace.eval.runner.harness.inputs import load_dev
from grace.eval.runner.harness.models import FakeBackend, RecordingModel
from grace.eval.runner.harness.outputs import RunWriter
from grace.llm.client import ChatResult as ClientChatResult
from grace.llm.records import CallLedger, CallRecord, read_calls

EXPERIMENT = "E005"
TEMPLATE_FAMILY = {"V1": "list", "V2": "current", "V3": "count", "V4": "constraints",
                   "V5": "pending", "V6": "choice"}
VIEW_ARMS = ("template", "llm")
EVENTS_FILE = "views/view_events.jsonl"
STRATEGY = "requery-at-read"


def run_root() -> Path:
    return shared_dir("runs_root") / EXPERIMENT / "artifacts" / "manager"


# ---------------------------------------------------------------------------------------------
# Config


def load_experiment(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for key in ("experiment", "seed", "model_config", "benchmark", "views", "arms", "budgets",
                "population", "scoring", "comparison"):
        if key not in config:
            raise ValueError(f"{path}: missing {key!r}")
    if config["experiment"] != EXPERIMENT:
        raise ValueError(f"{path}: experiment is {config['experiment']!r}")
    return config


def benchmark_config(config: Mapping[str, Any]) -> BenchmarkConfig:
    bc = BenchmarkConfig.from_dict(config["benchmark"]["config"])
    if bc.splits[config["benchmark"]["split"]].kind != "development":
        raise ValueError("ablation C reads development splits only")
    return bc


def view_config(config: Mapping[str, Any], mode: str) -> ViewConfig:
    views = config["views"]
    base = load_view_config(REPO_ROOT / views["base_config"])
    return replace(base, state_speaker=views["state_speaker"],
                   choice_predicate=views["choice_predicate"],
                   rendering=replace(base.rendering, mode=mode))


def repo_relative(path: Path) -> str:
    return drive.repo_relative(Path(path))


# ---------------------------------------------------------------------------------------------
# Gold-graph oracle


def sequence_dirs(bc: BenchmarkConfig, root: Path | None = None) -> dict[str, Path]:
    source = bc.source_dir(root or project_root())
    dataset = json.loads((source / "dataset.json").read_text(encoding="utf-8"))
    return {s["sequence_id"]: source / s["path"] for s in dataset["sequences"]}


def surface_labels(seq_dir: Path) -> dict[str, str]:
    """Generator entity ID -> surface label: tasks ("k1" -> "car rental A") and offered items
    ("car-astra" -> "Opel Astra"), as the dialogue and the questions name them."""
    meta = json.loads((seq_dir / "meta.json").read_text(encoding="utf-8"))
    if meta["split"] != "development":
        raise ValueError(f"{seq_dir.name} is in split {meta['split']!r}; development only")
    labels = {k: v.removeprefix("the ") for k, v in meta["world"]["tasks"].items()}
    labels.update(dict(load_family(meta["family"]).task.items))
    return labels


def relabelled(store: ClaimStore, labels: Mapping[str, str]) -> ClaimStore:
    """The same change sets with entity IDs (claim subjects and entity objects) relabelled."""
    def name(x: str) -> str:
        return labels.get(x, x)

    out = ClaimStore(store.history_id, store.mode)
    for cs in store.changesets():
        claims = tuple(replace(c, subject=name(c.subject),
                               object=Entity(name(c.object.id)) if isinstance(c.object, Entity)
                               else c.object) for c in cs.claims)
        out.commit(replace(cs, claims=claims))
    return out


@dataclass(frozen=True)
class GoldViews:
    """The gold graph of one sequence and its view bindings, with surface entity labels."""

    history_id: str
    graph: ClaimStore
    bindings: tuple[Binding, ...]


def load_gold_views(seq_dir: Path) -> GoldViews:
    labels = surface_labels(seq_dir)
    store = ClaimStore.restore(seq_dir / "graph")
    bindings = []
    for line in (seq_dir / "bindings.jsonl").read_text(encoding="utf-8").splitlines():
        b = json.loads(line)
        bindings.append(Binding(TEMPLATE_FAMILY[b["template"]], labels.get(b["subject"],
                                                                         b["subject"]),
                                b["predicate"]))
    return GoldViews(store.history_id, relabelled(store, labels), tuple(bindings))


# ---------------------------------------------------------------------------------------------
# Renderers


@dataclass(frozen=True)
class _Record:
    call_id: str


class ModelChat:
    """`ChatPort` of `LLMRenderer` over a harness `ModelPort` (the fake backend of tests and dry
    runs). Real runs hand the renderer the `ChatClient` of the model instead."""

    def __init__(self, model):
        self.model = model

    def chat(self, messages, context, *, prompt_sha256, decoding=None, validate=None):
        def parse(text):
            error = validate(text) if validate else None
            if error:
                raise ValueError(error)
            return text
        tag = CallTag(context.call_type, context.trigger, context.history_id, context.version,
                      context.read_id)
        result = self.model.chat(messages, tag, prompt_sha256=prompt_sha256, parse=parse,
                                 max_tokens=(decoding or {}).get("max_tokens"))
        return ClientChatResult(text=result.text or "", status="ok" if result.ok
                                else "invalid_output", error=None,
                                records=[_Record(c) for c in result.call_ids])


def make_renderer(mode: str, model, config: ViewConfig, seed: int) -> Renderer:
    if mode == "template":
        return TemplateRenderer()
    port = getattr(model, "client", None) or ModelChat(model)
    rendering = config.rendering
    return LLMRenderer(port, pinned_prompt(rendering.prompt),
                       {**dict(rendering.decoding), "seed": seed},
                       max_rows_per_call=rendering.max_rows_per_call)


# ---------------------------------------------------------------------------------------------
# The view engine


_DECISION = {"advance": ("fresh", "reuse"), "citation_repair": ("citation_stale", "patch"),
             "local_rebuild": ("answer_stale", "rebuild"),
             "full_rebuild": ("answer_stale", "rebuild")}


def read_order(read_id: str, view_id: str) -> str:
    return hashlib.sha256(f"{read_id}\x00{view_id}".encode()).hexdigest()


def fragment_text(view: View, version: int) -> str:
    """One view as a context fragment: its title, each sentence after the IDs of the messages it
    cites (the answer prompt's convention), and the read-time scope note."""
    lines = [f"View: {view.title}"]
    for s in view.sentences:
        text = " ".join(s.text.split())
        lines.append(f"[{', '.join(s.evidence)}] {text}" if s.evidence else text)
    note = scope_note(QueryResult(view.columns, () if not view.rows else (None,), version,
                                  is_count=view.is_count))
    if note:
        lines.append(note)
    return "\n".join(lines)


class GoldViewEngine(BaselineEngine):
    """Working context = the resident views of the gold bindings at the read version."""

    kind = "gold-views"

    def __init__(self, model, *, gold: GoldViews, store: ViewStore,
                 events: list[dict[str, Any]]):
        super().__init__(model)
        self.gold, self.store, self.events = gold, store, events
        self._decisions: dict[int, list[api.StalenessDecision]] = {}
        for binding in gold.bindings:
            store.build(binding, gold.graph, 0)
        self._sink(store.events)

    def open(self, history: api.HistoryInfo) -> None:
        if history.history_id != self.gold.history_id:
            raise ValueError(f"gold graph of {self.gold.history_id} for {history.history_id}")
        super().open(history)

    def _sink(self, events) -> list[str]:
        call_ids = []
        for e in events:
            self.events.append({"history_id": self.gold.history_id, **e.to_record()})
            call_ids += e.call_ids
        return call_ids

    def _maintain(self, task: api.ReadTask) -> list[str]:
        if task.version in self._decisions:
            return []
        start = len(self.store.events)
        decisions = []
        for view in self.store.views():
            event = self.store.maintain(view.view_id, self.gold.graph, task.version,
                                        read_id=task.read_id)
            decision, action = _DECISION[event.action]
            decisions.append(api.StalenessDecision(view.view_id, STRATEGY, decision, action))
        self._decisions[task.version] = decisions
        return self._sink(self.store.events[start:])

    def _read(self, task, budget, request) -> api.ReadResult:
        history = self._history()
        if task.history_id != history.history_id:
            raise ValueError(f"read of {task.history_id!r} sent to {history.history_id!r}")
        api.check_read(self, task)
        start = time.perf_counter()
        call_ids = self._maintain(task) if request is None else []
        packer = Packer(self.model.count_tokens)
        views = sorted(self.store.views(), key=lambda v: read_order(task.read_id, v.view_id))
        fragments = [packer.fragment(v.view_id, "view", fragment_text(v, task.version),
                                     sorted(v.evidence())) for v in views]
        context = packer.pack(task, budget, fragments)
        kept = {f.fragment_id for f in context.fragments}
        hits = [v.view_id for v in views if v.view_id in kept and v.rows]
        timings = {"read": (time.perf_counter() - start) * 1000}
        trace = api.read_trace(context, call_ids=call_ids, further_retrieval=request is not None,
                               timings_ms=timings, view_hits=hits,
                               staleness_decisions=self._decisions[task.version])
        return api.ReadResult(context, trace)


# ---------------------------------------------------------------------------------------------
# System stage


@dataclass(frozen=True)
class Served:
    """Where the models are: the real endpoint, or the deterministic fake (tests, dry runs)."""

    base_url: str | None = None
    model_config: Path = REPO_ROOT / "configs" / "models" / "qwen3-8b.yaml"
    fake_responder: Callable | None = None


def run_views(config: Mapping[str, Any], config_path: Path, arm: str, budget: int,
              served: Served, history_ids: list[str] | None = None,
              command: str | None = None, data_root: Path | None = None,
              out_root: Path | None = None) -> drive.SystemRun:
    if arm not in VIEW_ARMS:
        raise ValueError(f"not a view arm: {arm}")
    mode = config["arms"][arm]["rendering"]
    seed = int(config["seed"])
    bc = benchmark_config(config)
    split = config["benchmark"]["split"]
    inputs = load_dev(config["benchmark"]["slug"], split, None, history_ids, config=bc,
                      data_root=data_root)
    dirs = sequence_dirs(bc, data_root)
    vconfig = view_config(config, mode)
    code = rundir.code_state()
    max_tokens = int(drive.budgets()["answer"]["output_reserve_tokens"])
    if served.base_url:
        client = ClientSettings(served.base_url, served.model_config)
        make_model = client.factory({}, seed)
        model_info, device = client.model_info(), "cpu (model on the serving endpoint)"
    else:
        backend = FakeBackend(served.fake_responder) if served.fake_responder else FakeBackend()

        def make_model(ledger):
            return RecordingModel(backend, ledger, max_attempts=2)
        model_info, device = {"label": backend.model}, backend.device
    run_dir = rundir.create(out_root or run_root(), EXPERIMENT)
    run_id = run_dir.name
    dataset_run = bc.source_dir(data_root or project_root()).parent / "run.json"
    upstream_data = json.loads(dataset_run.read_text(encoding="utf-8")) \
        if dataset_run.is_file() else {"run_id": None}
    resolved = {
        "stage": "system", "experiment": EXPERIMENT, "arm": arm, "rendering": mode,
        "engine": {"engine": GoldViewEngine.kind, "description": f"E005 {arm} views on gold "
                   "graphs", "maintenance": STRATEGY, "order": "sha256(read_id, view_id)"},
        "views": {"base_config": config["views"]["base_config"],
                  "families": list(vconfig.families), "speakers": dict(vconfig.speakers),
                  "state_speaker": vconfig.state_speaker,
                  "choice_predicate": vconfig.choice_predicate,
                  "rendering": {"mode": vconfig.rendering.mode,
                                "prompt": vconfig.rendering.prompt,
                                "max_rows_per_call": vconfig.rendering.max_rows_per_call,
                                "decoding": {**dict(vconfig.rendering.decoding), "seed": seed}},
                  "entity_labels": config["views"]["entity_labels"]},
        "oracle": {"dataset_run": upstream_data["run_id"],
                   "generator": upstream_data.get("renderer", {}).get("name"),
                   "graph": "graph/ of every sequence, entity IDs relabelled to surface labels"},
        "benchmark": inputs.benchmark, "split": inputs.split, "read_tasks": inputs.schedule,
        "histories": [h.history.history_id for h in inputs.histories], "budget_tokens": budget,
        "seed": seed, "model": model_info, "answer_max_tokens": max_tokens, "max_attempts": 2,
        "experiment_config": repo_relative(config_path)}
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True), encoding="utf-8")
    data = [{"benchmark": inputs.benchmark, "version": inputs.data_version,
             "manifest_sha256": inputs.manifest_sha256, "split": inputs.split,
             "path": inputs.path.resolve().as_posix()}]
    run = rundir.RunJson(run_dir, {
        "run_id": run_id, "experiment": EXPERIMENT, "stage": "system", "upstream": [],
        "code_sha": code.sha, "code_dirty": code.dirty, "config_path": repo_relative(config_path),
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": data,
        "project_root": project_root().as_posix(), "seed": seed,
        "command": command or shlex.join(sys.argv),
        "environment": rundir.environment(device)})
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    ledger = CallLedger(run_dir / "calls.jsonl", run_id)
    ledger.path.touch()
    events: list[dict[str, Any]] = []
    answered, failure = 0, None
    try:
        model = make_model(ledger)
        writer = RunWriter(run_dir)
        for item in inputs.histories:
            sid = item.history.history_id
            gold = load_gold_views(dirs[sid])
            store = ViewStore(sid, make_renderer(mode, model, vconfig, seed), config=vconfig)
            engine = GoldViewEngine(model, gold=gold, store=store, events=events)
            answered += drive_history(engine, item, budget, model, writer, max_tokens)
            log.write(f"{sid}: {len(item.messages)} messages, {len(item.reads)} reads\n")
        if answered != inputs.n_reads or writer.counts["predictions.jsonl"] != inputs.n_reads:
            failure = f"record count: {answered} answered, {inputs.n_reads} read tasks"
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        failure = f"{type(exc).__name__}: {exc}"
        log.write(traceback.format_exc())
        _write_events(run_dir, events)
        run.finish(answered, failure)
        log.close()
        raise
    _write_events(run_dir, events)
    log.write(f"done: {answered} reads, {len(ledger.records)} model calls, "
              f"{len(events)} view events\n")
    log.close()
    run.finish(answered, failure)
    return drive.SystemRun(run_dir, run_id, run.data["status"], run.data["failure"], answered)


def _write_events(run_dir: Path, events: list[dict[str, Any]]) -> None:
    path = run_dir / EVENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for e in events:
            handle.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")


def run_raw(config: Mapping[str, Any], budget: int, served: Served,
            history_ids: list[str] | None = None, command: str | None = None,
            data_root: Path | None = None, out_root: Path | None = None) -> drive.SystemRun:
    client = ClientSettings(served.base_url, served.model_config) if served.base_url else None
    factory = None
    if client is None:
        def factory(caching):
            return (FakeBackend(served.fake_responder, prefix_caching=caching)
                    if served.fake_responder else FakeBackend(prefix_caching=caching))
    if data_root is not None:
        raise ValueError("the raw arm reads PROJECT_ROOT data only (the harness has no data_root)")
    return drive.run_system(
        engine_config=REPO_ROOT / config["arms"]["raw"]["engine_config"], budget=budget,
        experiment=EXPERIMENT, run_root=out_root or run_root(),
        benchmark=config["benchmark"]["slug"], split=config["benchmark"]["split"],
        seed=int(config["seed"]), history_ids=history_ids, client=client,
        backend_factory=factory, command=command or shlex.join(sys.argv),
        benchmark_config=benchmark_config(config))


# ---------------------------------------------------------------------------------------------
# Score stage


def _completed(run_dir: Path, stage: str) -> dict[str, Any]:
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if run.get("status") != "completed":
        raise ValueError(f"{run_dir.name}: upstream run is {run.get('status')!r}, not completed")
    if run.get("stage") != stage:
        raise ValueError(f"{run_dir.name}: stage {run.get('stage')!r}, expected {stage!r}")
    return run


def run_score(config: Mapping[str, Any], config_path: Path, system_dir: Path, *,
              command: str | None = None, data_root: Path | None = None,
              out_root: Path | None = None, experiment: str = EXPERIMENT) -> Path:
    """Set-match score run of one change-seq system run. `config` needs `benchmark` (`config`,
    `split`), `scoring` and `population` as in E005's config (E010 passes its target's)."""
    system_dir = Path(system_dir).resolve()
    upstream = _completed(system_dir, "system")
    bc = benchmark_config(config)
    split = config["benchmark"]["split"]
    scoring, population = config["scoring"], config["population"]
    code = rundir.code_state()
    run_dir = rundir.create(out_root or run_root(), experiment)
    resolved = {"stage": "score", "experiment": experiment, "scoring": scoring,
                "population": population, "upstream_system": upstream["run_id"],
                "experiment_config": repo_relative(config_path)}
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True), encoding="utf-8")
    source = bc.source_dir(data_root or project_root())
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": experiment, "stage": "score",
        "upstream": [{"run_id": upstream["run_id"], "stage": "system",
                      "path": system_dir.as_posix(),
                      "run_json_sha256": rundir.file_sha256(system_dir / "run.json")}],
        "code_sha": code.sha, "code_dirty": code.dirty, "config_path": repo_relative(config_path),
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(),
        "data": [{"benchmark": bc.benchmark, "version": bc.version,
                  "manifest_sha256": bc.manifest_sha256, "split": split,
                  "path": source.resolve().as_posix()}],
        "project_root": project_root().as_posix(), "seed": upstream["seed"],
        "command": command or shlex.join(sys.argv), "environment": rundir.environment("cpu")})
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    try:
        records = load_split(bc.benchmark, split, config=bc, data_root=data_root)
        write_records(records, run_dir / "records")
        sys_config = yaml.safe_load((system_dir / "resolved-config.yaml").read_text("utf-8"))
        schedule = sys_config["read_tasks"]
        histories = set(sys_config["histories"])  # a run over some histories scores those
        tasks = [t for t in read_jsonl(run_dir / "records" / schedule)
                 if t["history_id"] in histories]
        scored = metric.score_reads(tasks, read_jsonl(run_dir / "records" / "messages.jsonl"),
                                    read_jsonl(run_dir / "records" / "gold.jsonl"),
                                    read_jsonl(system_dir / "predictions.jsonl"),
                                    annotation=scoring["annotation"])
        with (run_dir / "scores.jsonl").open("x", encoding="utf-8") as handle:
            for s in scored:
                handle.write(json.dumps(s.to_record(), sort_keys=True) + "\n")
        write_metrics(run_dir / "metrics.json", metric.metric_records(
            scored, split=split, schedule=schedule, annotation=scoring["annotation"],
            seed=int(upstream["seed"]), evaluator_version=code.sha,
            include_types=population["include_types"],
            descriptive_types=population["descriptive_types"], strata=scoring["strata"],
            invalid_policy=scoring["invalid_policy"]))
        log.write(f"scored {len(scored)} reads of {upstream['run_id']}\n")
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        log.write(traceback.format_exc())
        log.close()
        run.finish(0, f"{type(exc).__name__}: {exc}")
        raise
    log.close()
    run.finish(len(scored))
    return run_dir


# ---------------------------------------------------------------------------------------------
# Comparison (not a run)


def render_stats(system_dir: Path) -> dict[str, Any]:
    """Rendering-check counts from the view events and write-side rendering cost (ledger W,
    call type render) from calls.jsonl; answering cost alongside."""
    events = [json.loads(line) for line in (system_dir / EVENTS_FILE).read_text(
        "utf-8").splitlines()] if (system_dir / EVENTS_FILE).exists() else []
    calls: list[CallRecord] = read_calls(system_dir / "calls.jsonl")
    by_type: dict[str, dict[str, Any]] = {}
    for call_type in ("render", "answer"):
        rows = [c for c in calls if c.call_type == call_type]
        by_type[call_type] = {
            "calls": len(rows), "status": dict(Counter(c.status for c in rows)),
            "category": dict(Counter(c.category for c in rows)),
            "input_tokens": sum(c.input_tokens for c in rows),
            "output_tokens": sum(c.output_tokens for c in rows),
            "cached_input_tokens": sum(c.cached_input_tokens for c in rows)}
    llm_ok = sum(e["llm_sentences"] for e in events)
    failed = sum(e["failed_sentences"] for e in events)
    units = sum(e["units_rendered"] for e in events)
    fallback = sum(e["fallback_units"] for e in events)
    return {"view_events": len(events), "actions": dict(Counter(e["action"] for e in events)),
            "units_rendered": units, "llm_sentences": llm_ok, "failed_sentences": failed,
            "fallback_units": fallback,
            "sentence_failure_rate": failed / (llm_ok + failed) if llm_ok + failed else None,
            "unit_fallback_rate": fallback / units if units else None,
            "calls": by_type}


def context_stats(system_dir: Path, budget: int) -> dict[str, Any]:
    contexts = read_jsonl(system_dir / "contexts.jsonl")
    tokens = [c["tokens"] for c in contexts]
    views = [len([f for f in c["fragments"] if f["kind"] == "view"]) for c in contexts]
    return {"reads": len(contexts), "budget_tokens": budget, "tokens_mean": mean(tokens),
            "tokens_max": max(tokens), "views_in_context_mean": mean(views),
            "views_in_context_min": min(views)}


def compare(config: Mapping[str, Any], budget: int, score_dirs: Mapping[str, Path],
            out: Path, exclude_templates: Sequence[str] = ()) -> dict[str, Any]:
    """`exclude_templates`: also report each pair without the reads of these view templates, as
    a descriptive sensitivity analysis (`paired[pair]["sensitivity_excluding_<T>"]`)."""
    comparison, population = config["comparison"], config["population"]
    boot = comparison["bootstrap"]
    inputs, values, clusters_by, templates = {}, {}, {}, {}
    arms = {}
    for arm, score_dir in score_dirs.items():
        score_dir = Path(score_dir).resolve()
        run = _completed(score_dir, "score")
        system_dir = Path(run["upstream"][0]["path"])
        system = _completed(system_dir, "system")
        resolved = yaml.safe_load((system_dir / "resolved-config.yaml").read_text("utf-8"))
        if resolved["budget_tokens"] != budget:
            raise ValueError(f"{arm}: system run {system['run_id']} has budget "
                             f"{resolved['budget_tokens']}, not {budget}")
        if resolved.get("arm", "raw") != arm:
            raise ValueError(f"{arm}: system run {system['run_id']} is arm "
                             f"{resolved.get('arm', 'raw')}")
        rows = read_jsonl(score_dir / "scores.jsonl")
        inputs[arm] = {"score_run": run["run_id"], "system_run": system["run_id"],
                       "score_run_json_sha256": rundir.file_sha256(score_dir / "run.json"),
                       "system_run_json_sha256": rundir.file_sha256(system_dir / "run.json"),
                       "code_sha": system["code_sha"], "evaluator_version": run["code_sha"]}
        included = [r for r in rows if r["question_type"] in population["include_types"]]
        values[arm] = {r["read_id"]: r["value"] for r in included}
        templates = {r["read_id"]: r["template"] for r in included}
        clusters_by = {"family": {r["read_id"]: r["family"] for r in included},
                       "sequence": {r["read_id"]: r["history_id"] for r in included}}
        historical = [r for r in rows if r["question_type"] in population["descriptive_types"]]
        arms[arm] = {
            "accuracy": metric.cluster_bootstrap(values[arm], clusters_by[boot["cluster_unit"]],
                                                 resamples=boot["resamples"], seed=boot["seed"]),
            "outputs": dict(Counter(r["output"] for r in included)),
            "by_question_type": _by(included, "question_type"),
            "by_template": _by(included, "template"),
            "historical_descriptive": {"n_reads": len(historical), "accuracy": (
                mean(r["value"] for r in historical) if historical else None)},
            "context": context_stats(system_dir, budget)}
        if arm in VIEW_ARMS:
            arms[arm]["rendering"] = render_stats(system_dir)
    pairs = {}
    names = [tuple(comparison["primary"])]
    ref = comparison.get("reference")
    names += [(a, ref) for a in VIEW_ARMS if ref and a in values and ref in values]
    for a, b in names:
        if a not in values or b not in values:
            continue
        key = f"{a}-{b}"
        pairs[key] = {unit: metric.paired_bootstrap(values[a], values[b], clusters_by[unit],
                                                    resamples=boot["resamples"],
                                                    seed=boot["seed"])
                      for unit in [boot["cluster_unit"], *boot["sensitivity_units"]]}
        pairs[key]["by_question_type"] = _paired_by(values[a], values[b], score_dirs[a],
                                                    population)
        family = clusters_by[boot["cluster_unit"]]
        by_template = {}
        for t in sorted(set(templates.values())):
            ids = [r for r in values[a] if templates[r] == t]
            out_t = metric.paired_bootstrap({r: values[a][r] for r in ids},
                                            {r: values[b][r] for r in ids}, family,
                                            resamples=boot["resamples"], seed=boot["seed"])
            out_t.update(a_accuracy=mean(values[a][r] for r in ids),
                         b_accuracy=mean(values[b][r] for r in ids),
                         descriptive_only=len(ids) < 100)
            by_template[t] = out_t
        pairs[key]["by_template"] = by_template
        if exclude_templates:
            ids = [r for r in values[a] if templates[r] not in exclude_templates]
            sens = metric.paired_bootstrap({r: values[a][r] for r in ids},
                                           {r: values[b][r] for r in ids}, family,
                                           resamples=boot["resamples"], seed=boot["seed"])
            sens.update(a_accuracy=mean(values[a][r] for r in ids),
                        b_accuracy=mean(values[b][r] for r in ids),
                        excluded_templates=list(exclude_templates),
                        kind="descriptive sensitivity analysis (post hoc, not preregistered)")
            pairs[key]["sensitivity_excluding_" + "_".join(exclude_templates)] = sens
    summary = {"experiment": EXPERIMENT, "budget_tokens": budget, "inputs": inputs,
               "population": population, "arms": arms, "paired": pairs,
               "bootstrap": boot, "metric": config["scoring"]["metric"],
               "exclude_templates_sensitivity": list(exclude_templates)}
    out.mkdir(parents=True, exist_ok=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    return summary


def _by(rows: Sequence[Mapping[str, Any]], label: str) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        groups[r[label]].append(r["value"])
    return {k: {"n_reads": len(v), "accuracy": mean(v)} for k, v in sorted(groups.items())}


def _paired_by(a: Mapping[str, float], b: Mapping[str, float], score_dir: Path,
               population: Mapping[str, Any]) -> dict[str, Any]:
    labels = {r["read_id"]: r["question_type"] for r in read_jsonl(Path(score_dir)
                                                                    / "scores.jsonl")}
    out = {}
    for qtype in population["include_types"]:
        ids = [r for r in a if labels[r] == qtype]
        if ids:
            out[qtype] = {"n_reads": len(ids),
                          "difference": mean(a[r] - b[r] for r in ids),
                          "descriptive_only": len(ids) < 100}
    return out


# ---------------------------------------------------------------------------------------------
# Entry point


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    system = sub.add_parser("system", help="one arm at one budget (stage system)")
    system.add_argument("--config", type=Path, required=True)
    system.add_argument("--arm", required=True, choices=[*VIEW_ARMS, "raw"])
    system.add_argument("--budget", type=int, required=True)
    system.add_argument("--base-url", default=None, help="chat endpoint; omitted: the fake "
                        "backend (dry runs only, no score from it is real)")
    system.add_argument("--history", action="append", default=None)
    score = sub.add_parser("score", help="score one system run (stage score)")
    score.add_argument("--config", type=Path, required=True)
    score.add_argument("--system", type=Path, required=True, help="system run directory")
    comp = sub.add_parser("compare", help="paired comparison over score runs (not a run)")
    comp.add_argument("--config", type=Path, required=True)
    comp.add_argument("--budget", type=int, required=True)
    comp.add_argument("--arm", action="append", required=True, help="<arm>=<score run dir>")
    comp.add_argument("--out", type=Path, required=True, help="new directory under runs_root")
    comp.add_argument("--exclude-template", action="append", default=[],
                      help="also report each pair without this view template (descriptive "
                           "sensitivity analysis)")
    args = parser.parse_args(argv)
    config = load_experiment(args.config)
    command = shlex.join([sys.executable, "-m", "grace.cli.ablation_c",
                          *(argv if argv is not None else sys.argv[1:])])
    if args.command == "system":
        if args.budget not in config["budgets"]:
            parser.error(f"budget {args.budget} is not in the config's budgets")
        served = Served(args.base_url, REPO_ROOT / config["model_config"])
        if args.arm == "raw":
            result = run_raw(config, args.budget, served, args.history, command)
        else:
            result = run_views(config, args.config, args.arm, args.budget, served, args.history,
                               command)
        print(f"{result.run_id}: {result.status} ({result.n_reads} reads) -> {result.run_dir}")
        return 0 if result.status == "completed" else 1
    if args.command == "score":
        run_dir = run_score(config, args.config, args.system, command=command)
        print(f"{run_dir.name}: score -> {run_dir}")
        return 0
    runs = shared_dir("runs_root").resolve()
    out = args.out.resolve()
    if runs not in out.parents:
        parser.error(f"--out must lie under {runs}")
    score_dirs = dict(a.split("=", 1) for a in args.arm)
    summary = compare(config, args.budget, {k: Path(v) for k, v in score_dirs.items()}, out,
                      args.exclude_template)
    print(json.dumps({k: v["family"]["difference"] for k, v in summary["paired"].items()},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
