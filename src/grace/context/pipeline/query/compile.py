"""Deterministic compiler: query representation -> parameterised SPARQL (plan 5.3).

`compile_query` type-checks a `Query` and produces a `CompiledQuery` with three SPARQL texts over
the RDF encoding of the claim graph (contracts.md, "Claim graph"; `memory/graph/rdf.py`):

- `main`: one basic graph pattern per claim pattern, with version filters on every claim and
  attribution, the built-in state negation, the valid-time filter, the user's filters and the
  NOT EXISTS. It projects the answer variables and, as witness, the claim node of every positive
  pattern and the attribution node of every attribution constraint. For `LATEST` it also projects
  the ordering key.
- `count`: for COUNT(DISTINCT ?x) only, the same body under the SPARQL aggregate (restricted
  aggregation). `execute.py` derives the count from the members of `main` so that it can return
  their witnesses; tests check that the two agree.
- `evidence`: the second query that fetches the evidence links, visible at the cut-off, of the
  witness claims. Evidence is not joined into `main`, because a claim with several pieces of
  evidence would multiply its rows.

Parameters stay placeholders in the text, so one compiled query serves every read:

- `%r%` is the cut-off version, replaced by `ClaimStore.query` with the integer of the version
  read (never a SPARQL variable and never a hard-coded constant: plan 5.3).
- `%k<i>%` stands for the members of the entity-equivalence class of an entity constant at the
  cut-off; `CompiledQuery.bind` fills them (without merges, the constant itself). An entity in a
  triple position is compiled as `VALUES ?_k<j> { %k<i>% }` plus the variable `?_k<j>` in the
  triple; when its class has one member, `bind` drops the `VALUES` line and writes the IRI in
  place of the variable (same rows: a one-row `VALUES` joined on an otherwise unbound variable
  is a constant; pyoxigraph 0.5.13 evaluates the inlined form much faster, E004). Classes with
  several members keep the `VALUES` block.
- `%claims%` in `evidence` is the list of witness claim nodes.

Compilation is a pure function of the query and the serialisation mode: the same query always
gives the same text. `absolutize` turns comparisons with the time of reading into constants at
compile time and marks the query temporary (plan 3.3): it may answer a read, never define a view.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from grace.context.memory.graph import rdf
from grace.context.memory.graph.entries import Entity, Value
from grace.context.memory.graph.vocabulary import GRACE, XSD
from grace.context.pipeline.query.ir import (
    Bound,
    ClaimPattern,
    Filter,
    LatestKey,
    NotExists,
    Op,
    Query,
    QueryTypeError,
    ReadTime,
    Scope,
    State,
    ValidBound,
    Var,
    typecheck,
)

CUTOFF = "%r%"
CLAIMS = "%claims%"
KEY = "_key"
COUNT = "_count"


@dataclass(frozen=True)
class PatternSlot:
    """Where the witness of one positive pattern appears in the rows of `main`."""

    label: str                    # claim-node variable (the pattern's label)
    attribution: str | None       # attribution-node variable, if the pattern has a constraint


@dataclass(frozen=True)
class CompiledQuery:
    query: Query                  # the labelled, type-checked query
    mode: rdf.Mode
    main: str
    count: str | None
    evidence: str
    answer_vars: tuple[str, ...]  # SPARQL names of the answer columns, in order
    slots: tuple[PatternSlot, ...]
    key: str | None               # ordering-key column for LATEST
    constants: tuple[tuple[str, str, str], ...]  # (placeholder, entity ID, separator)
    # (placeholder, variable) of every constant bound by `VALUES ?variable { placeholder }`
    values_vars: tuple[tuple[str, str], ...] = ()

    def bind(self, classes: Mapping[str, Sequence[str]] | None = None, *,
             inline: bool = True) -> tuple[str, str | None]:
        """`main` and `count` with every entity constant replaced by its class members.

        `classes` maps an entity ID to the members of its equivalence class at the cut-off;
        entities not in it stand for themselves. `%r%` is left for `ClaimStore.query`. With
        `inline` (the default), a `VALUES`-bound constant whose class has one member is written
        directly into its triples; `inline=False` keeps every `VALUES` block (the form compiled
        before E004, kept for equivalence tests and diagnostics).
        """
        classes = classes or {}
        values_vars = dict(self.values_vars)
        texts = [self.main, self.count]
        for placeholder, entity, sep in self.constants:
            members = sorted(set(classes.get(entity, ())) | {entity})
            iris = [_iri_ref(m) for m in members]
            var = values_vars.get(placeholder)
            if inline and var is not None and len(iris) == 1:
                texts = [_inline(t, placeholder, var, iris[0]) if t is not None else None
                         for t in texts]
                continue
            value = sep.join(iris)
            texts = [t.replace(placeholder, value) if t is not None else None for t in texts]
        return texts[0], texts[1]


# Characters that may not occur in a SPARQL IRIREF (SPARQL 1.1, production 139).
_IRI_FORBIDDEN = re.compile(r'[\x00-\x20<>"{}|^`\\]')


def _iri_ref(entity_id: str) -> str:
    """`<iri>` of an entity, refused if the IRI could break out of the IRI reference.

    `rdf.entity_iri` percent-encodes the ID, so this never fires for IDs built through it; the
    check guards the text substitution in `bind` against a future change of that encoding.
    """
    iri = rdf.entity_iri(entity_id).value
    if _IRI_FORBIDDEN.search(iri):
        raise ValueError(f"entity {entity_id!r} gives an IRI that is not a valid IRIREF: {iri!r}")
    return f"<{iri}>"


def _inline(text: str, placeholder: str, var: str, iri: str) -> str:
    """Drop the line `VALUES ?var { placeholder }` and write `iri` for every `?var`.

    The variable name is compiler-generated (`_k<j>`, unique per constant) and literals escape
    `?` and `%` (`_literal`), so `?var` occurs only as that variable.
    """
    line = re.compile(rf"^[ \t]*VALUES \?{var} \{{ {re.escape(placeholder)} \}}\n", re.MULTILINE)
    text, n = line.subn("", text)
    if n != 1:
        raise ValueError(f"expected one VALUES block for ?{var}, found {n}")
    return re.sub(rf"\?{var}(?![A-Za-z0-9_])", lambda _: iri, text)


# ---------------------------------------------------------------------------------------------
# SPARQL fragments


def _literal(value: Value) -> str:
    # `%` and `?` are written as code-point escapes so that a literal can never contain a
    # placeholder (`%r%`, `%k<i>%`) or a compiler variable that `bind` substitutes.
    text = (value.lexical.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            .replace("%", "\\u0025").replace("?", "\\u003F"))
    return f'"{text}"^^<{XSD}{value.datatype}>'


def _time(value: str) -> str:
    return _literal(Value(value, "dateTime" if "T" in value else "date"))


# Vocabulary terms are written with the prefixes that `ClaimStore.query` predeclares.
_G = {name: f"g:{name}" for name in rdf.G}
KNOWN = "g:knownFrom"
CHANGE = "g:Change"
CORRECTION = "g:Correction"


def _function(function) -> str:
    return f"gf:{function.value}"


def _concept(value) -> str:
    """A report-mode or polarity concept, in the `g:` prefix (memory/graph/rdf.py, CONCEPTS)."""
    iri = rdf.CONCEPTS[value].value
    if not iri.startswith(GRACE):
        raise ValueError(f"concept {value!r} is not in the g: namespace: {iri}")
    return "g:" + iri[len(GRACE):]


def _predicate(name: str) -> str:
    return f"gp:{name}"  # predicate names are [A-Za-z][A-Za-z0-9_]* (type-checked)


class _Body:
    """Accumulates the lines of one group graph pattern."""

    def __init__(self, compiler: _Compiler, indent: str):
        self.c = compiler
        self.indent = indent
        self.lines: list[str] = []

    def add(self, line: str) -> None:
        self.lines.append(self.indent + line)

    def term(self, term) -> str:
        if isinstance(term, Var):
            return f"?{term.name}"
        if isinstance(term, Entity):
            var = self.c.fresh("_k")
            self.add(f"VALUES ?{var} {{ {self.c.constant(term, ' ', var)} }}")
            return f"?{var}"
        if isinstance(term, Value):
            return _literal(term)
        if isinstance(term, str):
            return _predicate(term)
        raise TypeError(f"cannot compile term {term!r}")

    def pattern(self, p: ClaimPattern) -> str | None:
        """Triples of one claim pattern with version filters; returns the attribution var."""
        c = f"?{p.label.name}"
        n = p.label.name
        s, pr, o = self.term(p.subject), self.term(p.predicate), self.term(p.object)
        if self.c.mode == "rdf11":
            self.add(f"{c} rdf:subject {s} ; rdf:predicate {pr} ; rdf:object {o} ; "
                     f"{KNOWN} ?_v_{n} .")
        else:
            self.add(f"{c} rdf:reifies <<( {s} {pr} {o} )>> ; {KNOWN} ?_v_{n} .")
        self.add(f"FILTER(?_v_{n} <= {CUTOFF})")
        if isinstance(p.scope, Var):
            self.add(f"{c} {_G['scope']} ?{p.scope.name} .")
        elif p.scope is Scope.DEFAULT:
            self.add(f"FILTER NOT EXISTS {{ {c} {_G['scope']} ?_sc_{n} }}")
        elif p.scope is not Scope.ANY:
            self.add(f"{c} {_G['scope']} {_literal(Value(p.scope))} .")
        att = None
        if p.attribution is not None:
            att = f"_a_{n}"
            parts = [f"?{att} {_G['about']} {c}"]
            if p.attribution.speaker is not None:
                parts.append(f"prov:wasAttributedTo {self.term(p.attribution.speaker)}")
            if p.attribution.function is not None:
                parts.append(f"{_G['function']} {_function(p.attribution.function)}")
            # Defaults of [u, f] (plan 3.3): own statement, positive, not derived; each may be
            # relaxed (None), which drops its triple.
            if p.attribution.report_mode is not None:
                parts.append(f"{_G['reportMode']} {_concept(p.attribution.report_mode)}")
            if p.attribution.polarity is not None:
                parts.append(f"{_G['polarity']} {_concept(p.attribution.polarity)}")
            if p.attribution.derived is not None:
                parts.append(f"{_G['derived']} "
                             f"{_literal(Value(str(p.attribution.derived).lower(), 'boolean'))}")
            parts.append(f"{KNOWN} ?_w_{n}")
            self.add(" ; ".join(parts) + " .")
            self.add(f"FILTER(?_w_{n} <= {CUTOFF})")
        self.state(p)
        if self.c.query.at.valid is not None:
            self.valid_at(p, self.c.query.at.valid)
        return att

    def state(self, p: ClaimPattern) -> None:
        """Built-in negation: "currently accepted", or its historical (correction-only) form."""
        n = p.label.name
        kind = f" ; {_G['kind']} {CORRECTION}" if self.c.query.at.state is State.HISTORICAL else ""
        self.add(f"FILTER NOT EXISTS {{ ?_s_{n} {_G['supersedes']} ?{n}{kind} ; "
                 f"{KNOWN} ?_sv_{n} . FILTER(?_sv_{n} <= {CUTOFF}) }}")

    def earliest_change_end(self, n: str, tag: str) -> str:
        """Pattern binding `?_ee{tag}` to the valid end of the earliest change supersession of
        claim `?n` stamped <= r that states one (contracts.md, "Claim graph")."""
        s, e, v = f"?_es{tag}", f"?_ee{tag}", f"?_ev{tag}"
        s2, e2, v2 = f"?_es2{tag}", f"?_ee2{tag}", f"?_ev2{tag}"
        sup = f"{_G['supersedes']} ?{n} ; {_G['kind']} {CHANGE} ; {_G['validEnd']}"
        return (f"{s} {sup} {e} ; {KNOWN} {v} . FILTER({v} <= {CUTOFF}) "
                f"FILTER NOT EXISTS {{ {s2} {sup} {e2} ; {KNOWN} {v2} . "
                f"FILTER({v2} <= {CUTOFF} && ({v2} < {v} || "
                f"({v2} = {v} && STR({s2}) < STR({s})))) }}")

    def valid_at(self, p: ClaimPattern, valid: str) -> None:
        """Keep the claim unless it is known to be outside [start, effective end) at `valid`."""
        n, d = p.label.name, _time(valid)
        self.add(f"FILTER NOT EXISTS {{ ?{n} {_G['validFrom']} ?_vs_{n} . "
                 f"FILTER(?_vs_{n} > {d}) }}")
        self.add(f"FILTER NOT EXISTS {{ ?{n} {_G['validUntil']} ?_vu_{n} . "
                 f"FILTER(?_vu_{n} <= {d}) }}")
        tag = f"_at_{n}"
        self.add(f"FILTER(EXISTS {{ ?{n} {_G['validUntil']} ?_vo_{n} }} || NOT EXISTS {{ "
                 f"{self.earliest_change_end(n, tag)} FILTER(?_ee{tag} <= {d}) }})")

    def filter(self, f: Filter) -> None:
        op = f.op.value
        if isinstance(f.left, ValidBound):
            n, d = f.left.label.name, _time(f.right.lexical)
            j = self.c.fresh("")
            if f.left.bound is Bound.START:
                self.add(f"FILTER EXISTS {{ ?{n} {_G['validFrom']} ?_fs{j} . "
                         f"FILTER(?_fs{j} {op} {d}) }}")
                return
            open_end = "true" if f.op in (Op.GT, Op.GE, Op.NE) else "false"
            tag = f"_f{j}"
            self.add(
                f"FILTER(EXISTS {{ ?{n} {_G['validUntil']} ?_fe{j} . FILTER(?_fe{j} {op} {d}) }}"
                f" || (NOT EXISTS {{ ?{n} {_G['validUntil']} ?_fo{j} }} && ("
                f"EXISTS {{ {self.earliest_change_end(n, tag)} FILTER(?_ee{tag} {op} {d}) }}"
                f" || (NOT EXISTS {{ ?_fx{j} {_G['supersedes']} ?{n} ; {_G['kind']} {CHANGE} ; "
                f"{_G['validEnd']} ?_fy{j} ; {KNOWN} ?_fz{j} . FILTER(?_fz{j} <= {CUTOFF}) }}"
                f" && {open_end}))))")
            return
        left = f"?{f.left.name}"
        if isinstance(f.right, Entity):
            neg = "NOT " if f.op is Op.NE else ""
            self.add(f"FILTER({left} {neg}IN ({self.c.constant(f.right, ', ')}))")
        else:
            self.add(f"FILTER({left} {op} {_literal(f.right)})")


class _Compiler:
    def __init__(self, query: Query, mode: rdf.Mode):
        self.query = query
        self.mode = mode
        self.counter = 0
        self.constants: list[tuple[str, str, str]] = []
        self.values_vars: list[tuple[str, str]] = []

    def fresh(self, prefix: str) -> str:
        name = f"{prefix}{self.counter}"
        self.counter += 1
        return name

    def constant(self, entity: Entity, sep: str, var: str | None = None) -> str:
        placeholder = f"%k{len(self.constants)}%"
        self.constants.append((placeholder, entity.id, sep))
        if var is not None:
            self.values_vars.append((placeholder, var))
        return placeholder

    def body(self) -> tuple[list[str], list[PatternSlot]]:
        q = self.query
        body = _Body(self, "  ")
        slots = []
        for p in q.where:
            att = body.pattern(p)
            slots.append(PatternSlot(p.label.name, att))
        for f in q.filters:
            body.filter(f)
        if q.negation is not None:
            body.lines.extend(self.negation(q.negation))
        if q.latest is not None:
            n = q.latest.label.name
            if q.latest.key is LatestKey.VALID:
                body.add(f"?{n} {_G['validFrom']} ?{KEY} .")
            else:
                slot = next(s for s in slots if s.label == n)
                if slot.attribution:
                    body.add(f"BIND(IF(?_w_{n} > ?_v_{n}, ?_w_{n}, ?_v_{n}) AS ?{KEY})")
                else:
                    body.add(f"BIND(?_v_{n} AS ?{KEY})")
        return body.lines, slots

    def negation(self, neg: NotExists) -> list[str]:
        inner = _Body(self, "    ")
        inner.pattern(neg.pattern)
        for f in neg.filters:
            inner.filter(f)
        return ["  FILTER NOT EXISTS {", *inner.lines, "  }"]


def compile_query(query: Query, mode: rdf.Mode = "rdf11") -> CompiledQuery:
    """Type-check `query` and compile it for a store with serialisation `mode`."""
    if mode not in rdf.MODES:
        raise ValueError(f"unknown serialisation mode {mode!r}; expected one of {rdf.MODES}")
    typecheck(query)
    query = query.labelled()
    c = _Compiler(query, mode)
    lines, slots = c.body()
    answer = [v.name for v in query.select]
    if query.count is not None:
        answer.append(query.count.var.name)
    witness = []
    for s in slots:
        witness.append(s.label)
        if s.attribution:
            witness.append(s.attribution)
    key = KEY if query.latest is not None else None
    projected = " ".join(f"?{v}" for v in (*answer, *witness, *([key] if key else [])))
    body = "\n".join(lines)
    main = f"SELECT DISTINCT {projected} WHERE {{\n{body}\n}}"
    if key:
        main += f"\nORDER BY DESC(?{KEY})"
    count = None
    if query.count is not None:
        groups = " ".join(f"?{v.name}" for v in query.select)
        count = (f"SELECT {groups + ' ' if groups else ''}"
                 f"(COUNT(DISTINCT ?{query.count.var.name}) AS ?{COUNT}) WHERE {{\n{body}\n}}")
        if groups:
            count += f"\nGROUP BY {groups}"
    return CompiledQuery(query=query, mode=mode, main=main, count=count,
                         evidence=evidence_query(), answer_vars=tuple(answer),
                         slots=tuple(slots), key=key, constants=tuple(c.constants),
                         values_vars=tuple(c.values_vars))


def evidence_query() -> str:
    """The second query: evidence links, visible at the cut-off, of the claims in `%claims%`."""
    return (
        "SELECT ?_claim ?_evidence ?_message ?_start ?_end WHERE {\n"
        f"  VALUES ?_claim {{ {CLAIMS} }}\n"
        f"  ?_evidence {_G['supports']} ?_claim ; prov:wasDerivedFrom ?_message ; "
        f"{KNOWN} ?_ev .\n"
        f"  FILTER(?_ev <= {CUTOFF})\n"
        f"  OPTIONAL {{ ?_evidence oa:hasSelector ?_sel . ?_sel oa:start ?_start ; "
        "oa:end ?_end . }\n"
        "}")


# ---------------------------------------------------------------------------------------------
# Relative time


def _time_lexical(t: _dt.date | _dt.datetime) -> Value:
    if isinstance(t, _dt.datetime):
        text = t.isoformat(timespec="seconds")
        return Value(text.replace("+00:00", "Z") if t.utcoffset() == _dt.timedelta(0)
                     else text, "dateTime")
    return Value(t.isoformat(), "date")


def absolutize(query: Query, read_time: _dt.date | _dt.datetime) -> Query:
    """Replace every `now(offset)` by the absolute time `read_time + offset days`.

    The result is marked temporary: it runs only as a temporary query while answering and is
    never stored as a view, since its meaning depends on when it was compiled (plan 3.3).
    """
    if not isinstance(read_time, (_dt.date, _dt.datetime)):
        raise QueryTypeError(f"read_time must be a date or datetime, got {read_time!r}")
    changed = False

    def fix(filters: tuple[Filter, ...]) -> tuple[Filter, ...]:
        nonlocal changed
        out = []
        for f in filters:
            if isinstance(f.right, ReadTime):
                changed = True
                f = Filter(f.left, f.op,
                           _time_lexical(read_time + _dt.timedelta(days=f.right.offset_days)))
            out.append(f)
        return tuple(out)

    negation = query.negation
    if negation is not None:
        negation = NotExists(negation.pattern, fix(negation.filters))
    out = replace(query, filters=fix(query.filters), negation=negation)
    return replace(out, temporary=True) if changed else out
