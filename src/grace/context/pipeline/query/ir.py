"""Typed intermediate representation of the query fragment and its type checker (plan 3.3, 5.3).

Query planning (T023) produces only this representation; `compile.py` turns it into SPARQL. The
representation covers exactly the six operations of the fragment:

1. filters: a variable or a claim's valid-time bound compared with a constant (`Filter`);
2. joins over one to three claim patterns (`Query.where`);
3. negation: one non-nested NOT EXISTS over one claim pattern that shares a variable with the
   positive part, with optional local filters (`NotExists`);
4. distinct counting (`CountDistinct`), optionally grouped by the selected variables;
5. selection of the latest confirmed state, the maximum by version or by valid time (`Latest`);
6. provenance expansion: the witnesses of every answer and the evidence of their claims
   (`Query.provenance`).

The atom is the claim pattern (s, p, o, scope)[u, f]; by default the attribution constraint also
requires an own, positive, not derived attribution, and a query may relax that explicitly.
Every query is parameterised by its cut-off version (`At.known`; `None` means the version being
read), may fix a valid time (`At.valid`) and states whether it reads the current state (built-in
"currently accepted" negation) or the historical state (only corrected claims are excluded)
(`At.state`).

What the fragment excludes cannot be built from these types (property paths, OPTIONAL, UNION,
nested negation, other aggregates); the text parser in `grammar.py` rejects those forms with a
`QueryTypeError`. What the types can express but the fragment forbids is rejected by `typecheck`:
more than three patterns, comparisons with the time of reading (`ReadTime`, until `absolutize` in
`compile.py` turns it into a constant), comparisons between variables, unbound or ill-typed
variables, a negation that shares no variable with the positive part. The grammar is documented
in docs/research/query-ir.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from grace.context.memory.graph.entries import (
    CommunicativeFunction,
    Entity,
    EntryError,
    Polarity,
    ReportMode,
    ValidTime,
    Value,
)

MAX_PATTERNS = 3
_VAR = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_PREDICATE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


class QueryTypeError(ValueError):
    """The query lies outside the fragment or is ill-typed; the message says why."""


# ---------------------------------------------------------------------------------------------
# Terms


@dataclass(frozen=True, order=True)
class Var:
    """A query variable, written `?name`. Names starting with `_` are reserved for the compiler."""

    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _VAR.fullmatch(self.name):
            raise QueryTypeError(f"variable name {self.name!r} is not [A-Za-z][A-Za-z0-9_]*")

    def __str__(self) -> str:
        return "?" + self.name


@dataclass(frozen=True, order=True)
class Predicate:
    """A predicate name bound to a predicate variable in an answer."""

    name: str


class Scope(StrEnum):
    """Scope positions that are not a constant string or a variable."""

    ANY = "_"            # any scope, including the default scope
    DEFAULT = "default"  # only the default scope (the claim has no `g:scope`)


@dataclass(frozen=True)
class ReadTime:
    """The time of reading shifted by `offset_days` (for "in the last week": `ReadTime(-7)`).

    Filters may not compare with it (plan 3.3): such a view would go stale without any write.
    `compile.absolutize` replaces it by an absolute date and marks the query temporary.
    """

    offset_days: int = 0


Constant = Entity | Value
SubjectTerm = Var | Entity
PredicateTerm = Var | str
ObjectTerm = Var | Entity | Value
ScopeTerm = Var | str | Scope
SpeakerTerm = Var | Entity | None


@dataclass(frozen=True)
class AttributionConstraint:
    """`[u, f]`: the claim must carry an attribution by speaker `u` with function `f`.

    Either part may be left open (`None`); at least one must be given. By default the attribution
    must also be the speaker's own statement (report mode own), positive and not derived, so that
    quotes, hypotheticals, denials and inferred attributions do not satisfy it (plan 3.3). A query
    relaxes each default explicitly by setting the field to `None` ("any"; in the text form
    `[u, f, mode=_, polarity=_, derived=_]`). Only relaxation is in the fragment: a field is
    either its default or `None`, so a constraint can never require a quote or a denial.
    """

    speaker: SpeakerTerm = None
    function: CommunicativeFunction | None = None
    report_mode: ReportMode | None = ReportMode.OWN
    polarity: Polarity | None = Polarity.POSITIVE
    derived: bool | None = False

    def relaxed(self) -> tuple[str, ...]:
        """The names of the relaxed defaults, in canonical order (`mode`, `polarity`,
        `derived`)."""
        return tuple(name for name, value in (("mode", self.report_mode),
                                              ("polarity", self.polarity),
                                              ("derived", self.derived)) if value is None)


# Default of each relaxable field of `AttributionConstraint`, keyed by its text name.
ATTRIBUTION_DEFAULTS = {"mode": ("report_mode", ReportMode.OWN),
                        "polarity": ("polarity", Polarity.POSITIVE),
                        "derived": ("derived", False)}


@dataclass(frozen=True)
class ClaimPattern:
    """`(s, p, o, scope)[u, f] AS label`.

    `label` names the matched claim node, so that filters on valid time and `Latest` can refer
    to it; it is never an answer variable. The compiler assigns labels to unlabelled patterns.
    """

    subject: SubjectTerm
    predicate: PredicateTerm
    object: ObjectTerm
    scope: ScopeTerm = Scope.ANY
    attribution: AttributionConstraint | None = None
    label: Var | None = None

    def variables(self) -> dict[Var, str]:
        """The variables of the pattern (label excluded) with the kind of their position."""
        out: dict[Var, str] = {}
        for term, kind in ((self.subject, "entity"), (self.predicate, "predicate"),
                           (self.object, "object"), (self.scope, "scope"),
                           (self.attribution.speaker if self.attribution else None, "entity")):
            if isinstance(term, Var):
                out.setdefault(term, kind)
                if out[term] != kind:
                    out[term] = _join_kind(out[term], kind, term)
        return out


class Op(StrEnum):
    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="


class Bound(StrEnum):
    START = "start"
    END = "end"


@dataclass(frozen=True)
class ValidBound:
    """`start(?c)` or `end(?c)`: a bound of the valid time of the claim labelled `label`.

    `end` is the effective valid end as known at the cut-off: the claim's own end, else the valid
    end stated by the earliest change supersession (contracts.md, "Claim graph"); an open end is
    later than every time.
    """

    label: Var
    bound: Bound


@dataclass(frozen=True)
class Filter:
    """`left op right`: a variable or valid-time bound compared with a constant."""

    left: Var | ValidBound
    op: Op
    right: Constant | ReadTime | Var


@dataclass(frozen=True)
class NotExists:
    """NOT EXISTS over one claim pattern sharing a variable with the positive part."""

    pattern: ClaimPattern
    filters: tuple[Filter, ...] = ()


@dataclass(frozen=True)
class CountDistinct:
    """COUNT(DISTINCT var), grouped by the selected variables."""

    var: Var


class LatestKey(StrEnum):
    VERSION = "version"  # the version at which the pattern became matched (claim or attribution)
    VALID = "valid"      # the start of the claim's valid time; claims without one are skipped


@dataclass(frozen=True)
class Latest:
    """Keep only the answers whose claim `label` is the latest by `key`; ties keep all."""

    label: Var
    key: LatestKey = LatestKey.VERSION


class State(StrEnum):
    CURRENT = "current"        # "currently accepted": no supersession event stamped <= r
    HISTORICAL = "historical"  # excludes only claims superseded by a correction stamped <= r


@dataclass(frozen=True)
class At:
    """`AT(known=r, valid=d, state=...)`.

    `known=None` binds the cut-off to the version being read (a moving cut-off); an integer fixes
    it (a time-travel read). `valid` keeps only claims not known to be outside their valid
    interval at world time `d` (canonical xsd:date or xsd:dateTime).
    """

    known: int | None = None
    valid: str | None = None
    state: State = State.CURRENT


@dataclass(frozen=True)
class Query:
    """One query of the fragment. For a count, `select` holds the grouping variables."""

    select: tuple[Var, ...]
    where: tuple[ClaimPattern, ...]
    filters: tuple[Filter, ...] = ()
    negation: NotExists | None = None
    count: CountDistinct | None = None
    latest: Latest | None = None
    at: At = field(default_factory=At)
    provenance: bool = True
    temporary: bool = False  # set by `absolutize`: relative time was resolved; not a view

    def __post_init__(self) -> None:
        for name in ("select", "where", "filters"):
            value = getattr(self, name)
            if isinstance(value, list):
                object.__setattr__(self, name, tuple(value))

    def labelled(self) -> Query:
        """The same query with every pattern labelled (`_c<i>`, `_n` for the negated one)."""
        where = tuple(p if p.label else _relabel(p, f"_c{i}") for i, p in enumerate(self.where))
        negation = self.negation
        if negation is not None and negation.pattern.label is None:
            negation = NotExists(_relabel(negation.pattern, "_n"), negation.filters)
        return Query(self.select, where, self.filters, negation, self.count, self.latest,
                     self.at, self.provenance, self.temporary)

    def positive_variables(self) -> dict[Var, str]:
        out: dict[Var, str] = {}
        for p in self.where:
            for var, kind in p.variables().items():
                out[var] = _join_kind(out[var], kind, var) if var in out else kind
        return out


def _relabel(pattern: ClaimPattern, name: str) -> ClaimPattern:
    label = Var.__new__(Var)
    object.__setattr__(label, "name", name)  # reserved name, bypasses the user-name check
    return ClaimPattern(pattern.subject, pattern.predicate, pattern.object, pattern.scope,
                        pattern.attribution, label)


def _join_kind(a: str, b: str, var: Var) -> str:
    """Kinds `entity` and `object` meet in `entity`; predicate and scope variables stand alone."""
    if a == b:
        return a
    if {a, b} == {"entity", "object"}:
        return "entity"
    raise QueryTypeError(f"variable {var} is used both as {a} and as {b}")


# ---------------------------------------------------------------------------------------------
# Type checker


def typecheck(query: Query) -> None:
    """Raise `QueryTypeError` listing every way `query` falls outside the fragment."""
    errors: list[str] = []

    def check(fn, *args) -> None:
        try:
            fn(*args)
        except (QueryTypeError, EntryError) as exc:
            errors.append(str(exc))

    if not isinstance(query, Query):
        raise QueryTypeError(f"expected a Query, got {type(query).__name__}")
    if not query.where:
        errors.append("a query needs at least one claim pattern")
    if len(query.where) > MAX_PATTERNS:
        errors.append(f"joins are limited to {MAX_PATTERNS} claim patterns, got "
                      f"{len(query.where)}")
    for i, p in enumerate(query.where):
        check(_check_pattern, p, f"pattern {i + 1}")
    if query.negation is not None:
        if not isinstance(query.negation, NotExists):
            errors.append("negation must be a NotExists")
        else:
            check(_check_pattern, query.negation.pattern, "negated pattern")
    if errors:
        raise QueryTypeError("; ".join(errors))

    labels: dict[Var, str] = {}
    for p in query.where:
        if p.label is not None:
            if p.label in labels:
                errors.append(f"label {p.label} is used by two patterns")
            labels[p.label] = "positive"
    try:
        positive = query.positive_variables()
    except QueryTypeError as exc:
        raise QueryTypeError(str(exc)) from None
    if clash := sorted(str(v) for v in labels if v in positive):
        errors.append(f"labels {clash} are also used as pattern variables")

    # select / count
    if len(set(query.select)) != len(query.select):
        errors.append("a variable is selected twice")
    for var in query.select:
        if not isinstance(var, Var):
            errors.append(f"select holds a non-variable {var!r}")
        elif var not in positive:
            errors.append(f"selected variable {var} does not occur in a positive pattern"
                          + (" (labels name claims, not answers)" if var in labels else ""))
    if query.count is not None:
        if not isinstance(query.count, CountDistinct):
            errors.append("only COUNT(DISTINCT ?x) is in the fragment")
        elif query.count.var not in positive:
            errors.append(f"counted variable {query.count.var} does not occur in a positive "
                          "pattern")
        elif query.count.var in query.select:
            errors.append(f"counted variable {query.count.var} is also a grouping variable")
        if query.latest is not None:
            errors.append("a query cannot both count and select the latest state")
    elif not query.select:
        errors.append("select at least one variable")

    # filters
    for f in query.filters:
        check(_check_filter, f, positive, labels, "filter")

    # negation
    if query.negation is not None:
        neg = query.negation
        try:
            neg_vars = neg.pattern.variables()
        except QueryTypeError as exc:
            neg_vars = {}
            errors.append(str(exc))
        shared = [v for v in neg_vars if v in positive]
        if not shared:
            errors.append("the negated pattern must share a variable with the positive part")
        for var in shared:
            try:
                _join_kind(positive[var], neg_vars[var], var)
            except QueryTypeError as exc:
                errors.append(str(exc))
        if neg.pattern.label is not None:
            if neg.pattern.label in labels or neg.pattern.label in positive:
                errors.append(f"label {neg.pattern.label} of the negated pattern is already "
                              "used")
            if neg.pattern.label in neg_vars:
                errors.append(f"label {neg.pattern.label} is also a variable of the negated "
                              "pattern")
        local_labels = dict(labels)
        if neg.pattern.label is not None:
            local_labels[neg.pattern.label] = "negated"
        scope = {**neg_vars, **positive}
        for f in neg.filters:
            check(_check_filter, f, scope, local_labels, "filter inside NOT EXISTS")
        if any(v in query.select for v in neg_vars if v not in positive):
            errors.append("a variable bound only inside NOT EXISTS cannot be selected")

    # latest
    if query.latest is not None:
        if not isinstance(query.latest, Latest):
            errors.append("latest must be a Latest")
        elif query.latest.label not in labels:
            errors.append(f"LATEST names {query.latest.label}, which labels no positive pattern")
        elif not isinstance(query.latest.key, LatestKey):
            errors.append(f"LATEST key must be one of {[k.value for k in LatestKey]}")

    # temporal parameters
    check(_check_at, query.at)
    if not isinstance(query.provenance, bool):
        errors.append("provenance must be a boolean")
    if errors:
        raise QueryTypeError("; ".join(errors))


def _check_pattern(p: ClaimPattern, where: str) -> None:
    if not isinstance(p, ClaimPattern):
        raise QueryTypeError(f"{where}: expected a ClaimPattern, got {type(p).__name__}")
    if not isinstance(p.subject, (Var, Entity)):
        raise QueryTypeError(f"{where}: subject must be a variable or an entity, got "
                             f"{p.subject!r}")
    if isinstance(p.predicate, str):
        if not _PREDICATE.fullmatch(p.predicate):
            raise QueryTypeError(
                f"{where}: predicate {p.predicate!r} is not a predicate name; property paths "
                "are outside the fragment")
    elif not isinstance(p.predicate, Var):
        raise QueryTypeError(f"{where}: predicate must be a name or a variable")
    if not isinstance(p.object, (Var, Entity, Value)):
        raise QueryTypeError(f"{where}: object must be a variable, entity or literal")
    if isinstance(p.scope, str) and not isinstance(p.scope, Scope):
        if not p.scope.strip() or p.scope != p.scope.strip():
            raise QueryTypeError(f"{where}: scope {p.scope!r} is not a valid scope")
    elif not isinstance(p.scope, (Var, Scope)):
        raise QueryTypeError(f"{where}: scope must be a string, a variable, _ or default")
    a = p.attribution
    if a is not None:
        if not isinstance(a, AttributionConstraint):
            raise QueryTypeError(f"{where}: attribution must be an AttributionConstraint")
        if a.speaker is None and a.function is None:
            raise QueryTypeError(f"{where}: an attribution constraint needs a speaker or a "
                                 "function")
        if a.speaker is not None and not isinstance(a.speaker, (Var, Entity)):
            raise QueryTypeError(f"{where}: speaker must be a variable or an entity")
        if a.function is not None and not isinstance(a.function, CommunicativeFunction):
            raise QueryTypeError(f"{where}: function must be one of "
                                 f"{[f.value for f in CommunicativeFunction]}")
        for name, (attr, default) in ATTRIBUTION_DEFAULTS.items():
            value = getattr(a, attr)
            if value is not None and (value is not default or type(value) is not type(default)):
                raise QueryTypeError(
                    f"{where}: attribution {name} must be its default {default!r} or relaxed "
                    f"(None, `{name}=_`), got {value!r}; an attribution constraint can only "
                    "relax its defaults")
    if p.label is not None and not isinstance(p.label, Var):
        raise QueryTypeError(f"{where}: label must be a variable")
    p.variables()


def _check_filter(f: Filter, scope: dict[Var, str], labels: dict[Var, str], where: str) -> None:
    if not isinstance(f, Filter):
        raise QueryTypeError(f"{where}: expected a Filter")
    if not isinstance(f.op, Op):
        raise QueryTypeError(f"{where}: operator must be one of {[o.value for o in Op]}")
    if isinstance(f.right, ReadTime):
        raise QueryTypeError(
            f"{where}: comparison with the time of reading is outside the fragment (a view "
            "would go stale without any write); resolve it to an absolute time with "
            "compile.absolutize, which makes the query temporary")
    if isinstance(f.right, Var):
        raise QueryTypeError(f"{where}: filters compare only with constants, not with "
                             f"variable {f.right}")
    if not isinstance(f.right, (Entity, Value)):
        raise QueryTypeError(f"{where}: right-hand side must be a constant, got {f.right!r}")
    if isinstance(f.left, ValidBound):
        if f.left.label not in labels:
            raise QueryTypeError(f"{where}: {f.left.bound}({f.left.label}) names no pattern "
                                 "label")
        if not isinstance(f.left.bound, Bound):
            raise QueryTypeError(f"{where}: bound must be start or end")
        if not isinstance(f.right, Value) or f.right.datatype not in ("date", "dateTime"):
            raise QueryTypeError(f"{where}: valid time is compared only with an xsd:date or "
                                 "xsd:dateTime constant")
        return
    if not isinstance(f.left, Var):
        raise QueryTypeError(f"{where}: left-hand side must be a variable or start/end(?c)")
    if f.left in labels:
        raise QueryTypeError(f"{where}: {f.left} labels a claim; compare its valid time with "
                             "start() or end()")
    if f.left not in scope:
        raise QueryTypeError(f"{where}: variable {f.left} is not bound by a pattern")
    kind = scope[f.left]
    if isinstance(f.right, Entity):
        if f.op not in (Op.EQ, Op.NE):
            raise QueryTypeError(f"{where}: entities are compared only with = and !=")
        if kind in ("predicate", "scope"):
            raise QueryTypeError(f"{where}: {kind} variable {f.left} compared with an entity")
    elif kind == "predicate":
        raise QueryTypeError(f"{where}: predicate variable {f.left} cannot be filtered; put "
                             "the predicate name in the pattern")
    elif kind == "entity":
        raise QueryTypeError(f"{where}: entity variable {f.left} compared with a literal")
    elif kind == "scope" and f.right.datatype != "string":
        raise QueryTypeError(f"{where}: scope variable {f.left} compared with a non-string")


def _check_at(at: At) -> None:
    if not isinstance(at, At):
        raise QueryTypeError("AT must be an At")
    if at.known is not None and (not isinstance(at.known, int) or isinstance(at.known, bool)
                                 or at.known < 0):
        raise QueryTypeError(f"AT known must be an integer >= 0 or r, got {at.known!r}")
    if at.valid is not None:
        if isinstance(at.valid, ReadTime):
            raise QueryTypeError("AT valid relative to the time of reading is outside the "
                                 "fragment; resolve it with compile.absolutize")
        if not isinstance(at.valid, str):
            raise QueryTypeError(f"AT valid must be an xsd:date or xsd:dateTime, got "
                                 f"{at.valid!r}")
        ValidTime(start=at.valid)
    if not isinstance(at.state, State):
        raise QueryTypeError(f"AT state must be one of {[s.value for s in State]}")
