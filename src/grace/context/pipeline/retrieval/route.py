"""Rule-based routing from structural signals of the request (plan 5.5, "Routing").

The plan: identifiers favour BM25, paraphrase favours dense retrieval; relational joins, timing,
counts and corrections favour the graph; with low confidence all channels are used. The router
reads only the request text and whether the planner compiled a graph query; it knows no
benchmark.

Signals (each a family of regular expressions, `SIGNALS`):

- `identifier` -> bm25: a token mixing letters and digits ("B2", "AX-1043"), a `#` reference, a
  quoted phrase, an e-mail address or URL.
- `time`, `count`, `correction`, `relation` -> graph: temporal cues ("when", "before", "since",
  "still", "currently", dates), counting ("how many", "number of"), revisions ("changed",
  "instead", "no longer", "originally"), and relational joins ("who confirmed", "which ... that").
- `paraphrase` -> dense: the request has no identifier signal (its words must be matched by
  meaning rather than by form).

`confidence` is the number of structural signal families that fired (all but `paraphrase`). Below
`min_confidence` the route is every available channel (`reason: low_confidence`). Otherwise it is
the channels the fired signals favour, restricted to the available ones; the graph is available
only when a graph query compiled. If that leaves no channel, or only the graph (whose candidates
are exact but few), the route is widened to every available channel.

Thresholds and the signal-to-channel map are set on development data only (T025 task file).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from grace.context.pipeline.retrieval.candidates import CHANNELS

_MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|"
           "december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
SIGNALS: dict[str, tuple[re.Pattern[str], ...]] = {
    "identifier": (
        re.compile(r"\b(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b"),
        re.compile(r"#\w+"),
        re.compile(r"[\"“][^\"”]{2,}[\"”]"),
        re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b|https?://\S+"),
    ),
    "time": (
        re.compile(r"\b(when|before|after|since|until|till|during|while|ago|yet|still|"
                   r"currently|current|now|today|yesterday|tomorrow|recently|latest|last|"
                   r"first|earlier|later|previous|next|date|time|year|month|week|day|"
                   r"weekend|morning|evening|night)\b", re.IGNORECASE),
        re.compile(rf"\b({_MONTHS})\b", re.IGNORECASE),
        re.compile(r"\b(19|20)\d\d\b"),
    ),
    "count": (
        re.compile(r"\b(how many|how much|how often|number of|count|total|times)\b",
                   re.IGNORECASE),
    ),
    "correction": (
        re.compile(r"\b(change[sd]?|changing|instead|switch(ed)?|updated?|correct(ed|ion)?|"
                   r"no longer|any ?more|originally|previously|initially|used to|cancel(l?ed)?|"
                   r"replace[sd]?|revis(ed|e)|moved?)\b", re.IGNORECASE),
    ),
    "relation": (
        re.compile(r"\b(who|whom|whose)\s+(confirmed|offered|accepted|rejected|said|told|"
                   r"suggested|recommended|booked|chose|picked)\b", re.IGNORECASE),
        re.compile(r"\b(which|what)\b[^?]*\b(that|whose|where)\b", re.IGNORECASE),
        re.compile(r"\b(both|between|relationship|related|together)\b", re.IGNORECASE),
    ),
}
FAVOURS = {"identifier": "bm25", "time": "graph", "count": "graph", "correction": "graph",
           "relation": "graph", "paraphrase": "dense"}
STRUCTURAL = ("identifier", "time", "count", "correction", "relation")
MODES = ("rules", "all")


def signals(request: str) -> tuple[str, ...]:
    """The signal families that fire on `request`, in `SIGNALS` order, then `paraphrase`."""
    fired = [name for name, patterns in SIGNALS.items()
             if any(p.search(request) for p in patterns)]
    if "identifier" not in fired:
        fired.append("paraphrase")
    return tuple(fired)


@dataclass(frozen=True)
class Route:
    channels: tuple[str, ...]  # in CHANNELS order
    signals: tuple[str, ...]
    confidence: int
    reason: str  # all_channels | low_confidence | rules | widened

    def to_record(self) -> dict:
        return {"channels": list(self.channels), "signals": list(self.signals),
                "confidence": self.confidence, "reason": self.reason}


def _ordered(channels) -> tuple[str, ...]:
    wanted = set(channels)
    return tuple(c for c in CHANNELS if c in wanted)


def route(request: str, available: Sequence[str], *, mode: str = "rules",
          min_confidence: int = 1) -> Route:
    """Channels for one request among the `available` ones (enabled, graph only if compiled)."""
    if mode not in MODES:
        raise ValueError(f"unknown routing mode {mode!r}; known: {MODES}")
    if unknown := set(available) - set(CHANNELS):
        raise ValueError(f"unknown channels {sorted(unknown)}")
    available = _ordered(available)
    fired = signals(request)
    confidence = sum(1 for s in fired if s in STRUCTURAL)
    if mode == "all":
        return Route(available, fired, confidence, "all_channels")
    if confidence < min_confidence:
        return Route(available, fired, confidence, "low_confidence")
    chosen = _ordered(FAVOURS[s] for s in fired if FAVOURS[s] in available)
    if not chosen or chosen == ("graph",):
        return Route(available, fired, confidence, "widened")
    return Route(chosen, fired, confidence, "rules")
