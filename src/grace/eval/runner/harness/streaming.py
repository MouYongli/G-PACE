"""Evidence-anchored streaming (plan 6.5, task T031): read selection and the state probe.

The protocol needs no runner of its own. The schedule is a read-task file,
`read_tasks.streaming.jsonl`, emitted by the LoCoMo adapter from the T007 read-point list: every
question with complete evidence is asked at v(q), the end of the session holding its latest
evidence turn, and again at N; the questions T007 excludes (missing or unresolvable evidence) are
not in it. `drive.run_system(..., schedule="streaming")` runs it like any schedule: messages are
written in version order, every read at version r is answered on that snapshot, each
independently, followed by `end_read` (the question's temporary artefacts are discarded), and
writing continues with message r+1 after the last read at r.

This module adds:

- `select_reads`: keep only some questions (smoke runs) and fix the order of the reads that share
  a version (`schedule` order or `reversed`), so the same schedule can be run in two orders.
- `StateProbe`: an engine wrapper that records, for every read, the engine version, a fingerprint
  of the engine's resident state as the read used it (taken after `read`, so after any flush the
  read itself triggered), the evidence input (the working context: text, fragments, provenance)
  and the fingerprint after `end_read`. It raises when answering or `end_read` changes resident
  state, so a run with the probe fails instead of carrying state from one question into the next.
  The fingerprint is the SHA-256 of the files `save` writes. The index version
  (`state_sha256`) leaves out event logs (`*_events.jsonl`, e.g. GRACE's view events): they record
  which read triggered a maintenance step and how long it took, which depends on the order of
  the reads and on the clock, and no read uses them. The check after `end_read` compares the full
  fingerprint, event logs included. Temporary per-read state that an engine keeps outside its
  saved state is checked through order independence: two orders must give the same version,
  index version and evidence input for every read (tests/integration/test_locomo_streaming.py).

Under streaming most reads fall inside an open extraction unit, so GRACE flushes it inside
`read`; the flush's change sets, write traces and stale marks come back in `ReadResult.writes`
(trigger `read`) and are recorded like writes, and `finish()` after the last message extracts a
unit still open (trigger `finish`), so write cost and staleness counts are complete (T026).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from grace.context import api
from grace.eval.runner.harness.inputs import HistoryInputs, Inputs

READ_ORDERS = ("schedule", "reversed")
EVENT_LOG_SUFFIX = "_events.jsonl"


def select_reads(inputs: Inputs, task_ids: Sequence[str] | None = None,
                 read_order: str = "schedule") -> Inputs:
    """`inputs` with only the reads of `task_ids` (all when None), and the reads of one version
    in schedule order or reversed. Fails when a requested task has no read."""
    if read_order not in READ_ORDERS:
        raise ValueError(f"read_order {read_order!r} not in {READ_ORDERS}")
    wanted = None if task_ids is None else set(task_ids)
    found: set[str] = set()
    histories = []
    for item in inputs.histories:
        reads = [t for t in item.reads if wanted is None or t.task_id in wanted]
        found.update(t.task_id for t in reads)
        if read_order == "reversed":
            reads = list(reversed(reads))
        reads.sort(key=lambda t: t.version)  # stable: keeps the chosen order within a version
        histories.append(HistoryInputs(item.history, item.messages, tuple(reads)))
    if wanted is not None and wanted - found:
        raise ValueError(f"tasks without a read in {inputs.schedule}: {sorted(wanted - found)}")
    return replace(inputs, histories=tuple(histories))


def state_fingerprints(engine: api.ContextEngine) -> tuple[str, str]:
    """(index version, full fingerprint): SHA-256 over the files `engine.save` writes (relative
    path and content, sorted), without and with the event logs."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        engine.save(root)
        index, full = hashlib.sha256(), hashlib.sha256()
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            line = (path.relative_to(root).as_posix().encode("utf-8") + b"\0"
                    + hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
            full.update(line)
            if not path.name.endswith(EVENT_LOG_SUFFIX):
                index.update(line)
        return index.hexdigest(), full.hexdigest()


def evidence_digest(context: api.WorkingContext) -> str:
    """SHA-256 of the evidence input of a read: context text, fragments and provenance."""
    record = context.to_record()
    payload = {k: record[k] for k in ("read_id", "version", "budget_tokens", "text",
                                      "fragments")}
    payload["provenance"] = context.provenance
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass
class ProbeRecord:
    read_id: str
    task_id: str
    history_id: str
    version: int                 # engine version when the read was served
    state_sha256: str            # index version: resident state the read used (after read,
                                 # incl. its flush), without event logs
    full_sha256: str             # the same state with event logs
    evidence_sha256: str         # working context of the first read call
    final_evidence_sha256: str   # working context after the further retrieval (or the same)
    context_ids: tuple[str, ...]
    further_retrieval: bool = False
    full_after_end_sha256: str | None = None


    @property
    def unchanged(self) -> bool:
        """Answering and end_read left the resident state (event logs included) as the read
        left it."""
        return self.full_after_end_sha256 == self.full_sha256


class ProbeError(RuntimeError):
    """Answering or end_read changed the engine's resident state."""


class StateProbe(api.ContextEngine):
    """Wraps an engine; see the module docstring. `records` holds one ProbeRecord per read."""

    def __init__(self, inner: api.ContextEngine, records: list[ProbeRecord] | None = None):
        self.inner = inner
        self.records = records if records is not None else []
        self._open: dict[str, ProbeRecord] = {}

    def open(self, history):
        return self.inner.open(history)

    @property
    def version(self) -> int:
        return self.inner.version

    def write(self, message):
        if self._open:
            raise ProbeError(f"write while reads are open: {sorted(self._open)}")
        return self.inner.write(message)

    def read(self, task, budget_tokens):
        result = self.inner.read(task, budget_tokens)
        digest = evidence_digest(result.context)
        index, full = state_fingerprints(self.inner)
        record = ProbeRecord(task.read_id, task.task_id, task.history_id, self.inner.version,
                             index, full, digest, digest, tuple(result.context.context_ids))
        self._open[task.read_id] = record
        return result

    def further_retrieval(self, task, request, budget_tokens):
        result = self.inner.further_retrieval(task, request, budget_tokens)
        record = self._open[task.read_id]
        record.further_retrieval = True
        record.final_evidence_sha256 = evidence_digest(result.context)
        return result

    def end_read(self, task):
        self.inner.end_read(task)
        record = self._open.pop(task.read_id)
        record.full_after_end_sha256 = state_fingerprints(self.inner)[1]
        self.records.append(record)
        if not record.unchanged:
            raise ProbeError(f"{task.read_id}: resident state changed between the read and "
                             "end_read (answering or end_read wrote to the engine)")

    def finish(self):
        if self._open:
            raise ProbeError(f"finish while reads are open: {sorted(self._open)}")
        return self.inner.finish()

    def save(self, directory):
        return self.inner.save(directory)

    def restore(self, directory):
        return self.inner.restore(directory)


def probe_summary(records: Sequence[ProbeRecord]) -> dict:
    """Counts for the run log: reads checked, versions, unchanged state after every read."""
    return {"reads": len(records),
            "versions": sorted({r.version for r in records}),
            "state_unchanged_after_end_read": sum(r.unchanged for r in records),
            "further_retrievals": sum(r.further_retrieval for r in records)}


def probe_rows(records: Sequence[ProbeRecord]) -> list[dict]:
    return [{**asdict(r), "context_ids": list(r.context_ids)} for r in records]
