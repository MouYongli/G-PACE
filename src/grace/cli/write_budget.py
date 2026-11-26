"""T013 write-budget estimate and break-even curves (plan 8.2 and 8.4; development data only).

    uv run python -m grace.cli.write_budget measure-c \\
        --config configs/experiments/T013-write-budget.yaml \\
        --base-url http://127.0.0.1:<port>/v1 --gpu <id> --server-pid <pid>
    uv run python -m grace.cli.write_budget estimate \\
        --config configs/experiments/T013-write-budget.yaml

- `measure-c` (stage `probe`, no benchmark data): the compute ratio c of cache-hit input on a
  local server. Answer-type calls with one output token go through `grace.llm.client` (one at a
  time, wall-clock GPU accounting) over a designed grid of new and cached prompt tokens; c is
  `b_cached / b_new` of the least-squares fit `latency = a + b_new*new + b_cached*cached` with a
  bootstrap interval over calls. Before the first and after the last call `nvidia-smi` must show no
  compute process on the GPU but the server's; otherwise the run fails ("exclusive" GPU).
  Writes `calls.jsonl`, `trials.jsonl`, `gpu-check.json`, `compute-ratio.json`.
- `estimate` (stage `probe`, CPU only, no model): LoCoMo development records through `load_split`,
  every message counted with the primary model's pinned tokenizer as the raw-text engine renders
  it; writer tokens per history at each extraction granularity and writer scenario (paper model,
  see the config); the cached full-history read cost and GRACE's read cost priced at c from
  measured E001 call records; the break-even read count M*(c) = ceil(W(c) / Delta(c)) of plan 8.2
  over c in [0, 1], the smallest c at which payback falls within the history's own reads, and the
  values at the measured cache ratios of the config. Writes `write-budget.json`, `curves.csv`,
  `units.csv` and `break-even.png`. Run files it reads are listed with the checksum of their
  run.json in `write-budget.json` (`inputs`); they are inputs of a paper calculation, not upstream
  runs of a stage.

Pricing follows T030 (`grace.eval.analysis.metrics.cost.amortisation.price`): a record costs
`input - (1 - c) * cached + output`, so c = 1 is the logical ledger and c = 0 the computed one.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shlex
import subprocess
import sys
import traceback
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.context import api
from grace.eval.analysis.metrics.cost.amortisation import payback_read_count, price
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.engines.baselines.base import render_message
from grace.eval.runner.harness import rundir
from grace.llm.client import ChatClient, Endpoint
from grace.llm.prompts import PROMPTS_DIR, load_pinned
from grace.llm.records import CallContext, CallLedger, CallRecord, read_calls
from grace.llm.tokens import HFTokenCounter, TokenCounter, TokenizerPin

PROMPT_REGISTRY = REPO_ROOT / "configs" / "common" / "prompts.yaml"
SCENARIOS = ("low", "central", "high")


def load_experiment(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for key in ("experiment", "model_config", "benchmark", "split", "granularities", "writer",
                "read", "cache_ratios", "compute_ratio"):
        if key not in config:
            raise ValueError(f"{path}: missing {key!r}")
    return config


def runs_path(relative: str) -> Path:
    path = shared_dir("runs_root") / relative
    if not (path / "run.json").is_file():
        raise FileNotFoundError(f"{path}: no run.json")
    return path


def run_input(path: Path) -> dict[str, Any]:
    """A run read by the estimate, with its status and the checksum of its run.json."""
    run = json.loads((path / "run.json").read_text(encoding="utf-8"))
    if run["status"] != "completed":
        raise ValueError(f"{run['run_id']}: status {run['status']}, not completed")
    return {"run_id": run["run_id"], "stage": run["stage"], "path": path.resolve().as_posix(),
            "run_json_sha256": rundir.file_sha256(path / "run.json")}


# ---------------------------------------------------------------------------------------------
# Units and writer cost


def units_of(messages: Sequence[api.Message], granularity: Mapping[str, Any]) -> list[list[int]]:
    """Indices (into `messages`, in version order) of each writer call's messages."""
    unit = granularity["unit"]
    if unit == "message":
        return [[i] for i in range(len(messages))]
    sessions: list[list[int]] = []
    for i, message in enumerate(messages):
        if not sessions or messages[sessions[-1][-1]].segment_id != message.segment_id:
            sessions.append([])
        sessions[-1].append(i)
    if unit == "session":
        return sessions
    if unit == "segment":
        size = int(granularity["size"])
        if size < 1:
            raise ValueError("segment size must be >= 1")
        return [s[k:k + size] for s in sessions for k in range(0, len(s), size)]
    raise ValueError(f"unknown unit {unit!r}")


@dataclass(frozen=True)
class WriterParams:
    prefix_tokens: int
    candidate_base_tokens: int
    candidate_tokens_per_message: int
    context_messages: int
    output_tokens_per_message: int
    output_tokens_per_call: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> WriterParams:
        return cls(**{k: int(d[k]) for k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class WriteCost:
    """Writer tokens of one history: `prefix` per call (cacheable), the rest at full price."""

    calls: int
    prefix: int  # prefix tokens of one call
    varying: int  # every non-prefix input token of all calls
    output: int

    def price(self, c: float) -> float:
        """The first call pays its prefix in full, every later call at c."""
        if not 0.0 <= c <= 1.0:
            raise ValueError("c must be in [0, 1]")
        if self.calls == 0:
            return 0.0
        return self.prefix * (1 + c * (self.calls - 1)) + self.varying + self.output

    @property
    def logical(self) -> int:
        return int(self.price(1.0))

    @property
    def computed(self) -> int:
        return int(self.price(0.0))


def writer_cost(tokens: Sequence[int], units: Sequence[Sequence[int]],
                params: WriterParams) -> WriteCost:
    """Writer tokens of one history: `tokens[i]` is message i rendered, `units` its calls."""
    varying = output = 0
    for unit in units:
        n = len(unit)
        start = unit[0]
        context = sum(tokens[max(0, start - params.context_messages):start])
        varying += (params.candidate_base_tokens + params.candidate_tokens_per_message * n
                    + context + sum(tokens[i] for i in unit))
        output += params.output_tokens_per_call + params.output_tokens_per_message * n
    return WriteCost(len(units), params.prefix_tokens, varying, output)


# ---------------------------------------------------------------------------------------------
# Read side from measured records


def answer_records_by_read(records: Sequence[CallRecord]
                           ) -> dict[str, list[tuple[str, list[CallRecord]]]]:
    """history -> [(read_id, its A records)] in the order the run first called each read."""
    out: dict[str, dict[str, list[CallRecord]]] = defaultdict(dict)
    for r in records:
        if r.category == "A" and r.read_id is not None:
            out[r.history_id].setdefault(r.read_id, []).append(r)
    return {h: list(reads.items()) for h, reads in out.items()}


@dataclass(frozen=True)
class ReadSide:
    """Per history: the cached full-history baseline and GRACE's answer calls, as records."""

    full_first: list[CallRecord]  # A records of the first read of the history
    full_warm: list[list[CallRecord]]  # A records of each later read
    answers: list[list[CallRecord]]  # A records of each read of the answer proxy

    @property
    def reads(self) -> int:
        return 1 + len(self.full_warm)

    def full_per_read(self, c: float) -> float:
        """f(c): mean cost of a warm read of the cached full history (plan 8.2)."""
        return sum(price(rs, c) for rs in self.full_warm) / len(self.full_warm)

    def full_total(self, c: float) -> float:
        return price(self.full_first, c) + sum(price(rs, c) for rs in self.full_warm)

    def answer_per_read(self, c: float) -> float:
        return sum(price(rs, c) for rs in self.answers) / len(self.answers)


def read_sides(full: Sequence[CallRecord], answers: Sequence[CallRecord]) -> dict[str, ReadSide]:
    f, a = answer_records_by_read(full), answer_records_by_read(answers)
    out = {}
    for history, reads in f.items():
        if len(reads) < 2:
            raise ValueError(f"{history}: the full-history run needs at least two reads")
        if history not in a:
            raise ValueError(f"{history}: no answer calls in the answer run")
        out[history] = ReadSide(reads[0][1], [rs for _, rs in reads[1:]],
                                [rs for _, rs in a[history]])
    return out


@dataclass(frozen=True)
class PlannerParams:
    calls_per_read: int
    vocabulary_tokens: int
    request_tokens: int
    output_tokens: int

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PlannerParams:
        return cls(**{k: int(d[k]) for k in cls.__dataclass_fields__})

    def per_read(self, c: float, prompt_tokens: int) -> float:
        """U_i: stable prompt and vocabulary at c, request and output in full."""
        return self.calls_per_read * (c * (prompt_tokens + self.vocabulary_tokens)
                                      + self.request_tokens + self.output_tokens)


# ---------------------------------------------------------------------------------------------
# Break-even


def c_grid(steps: int) -> list[float]:
    return [round(i / steps, 6) for i in range(steps + 1)]


@dataclass(frozen=True)
class Point:
    c: float
    w: float
    full_per_read: float
    system_per_read: float
    delta: float
    m_star: int | None

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def point(c: float, write: Callable[[float], float], side: ReadSide,
          planner: Callable[[float], float]) -> Point:
    w = write(c)
    f = side.full_per_read(c)
    a = side.answer_per_read(c) + planner(c)
    delta = f - a
    return Point(c, w, f, a, delta, payback_read_count(w, delta))


def smallest_c(fn: Callable[[float], Point], reads: int, steps: int) -> float | None:
    """The smallest c on the grid at which M*(c) exists and is at most `reads`; None if none.
    The whole grid is scanned (no monotonicity is assumed)."""
    for c in c_grid(steps):
        p = fn(c)
        if p.m_star is not None and p.m_star <= reads:
            return c
    return None


# ---------------------------------------------------------------------------------------------
# estimate


def message_tokens(messages: Sequence[api.Message], history: api.HistoryInfo,
                   counter: TokenCounter) -> list[int]:
    """Tokens of each message as the raw-text engine renders it (a line separator merges into
    the next token with this tokenizer, so the sum matches the joined history within a token)."""
    return [counter.count_text(render_message(m, history)) for m in messages]


def cache_ratio_marks(config: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    marks = []
    for entry in config:
        if "value" in entry:
            marks.append({"label": entry["label"], "c": float(entry["value"]), "run": None})
        else:
            path = runs_path(entry["run"])
            result = json.loads((path / "compute-ratio.json").read_text(encoding="utf-8"))
            marks.append({"label": entry["label"], "c": float(result["c"]),
                          "ci95": result.get("c_ci95"), "run": run_input(path)})
    for mark in marks:
        if not 0.0 <= mark["c"] <= 1.0:
            raise ValueError(f"cache ratio {mark['label']}: {mark['c']} outside [0, 1]")
    return marks


def estimate(exp: Mapping[str, Any], records, counter: TokenCounter, *,
             full: Sequence[CallRecord], answers: Sequence[CallRecord],
             references: Mapping[str, Sequence[CallRecord]], planner_prompt_tokens: int,
             marks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The whole calculation from loaded inputs (pure apart from token counting)."""
    steps = int(exp.get("c_grid_steps", 100))
    by_history: dict[str, list[api.Message]] = defaultdict(list)
    for m in records.messages:
        by_history[m.history_id].append(m)
    infos = {h.history_id: h for h in records.histories}
    sides = read_sides(full, answers)
    scenarios = {s: WriterParams.from_dict(exp["writer"]["scenarios"][s]) for s in SCENARIOS}
    planners = {s: PlannerParams.from_dict(exp["read"]["planner"][s]) for s in SCENARIOS}
    histories, units_rows, results = [], [], []
    for history_id in sorted(by_history):
        messages = sorted(by_history[history_id], key=lambda m: m.version)
        tokens = message_tokens(messages, infos[history_id], counter)
        side = sides[history_id]
        sessions = units_of(messages, {"unit": "session"})
        histories.append({
            "history_id": history_id, "messages": len(messages), "sessions": len(sessions),
            "history_tokens": sum(tokens), "mean_message_tokens": sum(tokens) / len(tokens),
            "reads": side.reads,
            "full_history_cached": {"logical": side.full_total(1.0),
                                    "computed": side.full_total(0.0)},
            "full_per_read": {"c=0": side.full_per_read(0.0), "c=1": side.full_per_read(1.0)},
            "answer_per_read": {"c=0": side.answer_per_read(0.0),
                                "c=1": side.answer_per_read(1.0)}})
        for granularity in exp["granularities"]:
            units = units_of(messages, granularity)
            sizes = [len(u) for u in units]
            units_rows.append({"history_id": history_id, "granularity": granularity["name"],
                               "calls": len(units), "mean_messages": sum(sizes) / len(sizes),
                               "max_messages": max(sizes),
                               "max_unit_tokens": max(sum(tokens[i] for i in u) for u in units)})
            for scenario in SCENARIOS:
                cost = writer_cost(tokens, units, scenarios[scenario])
                planner = planners[scenario]

                def fn(c, cost=cost, planner=planner, side=side):
                    return point(c, cost.price, side,
                                 lambda c: planner.per_read(c, planner_prompt_tokens))
                results.append(_result(history_id, granularity["name"], scenario, cost.calls,
                                       fn, side.reads, steps, marks,
                                       {"logical": cost.logical, "computed": cost.computed}))
        for name, refs in references.items():
            mine = [r for r in refs if r.history_id == history_id and r.category == "W"]
            if not mine:
                continue
            planner = planners["central"]

            def fn(c, mine=mine, planner=planner, side=side):
                return point(c, lambda c: price(mine, c), side,
                             lambda c: planner.per_read(c, planner_prompt_tokens))
            results.append(_result(history_id, f"measured:{name}", "measured",
                                   len(mine), fn, side.reads, steps, marks,
                                   {"logical": price(mine, 1.0), "computed": price(mine, 0.0),
                                    "cached_input": sum(r.cached_input_tokens for r in mine),
                                    "failed_attempts": sum(r.status != "ok" for r in mine)}))
    return {"histories": histories, "units": units_rows, "results": results,
            "planner_prompt_tokens": planner_prompt_tokens, "marks": list(marks),
            "c_grid_steps": steps}


def _result(history_id, granularity, scenario, calls, fn, reads, steps, marks, w):
    curve = [fn(c).to_dict() for c in c_grid(steps)]
    return {"history_id": history_id, "granularity": granularity, "scenario": scenario,
            "calls": calls, "W": w, "reads": reads,
            "c_star": smallest_c(fn, reads, steps * 10),
            "at_marks": [{"label": m["label"], **fn(m["c"]).to_dict(),
                          "payback_within_reads": (fn(m["c"]).m_star is not None
                                                   and fn(m["c"]).m_star <= reads)}
                         for m in marks],
            "curve": curve}


def write_outputs(run_dir: Path, result: Mapping[str, Any]) -> None:
    (run_dir / "write-budget.json").write_text(json.dumps(result, indent=2) + "\n",
                                               encoding="utf-8")
    with (run_dir / "units.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result["units"][0]))
        writer.writeheader()
        writer.writerows(result["units"])
    fields = ["history_id", "granularity", "scenario", "c", "w", "full_per_read",
              "system_per_read", "delta", "m_star", "reads"]
    with (run_dir / "curves.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in result["results"]:
            for p in row["curve"]:
                writer.writerow({"history_id": row["history_id"],
                                 "granularity": row["granularity"],
                                 "scenario": row["scenario"], "reads": row["reads"], **p})


def plot(run_dir: Path, result: Mapping[str, Any]) -> Path:
    """M*(c) of the central scenario per granularity, one panel per history, reads marked."""
    from grace.eval.analysis.metrics.cost.plots import INK, MUTED, SERIES, _pyplot

    plt = _pyplot()
    histories = [h["history_id"] for h in result["histories"]]
    fig, axes = plt.subplots(1, len(histories), figsize=(5.2 * len(histories), 3.8),
                             sharey=True, squeeze=False)
    rows = [r for r in result["results"] if r["scenario"] == "central"]
    names = list(dict.fromkeys(r["granularity"] for r in rows))
    for ax, history_id in zip(axes[0], histories, strict=True):
        reads = next(h["reads"] for h in result["histories"] if h["history_id"] == history_id)
        for name, color in zip(names, SERIES, strict=False):
            row = next(r for r in rows if r["granularity"] == name
                       and r["history_id"] == history_id)
            xs = [p["c"] for p in row["curve"] if p["m_star"] is not None]
            ys = [p["m_star"] for p in row["curve"] if p["m_star"] is not None]
            ax.plot(xs, ys, color=color, linewidth=1.6, label=name)
        ax.axhline(reads, color=INK, linewidth=1, linestyle="--")
        ax.text(1.0, reads, f" {reads} reads", color=INK, va="bottom", ha="right")
        for mark in result["marks"]:
            ax.axvline(mark["c"], color=MUTED, linewidth=0.8, linestyle=":")
            ax.text(mark["c"], 1.02, f"c={mark['c']:.3g}", color=MUTED, rotation=90,
                    transform=ax.get_xaxis_transform(), ha="right", va="bottom", fontsize=7)
        ax.set_yscale("log")
        ax.set_xlim(0, 1)
        ax.set_xlabel("cache ratio c")
        ax.set_title(f"LoCoMo {history_id}: break-even reads M*(c), central writer",
                     color=INK, fontsize=9)
    axes[0][0].set_ylabel("M* (reads)")
    axes[0][0].legend(loc="upper right", fontsize=7)
    fig.tight_layout()
    path = run_dir / "break-even.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def data_entry(slug: str, split: str) -> list[dict[str, Any]]:
    config = load_config(slug)
    return [{"benchmark": slug, "version": version, "manifest_sha256": sha, "split": split,
             "path": config.source_dir(project_root(), version).resolve().as_posix()}
            for version, sha in config.manifests().items()]


def planner_prompt_tokens(name: str, counter: TokenCounter) -> int:
    """Tokens of the pinned planner prompt's system text (variables unfilled)."""
    load_pinned(name, PROMPT_REGISTRY)  # checks the pin
    return counter.count_text((PROMPTS_DIR / name / "system.txt").read_text(encoding="utf-8"))


def new_run(exp: Mapping[str, Any], config_path: Path, run_root: Path, resolved: dict,
            data: list, device: str, code: rundir.CodeState | None,
            command: str | None) -> tuple[Path, rundir.RunJson]:
    code = code or rundir.code_state()
    run_dir = rundir.create(run_root, exp["experiment"])
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True), encoding="utf-8")
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": exp["experiment"], "stage": "probe",
        "upstream": [], "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": _repo_relative(config_path),
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": data,
        "project_root": project_root().as_posix(), "seed": int(exp.get("seed", 0)),
        "command": command or " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment(device)})
    return run_dir, run


def _repo_relative(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def run_estimate(config_path: Path, run_root: Path, *, counter: TokenCounter | None = None,
                 loader=None, code: rundir.CodeState | None = None,
                 command: str | None = None, draw: bool = True) -> tuple[Path, str]:
    exp = load_experiment(config_path)
    read = exp["read"]
    paths = {"full_history_run": runs_path(read["full_history_run"]),
             "answer_run": runs_path(read["answer_run"])}
    refs = {name: [runs_path(p) for p in items]
            for name, items in exp.get("reference_writers", {}).items()}
    inputs = {k: run_input(p) for k, p in paths.items()}
    inputs["reference_writers"] = {n: [run_input(p) for p in ps] for n, ps in refs.items()}
    marks = cache_ratio_marks(exp["cache_ratios"])
    resolved = {"stage": "probe", "task": exp["experiment"], **{k: v for k, v in exp.items()
                                                                if k != "compute_ratio"}}
    data = [] if loader is not None else data_entry(exp["benchmark"], exp["split"])
    run_dir, run = new_run(exp, config_path, run_root, resolved, data, "cpu", code, command)
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    try:
        counter = counter or HFTokenCounter.from_model_config(REPO_ROOT / exp["model_config"])
        if loader is None:
            if load_config(exp["benchmark"]).splits[exp["split"]].kind != "development":
                raise ValueError("T013 reads development splits only")
            records = load_split(exp["benchmark"], exp["split"])
        else:
            records = loader(exp["benchmark"], exp["split"])
        log.write(f"{exp['benchmark']}/{exp['split']}: {records.counts()}\n")
        result = estimate(
            exp, records, counter,
            full=read_calls(paths["full_history_run"] / "calls.jsonl"),
            answers=read_calls(paths["answer_run"] / "calls.jsonl"),
            references={n: [r for p in ps for r in read_calls(p / "calls.jsonl")]
                        for n, ps in refs.items()},
            planner_prompt_tokens=planner_prompt_tokens(read["planner_prompt"], counter),
            marks=marks)
        result = {"run_id": run_dir.name, "tokenizer": counter.name, "inputs": inputs, **result}
        write_outputs(run_dir, result)
        if draw:
            plot(run_dir, result)
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        log.write(traceback.format_exc())
        log.close()
        run.finish(0, f"{type(exc).__name__}: {exc}")
        raise
    n = len(result["histories"])
    log.write(f"done: {n} histories, {len(result['results'])} result rows\n")
    log.close()
    run.finish(n)
    return run_dir, run.data["status"]


# ---------------------------------------------------------------------------------------------
# measure-c


WORDS = ("river stone garden window market letter summer winter yellow purple engine silver "
         "island forest coffee planet bridge candle mirror rocket ladder pencil museum violin "
         "harbor saddle meadow tunnel blanket crystal lantern compass orchard falcon granite "
         "velvet thunder walnut glacier pepper ribbon canyon parrot marble cactus dolphin").split()


def filler(rng: random.Random, target: int, counter: TokenCounter) -> str:
    """Seeded random words of about `target` tokens (within one word)."""
    if target <= 0:
        return ""
    words = [rng.choice(WORDS) for _ in range(max(1, int(target / 1.3)))]
    n = counter.count_text(" ".join(words))
    while n < target:
        words.extend(rng.choice(WORDS) for _ in range(max(1, int((target - n) / 1.3))))
        n = counter.count_text(" ".join(words))
    while n > target and len(words) > 1:
        del words[-max(1, min(len(words) - 1, (n - target) // 2)):]
        n = counter.count_text(" ".join(words))
    return " ".join(words)


@dataclass(frozen=True)
class Trial:
    trial_id: str
    cached: int
    new: int
    repeat: int


def trials(spec: Mapping[str, Any], seed: int) -> list[Trial]:
    out = [Trial(f"t{len_c}-{len_n}-{r}", len_c, len_n, r)
           for len_c in spec["cached_tokens"] for len_n in spec["new_tokens"]
           for r in range(int(spec["repeats"]))]
    random.Random(seed).shuffle(out)
    return out


def fit(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """Least squares latency_s = a + b_new*new + b_cached*cached; c = b_cached / b_new."""
    import numpy as np

    x = np.array([[1.0, r["new"], r["cached"]] for r in rows])
    y = np.array([r["latency_s"] for r in rows])
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    pred = x @ coef
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    a, b_new, b_cached = (float(v) for v in coef)
    return {"a": a, "b_new": b_new, "b_cached": b_cached,
            "c": b_cached / b_new if b_new > 0 else math.nan,
            "r2": 1 - ss_res / ss_tot if ss_tot > 0 else math.nan, "n": len(rows)}


def bootstrap_c(rows: Sequence[Mapping[str, float]], n: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    values = []
    for _ in range(n):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        values.append(fit(sample)["c"])
    values = sorted(v for v in values if not math.isnan(v))
    if not values:
        return [math.nan, math.nan]
    return [values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]]


def gpu_processes(gpu: int) -> list[dict[str, Any]]:
    """Compute processes on one GPU, from nvidia-smi."""
    uuid = subprocess.run(["nvidia-smi", "-i", str(gpu), "--query-gpu=uuid",
                           "--format=csv,noheader"], check=True, capture_output=True,
                          text=True).stdout.strip()
    out = subprocess.run(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_memory",
                          "--format=csv,noheader,nounits"], check=True, capture_output=True,
                         text=True).stdout
    procs = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[0] == uuid:
            procs.append({"pid": int(parts[1]), "used_memory_mib": int(parts[2])})
    return procs


def gpu_state(gpu: int) -> dict[str, Any]:
    out = subprocess.run(["nvidia-smi", "-i", str(gpu), "--query-gpu=name,utilization.gpu,"
                          "memory.used", "--format=csv,noheader,nounits"], check=True,
                         capture_output=True, text=True).stdout.strip()
    name, util, mem = (p.strip() for p in out.split(","))
    return {"name": name, "utilization_pct": int(util), "memory_used_mib": int(mem)}


def descendants(pid: int) -> set[int]:
    """The process and all its descendants (vLLM runs its engine in a child process)."""
    out = subprocess.run(["ps", "-e", "-o", "pid=,ppid="], check=True, capture_output=True,
                         text=True).stdout
    children: dict[int, list[int]] = defaultdict(list)
    for line in out.splitlines():
        p, pp = (int(v) for v in line.split())
        children[pp].append(p)
    seen, stack = set(), [pid]
    while stack:
        p = stack.pop()
        if p not in seen:
            seen.add(p)
            stack.extend(children[p])
    return seen


def check_exclusive(gpu: int, server_pid: int, when: str) -> dict[str, Any]:
    procs = gpu_processes(gpu)
    ours = descendants(server_pid)
    foreign = [p for p in procs if p["pid"] not in ours]
    return {"when": when, "processes": procs, "server_pids": sorted(ours),
            "foreign": foreign, "exclusive": not foreign and bool(procs), **gpu_state(gpu)}


def run_measure_c(config_path: Path, run_root: Path, *, base_url: str, gpu: int,
                  server_pid: int, counter: TokenCounter | None = None,
                  client_options: Mapping[str, Any] | None = None, checker=None, code: rundir.CodeState | None = None,
                  command: str | None = None) -> tuple[Path, str]:
    exp = load_experiment(config_path)
    spec = exp["compute_ratio"]
    seed = int(exp.get("seed", 0))
    resolved = {"stage": "probe", "task": exp["experiment"], "model_config": exp["model_config"],
                "compute_ratio": spec, "base_url": base_url, "gpu": gpu,
                "server_pid": server_pid, "seed": seed}
    run_dir, run = new_run(exp, config_path, run_root, resolved, [], f"cuda:{gpu}", code,
                           command)
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    checker = checker or (lambda when: check_exclusive(gpu, server_pid, when))
    checks: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    try:
        pin = TokenizerPin.from_file(REPO_ROOT / exp["model_config"])
        counter = counter or HFTokenCounter.from_model_config(REPO_ROOT / exp["model_config"])
        ledger = CallLedger(run_dir / "calls.jsonl", run_dir.name)
        endpoint = Endpoint.for_model(pin, base_url, spec["served_model"],
                                      gpu_accounting="wall_clock", gpus=1)
        client = ChatClient(endpoint, ledger, counter, max_attempts=1,
                            **dict(client_options or {}))
        decoding = {"temperature": 0.0, "max_tokens": int(spec["max_tokens"]), "seed": seed}
        rng = random.Random(seed)
        checks.append(checker("before"))
        if not checks[-1]["exclusive"]:
            raise RuntimeError(f"GPU {gpu} is not exclusive: {checks[-1]}")

        def call(trial_id, kind, system, user, target_cached, target_new):
            context = CallContext("answer", "read", history_id="probe", read_id=trial_id)
            prompt = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            result = client.chat(prompt, context, prompt_sha256=None, decoding=decoding)
            if not result.cache_reported:
                raise RuntimeError("the server does not report cached tokens; start it with "
                                   "--enable-prompt-tokens-details")
            record = result.records[-1]
            row = {"trial_id": trial_id, "kind": kind, "call_id": record.call_id,
                   "target_cached": target_cached, "target_new": target_new,
                   "input_tokens": record.input_tokens,
                   "cached": record.cached_input_tokens,
                   "new": record.input_tokens - record.cached_input_tokens,
                   "output_tokens": record.output_tokens,
                   "latency_s": record.latency_ms / 1000.0}
            rows.append(row)
            return row

        for i in range(int(spec["warmup_calls"])):
            nonce = f"warmup {i} {rng.getrandbits(64):016x}"
            call(f"warmup-{i}", "warmup", nonce, filler(rng, 512, counter), 0, 512)
        for k, trial in enumerate(trials(spec, seed), start=1):
            nonce = f"Session {trial.trial_id} {rng.getrandbits(64):016x}. "
            system = nonce + filler(rng, trial.cached, counter)
            user = filler(rng, trial.new, counter)
            if trial.cached > 0:
                call(trial.trial_id, "prime", system, "Reply with one word.", 0, trial.cached)
            call(trial.trial_id, "measure", system, user, trial.cached, trial.new)
            if k % 20 == 0:
                checks.append(checker(f"after trial {k}"))
        checks.append(checker("after"))
        (run_dir / "gpu-check.json").write_text(json.dumps(checks, indent=2) + "\n",
                                                encoding="utf-8")
        with (run_dir / "trials.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        if not all(c["exclusive"] for c in checks):
            raise RuntimeError(f"GPU {gpu} was not exclusive during the probe; see gpu-check.json")
        data = [r for r in rows if r["kind"] != "warmup"]
        pooled = fit(data)
        by_new = {}
        for n in spec["new_tokens"]:
            subset = [r for r in data if r["kind"] == "prime" or r["target_cached"] == 0
                      or r["target_new"] == n]
            by_new[str(n)] = fit(subset)
        warm_hits = [r for r in data if r["kind"] == "measure" and r["target_cached"] > 0]
        hit_share = (sum(r["cached"] for r in warm_hits)
                     / max(1, sum(r["target_cached"] for r in warm_hits)))
        result = {"run_id": run_dir.name, "c": pooled["c"],
                  "c_ci95": bootstrap_c(data, int(spec["bootstrap"]), seed), "fit": pooled,
                  "fit_by_new_tokens": by_new, "calls": len(rows), "fit_calls": len(data),
                  "warm_cached_over_target": hit_share,
                  "gpu_exclusive": all(c["exclusive"] for c in checks),
                  "max_utilisation_pct_before": checks[0]["utilization_pct"]}
        (run_dir / "compute-ratio.json").write_text(json.dumps(result, indent=2) + "\n",
                                                    encoding="utf-8")
        log.write(json.dumps(result) + "\n")
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        if checks:
            (run_dir / "gpu-check.json").write_text(json.dumps(checks, indent=2) + "\n",
                                                    encoding="utf-8")
        log.write(traceback.format_exc())
        log.close()
        run.finish(len(rows), f"{type(exc).__name__}: {exc}")
        raise
    log.close()
    run.finish(len(rows))
    return run_dir, run.data["status"]


# ---------------------------------------------------------------------------------------------


def default_run_root() -> Path:
    return shared_dir("runs_root") / "T013" / "artifacts" / "manager"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    est = sub.add_parser("estimate", help="writer tokens and break-even curves (CPU)")
    est.add_argument("--config", type=Path, required=True)
    est.add_argument("--run-root", type=Path, default=None)
    mc = sub.add_parser("measure-c", help="compute ratio c on an exclusive GPU")
    mc.add_argument("--config", type=Path, required=True)
    mc.add_argument("--base-url", required=True)
    mc.add_argument("--gpu", type=int, required=True)
    mc.add_argument("--server-pid", type=int, required=True)
    mc.add_argument("--run-root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.run_root or default_run_root()
    if args.command == "estimate":
        run_dir, status = run_estimate(args.config, root)
    else:
        run_dir, status = run_measure_c(args.config, root, base_url=args.base_url, gpu=args.gpu,
                                        server_pid=args.server_pid)
    print(f"{run_dir} {status}")
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["WriteCost", "WriterParams", "estimate", "fit", "units_of", "writer_cost"]
