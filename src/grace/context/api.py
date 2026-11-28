"""The ContextEngine interface and its types (docs/work/plan/structure.md, decision D013).

Every system under comparison implements `ContextEngine`: GRACE (`context/engine.py`), its
variants and the baselines in `eval/engines/baselines/`. The harness (`eval/runner/harness/`)
drives every engine through this interface only, so all systems receive exactly the same inputs:
visible benchmark records, never gold data.

The record types mirror the visible records of docs/research/contracts.md (History, Message, Read
task) and the trace and working-context records of its "Experiment run" section. `from_record`
rejects missing, unknown and mistyped fields, so a gold field cannot reach an engine through these
types. `to_record` returns the JSON object the contract specifies.

The five requirements of structure.md, "What the interface must support":

1. A read is bound to a version. `read` sees exactly the messages with `version <= task.version`
   and never writes to the history or the claim graph. A lazy rebuild of a resident view may be
   kept; temporary artefacts of a question are discarded at `end_read`.
2. State can be saved and restored (`save`, `restore`), so that one ingestion serves several read
   runs and long histories can resume.
3. The answering LLM may request one further retrieval (`further_retrieval`); baselines take the
   same path.
4. Under segment extraction, when a read falls inside a segment, the engine first extracts the part
   that has arrived. This happens inside `read`; its calls are write cost (`W`, trigger `read`).
5. Every write and read returns a trace (`WriteTrace`, `ReadTrace`).

This module imports nothing else from `context/` (structure.md, "Inside context/").
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from dataclasses import MISSING as _MISSING
from dataclasses import dataclass, field, fields
from pathlib import Path
from types import UnionType
from typing import Any, get_args, get_origin, get_type_hints

ROLES = frozenset({"user", "agent", "peer", "document"})
READ_KINDS = frozenset({"question", "state"})
FRAGMENT_KINDS = frozenset({"message", "view", "claim", "summary", "retrieved", "other"})
STALE_LEVELS = frozenset({"answer", "citation", "unknown"})
STALENESS_DECISIONS = frozenset({"fresh", "answer_stale", "citation_stale"})
STALENESS_ACTIONS = frozenset({"reuse", "patch", "rebuild"})


class RecordError(ValueError):
    """A record does not match its contract; the message names the record type and the field."""


def _check_type(name: str, key: str, value: Any, hint: Any) -> None:
    """Check the top-level type of one field; `bool` is not accepted where `int` is expected."""
    if get_origin(hint) is UnionType:
        allowed = tuple(get_origin(arg) or arg for arg in get_args(hint))
    else:
        allowed = (get_origin(hint) or hint,)
    allowed = tuple(list if a in (tuple, Sequence) else dict if a is Mapping else a
                    for a in allowed)
    if isinstance(value, bool) and bool not in allowed:
        raise RecordError(f"{name}.{key}: expected {hint}, got bool")
    if float in allowed and isinstance(value, int) and not isinstance(value, bool):
        return
    if not isinstance(value, allowed):
        raise RecordError(f"{name}.{key}: expected {hint}, got {type(value).__name__}")
    if value == "":
        raise RecordError(f"{name}.{key}: empty string")


def _parse(cls, record: Mapping[str, Any], nested: Mapping[str, Any] | None = None) -> dict:
    """Validate `record` against the fields of dataclass `cls`; return constructor arguments.

    Fields with a default are optional; all others are required. Unknown fields are an error.
    `nested` maps a field name to the dataclass of its list elements.
    """
    name = cls.__name__
    if not isinstance(record, Mapping):
        raise RecordError(f"{name}: expected an object, got {type(record).__name__}")
    hints = get_type_hints(cls)
    spec = {f.name: f for f in fields(cls)}
    unknown = sorted(record.keys() - spec.keys())
    if unknown:
        raise RecordError(f"{name}: unknown fields {unknown}")
    out = {}
    for key, f in spec.items():
        if key not in record:
            if f.default is f.default_factory is _MISSING:
                raise RecordError(f"{name}.{key}: missing")
            continue
        value = record[key]
        _check_type(name, key, value, hints[key])
        if nested and key in nested:
            value = tuple(nested[key].from_record(item) for item in value)
        elif isinstance(value, list):
            value = tuple(value)
        out[key] = value
    return out


# ---------------------------------------------------------------------------------------------
# Visible benchmark records (contracts.md: History, Message, Read task)


@dataclass(frozen=True)
class Segment:
    """A dated part of a history; covers versions `first_version..last_version`."""

    segment_id: str
    first_version: int
    last_version: int
    timestamp: str | None
    timestamp_raw: str | None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Segment:
        return cls(**_parse(cls, record))

    def to_record(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(frozen=True)
class HistoryInfo:
    """The visible header of one history (contracts.md, "History"), given to `open`."""

    benchmark: str
    split: str
    history_id: str
    subset: str | None
    n_messages: int
    segments: tuple[Segment, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> HistoryInfo:
        info = cls(**_parse(cls, record, {"segments": Segment}))
        if info.n_messages < 1:
            raise RecordError(f"HistoryInfo.n_messages: {info.n_messages} < 1")
        return info

    def segment(self, segment_id: str | None) -> Segment | None:
        """The segment with this ID, or None when the history has no segments."""
        for segment in self.segments:
            if segment.segment_id == segment_id:
                return segment
        return None

    def to_record(self) -> dict[str, Any]:
        record = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "metadata"}
        record["segments"] = [s.to_record() for s in self.segments]
        if self.metadata:
            record["metadata"] = dict(self.metadata)
        return record


@dataclass(frozen=True)
class Message:
    """One message h_r of a history (contracts.md, "Message"); writing it commits version r."""

    benchmark: str
    split: str
    history_id: str
    version: int
    message_id: str
    segment_id: str | None
    speaker: str | None
    role: str
    text: str
    timestamp: str | None
    timestamp_raw: str | None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Message:
        message = cls(**_parse(cls, record))
        if message.role not in ROLES:
            raise RecordError(f"Message.role: {message.role!r} not in {sorted(ROLES)}")
        if message.version < 1:
            raise RecordError(f"Message.version: {message.version} < 1")
        return message

    def to_record(self) -> dict[str, Any]:
        record = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "metadata"}
        if self.metadata:
            record["metadata"] = dict(self.metadata)
        return record


@dataclass(frozen=True)
class ReadTask:
    """A question or state request bound to version `version` (contracts.md, "Read task")."""

    benchmark: str
    split: str
    history_id: str
    read_id: str
    task_id: str
    version: int
    kind: str
    question: str | None
    state_schema: str | None
    asked_at: str | None
    asked_at_raw: str | None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ReadTask:
        task = cls(**_parse(cls, record))
        if task.kind not in READ_KINDS:
            raise RecordError(f"ReadTask.kind: {task.kind!r} not in {sorted(READ_KINDS)}")
        if (task.kind == "question") != (task.question is not None):
            raise RecordError(f"ReadTask {task.read_id}: `question` must be set iff kind=question")
        if (task.kind == "state") != (task.state_schema is not None):
            raise RecordError(f"ReadTask {task.read_id}: `state_schema` must be set iff kind=state")
        if task.read_id != f"{task.task_id}@{task.version}":
            raise RecordError(f"ReadTask.read_id: {task.read_id!r} is not <task_id>@<version>")
        return task

    def to_record(self) -> dict[str, Any]:
        record = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "metadata"}
        if self.metadata:
            record["metadata"] = dict(self.metadata)
        return record


# ---------------------------------------------------------------------------------------------
# Working context (contracts.md, "Intermediate artefacts", contexts.jsonl)


@dataclass(frozen=True)
class Fragment:
    """One piece of the working context with the message IDs whose text it carries or cites.

    `kind` is `message` (raw message text), `view`, `claim`, `summary`, `retrieved` (a retrieved
    chunk) or `other`. `source_ids` lists the `message_id`s whose source text is in `text`; they
    form the set R of plan 3.1 (strict evidence recall). `evidence_ids` lists every message the
    fragment rests on, including provenance of derived text (lenient recall).
    """

    fragment_id: str
    kind: str
    text: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    tokens: int

    def __post_init__(self) -> None:
        if self.kind not in FRAGMENT_KINDS:
            raise RecordError(f"Fragment.kind: {self.kind!r} not in {sorted(FRAGMENT_KINDS)}")
        if self.tokens < 0:
            raise RecordError(f"Fragment.tokens: {self.tokens} < 0")

    def to_record(self) -> dict[str, Any]:
        return {"fragment_id": self.fragment_id, "kind": self.kind,
                "evidence_ids": list(self.evidence_ids), "tokens": self.tokens}


@dataclass(frozen=True)
class WorkingContext:
    """The context an engine builds for one read; `text` is exactly what the answer prompt gets.

    `budget_tokens` is the memory budget of the read (`None` for the full history); `tokens` is
    the size of `text` counted with the answering model's tokenizer.
    """

    read_id: str
    history_id: str
    version: int
    budget_tokens: int | None
    tokens: int
    text: str
    fragments: tuple[Fragment, ...]

    @property
    def context_ids(self) -> list[str]:
        """Message IDs whose source text is in the context, in first-seen order (set R)."""
        return _unique(i for f in self.fragments for i in f.source_ids)

    @property
    def provenance(self) -> dict[str, list[str]]:
        """Fragment ID -> message IDs it rests on, for lenient evidence recall."""
        return {f.fragment_id: list(f.evidence_ids) for f in self.fragments}

    def to_record(self) -> dict[str, Any]:
        return {"read_id": self.read_id, "history_id": self.history_id, "version": self.version,
                "budget_tokens": self.budget_tokens, "tokens": self.tokens, "text": self.text,
                "fragments": [f.to_record() for f in self.fragments]}


# ---------------------------------------------------------------------------------------------
# Traces (contracts.md, "Intermediate artefacts", traces/write.jsonl and traces/read.jsonl)


@dataclass(frozen=True)
class StaleMark:
    """A view marked stale at write time by a staleness strategy."""

    view_id: str
    strategy: str
    level: str

    def __post_init__(self) -> None:
        if self.level not in STALE_LEVELS:
            raise RecordError(f"StaleMark.level: {self.level!r} not in {sorted(STALE_LEVELS)}")

    def to_record(self) -> dict[str, Any]:
        return {"view_id": self.view_id, "strategy": self.strategy, "level": self.level}


@dataclass(frozen=True)
class Candidate:
    """A retrieval candidate: a unified evidence ID, its channel and score."""

    id: str
    channel: str
    score: float

    def to_record(self) -> dict[str, Any]:
        return {"id": self.id, "channel": self.channel, "score": self.score}


@dataclass(frozen=True)
class StalenessDecision:
    """A read-time staleness decision on one view and the action taken."""

    view_id: str
    strategy: str
    decision: str
    action: str

    def __post_init__(self) -> None:
        if self.decision not in STALENESS_DECISIONS:
            raise RecordError(f"StalenessDecision.decision: {self.decision!r}")
        if self.action not in STALENESS_ACTIONS:
            raise RecordError(f"StalenessDecision.action: {self.action!r}")

    def to_record(self) -> dict[str, Any]:
        return {"view_id": self.view_id, "strategy": self.strategy,
                "decision": self.decision, "action": self.action}


@dataclass(frozen=True)
class WriteTrace:
    """What one committed write (a message, or a segment flushed by it) did."""

    history_id: str
    version: int
    message_ids: tuple[str, ...]
    call_ids: tuple[str, ...] = ()
    stale_marks: tuple[StaleMark, ...] = ()
    timings_ms: Mapping[str, float] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {"history_id": self.history_id, "version": self.version,
                "message_ids": list(self.message_ids), "call_ids": list(self.call_ids),
                "stale_marks": [m.to_record() for m in self.stale_marks],
                "timings_ms": dict(self.timings_ms)}


@dataclass(frozen=True)
class ReadTrace:
    """What one read did. `included_ids` equals the `context_ids` of the prediction.

    `retrieval_used`: the read's one extra retrieval (plan 5.6) is spent, by the engine's own
    query expansion or by a further retrieval; the harness then resolves a `retrieve` output of the
    answering LLM as `unknown`. `utilisation`: context tokens / budget (None for the full
    history). `expansions_used`: expansions the engine's assembly made (0 for engines without).
    """

    read_id: str
    history_id: str
    version: int
    candidates: tuple[Candidate, ...]
    included_ids: tuple[str, ...]
    provenance: Mapping[str, tuple[str, ...]]
    view_hits: tuple[str, ...] = ()
    staleness_decisions: tuple[StalenessDecision, ...] = ()
    further_retrieval: bool = False
    call_ids: tuple[str, ...] = ()
    timings_ms: Mapping[str, float] = field(default_factory=dict)
    retrieval_used: bool = False
    utilisation: float | None = None
    expansions_used: int = 0

    def to_record(self) -> dict[str, Any]:
        return {"read_id": self.read_id, "history_id": self.history_id, "version": self.version,
                "candidates": [c.to_record() for c in self.candidates],
                "included_ids": list(self.included_ids),
                "provenance": {k: list(v) for k, v in self.provenance.items()},
                "view_hits": list(self.view_hits),
                "staleness_decisions": [d.to_record() for d in self.staleness_decisions],
                "further_retrieval": self.further_retrieval, "call_ids": list(self.call_ids),
                "timings_ms": dict(self.timings_ms), "retrieval_used": self.retrieval_used,
                "utilisation": self.utilisation, "expansions_used": self.expansions_used}


@dataclass(frozen=True)
class WriteResult:
    """Return value of `write`. `changeset` is the serialised change set of the committed version
    (format owned by `context/memory/graph/changeset.py`), or None for engines without a graph."""

    trace: WriteTrace
    changeset: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ReadResult:
    """Return value of `read` and `further_retrieval`."""

    context: WorkingContext
    trace: ReadTrace


def read_trace(context: WorkingContext, *, candidates: Sequence[Candidate] = (),
               further_retrieval: bool = False, call_ids: Sequence[str] = (),
               timings_ms: Mapping[str, float] | None = None, view_hits: Sequence[str] = (),
               staleness_decisions: Sequence[StalenessDecision] = (),
               retrieval_used: bool = False, expansions_used: int = 0) -> ReadTrace:
    """Build the read trace that matches `context` (included IDs and provenance taken from it).

    `retrieval_used` is also True after a further retrieval; `utilisation` is computed from the
    context (tokens / budget, None for the full history)."""
    utilisation = (context.tokens / context.budget_tokens if context.budget_tokens else None)
    return ReadTrace(
        read_id=context.read_id, history_id=context.history_id, version=context.version,
        candidates=tuple(candidates), included_ids=tuple(context.context_ids),
        provenance={k: tuple(v) for k, v in context.provenance.items()},
        view_hits=tuple(view_hits), staleness_decisions=tuple(staleness_decisions),
        further_retrieval=further_retrieval, call_ids=tuple(call_ids),
        timings_ms=dict(timings_ms or {}), retrieval_used=retrieval_used or further_retrieval,
        utilisation=utilisation, expansions_used=expansions_used)


# ---------------------------------------------------------------------------------------------
# The interface


class ContextEngine(abc.ABC):
    """A system that builds working contexts from a history; one instance serves one history.

    Life cycle, driven by the harness:

    1. `open(history)` once, or `restore(directory)` to continue from a saved state.
    2. `write(message)` for versions 1, 2, ... in order; each call commits one version.
    3. Between writes, any number of reads at the current version: `read(task, budget)`,
       optionally one `further_retrieval(task, request, budget)`, then `end_read(task)`.
    4. `save(directory)` at any point between operations.

    Engines that call a model receive their client when they are constructed and tag each call
    with its ledger category (contracts.md, "Cost ledger"); the call IDs go into the traces.
    """

    @abc.abstractmethod
    def open(self, history: HistoryInfo) -> None:
        """Start an empty history. Called once, before the first write."""

    @property
    @abc.abstractmethod
    def version(self) -> int:
        """The last committed version (0 before the first write)."""

    @abc.abstractmethod
    def write(self, message: Message) -> WriteResult:
        """Commit `message` as version `self.version + 1`. Raise ValueError on any other version
        or on a message of another history."""

    @abc.abstractmethod
    def read(self, task: ReadTask, budget_tokens: int | None) -> ReadResult:
        """Build the working context for `task` at version `task.version`, within `budget_tokens`
        tokens of memory (`None`: the full history). `task.version` must equal `self.version`.
        Never writes to the history or the claim graph."""

    @abc.abstractmethod
    def further_retrieval(self, task: ReadTask, request: str,
                          budget_tokens: int | None) -> ReadResult:
        """Serve the answering LLM's one permitted request for further retrieval. Returns the
        complete working context for the second answering call, with
        `trace.further_retrieval = True`. Same version and budget rules as `read`."""

    def end_read(self, task: ReadTask) -> None:  # noqa: B027 (optional hook, empty by default)
        """Discard the temporary artefacts of `task`. Resident state is kept."""

    @abc.abstractmethod
    def save(self, directory: Path) -> list[Path]:
        """Write the engine state into `directory` (which exists and is empty); return the files
        written. The harness records them with their checksums in `snapshot/manifest.json`."""

    @abc.abstractmethod
    def restore(self, directory: Path) -> None:
        """Load a state written by `save`; afterwards `version` is the saved version."""


def check_read(engine: ContextEngine, task: ReadTask) -> None:
    """Raise ValueError unless `task` reads the engine's current version (requirement 1)."""
    if task.version != engine.version:
        raise ValueError(f"read {task.read_id} is bound to version {task.version}, "
                         f"but the engine is at version {engine.version}")


def _unique(items) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)


__all__ = [
    "Candidate", "ContextEngine", "Fragment", "HistoryInfo", "Message", "ReadResult",
    "ReadTask", "ReadTrace", "RecordError", "Segment", "StaleMark", "StalenessDecision",
    "WorkingContext", "WriteResult", "WriteTrace", "check_read", "read_trace",
]
