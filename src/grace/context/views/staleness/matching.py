"""Matching change sets against the dependency patterns of a view (plan 3.4, 5.4).

The write-side strategies never query the claim graph. They keep an `Index` of every change set
they have seen (claims, the attributions and change supersessions on each claim, entity
equivalences), so a decision is a pure function of the change-set records: the replay of ablation
A runs every strategy over the same stored change sets (docs/work/plan/structure.md).

`triggers(dp, changeset, index)` lists the entries of one change set that can affect a view
through one dependency pattern, following the conditions of the soundness proposition (plan 3.4):

- a new claim matches the pattern (patterns without an attribution constraint only);
- a new attribution satisfies the attribution constraint of the pattern (speaker, function, and
  report mode own, positive polarity and not derived unless the query relaxes them, plan 3.3, as
  the compiler applies them), on a claim (old or new) that matches it: "a pattern with an
  attribution constraint can be matched by a new claim, and also by a new attribution on an
  existing claim". A new claim of a constrained pattern matches through its attribution, which
  is a trigger in its own right;
- a supersession event points to a claim that matches the pattern (any role);
- an evidence link points to a claim that matches a *positive* pattern: citation level only,
  since negated patterns contribute no witness and therefore no evidence.

A claim matches a pattern when its subject, predicate, object and scope agree with the pattern's
constants (entity constants compared on class representatives, as the compiler does), it carries
an attribution that satisfies the constraint (for supersessions and evidence links, any such
attribution seen so far), and, with `local_filters`, it passes the pattern's local filters. The
attribution constraint is always applied: there is no option to drop it, because a matcher that
ignores it would only match new claims and miss a new attribution on an existing claim (user
decision of 2026-11-26). A filter
that cannot be decided from the records (an unknown start, mixed date and dateTime, an unexpected
datatype) counts as passed, so every simplification widens the match and never loses one. For a
supersession the filters are tried on the claim's valid end before and after the change set,
because a change supersession can set the end that `end(?c)` reads. Non-local filters, `AT(valid=)`
and the state of the query (current or historical) are not used: dropping a condition only widens
the match, which keeps every rung sound (plan 3.4, "Ladder of decision strategies").
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entities import EntityEquivalence, representatives
from grace.context.memory.graph.entries import (
    Attribution,
    Claim,
    Entity,
    Supersession,
    SupersessionKind,
    Value,
)
from grace.context.pipeline.query.ir import (
    Bound,
    ClaimPattern,
    Filter,
    Op,
    Predicate,
    Scope,
    ValidBound,
    Var,
)
from grace.context.views.dependencies import POSITIVE, DependencyPattern

ANSWER = "answer"
CITATION = "citation"


class Index:
    """What the change sets seen so far contain, for matching without the graph."""

    def __init__(self) -> None:
        self.claims: dict[str, Claim] = {}
        self.attributions: dict[str, list[Attribution]] = defaultdict(list)
        self.change_ends: dict[str, list[Supersession]] = defaultdict(list)
        self.equivalences: list[EntityEquivalence] = []
        self.reps: dict[str, str] = {}
        self.version = 0

    def add(self, cs: ChangeSet) -> None:
        if cs.version <= self.version:
            raise ValueError(f"change set {cs.version} given after version {self.version}; "
                             "change sets must be seen once each, in version order")
        for c in cs.claims:
            self.claims[c.claim_id] = c
        for a in cs.attributions:
            self.attributions[a.claim_id].append(a)
        for s in cs.supersessions:
            if s.kind is SupersessionKind.CHANGE and s.valid_end is not None:
                self.change_ends[s.claim_id].append(s)
        if cs.entity_merges:
            self.equivalences.extend(cs.entity_merges)
            self.reps = representatives(self.equivalences, cs.version)
        self.version = cs.version

    def rep(self, entity_id: str) -> str:
        return self.reps.get(entity_id, entity_id)

    def valid_end(self, claim: Claim, upto: int) -> str | None:
        """The effective valid end known at `upto` (contracts.md, "Claim graph")."""
        if claim.valid_time.end is not None:
            return claim.valid_time.end
        ends = sorted((s for s in self.change_ends.get(claim.claim_id, ()) if s.version <= upto),
                      key=lambda s: (s.version, s.supersession_id))
        return ends[0].valid_end if ends else None


# ---------------------------------------------------------------------------------------------
# Positions


def _entity_eq(index: Index, a: str, b: str) -> bool:
    return a == b or index.rep(a) == index.rep(b)


def _spo(p: ClaimPattern, c: Claim, index: Index) -> bool:
    if isinstance(p.subject, Entity) and not _entity_eq(index, c.subject, p.subject.id):
        return False
    if isinstance(p.predicate, str) and p.predicate != c.predicate:
        return False
    if isinstance(p.object, Entity):
        if not isinstance(c.object, Entity) or not _entity_eq(index, c.object.id, p.object.id):
            return False
    elif isinstance(p.object, Value) and c.object != p.object:
        return False
    scope = p.scope
    if scope is Scope.DEFAULT:
        return c.scope is None
    if isinstance(scope, str) and not isinstance(scope, Scope):
        return c.scope == scope
    return True  # `_` or a variable


def _satisfies(p: ClaimPattern, a: Attribution, index: Index) -> bool:
    constraint = p.attribution
    if constraint is None:
        return True
    if isinstance(constraint.speaker, Entity) and not _entity_eq(index, a.speaker,
                                                                 constraint.speaker.id):
        return False
    if constraint.function is not None and a.function is not constraint.function:
        return False
    # Defaults of [u, f] (plan 3.3), as the compiler applies them: own, positive, not derived;
    # a field set to None is relaxed and accepts any value.
    if constraint.report_mode is not None and a.report_mode is not constraint.report_mode:
        return False
    if constraint.polarity is not None and a.polarity is not constraint.polarity:
        return False
    return constraint.derived is None or a.derived is constraint.derived


# ---------------------------------------------------------------------------------------------
# Local filters


def _binding(p: ClaimPattern, var: Var, c: Claim, a: Attribution | None, index: Index):
    """The value `var` takes on claim `c` (and attribution `a`), or None if not decidable."""
    if p.subject == var:
        return Entity(index.rep(c.subject))
    if p.predicate == var:
        return Predicate(c.predicate)
    if p.object == var:
        return Entity(index.rep(c.object.id)) if isinstance(c.object, Entity) else c.object
    if p.scope == var:
        return Value(c.scope, "string") if c.scope is not None else None
    if p.attribution is not None and p.attribution.speaker == var and a is not None:
        return Entity(index.rep(a.speaker))
    return None


def _time(text: str) -> _dt.datetime:
    t = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t.astimezone(_dt.UTC).replace(tzinfo=None) if t.tzinfo else t


_COMPARE = {Op.EQ: lambda x, y: x == y, Op.NE: lambda x, y: x != y,
            Op.LT: lambda x, y: x < y, Op.LE: lambda x, y: x <= y,
            Op.GT: lambda x, y: x > y, Op.GE: lambda x, y: x >= y}


def _compare_values(left: Value, op: Op, right: Value) -> bool | None:
    if left.datatype != right.datatype:
        return None
    dt = left.datatype
    if dt == "integer":
        return _COMPARE[op](int(left.lexical), int(right.lexical))
    if dt in ("date", "dateTime"):
        return _COMPARE[op](_time(left.lexical), _time(right.lexical))
    if dt in ("string", "time"):
        return _COMPARE[op](left.lexical, right.lexical)
    if op in (Op.EQ, Op.NE):
        return _COMPARE[op](left.lexical, right.lexical)
    return None


def _filter_holds(f: Filter, p: ClaimPattern, c: Claim, a: Attribution | None, index: Index,
                  upto: int) -> bool:
    """Whether `f` holds on the claim; True when it cannot be decided (over-approximation)."""
    right = f.right
    if isinstance(f.left, ValidBound):
        if not isinstance(right, Value) or right.datatype not in ("date", "dateTime"):
            return True
        if f.left.bound is Bound.START:
            start = c.valid_time.start
            if start is None or ("T" in start) != (right.datatype == "dateTime"):
                return True
            return _COMPARE[f.op](_time(start), _time(right.lexical))
        end = index.valid_end(c, upto)
        if end is None:  # open: later than every time
            return f.op in (Op.GT, Op.GE, Op.NE)
        if ("T" in end) != (right.datatype == "dateTime"):
            return True
        return _COMPARE[f.op](_time(end), _time(right.lexical))
    value = _binding(p, f.left, c, a, index)
    if value is None:
        return True
    if isinstance(right, Entity):
        if not isinstance(value, Entity):
            return True
        same = _entity_eq(index, value.id, right.id)
        return same if f.op is Op.EQ else not same if f.op is Op.NE else True
    if isinstance(right, Value) and isinstance(value, Value):
        result = _compare_values(value, f.op, right)
        return True if result is None else result
    return True


def _filters_hold(dp: DependencyPattern, c: Claim, a: Attribution | None, index: Index,
                  upto: int) -> bool:
    return all(_filter_holds(f, dp.pattern, c, a, index, upto) for f in dp.filters)


# ---------------------------------------------------------------------------------------------
# Matching


@dataclass(frozen=True)
class Options:
    """Which parts of a dependency pattern are used (the rungs of plan 3.4's ladder).

    Only the local filters can be switched off; the attribution constraint is always applied.
    """

    local_filters: bool = True  # the pattern's local filters


@dataclass(frozen=True)
class Trigger:
    """An entry of a change set that can affect a view through one of its patterns."""

    level: str      # `answer` or `citation`
    entry: str      # entry ID
    kind: str       # claim, attribution, supersession, evidence
    pattern: int    # index of the dependency pattern
    role: str


def claim_matches(dp: DependencyPattern, c: Claim, index: Index, options: Options, *,
                  attribution: Attribution | None = None, upto: int | None = None,
                  ends: Iterable[int] = ()) -> bool:
    """Does claim `c` match pattern `dp`?

    With `attribution`, that attribution must satisfy the constraint; otherwise any attribution on
    `c` seen so far may. Filters are evaluated with the valid end known at `upto` and at each of
    `ends` (any one passing suffices).
    """
    p = dp.pattern
    if not _spo(p, c, index):
        return False
    upto = index.version if upto is None else upto
    if p.attribution is not None:
        candidates = (attribution,) if attribution is not None else tuple(
            index.attributions.get(c.claim_id, ()))
        candidates = tuple(a for a in candidates if _satisfies(p, a, index))
        if not candidates:
            return False
    else:
        candidates = (attribution,)
    if not options.local_filters or not dp.filters:
        return True
    return any(_filters_hold(dp, c, a, index, v) for a in candidates for v in (upto, *ends))


def triggers(dependencies: tuple[DependencyPattern, ...], cs: ChangeSet, index: Index,
             options: Options = Options(), *, roles: Iterable[str] | None = None
             ) -> list[Trigger]:
    """Entries of `cs` that match a dependency pattern; `index` must already include `cs`.

    `roles` restricts the patterns used (for the citation strategy that watches only negated and
    aggregated patterns, see `citation.py`, the caller filters instead).
    """
    wanted = set(roles) if roles is not None else None
    out: list[Trigger] = []
    for i, dp in enumerate(dependencies):
        if wanted is not None and dp.role not in wanted:
            continue
        p = dp.pattern
        if p.attribution is None:
            for c in cs.claims:
                if claim_matches(dp, c, index, options):
                    out.append(Trigger(ANSWER, c.claim_id, "claim", i, dp.role))
        else:
            for a in cs.attributions:
                c = index.claims.get(a.claim_id)
                if c is not None and claim_matches(dp, c, index, options, attribution=a):
                    out.append(Trigger(ANSWER, a.attribution_id, "attribution", i, dp.role))
        for s in cs.supersessions:
            c = index.claims.get(s.claim_id)
            if c is not None and claim_matches(dp, c, index, options, upto=cs.version - 1,
                                               ends=(cs.version,)):
                out.append(Trigger(ANSWER, s.supersession_id, "supersession", i, dp.role))
        if dp.role == POSITIVE:
            for e in cs.evidence_links:
                c = index.claims.get(e.claim_id)
                if c is not None and claim_matches(dp, c, index, options):
                    out.append(Trigger(CITATION, e.evidence_id, "evidence", i, dp.role))
    return out


def claim_of(entry, index: Index) -> Claim | None:
    """The claim an entry is about (the claim itself for a claim)."""
    if isinstance(entry, Claim):
        return entry
    return index.claims.get(entry.claim_id)
