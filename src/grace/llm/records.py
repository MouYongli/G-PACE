"""Call records of the Cost ledger (docs/research/contracts.md#cost-ledger) and calls.jsonl.

Every model call writes one `CallRecord`, including retries and failed attempts. The caller sets
the call type and the trigger; the ledger category follows from them by the table "Which tokens
are counted when", so a caller cannot book a lazy rebuild at read time to U or a judge call to A.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

CALL_TYPES = ("extract", "vocabulary", "render", "plan", "repair", "verify", "answer", "summary",
              "external", "embed", "judge")
TRIGGERS = ("write", "read", "evaluation")
CATEGORIES = ("W", "U", "A", "embedding", "evaluation")
STATUSES = ("ok", "failed", "invalid_output")

# call_type -> category; `external` depends on the trigger (write -> W, read -> U).
_CATEGORY = {"extract": "W", "vocabulary": "W", "render": "W", "summary": "W", "plan": "U",
             "repair": "U", "verify": "U", "answer": "A", "embed": "embedding",
             "judge": "evaluation"}
_EXTERNAL = {"write": "W", "read": "U"}


class CallRecordError(ValueError):
    """A call record that violates the Cost ledger contract."""


def category_for(call_type: str, trigger: str) -> str:
    """Ledger category of a call; raises for combinations the contract does not allow."""
    if call_type not in CALL_TYPES:
        raise CallRecordError(f"unknown call_type {call_type!r}")
    if trigger not in TRIGGERS:
        raise CallRecordError(f"unknown trigger {trigger!r}")
    if (call_type == "judge") != (trigger == "evaluation"):
        raise CallRecordError("judge calls, and only they, have trigger 'evaluation'")
    if call_type == "external":
        return _EXTERNAL[trigger]
    return _CATEGORY[call_type]


@dataclass(frozen=True)
class CallContext:
    """What a call serves; set by the caller (the harness cannot infer it from the stage)."""

    call_type: str
    trigger: str
    history_id: str | None = None
    read_id: str | None = None
    version: int | None = None

    def __post_init__(self):
        category_for(self.call_type, self.trigger)
        if self.trigger == "write" and self.read_id is not None:
            raise CallRecordError("a write-triggered call has read_id null")

    @property
    def category(self) -> str:
        return category_for(self.call_type, self.trigger)


@dataclass(frozen=True)
class CallRecord:
    """One line of calls.jsonl; field names and types follow the Cost ledger section."""

    call_id: str
    run_id: str
    history_id: str | None
    read_id: str | None
    version: int | None
    call_type: str
    trigger: str
    category: str
    model: str
    attempt: int
    status: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    gpu_seconds: float | None
    latency_ms: float
    prompt_sha256: str | None

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        for name in ("call_id", "run_id", "model"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise CallRecordError(f"{name} must be a non-empty string")
        for name in ("history_id", "read_id", "prompt_sha256"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise CallRecordError(f"{name} must be null or a non-empty string")
        for name in ("attempt", "input_tokens", "output_tokens", "cached_input_tokens"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise CallRecordError(f"{name} must be an integer")
        if self.version is not None and (isinstance(self.version, bool)
                                         or not isinstance(self.version, int)):
            raise CallRecordError("version must be null or an integer")
        expected = category_for(self.call_type, self.trigger)
        if self.category != expected:
            raise CallRecordError(f"{self.call_type}/{self.trigger} is category {expected}, "
                                  f"not {self.category}")
        if self.trigger == "write" and self.read_id is not None:
            raise CallRecordError("a write-triggered call has read_id null")
        if self.status not in STATUSES:
            raise CallRecordError(f"unknown status {self.status!r}")
        if self.attempt < 1:
            raise CallRecordError("attempt starts at 1")
        if self.output_tokens < 0 or not 0 <= self.cached_input_tokens <= self.input_tokens:
            raise CallRecordError("token counts violate 0 <= cached <= input, output >= 0")
        if self.call_type == "embed" and self.output_tokens != 0:
            raise CallRecordError("embedding calls have output_tokens 0")
        if self.gpu_seconds is not None and (isinstance(self.gpu_seconds, bool)
                                             or not isinstance(self.gpu_seconds, int | float)
                                             or self.gpu_seconds < 0):
            raise CallRecordError("gpu_seconds must be null or a non-negative number")
        if (isinstance(self.latency_ms, bool) or not isinstance(self.latency_ms, int | float)
                or self.latency_ms < 0):
            raise CallRecordError("latency_ms must be a non-negative number")

    @property
    def logical_tokens(self) -> int:
        """Input plus output, whatever the cache served (plan 8.1)."""
        return self.input_tokens + self.output_tokens

    @property
    def computed_tokens(self) -> int:
        """Tokens actually computed after prefix-cache reuse."""
        return self.input_tokens - self.cached_input_tokens + self.output_tokens

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=False)

    @classmethod
    def from_dict(cls, row: dict) -> CallRecord:
        names = {f.name for f in fields(cls)}
        missing, unknown = names - row.keys(), row.keys() - names
        if missing or unknown:
            raise CallRecordError(f"missing fields {sorted(missing)}, "
                                  f"unknown fields {sorted(unknown)}")
        return cls(**row)


class CallLedger:
    """Append-only writer of `calls.jsonl` for one run; thread-safe, call IDs unique per run.

    Reopening an existing file (resuming a run) loads its call IDs and continues the numbering.
    """

    def __init__(self, path: Path, run_id: str):
        self.path = Path(path)
        self.run_id = run_id
        self._lock = threading.Lock()
        self._ids: set[str] = set()
        self._next = 1
        if self.path.exists():
            for record in read_calls(self.path):
                if record.run_id != run_id:
                    raise CallRecordError(f"{self.path} belongs to run {record.run_id}")
                self._ids.add(record.call_id)
            self._next = len(self._ids) + 1

    def new_call_id(self) -> str:
        with self._lock:
            while (call_id := f"c{self._next:07d}") in self._ids:
                self._next += 1
            self._next += 1
            return call_id

    def write(self, record: CallRecord) -> None:
        if record.run_id != self.run_id:
            raise CallRecordError(f"record of run {record.run_id} written to {self.run_id}")
        with self._lock:
            if record.call_id in self._ids:
                raise CallRecordError(f"duplicate call_id {record.call_id}")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.to_json() + "\n")
            self._ids.add(record.call_id)


def read_calls(path: Path) -> list[CallRecord]:
    """Read and validate calls.jsonl; fails on the first invalid line, naming it."""
    records, seen = [], set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        try:
            record = CallRecord.from_dict(json.loads(line))
        except (json.JSONDecodeError, CallRecordError, TypeError) as exc:
            raise CallRecordError(f"{path}:{number}: {exc}") from exc
        if record.call_id in seen:
            raise CallRecordError(f"{path}:{number}: duplicate call_id {record.call_id}")
        seen.add(record.call_id)
        records.append(record)
    return records
