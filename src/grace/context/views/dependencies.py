"""Dependency patterns of a view, derived from its query representation (plan 5.4).

"The compiler derives all claim patterns of a view directly from the intermediate representation,
including patterns inside negated conditions and aggregations, the attribution constraint of each
pattern, and any local filter on a pattern that involves only that pattern's own variables."

`pipeline/query/patterns.py` is named for this in structure.md, but T017 left it unimplemented
(docs/research/query-ir.md, open question 3). The integration owner assigned the dependency
patterns to T019, which keeps them here, in the views package that stores them; the module depends
only on `query/ir.py`. The staleness strategies (`views/staleness/`) read the patterns from the
stored views; matching a change set against them is `views/staleness/matching.py`.

Not represented, and therefore ignored by matching (sound, since dropping a condition only widens
the match): filters that involve variables of more than one pattern, `AT(valid=d)`, and the state
of the query (current or historical).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from grace.context.memory.graph.entries import Entity, Value
from grace.context.pipeline.query.ir import (
    ClaimPattern,
    Filter,
    Query,
    ReadTime,
    Scope,
    ValidBound,
    Var,
)

POSITIVE = "positive"
NEGATED = "negated"


@dataclass(frozen=True)
class DependencyPattern:
    """One claim pattern of a view's query with what a staleness decision needs to know.

    - `role`: `positive` (a pattern of the join) or `negated` (the pattern inside NOT EXISTS);
    - `aggregated`: the query counts over the pattern (distinct count);
    - `selected`: the query selects the latest state over the claim this pattern labels;
    - `filters`: the local filters, those that involve only this pattern's own variables or label.
    """

    pattern: ClaimPattern
    role: str
    aggregated: bool = False
    selected: bool = False
    filters: tuple[Filter, ...] = ()

    def to_record(self) -> dict[str, Any]:
        p = self.pattern
        attribution = None
        if p.attribution is not None:
            attribution = {"speaker": _term(p.attribution.speaker),
                           "function": (p.attribution.function.value
                                        if p.attribution.function is not None else None)}
        return {"role": self.role, "aggregated": self.aggregated, "selected": self.selected,
                "subject": _term(p.subject), "predicate": _term(p.predicate),
                "object": _term(p.object), "scope": _term(p.scope), "attribution": attribution,
                "label": p.label.name if p.label is not None else None,
                "filters": [_filter(f) for f in self.filters]}


def _term(term) -> Any:
    if term is None:
        return None
    if isinstance(term, Var):
        return {"var": term.name}
    if isinstance(term, Scope):
        return {"scope": term.value}
    if isinstance(term, Entity):
        return {"entity": term.id}
    if isinstance(term, Value):
        return {"value": term.lexical, "datatype": term.datatype}
    if isinstance(term, str):
        return {"name": term}
    raise TypeError(f"cannot serialise term {term!r}")


def _filter(f: Filter) -> dict[str, Any]:
    if isinstance(f.left, ValidBound):
        left = {"bound": f.left.bound.value, "label": f.left.label.name}
    else:
        left = _term(f.left)
    if isinstance(f.right, ReadTime):  # rejected by the type checker; kept for completeness
        right = {"read_time": f.right.offset_days}
    else:
        right = _term(f.right)
    return {"left": left, "op": f.op.value, "right": right}


def _own(pattern: ClaimPattern, f: Filter) -> bool:
    """A filter is local to a pattern if its only variable is one of the pattern's own."""
    own = set(pattern.variables())
    if pattern.label is not None:
        own.add(pattern.label)
    left = f.left.label if isinstance(f.left, ValidBound) else f.left
    return left in own and not isinstance(f.right, Var)


def dependency_patterns(query: Query) -> tuple[DependencyPattern, ...]:
    """Every claim pattern of `query`, positive ones first, with its local filters."""
    q = query.labelled()
    aggregated = q.count is not None
    latest = q.latest.label if q.latest is not None else None
    out = [DependencyPattern(p, POSITIVE, aggregated, p.label == latest,
                             tuple(f for f in q.filters if _own(p, f)))
           for p in q.where]
    if q.negation is not None:
        n = q.negation.pattern
        local = tuple(f for f in q.negation.filters if _own(n, f))
        out.append(DependencyPattern(n, NEGATED, aggregated, False, local))
    return tuple(out)
