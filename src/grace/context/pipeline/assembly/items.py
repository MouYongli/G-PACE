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

from dataclasses import dataclass, field

from grace.context import api
from grace.context.memory.history.log import MessageLog
from grace.context.memory.history.spans import message_of

SECTIONS = ("recent", "state", "evidence")
STATE_KINDS = frozenset({"view", "claim"})


def _unique(items) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


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
        if self.retired is not None and self.retired <= self.version:
            raise ValueError(f"item {self.item_id}: retired at {self.retired} but known only "
                             f"from {self.version}")
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


def answer_items(result, *, prefix: str, variables: dict[str, str] | None = None,
                 version_of=None, rank_start: int = 1) -> list[Item]:
    """Items from a claim-graph query result, one per answer (duck-typed, see below).

    `result` has `variables` (answer column names) and `answers`, each with `values` and
    `evidence` (unified evidence IDs), as `pipeline/query/result.QueryResult` provides; this
    module does not import `query/`. The text states the answer row ("?train = TR123; ...").
    An answer binds every answer column, so it covers the demand variables named like its
    columns; `variables` may map a column name to a demand variable name when they differ.
    `version_of` maps a message ID to its version, to stamp the item's knowledge version.
    """
    out: list[Item] = []
    names = tuple(getattr(result, "variables", ()))
    for i, answer in enumerate(getattr(result, "answers", ())):
        pairs = [f"{n} = {_display(v)}" for n, v in zip(names, answer.values, strict=False)]
        evidence = _unique(answer.evidence)
        covers = frozenset((variables or {}).get(n, n) for n in names)
        version = 0
        if version_of is not None:
            known = [version_of(message_of(e)) for e in evidence]
            version = max((v for v in known if v is not None), default=0)
        out.append(Item(f"{prefix}{i + 1}", "claim", "; ".join(pairs) or "(match)", evidence,
                        (), version=version, rank=rank_start + i, covers=covers))
    return out
