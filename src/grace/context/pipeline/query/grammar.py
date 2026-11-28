"""Text form of the query intermediate representation: parser and printer.

The grammar (EBNF and examples) is in docs/research/query-ir.md. Example:

    SELECT ?train WHERE {
      (request1, selectedService, ?train) [user, accept] AS ?c
    } AT(known=r, state=current)

`parse` rejects SPARQL constructs outside the fragment with a `QueryTypeError` that names the
construct (property paths, OPTIONAL, UNION, nested negation, aggregates other than
COUNT(DISTINCT ...), comparisons between variables) and then runs `ir.typecheck` unless
`check=False` (needed before `compile.absolutize` resolves `now(...)`). `to_text` prints the
canonical form; `parse(to_text(q)) == q` for every query whose labels are not reserved (labels
starting with `_` are assigned by the compiler and are not printed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

from grace.context.memory.graph.entries import (
    CommunicativeFunction,
    Entity,
    EntryError,
    Value,
    time_datatype,
)
from grace.context.pipeline.query.ir import (
    ATTRIBUTION_DEFAULTS,
    At,
    AttributionConstraint,
    Bound,
    ClaimPattern,
    CountDistinct,
    Filter,
    Latest,
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

_TOKEN = re.compile(r"""
    (?P<ws>\s+|\#[^\n]*)
  | (?P<var>\?[A-Za-z_][A-Za-z0-9_]*)
  | (?P<iri><[^<>\s()"{}\[\],]+>)
  | (?P<string>"(?:[^"\\]|\\.)*"(?:\^\^[A-Za-z]+)?)
  | (?P<number>-?\d+(?![A-Za-z0-9_\-]))   # not the start of a name such as "50mm" (E013)
  | (?P<name>[A-Za-z0-9_][A-Za-z0-9_\-]*)
  | (?P<op>!=|<=|>=|&&|\|\||[=<>(){}\[\],./|+*^!])
""", re.VERBOSE)

_AGGREGATES = {"SUM", "AVG", "MIN", "MAX", "SAMPLE", "GROUP_CONCAT"}
_OUTSIDE = {"OPTIONAL", "UNION", "MINUS", "BIND", "SERVICE", "GRAPH", "VALUES", "ORDER",
            "LIMIT", "OFFSET", "HAVING", "GROUP", "CONSTRUCT", "ASK", "DESCRIBE"}
_READ_TIME = {"NOW", "TODAY"}
_PATH_OPS = {"/", "|", "+", "*", "^", "!"}
_DATATYPES = {"string", "integer", "boolean", "date", "dateTime", "time"}


@dataclass
class _Tok:
    kind: str
    text: str
    pos: int

    @property
    def upper(self) -> str:
        return self.text.upper() if self.kind == "name" else ""


def _tokens(text: str) -> list[_Tok]:
    out, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise QueryTypeError(f"unexpected character {text[pos]!r} at offset {pos}")
        if m.lastgroup != "ws":
            out.append(_Tok(m.lastgroup, m.group(), pos))
        pos = m.end()
    out.append(_Tok("end", "", pos))
    return out


class _Parser:
    def __init__(self, text: str):
        self.toks = _tokens(text)
        self.i = 0

    # -- helpers -------------------------------------------------------------------------------

    @property
    def tok(self) -> _Tok:
        return self.toks[self.i]

    def peek(self, k: int = 1) -> _Tok:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self) -> _Tok:
        tok = self.tok
        self.i += 1
        return tok

    def error(self, message: str, tok: _Tok | None = None) -> QueryTypeError:
        tok = tok or self.tok
        found = tok.text or "end of input"
        return QueryTypeError(f"{message} at offset {tok.pos} (found {found!r})")

    def expect(self, text: str) -> _Tok:
        tok = self.tok
        if tok.text != text and tok.upper != text:
            raise self.error(f"expected {text!r}")
        return self.next()

    def accept(self, text: str) -> bool:
        if self.tok.text == text or self.tok.upper == text:
            self.i += 1
            return True
        return False

    def keyword_guard(self) -> None:
        """Reject keywords of constructs outside the fragment with a specific message."""
        up = self.tok.upper
        if up in _AGGREGATES and self.peek().text == "(":
            raise self.error(f"aggregate {up} is outside the fragment; only COUNT(DISTINCT ?x) "
                             "is allowed")
        if up in _OUTSIDE:
            raise self.error(f"{up} is outside the fragment (basic graph patterns, one "
                             "NOT EXISTS, filters against constants only)")
        if up in _READ_TIME and self.peek().text != "(":
            raise self.error(f"{up} (the time of reading) is outside the fragment")

    # -- grammar -------------------------------------------------------------------------------

    def query(self) -> Query:
        self.expect("SELECT")
        select: list[Var] = []
        count = None
        while self.tok.kind == "var" or self.tok.upper in {"COUNT", *_AGGREGATES}:
            if self.tok.kind == "var":
                select.append(self.var())
                continue
            self.keyword_guard()
            if count is not None:
                raise self.error("only one COUNT(DISTINCT ...) per query")
            count = self.count()
        if self.tok.text == "*":
            raise self.error("SELECT * is not allowed; name the answer variables")
        self.expect("WHERE")
        where, filters, negation = self.group()
        latest = None
        at = At()
        provenance, temporary = True, False
        while self.tok.kind != "end":
            self.keyword_guard()
            if self.accept("LATEST"):
                if latest is not None:
                    raise self.error("only one LATEST per query")
                latest = self.latest()
            elif self.accept("AT"):
                at = self.at()
            elif self.accept("WITHOUT"):
                self.expect("PROVENANCE")
                provenance = False
            elif self.accept("WITH"):
                self.expect("PROVENANCE")
            elif self.accept("TEMPORARY"):
                temporary = True
            else:
                raise self.error("expected LATEST, AT, WITH PROVENANCE, WITHOUT PROVENANCE or "
                                 "end of query")
        return Query(tuple(select), tuple(where), tuple(filters), negation, count, latest, at,
                     provenance, temporary)

    def count(self) -> CountDistinct:
        self.expect("COUNT")
        self.expect("(")
        if not self.accept("DISTINCT"):
            raise self.error("only COUNT(DISTINCT ?x) is in the fragment")
        if self.tok.text == "*":
            raise self.error("COUNT(DISTINCT *) is not allowed; count one variable")
        var = self.var()
        self.expect(")")
        return CountDistinct(var)

    def group(self):
        self.expect("{")
        where: list[ClaimPattern] = []
        filters: list[Filter] = []
        negation = None
        expect_pattern = True
        while not self.accept("}"):
            self.keyword_guard()
            if self.tok.text == "(":
                if not expect_pattern:
                    raise self.error("separate claim patterns with '.'")
                where.append(self.pattern())
                expect_pattern = self.accept(".")
            elif self.accept("FILTER"):
                if self.tok.upper == "NOT" or self.tok.upper == "EXISTS":
                    raise self.error("write negation as NOT EXISTS { ... }")
                filters.append(self.filter())
                expect_pattern = True
            elif self.accept("NOT"):
                if negation is not None:
                    raise self.error("only one NOT EXISTS per query")
                self.expect("EXISTS")
                negation = self.negated()
                expect_pattern = True
            elif self.tok.kind == "end":
                raise self.error("unterminated WHERE block")
            elif self.tok.text == "{":
                raise self.error("nested groups are outside the fragment")
            elif self.tok.kind in ("var", "name", "iri"):
                raise self.error("write a claim pattern as (s, p, o) or (s, p, o, scope); "
                                 "triple patterns are outside the fragment")
            else:
                raise self.error("expected a claim pattern, FILTER or NOT EXISTS")
        return where, filters, negation

    def negated(self) -> NotExists:
        self.expect("{")
        pattern = None
        filters: list[Filter] = []
        while not self.accept("}"):
            self.keyword_guard()
            if self.tok.text == "(":
                if pattern is not None:
                    raise self.error("NOT EXISTS ranges over exactly one claim pattern")
                pattern = self.pattern()
                self.accept(".")
            elif self.accept("FILTER"):
                filters.append(self.filter())
            elif self.tok.upper == "NOT":
                raise self.error("nested negation is outside the fragment")
            else:
                raise self.error("expected the negated claim pattern or a FILTER")
        if pattern is None:
            raise self.error("NOT EXISTS needs one claim pattern")
        return NotExists(pattern, tuple(filters))

    def pattern(self) -> ClaimPattern:
        self.expect("(")
        subject = self.entity_or_var("subject")
        self.expect(",")
        predicate = self.predicate()
        self.expect(",")
        obj = self.object()
        scope: object = Scope.ANY
        if self.accept(","):
            scope = self.scope()
        self.expect(")")
        attribution = None
        if self.accept("["):
            speaker = None if self.accept("_") else self.entity_or_var("speaker")
            self.expect(",")
            function = None
            if not self.accept("_"):
                tok = self.next()
                try:
                    function = CommunicativeFunction(tok.text.lower())
                except ValueError:
                    raise self.error("unknown communicative function; expected one of "
                                     f"{[f.value for f in CommunicativeFunction]} or _",
                                     tok) from None
            relaxed: dict[str, None] = {}
            while self.accept(","):
                tok = self.next()
                name = tok.text.lower() if tok.kind == "name" else ""
                if name not in ATTRIBUTION_DEFAULTS:
                    raise self.error("expected a relaxed default of the attribution constraint "
                                     f"({', '.join(f'{n}=_' for n in ATTRIBUTION_DEFAULTS)})",
                                     tok)
                if ATTRIBUTION_DEFAULTS[name][0] in relaxed:
                    raise self.error(f"{name} is relaxed twice", tok)
                self.expect("=")
                if not self.accept("_"):
                    raise self.error(f"{name} can only be relaxed to _ (any); an attribution "
                                     "constraint cannot require a non-default value")
                relaxed[ATTRIBUTION_DEFAULTS[name][0]] = None
            self.expect("]")
            attribution = AttributionConstraint(speaker, function, **relaxed)
        label = None
        if self.accept("AS"):
            label = self.var()
        return ClaimPattern(subject, predicate, obj, scope, attribution, label)

    def var(self) -> Var:
        tok = self.next()
        if tok.kind != "var":
            raise self.error("expected a variable", tok)
        if tok.text[1] == "_":
            raise self.error("variables starting with _ are reserved for the compiler", tok)
        return Var(tok.text[1:])

    def entity(self) -> Entity:
        tok = self.next()
        if tok.kind == "iri":
            return Entity(unquote(tok.text[1:-1]))
        if tok.kind in ("name", "number"):
            return Entity(tok.text)
        raise self.error("expected an entity", tok)

    def entity_or_var(self, what: str):
        if self.tok.kind == "var":
            return self.var()
        if self.tok.kind == "string":
            raise self.error(f"{what} must be an entity or a variable, not a literal")
        return self.entity()

    def predicate(self):
        tok = self.tok
        if tok.text in _PATH_OPS:
            raise self.error("property paths are outside the fragment")
        if tok.kind == "var":
            value = self.var()
        elif tok.kind == "name":
            value = self.next().text
        else:
            raise self.error("expected a predicate name or a variable")
        if self.tok.text in _PATH_OPS:
            raise self.error("property paths are outside the fragment")
        if isinstance(value, str) and "-" in value:
            raise self.error("predicate names are [A-Za-z][A-Za-z0-9_]*", tok)
        return value

    def literal(self) -> Value:
        tok = self.next()
        if tok.kind == "number":
            return Value(tok.text, "integer")
        if tok.kind == "name" and tok.text in ("true", "false"):
            return Value(tok.text, "boolean")
        if tok.kind != "string":
            raise self.error("expected a literal", tok)
        body, _, dt = tok.text.rpartition('"^^') if '"^^' in tok.text else (tok.text[:-1], "", "")
        lexical = _unescape(body[1:] if body.startswith('"') else body)
        datatype = dt or "string"
        if datatype not in _DATATYPES:
            raise self.error(f"unknown datatype {datatype!r}; expected one of "
                             f"{sorted(_DATATYPES)}", tok)
        try:
            return Value(lexical, datatype)
        except EntryError as exc:
            raise self.error(str(exc), tok) from None

    def object(self):
        if self.tok.kind == "var":
            return self.var()
        if self.tok.kind in ("string", "number") or self.tok.text in ("true", "false"):
            return self.literal()
        return self.entity()

    def scope(self):
        if self.accept("_"):
            return Scope.ANY
        if self.tok.text == "default":
            self.next()
            return Scope.DEFAULT
        if self.tok.kind == "var":
            return self.var()
        value = self.literal()
        if value.datatype != "string":
            raise self.error("scope must be a string, a variable, _ or default")
        return value.lexical

    def filter(self) -> Filter:
        self.expect("(")
        if self.tok.upper in ("START", "END") and self.peek().text == "(":
            bound = Bound(self.next().text.lower())
            self.expect("(")
            left: object = ValidBound(self.var(), bound)
            self.expect(")")
        elif self.tok.kind == "var":
            left = self.var()
        else:
            self.keyword_guard()
            raise self.error("a filter compares a variable or start(?c)/end(?c) with a constant")
        tok = self.next()
        try:
            op = Op(tok.text)
        except ValueError:
            raise self.error(f"expected one of {[o.value for o in Op]}", tok) from None
        right: object
        if self.tok.kind == "var":
            right = self.var()  # rejected by the type checker with its own message
        elif self.tok.upper in _READ_TIME and self.peek().text == "(":
            self.next()
            self.expect("(")
            offset = 0
            if self.tok.kind == "number":
                offset = int(self.next().text)
            self.expect(")")
            right = ReadTime(offset)
        elif self.tok.kind in ("string", "number") or self.tok.text in ("true", "false"):
            right = self.literal()
        else:
            right = self.entity()
        if self.tok.text in ("&&", "||"):
            raise self.error("one comparison per FILTER; write several FILTERs for a "
                             "conjunction (disjunction is outside the fragment)")
        self.expect(")")
        return Filter(left, op, right)

    def latest(self) -> Latest:
        self.expect("BY")
        tok = self.next()
        try:
            key = LatestKey(tok.text.lower())
        except ValueError:
            raise self.error("LATEST BY takes version or valid", tok) from None
        self.expect("OF")
        return Latest(self.var(), key)

    def at(self) -> At:
        self.expect("(")
        known, valid, state = None, None, State.CURRENT
        seen: set[str] = set()
        while not self.accept(")"):
            if seen:
                self.expect(",")
            key = self.next()
            name = key.text.lower()
            if name in seen or name not in ("known", "valid", "state"):
                raise self.error("AT takes known=, valid= and state=, each once", key)
            seen.add(name)
            self.expect("=")
            if name == "known":
                if self.accept("r"):
                    known = None
                else:
                    tok = self.next()
                    if tok.kind != "number":
                        raise self.error("known= takes a version number or r", tok)
                    known = int(tok.text)
            elif name == "valid":
                if self.tok.upper in _READ_TIME:
                    raise self.error("valid time relative to the time of reading is outside "
                                     "the fragment")
                tok = self.tok
                value = self.literal()
                if value.datatype == "string":
                    try:
                        value = Value(value.lexical, time_datatype(value.lexical))
                    except EntryError as exc:
                        raise self.error(str(exc), tok) from None
                if value.datatype not in ("date", "dateTime"):
                    raise self.error("valid= takes an xsd:date or xsd:dateTime", tok)
                valid = value.lexical
            else:
                tok = self.next()
                try:
                    state = State(tok.text.lower())
                except ValueError:
                    raise self.error("state= takes current or historical", tok) from None
        return At(known, valid, state)


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), text)


def parse(text: str, *, check: bool = True) -> Query:
    """Parse the text form; run the type checker unless `check=False`."""
    parser = _Parser(text)
    query = parser.query()
    if check:
        typecheck(query)
    return query


# ---------------------------------------------------------------------------------------------
# Printer

_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-]*")
_KEYWORDS = {"true", "false", "default", "_", "r"}


def _entity_text(entity: Entity) -> str:
    if _NAME.fullmatch(entity.id) and entity.id not in _KEYWORDS and \
            not re.fullmatch(r"-?\d+", entity.id):
        return entity.id
    return f"<{quote(entity.id, safe='')}>"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def _literal_text(value: Value) -> str:
    if value.datatype == "integer":
        return value.lexical
    if value.datatype == "boolean":
        return value.lexical
    suffix = "" if value.datatype == "string" else f"^^{value.datatype}"
    return f'"{_escape(value.lexical)}"{suffix}'


def _term_text(term) -> str:
    if isinstance(term, Var):
        return str(term)
    if isinstance(term, Entity):
        return _entity_text(term)
    if isinstance(term, Value):
        return _literal_text(term)
    if isinstance(term, ReadTime):
        return f"now({term.offset_days})" if term.offset_days else "now()"
    if isinstance(term, Scope):
        return term.value
    if isinstance(term, str):
        return term
    raise TypeError(f"cannot print {term!r}")


def _pattern_text(p: ClaimPattern) -> str:
    parts = [_term_text(p.subject), _term_text(p.predicate), _term_text(p.object)]
    if p.scope is not Scope.ANY:
        scope = p.scope
        parts.append(_term_text(scope) if isinstance(scope, (Var, Scope))
                     else _literal_text(Value(scope)))
    text = "(" + ", ".join(parts) + ")"
    if p.attribution is not None:
        a = p.attribution
        speaker = "_" if a.speaker is None else _term_text(a.speaker)
        function = "_" if a.function is None else a.function.value
        relax = "".join(f", {name}=_" for name in a.relaxed())
        text += f" [{speaker}, {function}{relax}]"
    if p.label is not None and not p.label.name.startswith("_"):
        text += f" AS {p.label}"  # reserved labels are the compiler's and are not printed
    return text


def _filter_text(f: Filter) -> str:
    left = (f"{f.left.bound.value}({f.left.label})" if isinstance(f.left, ValidBound)
            else str(f.left))
    return f"FILTER({left} {f.op.value} {_term_text(f.right)})"


def to_text(query: Query) -> str:
    """Canonical text form of a query (one clause per line)."""
    head = " ".join(str(v) for v in query.select)
    if query.count is not None:
        head = (head + " " if head else "") + f"COUNT(DISTINCT {query.count.var})"
    lines = [f"SELECT {head} WHERE {{"]
    lines += [f"  {_pattern_text(p)}" + (" ." if i < len(query.where) - 1 else "")
              for i, p in enumerate(query.where)]
    lines += [f"  {_filter_text(f)}" for f in query.filters]
    if query.negation is not None:
        inner = " ".join([_pattern_text(query.negation.pattern),
                          *(_filter_text(f) for f in query.negation.filters)])
        lines.append(f"  NOT EXISTS {{ {inner} }}")
    lines.append("}")
    if query.latest is not None:
        lines.append(f"LATEST BY {query.latest.key.value} OF {query.latest.label}")
    at = query.at
    parts = [f"known={'r' if at.known is None else at.known}"]
    if at.valid is not None:
        parts.append(f'valid="{at.valid}"^^{time_datatype(at.valid)}')
    parts.append(f"state={at.state.value}")
    lines.append(f"AT({', '.join(parts)})")
    if not query.provenance:
        lines.append("WITHOUT PROVENANCE")
    if query.temporary:
        lines.append("TEMPORARY")
    return "\n".join(lines)
