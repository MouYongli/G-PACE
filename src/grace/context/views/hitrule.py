"""The view hit rule: when a plan's query is served by a view (plan 5.4; user decision of
2026-11-28, follow-up of E010).

A plan's query hits a view when it is equal to the view's bound query modulo a consistent
renaming of variables (alpha-equivalence over the query IR): the same patterns in the same
order, the same constants, predicates, scopes and attribution constraints (speaker, function and
relaxed defaults), the same filters, negation, aggregation, `LATEST` and `AT` clause, and a
bijective mapping between the two queries' variable names. Nothing else is ignored: a different
speaker, a different constant or swapped subject and object is no hit.

`canonical` renames every user-named variable to `v1`, `v2`, ... in order of first occurrence in
a structural walk of the IR (field order of the IR dataclasses, which is position-based, never
name-based) and prints the result with `grammar.to_text`. Two queries are alpha-equivalent
exactly when their canonical texts are equal. Variables whose name starts with `_` are the
compiler's labels; they are not renamed (and, as before, unprinted labels are not compared), so
every query that was a hit under the earlier exact-text rule is still a hit.

Every view source uses this module: the resident store (`engine.Views.hit`), the template
serialisation variant (`serialise.SerialisedViews`) and the read-time sources
(`readtime.ReadTimeViews`). A view was built with its own variable names; `match` returns the
mapping from the plan's variable names to the view's, and `for_plan` re-expresses a view in the
plan's names (its columns, which the assembly matches against the plan's variables).
"""

from __future__ import annotations

from dataclasses import fields, replace
from enum import StrEnum
from typing import Any

from grace.context.memory.graph.entries import Entity
from grace.context.pipeline.query.grammar import to_text
from grace.context.pipeline.query.ir import (
    AttributionConstraint,
    ClaimPattern,
    CountDistinct,
    Filter,
    Latest,
    NotExists,
    Query,
    ValidBound,
    Var,
)

_IR = (Query, ClaimPattern, AttributionConstraint, Filter, ValidBound, NotExists, CountDistinct,
       Latest)


def _renamable(var: Var) -> bool:
    return not var.name.startswith("_")


def _collect(node: Any, names: dict[str, str]) -> None:
    if isinstance(node, Var):
        if _renamable(node):
            names.setdefault(node.name, f"v{len(names) + 1}")
    elif isinstance(node, tuple):
        for item in node:
            _collect(item, names)
    elif isinstance(node, _IR):
        for f in fields(node):
            _collect(getattr(node, f.name), names)


def _substitute(node: Any, names: dict[str, str]) -> Any:
    if isinstance(node, Var):
        return Var(names[node.name]) if node.name in names else node
    if isinstance(node, tuple):
        out = tuple(_substitute(item, names) for item in node)
        return node if all(a is b for a, b in zip(out, node, strict=True)) else out
    if isinstance(node, _IR):
        changes = {}
        for f in fields(node):
            value = getattr(node, f.name)
            new = _substitute(value, names)
            if new is not value:
                changes[f.name] = new
        return replace(node, **changes) if changes else node
    return node


def renaming(query: Query) -> dict[str, str]:
    """Variable name -> canonical name (`v1`, `v2`, ...) in order of first occurrence."""
    names: dict[str, str] = {}
    _collect(query, names)
    return names


def canonical(query: Query) -> str:
    """The canonical text of `query`: `to_text` after renaming its variables (`renaming`)."""
    return to_text(_substitute(query, renaming(query)))


def match(plan_query: Query | None, bound_query: Query) -> dict[str, str] | None:
    """The mapping from the plan's variable names to the bound query's when the two queries are
    alpha-equivalent, else None. Equal queries map every variable to itself."""
    if plan_query is None:
        return None
    if plan_query == bound_query:
        return {name: name for name in renaming(plan_query)}
    if canonical(plan_query) != canonical(bound_query):
        return None
    back = {c: name for name, c in renaming(bound_query).items()}
    return {name: back[c] for name, c in renaming(plan_query).items()}


def constants(query: Query) -> frozenset[str]:
    """Entity IDs and predicate (or scope) names of `query`: a cheap pre-filter for bindings,
    since an alpha-equivalent bound query has the same constants."""
    out: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, Entity):
            out.add(node.id)
        elif isinstance(node, str) and not isinstance(node, StrEnum):
            out.add(node)
        elif isinstance(node, tuple):
            for item in node:
                walk(item)
        elif isinstance(node, _IR):
            for f in fields(node):
                walk(getattr(node, f.name))
    walk(query)
    return frozenset(out)


def plan_columns(columns: tuple[str, ...], mapping: dict[str, str]) -> tuple[str, ...]:
    """A view's columns in the plan's variable names (`mapping`: plan name -> view name)."""
    inverse = {v: p for p, v in mapping.items()}
    return tuple(inverse.get(c, c) for c in columns)


def for_plan(view, plan_query: Query, mapping: dict[str, str]):
    """The view re-expressed in the plan's variable names: its query is the plan's query and its
    columns are renamed; rows, sentences, citations and cut-off are the view's. The view itself
    when the names agree."""
    if all(p == v for p, v in mapping.items()):
        return view
    return replace(view, query=plan_query, columns=plan_columns(view.columns, mapping),
                   dependencies=())


__all__ = ["canonical", "constants", "for_plan", "match", "plan_columns", "renaming"]
