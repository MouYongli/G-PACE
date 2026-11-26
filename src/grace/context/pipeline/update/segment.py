"""Extraction granularity: which messages one writer call extracts (plan 8.4; ablation G).

Three granularities (T013 recommends segments of 8 messages as the starting point):

- `message`: every message is its own unit;
- `segment`: runs of at most `size` consecutive messages inside one session (a session is a
  benchmark segment, `Message.segment_id`); a unit never crosses a session boundary, and the last
  unit of a session may be shorter;
- `session`: all messages of one session.

Units are cut from the *pending* messages: those in the log after the last version the writer has
committed. A unit is complete when it is full (`segment`), when its session is closed, or at the
end of the history. A session is closed when the history header says it ends there
(`Segment.last_version`), when a later message of another session has arrived, or when the last
message of the history (`HistoryInfo.n_messages`) has arrived. When a read falls inside an
incomplete unit, the engine flushes the part that has arrived (`units(..., flush=True)`); the rest
of that unit then starts a new unit.

Knowledge versions follow the evidence message, not the unit: the updater commits one change set
per message version of the unit (contracts.md, "Claim graph": versions may have gaps, every entry
carries its change set's version).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from grace.context.api import HistoryInfo, Message

UNITS = ("message", "segment", "session")


@dataclass(frozen=True)
class Granularity:
    unit: str = "segment"
    size: int | None = 8

    def __post_init__(self) -> None:
        if self.unit not in UNITS:
            raise ValueError(f"granularity unit must be one of {UNITS}, got {self.unit!r}")
        if self.unit == "segment":
            if not isinstance(self.size, int) or isinstance(self.size, bool) or self.size < 1:
                raise ValueError("a segment granularity needs an integer size >= 1")
        elif self.size is not None:
            raise ValueError(f"granularity {self.unit} takes no size")

    @property
    def name(self) -> str:
        return f"segment-{self.size}" if self.unit == "segment" else self.unit

    @classmethod
    def from_record(cls, record: Mapping[str, Any] | str) -> Granularity:
        if isinstance(record, str):
            if record.startswith("segment-"):
                return cls("segment", int(record.split("-", 1)[1]))
            return cls(record, None)
        if not isinstance(record, Mapping) or not set(record) <= {"unit", "size"}:
            raise ValueError(f"granularity must be {{unit, size}}, got {record!r}")
        unit = record.get("unit", "segment")
        return cls(unit, record.get("size", 8 if unit == "segment" else None))


@dataclass(frozen=True)
class Unit:
    """Messages extracted by one writer call, in version order."""

    messages: tuple[Message, ...]
    partial: bool = False   # flushed before it was complete (a read fell inside it)

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("a unit has at least one message")
        versions = [m.version for m in self.messages]
        if versions != list(range(versions[0], versions[0] + len(versions))):
            raise ValueError(f"unit versions are not consecutive: {versions}")

    @property
    def first_version(self) -> int:
        return self.messages[0].version

    @property
    def last_version(self) -> int:
        return self.messages[-1].version

    def __len__(self) -> int:
        return len(self.messages)

    def split(self) -> tuple[Unit, Unit]:
        half = (len(self.messages) + 1) // 2
        return Unit(self.messages[:half], self.partial), Unit(self.messages[half:], self.partial)


def _session(message: Message) -> str | None:
    return message.segment_id


class Segmenter:
    """Cuts the pending messages of one history into extraction units."""

    def __init__(self, granularity: Granularity, history: HistoryInfo | None = None):
        self.granularity = granularity
        self.n_messages = history.n_messages if history is not None else None
        self._last = ({s.segment_id: s.last_version for s in history.segments}
                      if history is not None else {})

    def _closed(self, session: Sequence[Message], following: Message | None) -> bool:
        last = session[-1]
        if following is not None:
            return True
        if self.n_messages is not None and last.version >= self.n_messages:
            return True
        end = self._last.get(_session(last))
        return end is not None and last.version >= end

    def units(self, pending: Sequence[Message], *, flush: bool = False) -> list[Unit]:
        """Complete units at the front of `pending` (consecutive versions, oldest first); with
        `flush`, every pending message, the incomplete tail as a partial unit."""
        sessions: list[list[Message]] = []
        for m in pending:
            if sessions and _session(sessions[-1][-1]) == _session(m):
                sessions[-1].append(m)
            else:
                sessions.append([m])
        out: list[Unit] = []
        for i, session in enumerate(sessions):
            following = sessions[i + 1][0] if i + 1 < len(sessions) else None
            closed = self._closed(session, following)
            if self.granularity.unit == "message":
                chunks = [[m] for m in session]
            elif self.granularity.unit == "session":
                chunks = [session]
            else:
                size = self.granularity.size
                chunks = [session[j:j + size] for j in range(0, len(session), size)]
            for chunk in chunks:
                complete = (closed or self.granularity.unit == "message"
                            or (self.granularity.unit == "segment"
                                and len(chunk) == self.granularity.size))
                if not complete:
                    if flush:
                        out.append(Unit(tuple(chunk), partial=True))
                    return out
                out.append(Unit(tuple(chunk)))
        return out
