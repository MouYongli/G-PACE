"""Filter candidates by knowledge version, valid time, scope and attribution (plan 5.5, step 2).

`Constraints` come from the read: its version, and from the plan the valid-time window, the
scopes and the attribution the question asks for ("who confirmed it" restricts attribution;
"which train was accepted on Monday" restricts valid time). Each check drops an item only when the
item states the property and it contradicts the constraint; an item that states no valid time,
scope or attribution is kept, because absence is not contradiction.

Drop reasons, in the order they are checked:

- `version`: the item became known after the read version (`item.version > version`). Reads are
  bound to their version (structure.md); an engine should never hand such an item in, and the
  check makes that a guarantee.
- `retired`: the item was superseded at or before the read version and `current_only` is set.
  Questions about an earlier state set `current_only=False` (or pass a valid-time window).
- `valid`: the item's valid-time interval does not overlap the read's window.
- `scope`: the item's scope is not among the read's scopes.
- `attribution`: none of the item's attributions is among the read's.

A duplicate `item_id` keeps the first occurrence with the best rank; later ones are dropped with
reason `duplicate`. The filter applies to two-hop groups as a whole: when any member of a group
is dropped, the remaining members are dropped with reason `group` (a path with one end missing
is not evidence for the hop). Valid-time values must be ISO 8601 dates or date-times; anything
else fails when the item or the constraints are built.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from grace.context.pipeline.assembly.items import Item, check_iso

REASONS = ("version", "retired", "valid", "scope", "attribution", "duplicate", "group")


@dataclass(frozen=True)
class Constraints:
    """What the read admits. `valid` is a window `(start, end)` of ISO dates, ends may be None."""

    version: int
    valid: tuple[str | None, str | None] | None = None
    scopes: frozenset[str] | None = None
    attribution: frozenset[str] | None = None
    current_only: bool = True

    def __post_init__(self) -> None:
        if self.valid is not None:
            if len(self.valid) != 2:
                raise ValueError("Constraints.valid must be a (start, end) pair")
            for value in self.valid:
                check_iso(value, "Constraints.valid")

    def to_record(self) -> dict:
        return {"version": self.version, "valid": list(self.valid) if self.valid else None,
                "scopes": sorted(self.scopes) if self.scopes is not None else None,
                "attribution": (sorted(self.attribution) if self.attribution is not None
                                else None),
                "current_only": self.current_only}


def _day(value: str | None) -> str | None:
    return value[:10] if value else None


def overlaps(a: tuple[str | None, str | None], b: tuple[str | None, str | None]) -> bool:
    """Whether two closed intervals of ISO dates overlap (None is an open end); day precision."""
    a0, a1 = _day(a[0]), _day(a[1])
    b0, b1 = _day(b[0]), _day(b[1])
    return (a1 is None or b0 is None or b0 <= a1) and (b1 is None or a0 is None or a0 <= b1)


def reason(item: Item, c: Constraints) -> str | None:
    """Why `item` is dropped under `c`, or None when it is kept."""
    if item.version > c.version:
        return "version"
    if c.current_only and item.retired is not None and item.retired <= c.version:
        return "retired"
    if c.valid is not None and item.valid is not None and not overlaps(item.valid, c.valid):
        return "valid"
    if c.scopes is not None and item.scope is not None and item.scope not in c.scopes:
        return "scope"
    if c.attribution is not None and item.attribution and \
            not set(item.attribution) & c.attribution:
        return "attribution"
    return None


@dataclass(frozen=True)
class Filtered:
    kept: tuple[Item, ...]
    dropped: tuple[tuple[str, str], ...]  # (item_id, reason)


def filter_items(items: Iterable[Item], c: Constraints) -> Filtered:
    """Apply `c` to `items`; the kept items keep their order."""
    items = list(items)
    best: dict[str, int] = {}
    for i, item in enumerate(items):
        j = best.get(item.item_id)
        if j is None or _rank(item) < _rank(items[j]):
            best[item.item_id] = i
    kept, dropped = [], []
    for i, item in enumerate(items):
        if best[item.item_id] != i:
            dropped.append((item.item_id, "duplicate"))
        elif (why := reason(item, c)) is not None:
            dropped.append((item.item_id, why))
        else:
            kept.append(item)
    have = {i.item_id for i in kept}
    broken = {i.group for i in items if i.group is not None and i.item_id not in have}
    if broken:
        dropped += [(i.item_id, "group") for i in kept if i.group in broken]
        kept = [i for i in kept if i.group not in broken]
    return Filtered(tuple(kept), tuple(dropped))


def _rank(item: Item) -> float:
    return item.rank if item.rank is not None else float("inf")
