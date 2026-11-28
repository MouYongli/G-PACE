"""Selection within a token budget (plan 5.5, step 3) and rank truncation as the contrast.

Items are first grouped into units: an item with a `group` forms one unit with every other item
of that group (both ends of a two-hop path are selected together); every other item is a unit of
its own. A unit's cost is the sum of its items' costs (the tokens of each serialised line plus
its line break, `layout.item_cost`), its coverage is the union of its items' coverage, and its
rank is the best rank of its items.

- `greedy` (main configuration). Repeatedly take the unit that fits and has the highest number of
  newly covered variables per added token; ties go to the better rank, then the cheaper unit.
  When no fitting unit covers a new variable, the remaining budget is filled in rank order with
  units that add a message not yet shown (`fill`; skipped units do not stop the fill).
- `truncate` (comparison mode). Only the fill: units in rank order, skipping a unit that does not
  fit or adds no message not yet shown, and continuing with the next (at most `k` units). This is
  rank truncation under the same conditions as greedy (same candidates, filter, fill rule and
  layout); only the coverage-driven first phase differs (decision of s00-super, 2026-11-28).

A message counts as shown only when its raw text is in the context: a message or retrieved-chunk
item shows the messages it cites, while a claim, view or summary only cites them. So a terse
structured line ("event = picnic [D6:11]") never keeps the raw text of D6:11 out of the fill; a
claim or view whose cited messages are all shown raw adds nothing and is skipped. (Before E013 a
claim's citations counted as shown, which removed the raw evidence behind every selected claim,
dates included; E013 development diagnosis, 2026-11-28.)

Both return the units in the order they were taken, which is the order in which the assembler
drops them again if the exact token count of the serialised context exceeds the budget.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from grace.context.pipeline.assembly.items import Item

MODES = ("greedy", "truncate")
INF = float("inf")
RAW_KINDS = frozenset({"message", "retrieved"})  # item kinds whose text is the raw message text


@dataclass(frozen=True)
class Unit:
    items: tuple[Item, ...]
    covers: frozenset[str]
    tokens: int

    @property
    def rank(self) -> float:
        return min((i.rank for i in self.items if i.rank is not None), default=INF)

    @property
    def sources(self) -> frozenset[str]:
        return frozenset(c for i in self.items for c in i.citations)

    @property
    def shows(self) -> frozenset[str]:
        """Messages whose raw text this unit puts into the context."""
        return frozenset(c for i in self.items if i.kind in RAW_KINDS for c in i.citations)

    @property
    def unit_id(self) -> str:
        return self.items[0].group or self.items[0].item_id


def units_of(items: Iterable[Item], cost: Callable[[Item], int],
             covers: Callable[[Item], frozenset[str]]) -> list[Unit]:
    """Group items into units, in the order of each unit's first item."""
    groups: dict[str, list[Item]] = {}
    order: list[str] = []
    for item in items:
        key = f"g:{item.group}" if item.group is not None else f"i:{item.item_id}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    out = []
    for key in order:
        members = tuple(groups[key])
        out.append(Unit(members, frozenset().union(*(covers(i) for i in members)),
                        sum(cost(i) for i in members)))
    return out


def by_rank(units: Sequence[Unit]) -> list[Unit]:
    """Units in rank order; unranked units keep their given order after the ranked ones."""
    return [u for _, u in sorted(enumerate(units), key=lambda p: (p[1].rank, p[0]))]


def greedy(units: Sequence[Unit], demand: Iterable[str], budget: int, *, fill: bool = True,
           taken: Sequence[Unit] = ()) -> list[Unit]:
    """Greedy selection by new demand coverage per token; `taken` units are already in."""
    need = set(demand)
    chosen = list(taken)
    used = sum(u.tokens for u in chosen)
    covered = set().union(*(u.covers for u in chosen)) if chosen else set()
    rest = [u for u in units if u not in chosen]
    while True:
        best, best_key = None, None
        for u in rest:
            new = len((u.covers & need) - covered)
            if new == 0 or used + u.tokens > budget:
                continue
            key = (-new / max(u.tokens, 1), u.rank, u.tokens)
            if best_key is None or key < best_key:
                best, best_key = u, key
        if best is None:
            break
        chosen.append(best)
        rest.remove(best)
        used += best.tokens
        covered |= best.covers
    if fill:
        chosen = fill_by_rank(rest, budget, taken=chosen)
    return chosen


def fill_by_rank(units: Sequence[Unit], budget: int, *, taken: Sequence[Unit] = (),
                 k: int | None = None) -> list[Unit]:
    """Add units in rank order while they fit, skipping a unit that does not fit or whose
    messages are all shown already as raw text (`Unit.shows`); at most `k` units are added."""
    chosen = list(taken)
    used = sum(u.tokens for u in chosen)
    shown = set().union(*(u.shows for u in chosen)) if chosen else set()
    added = 0
    for u in by_rank([u for u in units if u not in chosen]):
        if k is not None and added >= k:
            break
        if used + u.tokens > budget or (u.sources and u.sources <= shown):
            continue
        chosen.append(u)
        used += u.tokens
        shown |= u.shows
        added += 1
    return chosen


def truncate(units: Sequence[Unit], budget: int, *, k: int | None = None,
             taken: Sequence[Unit] = ()) -> list[Unit]:
    """Rank truncation: the fill rule alone, in rank order (at most `k` units)."""
    return fill_by_rank(units, budget, taken=taken, k=k)
