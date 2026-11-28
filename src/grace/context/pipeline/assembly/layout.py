"""Serialisation into the fixed working-context layout (plan 5.5, step 5).

The plan's layout is: task, recent raw text, verified state, evidence spans, open items, output
contract. The task (the request) and the output contract are parts of the shared answer prompt
(`resources/prompts/answer/`), identical for every system and outside the memory budget
(`configs/common/budgets.yaml`), so the working context text carries the four memory sections in
this fixed order, each under its heading and omitted when empty:

    Recent messages:
    [D9:4] (2023-05-08) Melanie: ...
    Verified state:
    [D1:3, D2:5] train = TR123; arrival = 10:15
    Evidence:
    [D1:3] (2023-05-07) Caroline: ...
    Open items (not found in memory):
    - the arrival time of the accepted train

Every item line starts with its stable citation, the message IDs in square brackets, as the
answer prompt states. Within a section, items with a timestamp or version are in chronological
order (version, then rank), so that temporal reasoning sees the order of the history.

`EMPTY` is the text of a context with nothing in it; it equals the baselines' marker, so the
answering LLM sees the same text for an empty memory whichever system built it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from grace.context import api
from grace.context.memory.history.spans import message_of
from grace.context.pipeline.assembly.demand import Variable
from grace.context.pipeline.assembly.items import SECTIONS, Item

EMPTY = "[no memory]"
HEADINGS = {"recent": "Recent messages:", "state": "Verified state:", "evidence": "Evidence:",
            "open": "Open items (not found in memory):"}
SEPARATOR = "\n"


def line(item: Item) -> str:
    """The serialised line of one item: citation, optional time, text."""
    cite = "[" + ", ".join(item.citations) + "]" if item.citations else f"[{item.item_id}]"
    stamp = f" ({item.timestamp})" if item.timestamp else ""
    return f"{cite}{stamp} {item.text}"


def item_cost(item: Item, count: Callable[[str], int]) -> int:
    """Token estimate of one item inside a context: its line plus the line break."""
    return count(line(item) + SEPARATOR)


def open_line(variable: Variable) -> str:
    return f"- {variable.describes}"


def _ordered(items: Sequence[Item]) -> list[Item]:
    def key(pair):
        i, item = pair
        return (item.version, item.rank if item.rank is not None else float("inf"), i)
    return [item for _, item in sorted(enumerate(items), key=key)]


@dataclass(frozen=True)
class Serialised:
    text: str
    items: tuple[Item, ...]  # in display order
    lines: tuple[str, ...]   # the line of each item in `items`


def serialise(items: Sequence[Item], open_variables: Sequence[Variable] = ()) -> Serialised:
    """The context text of the selected `items` and the still open variables."""
    parts: list[str] = []
    shown: list[Item] = []
    lines: list[str] = []
    for section in SECTIONS:
        members = _ordered([i for i in items if i.layout_section == section])
        if not members:
            continue
        parts.append(HEADINGS[section])
        for item in members:
            text = line(item)
            parts.append(text)
            shown.append(item)
            lines.append(text)
    if open_variables:
        parts.append(HEADINGS["open"])
        parts.extend(open_line(v) for v in open_variables)
    return Serialised(SEPARATOR.join(parts) or EMPTY, tuple(shown), tuple(lines))


def fragments(serialised: Serialised, count: Callable[[str], int]) -> tuple[api.Fragment, ...]:
    """The `api.Fragment` of every shown item, with its line's own token count."""
    out = []
    for item, text in zip(serialised.items, serialised.lines, strict=True):
        sources = tuple(dict.fromkeys(message_of(s) for s in item.source_ids))
        out.append(api.Fragment(item.item_id, item.kind, text, item.citations, sources,
                                count(text)))
    return tuple(out)


@dataclass(frozen=True)
class TokenLedger:
    """Where the tokens of one working context go; `total` is the count of the whole text.

    `fragments` maps each fragment ID to the tokens of its line counted alone; `layout` is the
    rest (headings, open items, line breaks, and the difference a tokenizer makes when lines are
    joined), so `sum(fragments) + layout == total` holds exactly.
    """

    counter: str
    budget: int | None
    total: int
    fragments: dict[str, int]
    layout: int

    def to_record(self) -> dict:
        return {"counter": self.counter, "budget": self.budget, "total": self.total,
                "fragments": dict(self.fragments), "layout": self.layout}


def ledger(text: str, frags: Sequence[api.Fragment], count: Callable[[str], int],
           budget: int | None, counter: str) -> TokenLedger:
    total = count(text)
    per = {f.fragment_id: f.tokens for f in frags}
    return TokenLedger(counter, budget, total, per, total - sum(per.values()))
