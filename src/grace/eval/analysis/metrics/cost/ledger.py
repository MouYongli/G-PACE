"""The three cost ledgers of plan 8.1 over the call records of a run (Cost ledger contract).

Every record counts, whatever its status: failed attempts and invalid outputs are part of the
cost (plan 8.1). Per category (`W`, `U`, `A`, `embedding`, `evaluation`):

- logical tokens   = sum(input + output);
- computed tokens  = sum(input - cached + output), tokens actually computed after prefix reuse;
- GPU seconds      = sum(gpu_seconds), with the number of calls whose value is null.

System cost is `W + U + A`; `embedding` is reported separately and `evaluation` (judge calls) is
evaluation overhead, never system cost.

Per read (plan 8.2, contract "Which tokens are counted when"): read i of a history is charged the
`W` records with `version` in (r_{i-1}, r_i] or with `read_id` i, and the `U` and `A` records with
`read_id` i. `W` records after the last read of a history are reported as unassigned, so the
per-read charges and the unassigned rest always add up to the category totals
(`reconcile`).

This module reads only files of run directories (`calls.jsonl`, `predictions.jsonl`,
`contexts.jsonl`, `traces/`); it never imports engine code.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from grace.llm.records import CATEGORIES, CallRecord, read_calls

SYSTEM = ("W", "U", "A")


class LedgerError(ValueError):
    """Call records and reads that do not reconcile."""


@dataclass(frozen=True)
class Ledger:
    """Totals of a set of call records."""

    calls: int = 0
    failed_calls: int = 0  # status failed or invalid_output; counted in every total
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    gpu_seconds: float = 0.0
    gpu_null: int = 0  # calls without a GPU time (remote APIs, no accounting)
    latency_ms: float = 0.0

    @property
    def logical(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def computed(self) -> int:
        return self.input_tokens - self.cached_input_tokens + self.output_tokens

    def __add__(self, other: Ledger) -> Ledger:
        return Ledger(*(getattr(self, f) + getattr(other, f) for f in _FIELDS))

    def to_dict(self) -> dict:
        return {**asdict(self), "logical": self.logical, "computed": self.computed,
                "gpu_seconds": round(self.gpu_seconds, 6), "latency_ms": round(self.latency_ms, 3)}


_FIELDS = tuple(Ledger.__dataclass_fields__)


def ledger_of(records: Iterable[CallRecord]) -> Ledger:
    total = Ledger()
    for r in records:
        total = total + Ledger(
            calls=1, failed_calls=int(r.status != "ok"), input_tokens=r.input_tokens,
            cached_input_tokens=r.cached_input_tokens, output_tokens=r.output_tokens,
            gpu_seconds=r.gpu_seconds or 0.0, gpu_null=int(r.gpu_seconds is None),
            latency_ms=r.latency_ms)
    return total


def ledgers(records: Iterable[CallRecord]) -> dict[str, Ledger]:
    """The ledger of every category; categories without records are zero."""
    groups: dict[str, list[CallRecord]] = defaultdict(list)
    for r in records:
        groups[r.category].append(r)
    return {c: ledger_of(groups[c]) for c in CATEGORIES}


def system_cost(by_category: Mapping[str, Ledger]) -> Ledger:
    """W + U + A; embedding and evaluation are never system cost."""
    return by_category["W"] + by_category["U"] + by_category["A"]


@dataclass(frozen=True)
class Read:
    read_id: str
    history_id: str
    version: int


@dataclass(frozen=True)
class ReadCost:
    read: Read
    w_before: Ledger  # write cost charged before this read (W)
    u: Ledger
    a: Ledger

    @property
    def system(self) -> Ledger:
        return self.w_before + self.u + self.a

    def to_dict(self) -> dict:
        return {**asdict(self.read), "W_before": self.w_before.to_dict(), "U": self.u.to_dict(),
                "A": self.a.to_dict()}


@dataclass(frozen=True)
class Allocation:
    """Per-read charges and the W records no read was charged with."""

    reads: list[ReadCost]
    unassigned_w: Ledger
    unassigned_w_ids: list[str] = field(default_factory=list)
    # read_id -> {"W", "U", "A"} -> the records charged to it, in call order
    records: dict[str, dict[str, list[CallRecord]]] = field(default_factory=dict)


def allocate(records: Sequence[CallRecord], reads: Sequence[Read]) -> Allocation:
    """Charge W, U and A records to reads by the contract's rule (module docstring).

    Reads are taken in the given order within a history; reads at the same version keep that
    order and the later ones are charged no write cost by version. Raises `LedgerError` when a
    U or A record names a read that is not in `reads`, or a read ID is duplicated."""
    known = {}
    for read in reads:
        if read.read_id in known:
            raise LedgerError(f"duplicate read {read.read_id}")
        known[read.read_id] = read
    position = {id(r): i for i, r in enumerate(records)}
    system = [r for r in records if r.category in SYSTEM]
    for r in system:
        if r.read_id is not None and r.read_id not in known:
            raise LedgerError(f"call {r.call_id} names read {r.read_id}, which is not a read "
                              "of the run")
        if r.read_id is not None and known[r.read_id].history_id != r.history_id:
            raise LedgerError(f"call {r.call_id}: history {r.history_id} differs from the "
                              f"history of read {r.read_id}")
        if r.category in ("U", "A") and r.read_id is None:
            raise LedgerError(f"call {r.call_id} is {r.category} without a read_id")
    by_read: dict[str, dict[str, list[CallRecord]]] = defaultdict(lambda: defaultdict(list))
    loose_w: dict[str | None, list[CallRecord]] = defaultdict(list)
    for r in system:
        if r.read_id is not None:
            by_read[r.read_id][r.category].append(r)
        else:
            loose_w[r.history_id].append(r)
    taken: set[int] = set()  # id() of records: call IDs repeat across a run and its upstream
    per_history: dict[str, list[Read]] = defaultdict(list)
    for read in reads:
        per_history[read.history_id].append(read)
    charged: dict[str, dict[str, list[CallRecord]]] = {}
    for history_id, items in per_history.items():
        previous = None
        for read in sorted(items, key=lambda x: x.version):  # stable: ties keep input order
            writes = [r for r in loose_w.get(history_id, [])
                      if r.version is not None and r.version <= read.version
                      and (previous is None or r.version > previous)]
            taken.update(id(r) for r in writes)
            mine = by_read[read.read_id]
            w = sorted(writes + mine["W"], key=lambda r: position[id(r)])
            charged[read.read_id] = {"W": w, "U": mine["U"], "A": mine["A"]}
            previous = read.version
    out = [ReadCost(read, *(ledger_of(charged[read.read_id][c]) for c in SYSTEM))
           for read in reads]
    rest = [r for rows in loose_w.values() for r in rows if id(r) not in taken]
    return Allocation(out, ledger_of(rest), [f"{r.run_id}/{r.call_id}" for r in rest],
                      {read.read_id: charged[read.read_id] for read in reads})


def reconcile(records: Sequence[CallRecord], allocation: Allocation) -> dict:
    """Check that per-read charges plus unassigned writes equal the category totals.

    Returns the totals compared; raises `LedgerError` on any difference."""
    totals = ledgers(records)
    summed = {
        "W": sum((c.w_before for c in allocation.reads), Ledger()) + allocation.unassigned_w,
        "U": sum((c.u for c in allocation.reads), Ledger()),
        "A": sum((c.a for c in allocation.reads), Ledger()),
    }
    report = {}
    for category, got in summed.items():
        want = totals[category]
        same = (got.calls, got.input_tokens, got.cached_input_tokens, got.output_tokens,
                got.gpu_null) == (want.calls, want.input_tokens, want.cached_input_tokens,
                                  want.output_tokens, want.gpu_null) \
            and abs(got.gpu_seconds - want.gpu_seconds) < 1e-6
        if not same:
            raise LedgerError(f"{category}: per-read charges {got.to_dict()} differ from the "
                              f"total {want.to_dict()}")
        report[category] = {"logical": want.logical, "computed": want.computed,
                            "gpu_seconds": round(want.gpu_seconds, 6), "calls": want.calls}
    return report


# ---------------------------------------------------------------------------------------------
# Run directories


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise LedgerError(f"{path}:{number}: {exc}") from exc
    return rows


@dataclass
class RunCost:
    """The cost-relevant files of one run directory and of its upstream chain."""

    run_dir: Path
    run: dict
    records: list[CallRecord]  # own calls followed by those of upstream ingest runs
    reads: list[Read]
    context_tokens: dict[str, int]  # read_id -> tokens of the working context
    upstream: list[RunCost] = field(default_factory=list)

    @property
    def run_id(self) -> str:
        return self.run["run_id"]

    def ledgers(self) -> dict[str, Ledger]:
        return ledgers(self.records)

    def allocation(self) -> Allocation:
        return allocate(self.records, self.reads)


def reads_of(run_dir: Path) -> list[Read]:
    """Reads in the order the run answered them: predictions.jsonl, else the read calls."""
    predictions = _jsonl(run_dir / "predictions.jsonl")
    if predictions:
        return [Read(p["read_id"], p["history_id"], int(p["version"])) for p in predictions]
    seen: dict[str, Read] = {}
    for r in read_calls(run_dir / "calls.jsonl"):
        if r.read_id is not None and r.read_id not in seen and r.category != "evaluation":
            seen[r.read_id] = Read(r.read_id, r.history_id, r.version)
    return list(seen.values())


def load_run(run_dir: Path, *, include_ingest: bool = True) -> RunCost:
    """Read a run directory. A `read` run also carries the calls of its `ingest` upstream, so
    the write cost of the ingestion it reuses is charged to it."""
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    records = read_calls(run_dir / "calls.jsonl")
    for r in records:
        if r.run_id != run["run_id"]:
            raise LedgerError(f"{run_dir}: call {r.call_id} belongs to run {r.run_id}")
    upstream = []
    if include_ingest:
        for item in run.get("upstream", []):
            if item["stage"] == "ingest":
                upstream.append(load_run(Path(item["path"]), include_ingest=False))
    contexts = {c["read_id"]: int(c["tokens"]) for c in _jsonl(run_dir / "contexts.jsonl")}
    all_records = records + [r for u in upstream for r in u.records]
    return RunCost(run_dir, run, all_records, reads_of(run_dir), contexts, upstream)


# ---------------------------------------------------------------------------------------------
# Separately reported quantities (plan 8.1): not ledger entries


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile (numpy's default); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100.0
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _spread(values: Sequence[float]) -> dict:
    return {"n": len(values), "p50": percentile(values, 50), "p95": percentile(values, 95),
            "total": round(sum(values), 3)}


def separate(run: RunCost) -> dict:
    """Embedding tokens, latency, component timings and tool calls, reported apart from the
    ledgers. Memory is not recorded by any component yet and is reported as null."""
    by_category = run.ledgers()
    call_latency = {c: _spread([r.latency_ms for r in run.records if r.category == c])
                    for c in CATEGORIES}
    per_read: dict[str, float] = defaultdict(float)
    for r in run.records:
        if r.read_id is not None and r.category in SYSTEM:
            per_read[r.read_id] += r.latency_ms
    timings: dict[str, dict[str, list[float]]] = {"write": defaultdict(list),
                                                  "read": defaultdict(list)}
    further = 0
    traced = [run.run_dir] + [u.run_dir for u in run.upstream]
    for directory in traced:
        for kind in ("write", "read"):
            for row in _jsonl(directory / "traces" / f"{kind}.jsonl"):
                for component, ms in (row.get("timings_ms") or {}).items():
                    timings[kind][component].append(float(ms))
                if kind == "read" and row.get("further_retrieval"):
                    further += 1
    external = sum(1 for r in run.records if r.call_type == "external")
    return {
        "embedding": {"calls": by_category["embedding"].calls,
                      "tokens": by_category["embedding"].input_tokens,
                      "gpu_seconds": round(by_category["embedding"].gpu_seconds, 6)},
        "evaluation_overhead": by_category["evaluation"].to_dict(),
        "call_latency_ms": call_latency,
        "read_model_latency_ms": _spread([per_read.get(r.read_id, 0.0) for r in run.reads]),
        "component_timings_ms": {kind: {c: _spread(v) for c, v in sorted(rows.items())}
                                 for kind, rows in timings.items()},
        "tool_calls": {"further_retrievals": further, "external_calls": external},
        "memory_bytes": None,
    }


def summary(run: RunCost) -> dict:
    """Ledgers, reconciliation, per-read charges and the separate quantities of one run."""
    by_category = run.ledgers()
    allocation = run.allocation()
    return {
        "run_id": run.run_id,
        "upstream": [u.run_id for u in run.upstream],
        "n_reads": len(run.reads),
        "ledgers": {c: by_category[c].to_dict() for c in CATEGORIES},
        "system": system_cost(by_category).to_dict(),
        "failed": {c: {"calls": by_category[c].failed_calls} for c in CATEGORIES},
        "reconciliation": reconcile(run.records, allocation),
        "unassigned_w": {**allocation.unassigned_w.to_dict(),
                         "call_ids": allocation.unassigned_w_ids},
        "reads": [c.to_dict() for c in allocation.reads],
        "separate": separate(run),
    }
