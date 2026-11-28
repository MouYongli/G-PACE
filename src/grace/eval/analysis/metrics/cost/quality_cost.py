"""Quality against cost, cumulative cost and break-even over measured runs (E014; plan 8.2, 8.3).

Prices. A record's cost at cache ratio c under a model weighting is

    price = weight(model) * (input - (1 - c) * cached + output),

with `weight` 1 for every model (token ledger) or a compute weight per model (E007: compute per
token scales with the parameter count). c = 1 is the logical ledger, c = 0 the computed one.

Cached tokens and the accounting. A server started without `--enable-prompt-tokens-details`
reports no cached tokens, so its records carry `cached_input_tokens` 0 although the server reuses
prefixes. A run is *unreported* for a model when none of its records of that model has a cached
token. Three accountings:

- `reported`: cached tokens as recorded (no credit on unreported runs; an upper bound of their
  cost);
- `imputed`: on unreported records, cached = the block-aligned token length of the fixed prefix of
  the record's prompt (`static_prefixes`), a lower bound of what a prefix-caching server serves;
- `probe`: on unreported records, cached = the mean cached tokens per call that a probe run on a
  reporting server measured for the same call type (`probe_cached_means`), capped at the input;
  call types the probe did not see fall back to `imputed`.

Records of reporting runs are never changed. This module reads only run-directory files and the
pinned prompt files; it never imports engine code.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from grace.eval.analysis.metrics.cost.ledger import SYSTEM, RunCost
from grace.llm.records import CallRecord

ACCOUNTINGS = ("reported", "imputed", "probe")


def model_name(record: CallRecord) -> str:
    """The served model without its revision pin (`Qwen/Qwen3-8B@<sha>` -> `Qwen/Qwen3-8B`)."""
    return record.model.split("@", 1)[0]


def unreported_runs(records: Iterable[CallRecord]) -> set[tuple[str, str]]:
    """(run_id, model) pairs of chat records none of which reports a cached token."""
    seen: dict[tuple[str, str], bool] = {}
    for r in records:
        if r.category not in SYSTEM:
            continue
        key = (r.run_id, model_name(r))
        seen[key] = seen.get(key, False) or r.cached_input_tokens > 0
    return {key for key, reported in seen.items() if not reported}


def block_floor(tokens: int, block: int) -> int:
    return (tokens // block) * block if block > 0 else tokens


def probe_cached_means(records: Iterable[CallRecord]) -> dict[str, dict]:
    """Per call type of the probe's chat records: calls, mean input and mean cached tokens."""
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in records:
        if r.category not in SYSTEM or r.status == "failed":
            continue
        row = sums[r.call_type]
        row[0] += 1
        row[1] += r.input_tokens
        row[2] += r.cached_input_tokens
    return {t: {"calls": n, "mean_input": i / n, "mean_cached": c / n,
                "cached_share": c / i if i else None}
            for t, (n, i, c) in sorted(sums.items())}


@dataclass
class Pricer:
    """Prices records under one accounting and one weighting (module docstring)."""

    accounting: str = "reported"
    weights: Mapping[str, float] = field(default_factory=dict)
    unreported: set[tuple[str, str]] = field(default_factory=set)
    static_prefix: Mapping[str, int] = field(default_factory=dict)  # prompt_sha256 -> tokens
    probe_means: Mapping[str, float] = field(default_factory=dict)  # call_type -> cached tokens

    def __post_init__(self):
        if self.accounting not in ACCOUNTINGS:
            raise ValueError(f"unknown accounting {self.accounting!r}")

    def cached(self, r: CallRecord) -> int:
        if self.accounting == "reported" or (r.run_id, model_name(r)) not in self.unreported:
            return r.cached_input_tokens
        imputed = self.static_prefix.get(r.prompt_sha256 or "", 0)
        if self.accounting == "probe" and r.call_type in self.probe_means:
            imputed = int(round(self.probe_means[r.call_type]))
        return max(r.cached_input_tokens, min(imputed, r.input_tokens))

    def weight(self, r: CallRecord) -> float:
        return float(self.weights.get(model_name(r), 1.0))

    def price(self, records: Iterable[CallRecord], c: float) -> float:
        if not 0.0 <= c <= 1.0:
            raise ValueError("c must be in [0, 1]")
        return float(sum(self.weight(r) * (r.input_tokens - (1.0 - c) * self.cached(r)
                                           + r.output_tokens)
                         for r in records if r.category in SYSTEM))


# ---------------------------------------------------------------------------------------------
# Several runs as one system (e.g. one run per history)


@dataclass
class System:
    """The runs of one system at one budget; reads and records are the union of the runs."""

    label: str
    runs: list[RunCost]

    @property
    def records(self) -> list[CallRecord]:
        return [r for run in self.runs for r in run.records]

    def read_rows(self) -> list[tuple[str, str, dict[str, list[CallRecord]]]]:
        """(history_id, read_id, {"W", "U", "A"}) in run order, per the ledger allocation."""
        out = []
        for run in self.runs:
            records = run.allocation().records
            for read in run.reads:
                out.append((read.history_id, read.read_id, records[read.read_id]))
        return out

    def histories(self) -> list[str]:
        return list(dict.fromkeys(h for h, _, _ in self.read_rows()))

    def write_records(self, history_id: str) -> list[CallRecord]:
        return [r for r in self.records if r.category == "W" and r.history_id == history_id]


def per_history(system: System, pricer: Pricer, c: float) -> dict[str, dict]:
    """Per history: reads, W (every write record, ingestion and read-time view work alike) and
    the mean read cost U + A, priced at c. Write records with a read_id (lazy rebuilds at read
    time, flushes) are view maintenance and booked to W (plan 8.2)."""
    rows = system.read_rows()
    out = {}
    for h in system.histories():
        reads = [parts for hid, _, parts in rows if hid == h]
        out[h] = {"reads": len(reads), "W": pricer.price(system.write_records(h), c),
                  "read_mean": sum(pricer.price(p["U"] + p["A"], c) for p in reads) / len(reads)}
    return out


def total_cost(system: System, pricer: Pricer, c: float) -> float:
    return pricer.price(system.records, c)


def warm_read_mean(baseline: System, pricer: Pricer, c: float) -> dict[str, float]:
    """Per history, the mean cost of the baseline's reads after the first one (plan 8.2: the
    first read pays H at full price)."""
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    seen: set[str] = set()
    for h, _, parts in baseline.read_rows():
        if h not in seen:
            seen.add(h)
            continue
        sums[h][0] += pricer.price(parts["U"] + parts["A"], c)
        sums[h][1] += 1
    return {h: s / n for h, (s, n) in sums.items() if n}


def m_star(w: float, delta: float) -> int | None:
    """M* = ceil(W / Delta); None when Delta <= 0 (no payback point)."""
    if delta <= 0:
        return None
    return max(1, math.ceil(w / delta)) if w > 0 else 0


@dataclass(frozen=True)
class BreakEven:
    history_id: str
    c: float
    w: float
    system_read: float
    baseline_read: float
    delta: float
    m_star: int | None
    reads: int

    def to_row(self) -> tuple:
        return (self.history_id, self.c, round(self.w, 3), round(self.system_read, 3),
                round(self.baseline_read, 3), round(self.delta, 3), self.m_star, self.reads)


def break_even(system: System, baseline: System, sys_pricer: Pricer, base_pricer: Pricer,
               cs: Sequence[float]) -> list[BreakEven]:
    out = []
    for c in cs:
        mine = per_history(system, sys_pricer, c)
        base = warm_read_mean(baseline, base_pricer, c)
        for h, row in mine.items():
            if h not in base:
                continue
            delta = base[h] - row["read_mean"]
            out.append(BreakEven(h, c, row["W"], row["read_mean"], base[h], delta,
                                 m_star(row["W"], delta), row["reads"]))
    return out


def c_star(points: Sequence[BreakEven]) -> dict[str, float | None]:
    """Per history, the smallest c of the grid from which on M* stays within the history's own
    reads; None if there is none."""
    by_history: dict[str, list[BreakEven]] = defaultdict(list)
    for p in points:
        by_history[p.history_id].append(p)
    out = {}
    for h, items in by_history.items():
        items.sort(key=lambda p: p.c)
        ok = [p.m_star is not None and p.m_star <= p.reads for p in items]
        found = None
        for i in range(len(items)):
            if all(ok[i:]):
                found = items[i].c
                break
        out[h] = found
    return out


def cumulative(system: System, pricer: Pricer, c: float, *, upfront_writes: bool,
               order: Callable[[list], list] | None = None) -> dict[str, list[float]]:
    """Cumulative cost after each read, per history. `upfront_writes`: the whole ingestion (all W
    records of the history) is paid before the first read (end-of-history reading); otherwise each
    read carries the writes the allocation charged to it."""
    rows = system.read_rows()
    out = {}
    for h in system.histories():
        reads = [parts for hid, _, parts in rows if hid == h]
        if order is not None:
            reads = order(reads)
        total = pricer.price(system.write_records(h), c) if upfront_writes else 0.0
        points = []
        for parts in reads:
            charged = parts["U"] + parts["A"] + ([] if upfront_writes else parts["W"])
            total += pricer.price(charged, c)
            points.append(total)
        out[h] = points
    return out


def crossing(system: Sequence[float], baseline: Sequence[float]) -> int | None:
    """First read count from which the system's cumulative cost stays at or below the
    baseline's; None if it never does."""
    n = min(len(system), len(baseline))
    for m in range(1, n + 1):
        if all(system[k - 1] <= baseline[k - 1] for k in range(m, n + 1)):
            return m
    return None


# ---------------------------------------------------------------------------------------------
# Quality


def f1_summary(scores: Sequence[Mapping], threshold: float) -> dict:
    """Mean F1 over scored reads and the number of successes (F1 >= threshold)."""
    values = [float(s["f1"]) for s in scores]
    return {"n": len(values), "f1": sum(values) / len(values) if values else None,
            "n_success": sum(1 for v in values if v >= threshold),
            "n_unknown": sum(1 for s in scores if s.get("output") == "unknown"),
            "n_invalid": sum(1 for s in scores if s.get("output") == "invalid")}


def cheapest_at_quality(points: Sequence[Mapping], target: float) -> Mapping | None:
    """Among (f1, tokens) points of one system, the cheapest with f1 >= target."""
    ok = [p for p in points if p["f1"] is not None and p["f1"] >= target]
    return min(ok, key=lambda p: p["tokens"]) if ok else None
