"""History, question and gold records of the benchmark adapters (docs/research/contracts.md).

The visible record types (History header, Message, Read task) are the interface types of
`context/api.py`; they are re-exported here so that adapters and the harness name one set of
types. Gold data is scoring side only and lives only in this module (structure.md, "Where types
live"); it never reaches a system except through `eval/engines/oracles/`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from grace.context.api import HistoryInfo, Message, ReadTask, RecordError, Segment

History = HistoryInfo  # contracts.md calls the visible header of a history a "History" record

_GOLD_REQUIRED = ("benchmark", "split", "history_id", "task_id", "annotation", "reference",
                  "evidence_ids", "evidence_segment_ids", "evidence_unresolved", "labels")


def _id_list(name: str, value: Any, nullable: bool) -> tuple[str, ...] | None:
    if value is None and nullable:
        return None
    if not isinstance(value, list | tuple) or not all(isinstance(v, str) and v for v in value):
        raise RecordError(f"Gold.{name}: expected a list of non-empty strings")
    return tuple(value)


@dataclass(frozen=True)
class Gold:
    """The reference of one task under one annotation (contracts.md, "Gold"); key
    `(annotation, task_id)`."""

    benchmark: str
    split: str
    history_id: str
    task_id: str
    annotation: str
    reference: Any
    evidence_ids: tuple[str, ...] | None
    evidence_segment_ids: tuple[str, ...] | None
    evidence_unresolved: tuple[str, ...]
    labels: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("benchmark", "split", "history_id", "task_id", "annotation"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise RecordError(f"Gold.{name}: expected a non-empty string")
        object.__setattr__(self, "evidence_ids",
                           _id_list("evidence_ids", self.evidence_ids, True))
        object.__setattr__(self, "evidence_segment_ids",
                           _id_list("evidence_segment_ids", self.evidence_segment_ids, True))
        object.__setattr__(self, "evidence_unresolved",
                           _id_list("evidence_unresolved", self.evidence_unresolved, False))
        if not isinstance(self.labels, Mapping):
            raise RecordError("Gold.labels: expected an object")
        if not isinstance(self.metadata, Mapping):
            raise RecordError("Gold.metadata: expected an object")

    @property
    def key(self) -> tuple[str, str]:
        return self.annotation, self.task_id

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Gold:
        if not isinstance(record, Mapping):
            raise RecordError("Gold: expected an object")
        missing = [k for k in _GOLD_REQUIRED if k not in record]
        unknown = sorted(record.keys() - set(_GOLD_REQUIRED) - {"metadata"})
        if missing or unknown:
            raise RecordError(f"Gold: missing fields {missing}, unknown fields {unknown}")
        return cls(**record)

    def to_record(self) -> dict[str, Any]:
        record = {
            "benchmark": self.benchmark, "split": self.split, "history_id": self.history_id,
            "task_id": self.task_id, "annotation": self.annotation, "reference": self.reference,
            "evidence_ids": None if self.evidence_ids is None else list(self.evidence_ids),
            "evidence_segment_ids": (None if self.evidence_segment_ids is None
                                     else list(self.evidence_segment_ids)),
            "evidence_unresolved": list(self.evidence_unresolved),
            "labels": dict(self.labels),
        }
        if self.metadata:
            record["metadata"] = dict(self.metadata)
        return record


__all__ = ["Gold", "History", "HistoryInfo", "Message", "ReadTask", "RecordError", "Segment"]
