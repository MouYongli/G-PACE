"""A small local writer of `calls.jsonl` records (contracts.md, "Cost ledger", version 0.1).

Interim: the call record and its writer belong to `llm/records.py` (T004). This module exists so
that T003's harness can write contract-conforming records before T004 lands; it is replaced by
`llm/records.py` then, and the field list below must stay identical to the contract.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# call_type -> ledger category; `external` depends on the trigger (table "Which tokens are
# counted when").
CATEGORY = {"extract": "W", "vocabulary": "W", "render": "W", "summary": "W", "plan": "U",
            "repair": "U", "verify": "U", "answer": "A", "embed": "embedding",
            "judge": "evaluation"}
EXTERNAL = {"write": "W", "read": "U"}
TRIGGERS = ("write", "read", "evaluation")
STATUSES = ("ok", "failed", "invalid_output")


def category(call_type: str, trigger: str) -> str:
    if trigger not in TRIGGERS:
        raise ValueError(f"trigger {trigger!r} not in {TRIGGERS}")
    if call_type == "external":
        return EXTERNAL[trigger]
    if call_type not in CATEGORY:
        raise ValueError(f"unknown call type {call_type!r}")
    if (call_type == "judge") != (trigger == "evaluation"):
        raise ValueError(f"call type {call_type!r} cannot have trigger {trigger!r}")
    return CATEGORY[call_type]


@dataclass(frozen=True)
class CallRecord:
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

    def __post_init__(self) -> None:
        if self.category != category(self.call_type, self.trigger):
            raise ValueError(f"{self.call_id}: category {self.category!r} does not match "
                             f"{self.call_type}/{self.trigger}")
        if self.trigger == "write" and self.read_id is not None:
            raise ValueError(f"{self.call_id}: a write-triggered call has no read_id")
        if self.status not in STATUSES or self.attempt < 1:
            raise ValueError(f"{self.call_id}: bad status or attempt")
        if not 0 <= self.cached_input_tokens <= self.input_tokens or self.output_tokens < 0:
            raise ValueError(f"{self.call_id}: bad token counts")


class CallLedger:
    """Appends call records to `calls.jsonl` and hands out run-unique call IDs."""

    def __init__(self, path: Path, run_id: str):
        self.path, self.run_id = Path(path), run_id
        self._next = 0
        self.records: list[CallRecord] = []

    def new_id(self) -> str:
        self._next += 1
        return f"c{self._next:06d}"

    def append(self, record: CallRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        self.records.append(record)
