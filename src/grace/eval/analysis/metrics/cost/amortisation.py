"""Amortisation, payback and cost per success over measured call records (plan 8.2, 8.3).

Prices. A record's cost at cache ratio c (the price of a cache-hit input token relative to a
full-price one) is

    price_c = input - (1 - c) * cached + output,

so c = 1 gives the logical ledger and c = 0 the computed ledger. Because every record carries the
cached tokens the server actually reported, pricing the records of a full-history run that ran
with prefix caching gives the cached full-history row *measured* at every c, not estimated from the
uncached one (plan 8.2, last sentence). The formula rows of plan 8.2 (`formula_full_history`) are
reported beside it for comparison.

Payback. With W the write cost of one history, a-bar the mean cost of a read of the system
(U_i + A_i) and f-bar the mean cost of a read of the cached full-history baseline after its first
read, Delta(c) = f-bar(c) - a-bar(c) and M*(c) = ceil(W(c) / Delta(c)); no payback point when
Delta(c) <= 0 (plan 8.2).

The measured cache ratio. For local inference c is a compute ratio (plan 8.2). Two measured values
are reported:

- `token_cache_ratio`: the share of the reusable prefix (the history already sent in the previous
  call of the same history) that the server did *not* serve from its cache;
- `gpu_cache_ratio`: GPU seconds of a warm full-history read over those of the same read on a
  server without prefix caching. It includes the question and decoding time in both runs, so it is
  an upper bound of the prefill compute ratio.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from grace.eval.analysis.metrics.cost.ledger import SYSTEM, LedgerError, RunCost
from grace.llm.records import CallRecord

LEDGERS = ("logical", "computed", "gpu_seconds")


def price(records: Iterable[CallRecord], c: float) -> float:
    """Token cost of records when a cache-hit input token costs c of a full-price one."""
    if not 0.0 <= c <= 1.0:
        raise ValueError("c must be in [0, 1]")
    return float(sum(r.input_tokens - (1.0 - c) * r.cached_input_tokens + r.output_tokens
                     for r in records))


def cost(records: Iterable[CallRecord], ledger: str) -> float | None:
    """One of the three ledgers of plan 8.1 over records. GPU seconds are None when any record
    has no GPU time: a partial sum would read as a measured total."""
    records = list(records)
    if ledger == "logical":
        return price(records, 1.0)
    if ledger == "computed":
        return price(records, 0.0)
    if ledger == "gpu_seconds":
        if any(r.gpu_seconds is None for r in records):
            return None
        return float(sum(r.gpu_seconds for r in records))
    raise ValueError(f"unknown ledger {ledger!r}; one of {LEDGERS}")


# ---------------------------------------------------------------------------------------------
# Records per read


def records_by_read(run: RunCost) -> dict[str, dict[str, list[CallRecord]]]:
    """read_id -> {"W": writes charged before it, "U": ..., "A": ...}, by the allocation rule of
    `ledger.allocate`, records in call order."""
    return run.allocation().records


def histories(run: RunCost) -> list[str]:
    seen: dict[str, None] = {}
    for read in run.reads:
        seen.setdefault(read.history_id)
    return list(seen)


def write_records(run: RunCost, history_id: str) -> list[CallRecord]:
    """Every W record of a history, including writes after its last read."""
    return [r for r in run.records if r.category == "W" and r.history_id == history_id]


# ---------------------------------------------------------------------------------------------
# Cumulative cost over reads (amortisation curves, plan 8.3)


@dataclass(frozen=True)
class Curve:
    label: str
    history_id: str
    ledger: str
    order: str  # "run" (the order the run answered) or "seed=<n>"
    points: list[float]  # cumulative cost after 1, 2, ... reads

    def at(self, m: int) -> float:
        return self.points[m - 1]


def cumulative(run: RunCost, label: str, *, ledger: str = "computed", c: float | None = None,
               seed: int | None = None) -> list[Curve]:
    """Cumulative system cost after each read, one curve per history.

    Read m adds the writes charged before it and its U and A records, so under end-of-history
    reading the whole ingestion is paid before the first read. `c` prices tokens at cache ratio c
    instead of using `ledger`. `seed` draws the read order with a fixed seed (plan 8.3: different
    numbers of independent questions on one snapshot); the default keeps the measured run order,
    which is the only order in which cache-dependent costs were actually measured."""
    if c is None and cost(run.records, ledger) is None:
        raise LedgerError(f"{run.run_id}: calls without GPU time; no {ledger} curve")
    per_read = records_by_read(run)
    curves = []
    for history_id in histories(run):
        reads = [r for r in run.reads if r.history_id == history_id]
        writes = write_records(run, history_id)
        if seed is not None:
            reads = list(reads)
            random.Random(seed).shuffle(reads)
        upfront = 0.0
        if seed is not None:  # one snapshot: the whole ingestion is paid before any read
            upfront = price(writes, c) if c is not None else cost(writes, ledger)
        total, points = upfront, []
        for read in reads:
            rows = per_read[read.read_id]
            charged = rows["U"] + rows["A"] + ([] if seed is not None else rows["W"])
            total += price(charged, c) if c is not None else cost(charged, ledger)
            points.append(total)
        curves.append(Curve(label, history_id, f"price@c={c}" if c is not None else ledger,
                            "run" if seed is None else f"seed={seed}", points))
    return curves


def crossing(system: Curve, baseline: Curve) -> int | None:
    """First read count m at which the system's cumulative cost is at most the baseline's and
    stays so for every later m both curves cover; None if it never does."""
    n = min(len(system.points), len(baseline.points))
    for m in range(1, n + 1):
        if all(system.at(k) <= baseline.at(k) for k in range(m, n + 1)):
            return m
    return None


# ---------------------------------------------------------------------------------------------
# The full-history row


def _history_tokens(run: RunCost, read_id: str) -> int:
    if read_id not in run.context_tokens:
        raise LedgerError(f"{run.run_id}: no contexts.jsonl record for read {read_id}")
    return run.context_tokens[read_id]


def reusable_prefix(run: RunCost) -> list[tuple[CallRecord, int, int]]:
    """(answer call, history tokens H of its read, reusable prefix) in call order: the reusable
    prefix of a call is the history of the previous call of the same history (0 for the first);
    under end-of-history reading that is H for every call after the first."""
    per_read = records_by_read(run)
    previous: dict[str, int] = {}
    out = []
    for read in run.reads:
        h = _history_tokens(run, read.read_id)
        for record in per_read[read.read_id]["A"]:
            reusable = min(previous.get(read.history_id, 0), h)
            out.append((record, h, reusable))
            previous[read.history_id] = h
    return out


def token_cache_ratio(run: RunCost) -> dict:
    """Share of the reusable prefix not served from the cache (module docstring).

    Attempts that failed without a server response report no cache and are left out of this
    ratio (they stay in every ledger)."""
    reusable_total = served = 0
    n = 0
    for record, _, reusable in reusable_prefix(run):
        if reusable == 0 or record.status == "failed":
            continue
        n += 1
        reusable_total += reusable
        served += min(record.cached_input_tokens, reusable)
    value = None if reusable_total == 0 else 1.0 - served / reusable_total
    return {"value": value, "calls": n, "reusable_tokens": reusable_total,
            "served_from_cache": served}


def _single_ok_answer(run: RunCost) -> dict[str, CallRecord]:
    per_read = records_by_read(run)
    out = {}
    for read_id, rows in per_read.items():
        answers = rows["A"]
        if len(answers) == 1 and answers[0].status == "ok" and answers[0].gpu_seconds is not None:
            out[read_id] = answers[0]
    return out


def gpu_cache_ratio(cached: RunCost, uncached: RunCost) -> dict:
    """GPU seconds of warm reads with caching over the same reads without (module docstring).

    Paired by read ID over reads that are not the first of their history in the cached run and
    have exactly one successful answer call with a GPU time in both runs."""
    first = {}
    for read in cached.reads:
        first.setdefault(read.history_id, read.read_id)
    warm, cold = _single_ok_answer(cached), _single_ok_answer(uncached)
    pairs = [rid for rid in warm if rid in cold and rid not in first.values()]
    g_warm = sum(warm[rid].gpu_seconds for rid in pairs)
    g_cold = sum(cold[rid].gpu_seconds for rid in pairs)
    return {"value": None if not pairs or g_cold == 0 else g_warm / g_cold, "pairs": len(pairs),
            "gpu_seconds_cached": round(g_warm, 6), "gpu_seconds_uncached": round(g_cold, 6),
            "bound": "upper (includes question prefill and decoding)"}


def full_history_row(run: RunCost) -> dict:
    """The measured row of a full-history run: three ledgers, per-read means, and the formula
    of plan 8.2 evaluated with the measured token cache ratio, for comparison only."""
    per_read = records_by_read(run)
    answers = [r for read in run.reads for r in per_read[read.read_id]["A"]]
    h = [_history_tokens(run, read.read_id) for read in run.reads]
    measured_c = token_cache_ratio(run)["value"]
    row = {
        "run_id": run.run_id,
        "reads": len(run.reads),
        "histories": len(histories(run)),
        "calls": len(answers),
        "failed_calls": sum(1 for r in answers if r.status != "ok"),
        "mean_history_tokens": sum(h) / len(h) if h else None,
        "logical": cost(answers, "logical"),
        "computed": cost(answers, "computed"),
        "gpu_seconds": cost(answers, "gpu_seconds"),
        "gpu_null": sum(1 for r in answers if r.gpu_seconds is None),
        "cached_input_tokens": sum(r.cached_input_tokens for r in answers),
        "token_cache_ratio": measured_c,
    }
    row["formula_cached_at_measured_c"] = (None if measured_c is None
                                           else formula_full_history(run, measured_c))
    return row


def formula_full_history(run: RunCost, c: float) -> float:
    """Plan 8.2 evaluated on the run's calls: each call pays its input, with the reusable prefix
    at ratio c, plus its output. With one call per read this is H + c(M-1)H + sum(L(q)+L(g))
    under end-of-history reading, and the interleaved charge otherwise."""
    return float(sum(record.input_tokens - (1.0 - c) * reusable + record.output_tokens
                     for record, _, reusable in reusable_prefix(run)))


# ---------------------------------------------------------------------------------------------
# Payback over the cache ratio


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def payback_read_count(w: float, delta: float | None) -> int | None:
    """M* = ceil(W / Delta); None when there is no payback point (Delta <= 0)."""
    if delta is None or delta <= 0:
        return None
    return max(1, math.ceil(w / delta)) if w > 0 else 0


@dataclass(frozen=True)
class PaybackPoint:
    c: float
    w: float  # mean write cost per history of the system
    system_per_read: float  # mean U_i + A_i
    baseline_per_read: float  # mean cost of a warm read of the cached full history
    delta: float
    m_star: int | None

    def to_dict(self) -> dict:
        return {"c": self.c, "W": self.w, "system_per_read": self.system_per_read,
                "full_history_per_read": self.baseline_per_read, "delta": self.delta,
                "m_star": self.m_star}


def payback_curve(system: RunCost, full_history: RunCost,
                  cs: Sequence[float]) -> list[PaybackPoint]:
    """M*(c) from measured records of both runs, each priced at c (module docstring).

    The baseline's per-read cost is the mean over the reads that are not the first of their
    history (the first pays H at full price and is the "H" term of plan 8.2)."""
    sys_reads = records_by_read(system)
    hist = histories(system)
    base_reads = records_by_read(full_history)
    first = {}
    for read in full_history.reads:
        first.setdefault(read.history_id, read.read_id)
    warm = [rid for rid in base_reads if rid not in first.values()]
    if not warm:
        raise LedgerError(f"{full_history.run_id}: no read after the first of a history")
    points = []
    for c in cs:
        w = mean([price(write_records(system, h), c) for h in hist]) or 0.0
        a_bar = mean([price(rows["U"] + rows["A"], c) for rows in sys_reads.values()]) or 0.0
        f_bar = mean([price(base_reads[rid]["A"], c) for rid in warm])
        delta = f_bar - a_bar
        points.append(PaybackPoint(c, w, a_bar, f_bar, delta, payback_read_count(w, delta)))
    return points


def grid(steps: int = 20) -> list[float]:
    return [round(i / steps, 6) for i in range(steps + 1)]


# ---------------------------------------------------------------------------------------------
# Cost per successful task and quality against tokens


def cost_per_success(run: RunCost, success: Mapping[str, bool]) -> dict:
    """Total system cost including failed attempts over the number of successful reads, with the
    success rate (plan 8.3); undefined (None) when nothing succeeds. Reads missing from
    `success` count as unsuccessful and are reported in `n_unscored`."""
    reads = [read.read_id for read in run.reads]
    n_success = sum(1 for rid in reads if success.get(rid, False))
    system = [r for r in run.records if r.category in SYSTEM]
    totals = {ledger: cost(system, ledger) for ledger in LEDGERS}
    return {
        "run_id": run.run_id,
        "n_reads": len(reads),
        "n_success": n_success,
        "n_unscored": sum(1 for rid in reads if rid not in success),
        "success_rate": n_success / len(reads) if reads else None,
        "total": totals,
        "cost_per_success": {ledger: (value / n_success if n_success and value is not None
                                      else None)
                             for ledger, value in totals.items()},
    }


def success_from_judgements(rows: Iterable[Mapping], judge: str | None = None) -> dict[str, bool]:
    """read_id -> verdict is `correct`, from judgements.jsonl records of one judge."""
    out: dict[str, bool] = {}
    judges = set()
    for row in rows:
        judges.add(row["judge"])
        if judge is not None and row["judge"] != judge:
            continue
        if row["read_id"] in out:
            raise LedgerError(f"two judgements of read {row['read_id']}; name the judge")
        out[row["read_id"]] = row["verdict"] == "correct"
    if judge is None and len(judges) > 1:
        raise LedgerError(f"judgements of several judges {sorted(judges)}; name one")
    return out


def mean_cost_per_read(run: RunCost) -> dict:
    """Mean system cost per read in each ledger, the ingestion included."""
    system = [r for r in run.records if r.category in SYSTEM]
    n = len(run.reads)
    out = {}
    for ledger in LEDGERS:
        total = cost(system, ledger)
        out[ledger] = total / n if n and total is not None else None
    return out
