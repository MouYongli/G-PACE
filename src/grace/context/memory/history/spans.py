"""Span anchors and unified evidence IDs (plan 5.2, "Span anchors"; contracts.md, "Claim graph").

An evidence ID names either a whole message, by its `message_id` (the contract's evidence ID), or a
character range of it, as `<message_id>#char=<start>,<end>` (the RFC 5147 fragment for plain
text). Ranges are [start, end) over the message text as a Python string (code points). Scoring at
message granularity maps any evidence ID back to its `message_id` with `message_of`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from grace.context.api import Message

_FRAGMENT = re.compile(r"^(?P<message>.+)#char=(?P<start>0|[1-9]\d*),(?P<end>0|[1-9]\d*)$",
                       re.DOTALL)


class SpanError(ValueError):
    """A span anchor does not fit its message, or an evidence ID is malformed."""


@dataclass(frozen=True, order=True)
class SpanAnchor:
    """Characters [start, end) of message `message_id`; no bounds anchor the whole message."""

    message_id: str
    start: int | None = None
    end: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.message_id, str) or not self.message_id:
            raise SpanError("message_id must be a non-empty string")
        if (self.start is None) != (self.end is None):
            raise SpanError("start and end are both set or both None")
        if self.start is not None:
            for value in (self.start, self.end):
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise SpanError(f"span bounds must be integers >= 0, got {value!r}")
            if self.start >= self.end:
                raise SpanError(f"span start {self.start} is not before end {self.end}")

    @property
    def evidence_id(self) -> str:
        if self.start is None:
            return self.message_id
        return f"{self.message_id}#char={self.start},{self.end}"

    def text(self, message: Message) -> str:
        """The anchored text; fails if the anchor does not fit `message`."""
        check(self, message)
        return message.text if self.start is None else message.text[self.start:self.end]


def parse_evidence_id(evidence_id: str) -> SpanAnchor:
    """Inverse of `SpanAnchor.evidence_id`. A message ID that itself contains `#char=` followed
    by two integers cannot be told apart from a span; adapters do not produce such IDs."""
    if not isinstance(evidence_id, str) or not evidence_id:
        raise SpanError("evidence ID must be a non-empty string")
    match = _FRAGMENT.match(evidence_id)
    if match is None:
        return SpanAnchor(evidence_id)
    return SpanAnchor(match["message"], int(match["start"]), int(match["end"]))


def message_of(evidence_id: str) -> str:
    """The `message_id` an evidence ID refines."""
    return parse_evidence_id(evidence_id).message_id


def check(anchor: SpanAnchor, message: Message) -> None:
    """Fail unless `anchor` names `message` and lies within its text."""
    if anchor.message_id != message.message_id:
        raise SpanError(f"anchor names {anchor.message_id!r}, not {message.message_id!r}")
    if anchor.start is not None and anchor.end > len(message.text):
        raise SpanError(f"span [{anchor.start}, {anchor.end}) exceeds the text of "
                        f"{message.message_id!r} ({len(message.text)} characters)")


def anchor_quote(message: Message, quote: str, occurrence: int = 0) -> SpanAnchor:
    """Anchor the `occurrence`-th exact occurrence of `quote` in the message text.

    This is how span anchors of a claim patch are checked: the writer quotes, the program
    locates. Fails if the quote does not occur that often.
    """
    if not quote:
        raise SpanError("quote must be non-empty")
    start = -1
    for _ in range(occurrence + 1):
        start = message.text.find(quote, start + 1)
        if start < 0:
            raise SpanError(f"quote {quote!r} occurs fewer than {occurrence + 1} times in "
                            f"{message.message_id!r}")
    return SpanAnchor(message.message_id, start, start + len(quote))
