"""Assembly candidates: one `Item` per piece of memory that may enter a working context (plan 5.5).

The engine (`context/engine.py`) turns everything a read produced into items before it calls the
assembler: fused retrieval candidates (messages or chunks), query answers of the claim graph,
view sentences and summaries. The assembler never looks at where an item came from; it reads only
the fields below. This keeps `assembly/` free of `query/`, `retrieval/` and `views/` (structure.md:
the packages under `pipeline/` do not call each other, and no package under `pipeline/` imports
`views/`).

Fields that the filter reads (plan 5.5, step 2):

- `version`: the knowledge version at which the item became known (the latest version of its
  sources; for a claim, the later of the claim's and the attribution's stamps).
- `retired`: the version at which the item was superseded, or None while it is current.
- `valid`: the valid-time interval `(start, end)` the item states, as ISO dates (either end may be
  None for an open end), or None when the item states no valid time.
- `scope`: the scope the item belongs to (for example a speaker, a sub-dialogue or a domain), or
  None when it holds everywhere.
- `attribution`: who asserted or confirmed the content (speakers or roles), empty when unknown.

Fields that selection reads (steps 3 and 4):

- `rank`: the fused retrieval rank (1 = best); None for items that come unranked.
- `covers`: the demand variables the item binds by program (a query answer binds its answer
  columns); text items are additionally checked lexically (`demand.supports`).
- `group`: items with the same group form one unit and are selected together or not at all
  (both ends of a two-hop path).
- `expands_to`: for a summary, the message IDs of the raw text it summarises (step 4).
- `section`: the layout section (`recent`, `state`, `evidence`); by default `state` for views and
  claims and `evidence` for everything else.

`citations` are the message IDs printed in square brackets in front of the item; every evidence ID
of the item is mapped to its message (a span `m#char=a,b` cites `m`), because the answering LLM
cites message IDs.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from grace.context import api
from grace.context.memory.history.log import MessageLog
from grace.context.memory.history.spans import message_of

SECTIONS = ("recent", "state", "evidence")
_ISO_EXTENDED = re.compile(
    r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?")
STATE_KINDS = frozenset({"view", "claim"})


def _unique(items) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def check_iso(value: str | None, where: str) -> None:
    """Fail unless `value` is None or an ISO 8601 extended date or date-time (`2023-05-08`,
    `2023-05-08T10:15`, `2023-05-08T10:15:00.5+02:00`, `...Z`). Basic (`20230508`), week
    (`2023-W19`) and ordinal forms are rejected, because valid times are compared as strings."""
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{where}: expected an ISO date string, got {type(value).__name__}")
    if not _ISO_EXTENDED.fullmatch(value):
        raise ValueError(f"{where}: {value!r} is not an ISO 8601 extended date (YYYY-MM-DD...)")
    try:
        _dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{where}: {value!r} is not an ISO 8601 date") from exc


@dataclass(frozen=True)
class Item:
    """One candidate piece of memory for a read; `item_id` is its stable citation key."""

    item_id: str
    kind: str
    text: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...] = ()
    version: int = 0
    retired: int | None = None
    valid: tuple[str | None, str | None] | None = None
    scope: str | None = None
    attribution: tuple[str, ...] = ()
    rank: int | None = None
    covers: frozenset[str] = field(default_factory=frozenset)
    group: str | None = None
    section: str | None = None
    expands_to: tuple[str, ...] = ()
    timestamp: str | None = None

    def __post_init__(self) -> None:
        if not self.item_id:
            raise ValueError("item_id must be non-empty")
        if self.kind not in api.FRAGMENT_KINDS:
            raise ValueError(f"Item.kind: {self.kind!r} not in {sorted(api.FRAGMENT_KINDS)}")
        if not self.text:
            raise ValueError(f"item {self.item_id}: empty text")
        if self.section is not None and self.section not in SECTIONS:
            raise ValueError(f"item {self.item_id}: section {self.section!r} not in {SECTIONS}")
        if self.rank is not None and self.rank < 1:
            raise ValueError(f"item {self.item_id}: rank starts at 1")
        if self.version < 0 or (self.retired is not None and self.retired < 1):
            raise ValueError(f"item {self.item_id}: version must be >= 0 and retired >= 1")
        if self.valid is not None:
            if len(self.valid) != 2:
                raise ValueError(f"item {self.item_id}: valid must be a (start, end) pair")
            for value in self.valid:
                check_iso(value, f"item {self.item_id}: valid")
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        object.__setattr__(self, "attribution", tuple(self.attribution))
        object.__setattr__(self, "covers", frozenset(self.covers))
        object.__setattr__(self, "expands_to", tuple(self.expands_to))

    @property
    def citations(self) -> tuple[str, ...]:
        """Message IDs cited in front of the item, in first-seen order."""
        return _unique(message_of(e) for e in (*self.source_ids, *self.evidence_ids))

    @property
    def layout_section(self) -> str:
        if self.section is not None:
            return self.section
        return "state" if self.kind in STATE_KINDS else "evidence"


def message_time(message: api.Message, history: api.HistoryInfo | None = None) -> str | None:
    """The message's own time, else the time of its segment (contracts.md, "Message"); the same
    rule as the baselines' rendering, so every system shows the same dates."""
    if message.timestamp or history is None:
        return message.timestamp
    segment = history.segment(message.segment_id)
    return segment.timestamp if segment else None


def message_item(message: api.Message, *, rank: int | None = None, section: str | None = None,
                 covers=frozenset(), kind: str = "message",
                 history: api.HistoryInfo | None = None) -> Item:
    """The raw text of one message as an item; its `message_id` is the citation and the source.
    With `history`, a message without its own time shows the time of its segment."""
    speaker = message.speaker or message.role
    return Item(message.message_id, kind, f"{speaker}: {message.text}", (message.message_id,),
                (message.message_id,), version=message.version, rank=rank, section=section,
                covers=frozenset(covers), attribution=(speaker,),
                timestamp=message_time(message, history))


def history_items(log: MessageLog, version: int,
                  history: api.HistoryInfo | None = None) -> list[Item]:
    """Every message visible at `version`, in version order (the full-history read)."""
    return [message_item(m, history=history) for m in log.messages(version)]


def recent_items(log: MessageLog, version: int, k: int,
                 history: api.HistoryInfo | None = None) -> list[Item]:
    """The last `k` messages visible at `version`, for the "recent raw text" section."""
    if k <= 0:
        return []
    return [message_item(m, section="recent", history=history)
            for m in log.messages(version)[-k:]]


def _display(value) -> str:
    for attr in ("lexical", "id", "name"):
        text = getattr(value, attr, None)
        if isinstance(text, str):
            return text
    return str(value)


def answer_items(result, *, prefix: str, version_of: Callable[[str], int | None],
                 stamp_of: Callable[[str], int | None],
                 retired_of: Callable[[str], int | None],
                 variables: dict[str, str] | None = None, rank_start: int = 1) -> list[Item]:
    """Items from a claim-graph query result, one per answer (duck-typed, see below).

    `result` has `variables` (answer column names) and `answers`, each with `values`,
    `witnesses` (each with `claims` and `attributions` IDs) and `evidence` (unified evidence
    IDs), as `pipeline/query/result.QueryResult` provides; this module does not import `query/`.
    The text states the answer row ("train = TR123; ..."). An answer binds every answer column,
    so it covers the demand variables named like its columns; `variables` may map a column name
    to a demand variable name when they differ.

    The engine passes the stamps from the message log and the claim store:

    - `version_of(message_id)`: the version of an evidence message;
    - `stamp_of(entry_id)`: the knowledge version of a witness claim or attribution;
    - `retired_of(claim_id)`: the version from which a claim is superseded, or None.

    The item's knowledge version is the maximum of every witness stamp and every evidence
    message's version. An answer is retired once each of its witnesses contains a superseded
    claim (the latest such witness retirement); one witness without a superseded claim keeps it
    current. An unknown evidence message or entry (a lookup returning None) is an error, since a
    missing stamp would let the item pass the version filter.
    """
    out: list[Item] = []
    names = tuple(getattr(result, "variables", ()))
    for i, answer in enumerate(getattr(result, "answers", ())):
        pairs = [f"{n} = {_display(v)}" for n, v in zip(names, answer.values, strict=False)]
        evidence = _unique(answer.evidence)
        covers = frozenset((variables or {}).get(n, n) for n in names)
        stamps = []
        for e in evidence:
            v = version_of(message_of(e))
            if v is None:
                raise ValueError(f"answer {i + 1} of {prefix}: unknown evidence message {e!r}")
            stamps.append(v)
        witness_retired: list[int | None] = []
        for w in getattr(answer, "witnesses", ()):
            for entry in (*w.claims, *w.attributions):
                v = stamp_of(entry)
                if v is None:
                    raise ValueError(f"answer {i + 1} of {prefix}: unknown entry {entry!r}")
                stamps.append(v)
            ends = [r for r in (retired_of(c) for c in w.claims) if r is not None]
            witness_retired.append(min(ends) if ends else None)
        retired = (max(witness_retired) if witness_retired and None not in witness_retired
                   else None)
        out.append(Item(f"{prefix}{i + 1}", "claim", "; ".join(pairs) or "(match)", evidence,
                        (), version=max(stamps, default=0), retired=retired,
                        rank=rank_start + i, covers=covers))
    return out
