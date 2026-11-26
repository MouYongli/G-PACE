"""Rule templates: map a question to the query representation without an LLM call (plan 5.3).

A rule fires only when the question has one of a few fixed shapes *and* both its entity and its
predicate resolve unambiguously against the planning context (the entity table and the alias
table of the vocabulary fragment). Anything else is left to the planner LLM. The rules know no
benchmark: they read only the question text and the context.

- `count`: "How many <noun> do/does/did <entity> <verb> [prep]?", p multi-valued:
  `SELECT COUNT(DISTINCT ?o) WHERE { (e, p, ?o) [_, inform] }`
- `list`: "What/Which <noun> do/does <entity> <verb> [prep]?", p multi-valued:
  `SELECT ?o WHERE { (e, p, ?o) [_, inform] }`
- `current`: the same shape, or "Where do/does <entity> <verb>?", p exclusive:
  `SELECT ?o WHERE { (e, p, ?o) [_, inform] AS ?c FILTER(end(?c) > "9999-12-31"^^date) }
  LATEST BY version OF ?c`

All three read the current state at the version read (`AT(known=r, state=current)`). The question
names no speaker, so the only attribution constraint is `[_, inform]`: some speaker stated the
fact. (Until the open question F1 of query-ir.md is decided, `[u, f]` cannot also require report
mode own and positive polarity, so a hypothetical or quoted inform still matches.) The
`current` rule keeps only claims whose valid time is still open: the fragment has no "end is
unset" test, and `end(?c) > OPEN_END` holds exactly for an open end (an end at or before that
date fails it), so a past-dated claim ("I lived in Bremen until 2017") is not the current value.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from grace.context.memory.graph.entries import CommunicativeFunction, Entity, Value
from grace.context.pipeline.query.ir import (
    AttributionConstraint,
    Bound,
    ClaimPattern,
    CountDistinct,
    Filter,
    Latest,
    LatestKey,
    Op,
    Query,
    ValidBound,
    Var,
)

OPEN_END = "9999-12-31"
_INFORM = AttributionConstraint(None, CommunicativeFunction.INFORM)

_PREP = r"(?: (?:in|at|on|for|with|to|from|of))?"
_COUNT = re.compile(r"^how many (?P<noun>[\w' -]+?) (?:do|does|did) (?P<ent>[\w' .-]+?) "
                    rf"(?P<verb>[a-z]+{_PREP})$")
_WHAT = re.compile(r"^(?:what|which) (?P<noun>[\w' -]+?) (?:do|does) (?P<ent>[\w' .-]+?) "
                   rf"(?P<verb>[a-z]+{_PREP})$")
_WHERE = re.compile(r"^where (?:do|does) (?P<ent>[\w' .-]+?) (?P<verb>[a-z]+)$")


@dataclass(frozen=True)
class PredicateInfo:
    """One predicate of the vocabulary fragment shown to the planner."""

    name: str
    exclusive: bool
    aliases: tuple[str, ...] = ()
    description: str | None = None


@dataclass(frozen=True)
class EntityInfo:
    """One candidate entity: its ID in the claim graph and the names that refer to it."""

    id: str
    names: tuple[str, ...] = ()
    kind: str | None = None


@dataclass(frozen=True)
class RuleMatch:
    rule: str
    query: Query
    variables: tuple[tuple[str, str], ...]  # (variable, what it stands for)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().rstrip("?.! ")).strip()


def _forms(word: str) -> set[str]:
    """Crude inflections for alias lookup: enjoy ~ enjoys, speak ~ speaks, live ~ lives in."""
    out = {word}
    if word.endswith("ies"):
        out.add(word[:-3] + "y")
    if word.endswith("es"):
        out.add(word[:-2])
    if word.endswith("s"):
        out.add(word[:-1])
    out |= {word + "s", word + "es"}
    return out


def _phrases(*parts: str) -> set[str]:
    out: set[str] = set()
    for part in parts:
        words = part.split()
        if not words:
            continue
        for head in _forms(words[0]):
            out.add(" ".join([head, *words[1:]]))
        for tail in _forms(words[-1]):
            out.add(" ".join([*words[:-1], tail]))
    return out


def resolve_entity(mention: str, entities: Sequence[EntityInfo]) -> str | None:
    """The unique entity ID whose name (or ID) equals the mention, else None."""
    m = _norm(mention)
    hits = {e.id for e in entities
            if m == e.id.lower() or m in {_norm(n) for n in e.names}}
    return next(iter(hits)) if len(hits) == 1 else None


def resolve_predicate(candidates: set[str], predicates: Sequence[PredicateInfo]
                      ) -> PredicateInfo | None:
    """The unique predicate one of whose aliases (or its name) is among `candidates`."""
    hits = {}
    for p in predicates:
        names = {_norm(a) for a in p.aliases} | {p.name.lower()}
        if names & candidates:
            hits[p.name] = p
    return next(iter(hits.values())) if len(hits) == 1 else None


def match_rules(question: str, entities: Sequence[EntityInfo],
                predicates: Sequence[PredicateInfo]) -> RuleMatch | None:
    """The first rule template that covers `question`, or None."""
    q = _norm(question)
    o, c = Var("o"), Var("c")
    if m := _COUNT.match(q):
        subject = resolve_entity(m["ent"], entities)
        pred = resolve_predicate(_phrases(m["noun"], m["verb"], f"{m['verb']} {m['noun']}"),
                                 predicates)
        if subject is None or pred is None or pred.exclusive:
            return None
        pat = ClaimPattern(Entity(subject), pred.name, o, attribution=_INFORM)
        query = Query(select=(), where=(pat,), count=CountDistinct(o))
        return RuleMatch("count", query, (("?o", f"number of {m['noun']}"),))
    for pattern in (_WHAT, _WHERE):
        if not (m := pattern.match(q)):
            continue
        subject = resolve_entity(m["ent"], entities)
        noun = m.groupdict().get("noun") or ""
        pred = resolve_predicate(_phrases(*(x for x in (noun, m["verb"]) if x)), predicates)
        if subject is None or pred is None:
            return None
        if pred.exclusive:
            query = Query(select=(o,), where=(ClaimPattern(Entity(subject), pred.name, o,
                                                           attribution=_INFORM, label=c),),
                          filters=(Filter(ValidBound(c, Bound.END), Op.GT,
                                          Value(OPEN_END, "date")),),
                          latest=Latest(c, LatestKey.VERSION))
            return RuleMatch("current", query, (("?o", noun or pred.name),))
        if pattern is _WHERE:
            return None
        pat = ClaimPattern(Entity(subject), pred.name, o, attribution=_INFORM)
        query = Query(select=(o,), where=(pat,))
        return RuleMatch("list", query, (("?o", noun),))
    return None
