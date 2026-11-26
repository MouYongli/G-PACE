"""Retrieval candidates and the unified evidence ID space (plan 5.5, "Fusion").

Every channel returns candidates keyed by a *unified evidence ID* at message granularity: the
`message_id` of the message whose text supports the candidate. Text channels return chunks, and a
chunk holds the text of one or more messages (`Chunk.evidence_ids`); the graph channel returns the
evidence of query answers, which may be a span of a message (`<message_id>#char=<start>,<end>`,
`memory/history/spans.py`). Both are mapped to the `message_id`, so the same message found by two
channels is one candidate for fusion; the finer IDs a channel produced are kept in `spans`.

`message_id_of` repeats the parsing rule of `memory/history/spans.parse_evidence_id` because this
package may not import `memory/history/` (structure.md, import rules); a test checks that both
agree.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from grace.context import api

CHANNELS = ("bm25", "dense", "graph")
_SPAN = re.compile(r"^(?P<message>.+)#char=(?P<start>\d+),(?P<end>\d+)$")


def message_id_of(evidence_id: str) -> str:
    """The `message_id` a unified evidence ID refines (the ID itself for a whole message)."""
    if not isinstance(evidence_id, str) or not evidence_id:
        raise ValueError("evidence ID must be a non-empty string")
    match = _SPAN.match(evidence_id)
    return match["message"] if match else evidence_id


@dataclass(frozen=True)
class RetrievalCandidate:
    """One candidate of one channel: unified evidence ID, 1-based rank, channel score."""

    evidence_id: str
    channel: str
    rank: int
    score: float
    spans: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.channel not in CHANNELS:
            raise ValueError(f"unknown channel {self.channel!r}")
        if self.rank < 1:
            raise ValueError("rank starts at 1")

    def to_api(self) -> api.Candidate:
        return api.Candidate(self.evidence_id, self.channel, float(self.score))


@dataclass(frozen=True)
class FusedCandidate:
    """A candidate after fusion: its fused score and the rank it had in every channel."""

    evidence_id: str
    score: float
    ranks: tuple[tuple[str, int], ...]  # (channel, rank) for every channel that returned it
    spans: tuple[str, ...] = ()

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(channel for channel, _ in self.ranks)

    def to_api(self, label: str) -> api.Candidate:
        return api.Candidate(self.evidence_id, label, float(self.score))


def ranked(channel: str, hits: Iterable[tuple[Iterable[str], float]],
           k: int | None = None) -> list[RetrievalCandidate]:
    """Candidates of one channel from ranked hits `(evidence IDs, score)`, best first.

    The evidence IDs of a hit are mapped to message IDs; a message already returned by an earlier
    (better) hit is skipped, so ranks are dense over distinct messages. At most `k` candidates.
    """
    out: list[RetrievalCandidate] = []
    index: dict[str, int] = {}
    spans: dict[str, list[str]] = {}
    for evidence_ids, score in hits:
        for evidence_id in evidence_ids:
            message = message_id_of(evidence_id)
            if evidence_id != message:
                spans.setdefault(message, [])
                if evidence_id not in spans[message]:
                    spans[message].append(evidence_id)
            if message in index:
                continue
            if k is not None and len(out) >= k:
                continue
            index[message] = len(out)
            out.append(RetrievalCandidate(message, channel, len(out) + 1, float(score)))
    return [RetrievalCandidate(c.evidence_id, c.channel, c.rank, c.score,
                               tuple(spans.get(c.evidence_id, ()))) for c in out]
