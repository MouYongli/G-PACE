"""Mapping between claim-graph entries and RDF triples (contracts.md, "Claim graph").

Two serialisations of a claim node, chosen per store:

- `rdf11` (main configuration): RDF 1.1 standard reification, `?c rdf:subject s ; rdf:predicate p ;
  rdf:object o`, typed `rdf:Statement`.
- `rdf12`: RDF 1.2 reifier, `?c rdf:reifies <<( s p o )>>`.

In both, the reified triple `s p o` is never asserted, and every other triple is identical, so the
two differ only in the claim's proposition triples. Every entry is a named node under `gx:` whose
IRI encodes its kind and ID; every entry node carries `g:knownFrom` with its version stamp, which
is what reads at a cut-off version filter on. `entries_from_triples` inverts the mapping exactly
and rejects any triple it would not produce.

An entity label (contract version 0.3) is an entry node of its own, `gx:label/<id> a g:EntityLabel ;
g:knownFrom v ; g:labelOf <entity> ; rdfs:label "name"`, so that it is version-stamped like every
other entry. The entity node itself carries no `rdfs:label`: a triple on it could not be filtered
by cut-off.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Literal as TypingLiteral
from urllib.parse import quote, unquote

import pyoxigraph as ox

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entities import EntityEquivalence, EntityLabel
from grace.context.memory.graph.entries import (
    Attribution,
    Certainty,
    Claim,
    CommunicativeFunction,
    Entity,
    Entry,
    EntryError,
    EvidenceLink,
    Polarity,
    ReportMode,
    Span,
    Supersession,
    SupersessionKind,
    Term,
    ValidTime,
    Value,
    time_datatype,
)
from grace.context.memory.graph.vocabulary import (
    ENTITY,
    ENTRY,
    FUNCTION,
    GRACE,
    MESSAGE,
    OA,
    PREDICATE,
    PREFIXES,
    PROV,
    RDF,
    RDFS,
    XSD,
)

Mode = TypingLiteral["rdf11", "rdf12"]
MODES: tuple[Mode, ...] = ("rdf11", "rdf12")


class RdfError(ValueError):
    """Triples do not form a valid set of claim-graph entries."""


def _n(iri: str) -> ox.NamedNode:
    return ox.NamedNode(iri)


A = _n(RDF + "type")
RDF_STATEMENT = _n(RDF + "Statement")
RDF_SUBJECT, RDF_PREDICATE, RDF_OBJECT = (_n(RDF + x) for x in ("subject", "predicate", "object"))
RDF_REIFIES = _n(RDF + "reifies")
KNOWN_FROM = _n(GRACE + "knownFrom")
G = {name: _n(GRACE + name) for name in (
    "Claim", "Attribution", "EvidenceLink", "Supersession", "EntityEquivalence", "EntityLabel",
    "scope", "validFrom", "validUntil", "validTimeExpression",
    "about", "function", "reportMode", "polarity", "certainty", "derived",
    "supports", "supersedes", "kind", "validEnd", "replacedBy", "licensedBy",
    "entityA", "entityB", "labelOf")}
RDFS_LABEL = _n(RDFS + "label")
PROV_ATTRIBUTED = _n(PROV + "wasAttributedTo")
PROV_DERIVED = _n(PROV + "wasDerivedFrom")
OA_SELECTOR, OA_TPS, OA_START, OA_END = (
    _n(OA + x) for x in ("hasSelector", "TextPositionSelector", "start", "end"))

# Enumerations -> concept IRIs (declared in resources/rdf/core.ttl and functions.ttl).
CONCEPTS: dict[object, ox.NamedNode] = {
    **{f: _n(FUNCTION + f.value) for f in CommunicativeFunction},
    ReportMode.OWN: _n(GRACE + "OwnStatement"),
    ReportMode.QUOTE: _n(GRACE + "Quote"),
    ReportMode.HYPOTHETICAL: _n(GRACE + "Hypothetical"),
    Polarity.POSITIVE: _n(GRACE + "Positive"),
    Polarity.NEGATIVE: _n(GRACE + "Negative"),
    **{c: _n(GRACE + c.value.capitalize()) for c in Certainty},
    SupersessionKind.CHANGE: _n(GRACE + "Change"),
    SupersessionKind.CORRECTION: _n(GRACE + "Correction"),
}
_FROM_CONCEPT = {(type(k), v): k for k, v in CONCEPTS.items()}

KIND_PATH = {Claim: "claim", Attribution: "attribution", EvidenceLink: "evidence",
             Supersession: "supersession", EntityEquivalence: "equivalence",
             EntityLabel: "label"}
_CLASS = {Claim: "Claim", Attribution: "Attribution", EvidenceLink: "EvidenceLink",
          Supersession: "Supersession", EntityEquivalence: "EntityEquivalence",
          EntityLabel: "EntityLabel"}


def _local(prefix: str, local: str) -> ox.NamedNode:
    return _n(prefix + quote(local, safe=""))


def entry_iri(kind: type, entry_id: str) -> ox.NamedNode:
    return _local(f"{ENTRY}{KIND_PATH[kind]}/", entry_id)


def entity_iri(entity_id: str) -> ox.NamedNode:
    return _local(ENTITY, entity_id)


def message_iri(message_id: str) -> ox.NamedNode:
    return _local(MESSAGE, message_id)


def predicate_node(name: str) -> ox.NamedNode:
    return _local(PREDICATE, name)


def _int(value: int) -> ox.Literal:
    return ox.Literal(str(value), datatype=_n(XSD + "integer"))


def _bool(value: bool) -> ox.Literal:
    return ox.Literal("true" if value else "false", datatype=_n(XSD + "boolean"))


def _time(value: str) -> ox.Literal:
    return ox.Literal(value, datatype=_n(XSD + time_datatype(value)))


def term_node(term: Term) -> ox.NamedNode | ox.Literal:
    if isinstance(term, Entity):
        return entity_iri(term.id)
    return ox.Literal(term.lexical, datatype=_n(XSD + term.datatype))


# ---------------------------------------------------------------------------------------------
# Entries -> triples


def entry_triples(entry: Entry | EntityEquivalence | EntityLabel,
                  mode: Mode = "rdf11") -> list[ox.Triple]:
    """The triples of one entry under serialisation `mode`."""
    if mode not in MODES:
        raise ValueError(f"unknown serialisation mode {mode!r}; expected one of {MODES}")
    node = entry_iri(type(entry), entry.entry_id)
    out = [ox.Triple(node, A, G[_CLASS[type(entry)]]),
           ox.Triple(node, KNOWN_FROM, _int(entry.version))]

    def add(p: ox.NamedNode, o) -> None:
        out.append(ox.Triple(node, p, o))

    if isinstance(entry, Claim):
        s = entity_iri(entry.subject)
        p, o = predicate_node(entry.predicate), term_node(entry.object)
        if mode == "rdf11":
            add(A, RDF_STATEMENT)
            add(RDF_SUBJECT, s)
            add(RDF_PREDICATE, p)
            add(RDF_OBJECT, o)
        else:
            add(RDF_REIFIES, ox.Triple(s, p, o))
        if entry.scope is not None:
            add(G["scope"], ox.Literal(entry.scope))
        vt = entry.valid_time
        if vt.start is not None:
            add(G["validFrom"], _time(vt.start))
        if vt.end is not None:
            add(G["validUntil"], _time(vt.end))
        if vt.expression is not None:
            add(G["validTimeExpression"], ox.Literal(vt.expression))
    elif isinstance(entry, Attribution):
        add(G["about"], entry_iri(Claim, entry.claim_id))
        add(PROV_ATTRIBUTED, entity_iri(entry.speaker))
        add(G["function"], CONCEPTS[entry.function])
        add(G["reportMode"], CONCEPTS[entry.report_mode])
        add(G["polarity"], CONCEPTS[entry.polarity])
        add(G["certainty"], CONCEPTS[entry.certainty])
        add(G["derived"], _bool(entry.derived))
        add(PROV_DERIVED, message_iri(entry.message_id))
    elif isinstance(entry, EvidenceLink):
        add(G["supports"], entry_iri(Claim, entry.claim_id))
        add(PROV_DERIVED, message_iri(entry.message_id))
        if entry.span is not None:
            selector = _n(node.value + "/selector")
            add(OA_SELECTOR, selector)
            out.append(ox.Triple(selector, A, OA_TPS))
            out.append(ox.Triple(selector, OA_START, _int(entry.span.start)))
            out.append(ox.Triple(selector, OA_END, _int(entry.span.end)))
    elif isinstance(entry, Supersession):
        add(G["supersedes"], entry_iri(Claim, entry.claim_id))
        add(G["kind"], CONCEPTS[entry.kind])
        add(G["licensedBy"], entry_iri(Attribution, entry.attribution_id))
        if entry.replacing_claim_id is not None:
            add(G["replacedBy"], entry_iri(Claim, entry.replacing_claim_id))
        if entry.valid_end is not None:
            add(G["validEnd"], _time(entry.valid_end))
    elif isinstance(entry, EntityEquivalence):
        add(G["entityA"], entity_iri(entry.entity_a))
        add(G["entityB"], entity_iri(entry.entity_b))
    elif isinstance(entry, EntityLabel):
        add(G["labelOf"], entity_iri(entry.entity))
        add(RDFS_LABEL, ox.Literal(entry.label))
    else:
        raise TypeError(f"not a claim-graph entry: {entry!r}")
    return out


def changeset_triples(changeset: ChangeSet, mode: Mode = "rdf11") -> list[ox.Triple]:
    return [t for e in changeset.all_entries() for t in entry_triples(e, mode)]


# ---------------------------------------------------------------------------------------------
# Triples -> entries


def _id_of(node, kind: type) -> str:
    prefix = f"{ENTRY}{KIND_PATH[kind]}/"
    if not isinstance(node, ox.NamedNode) or not node.value.startswith(prefix):
        raise RdfError(f"expected a {KIND_PATH[kind]} node, got {node}")
    return unquote(node.value[len(prefix):])


def _local_of(node, prefix: str, what: str) -> str:
    if not isinstance(node, ox.NamedNode) or not node.value.startswith(prefix):
        raise RdfError(f"expected {what} under {prefix}, got {node}")
    return unquote(node.value[len(prefix):])


def _term_of(node) -> Term:
    if isinstance(node, ox.Literal):
        dt = node.datatype.value
        if not dt.startswith(XSD):
            raise RdfError(f"literal datatype outside XSD: {node}")
        return Value(node.value, dt[len(XSD):])
    return Entity(_local_of(node, ENTITY, "an entity"))


def _concept(node, enum: type):
    try:
        return _FROM_CONCEPT[(enum, node)]
    except KeyError:
        raise RdfError(f"{node} is not a {enum.__name__} concept") from None


def _literal(node, datatype: str | None = None) -> str:
    if not isinstance(node, ox.Literal):
        raise RdfError(f"expected a literal, got {node}")
    if datatype and node.datatype.value != XSD + datatype:
        raise RdfError(f"expected xsd:{datatype}, got {node}")
    return node.value


class _Props:
    """The objects of one node by predicate; each read consumes the predicate."""

    def __init__(self, node, triples: list[ox.Triple]):
        self.node = node
        self.values: dict[ox.NamedNode, list] = defaultdict(list)
        for t in triples:
            self.values[t.predicate].append(t.object)

    def take(self, predicate: ox.NamedNode, optional: bool = False):
        values = self.values.pop(predicate, [])
        if len(values) > 1:
            raise RdfError(f"{self.node}: more than one {predicate}")
        if not values:
            if optional:
                return None
            raise RdfError(f"{self.node}: missing {predicate}")
        return values[0]

    def done(self) -> None:
        if self.values:
            raise RdfError(f"{self.node}: unexpected triples {sorted(map(str, self.values))}")


def entries_from_triples(triples: Iterable[ox.Triple | ox.Quad]
                         ) -> list[Entry | EntityEquivalence | EntityLabel]:
    """Invert `entry_triples` for either mode (mixed modes are accepted per claim).

    Raises RdfError on any triple that the mapping would not produce, so a round trip is exact.
    """
    by_subject: dict = defaultdict(list)
    for t in triples:
        by_subject[t.subject].append(ox.Triple(t.subject, t.predicate, t.object))
    entries: list = []
    selectors = {s for s in by_subject if isinstance(s, ox.NamedNode)
                 and s.value.startswith(f"{ENTRY}evidence/") and s.value.endswith("/selector")}
    for node, node_triples in by_subject.items():
        if node in selectors:
            continue
        props = _Props(node, node_triples)
        types = set(props.values.pop(A, []))
        try:
            entries.append(_entry(node, props, types, by_subject))
        except EntryError as exc:
            raise RdfError(f"{node}: {exc}") from exc
    used = {_n(e.value + "/selector") for e in by_subject if e not in selectors} & selectors
    if stray := selectors - used:
        raise RdfError(f"selectors without an evidence link: {sorted(map(str, stray))}")
    return entries


def _entry(node, props: _Props, types: set, by_subject: dict):
    version = int(_literal(props.take(KNOWN_FROM), "integer"))
    if G["Claim"] in types:
        if RDF_REIFIES in props.values:
            if types != {G["Claim"]}:
                raise RdfError(f"{node}: unexpected types {types}")
            triple = props.take(RDF_REIFIES)
            if not isinstance(triple, ox.Triple):
                raise RdfError(f"{node}: rdf:reifies must name a triple term")
            s, p, o = triple.subject, triple.predicate, triple.object
        else:
            if types != {G["Claim"], RDF_STATEMENT}:
                raise RdfError(f"{node}: unexpected types {types}")
            s, p, o = props.take(RDF_SUBJECT), props.take(RDF_PREDICATE), props.take(RDF_OBJECT)
        scope = props.take(G["scope"], optional=True)
        start = props.take(G["validFrom"], optional=True)
        end = props.take(G["validUntil"], optional=True)
        expression = props.take(G["validTimeExpression"], optional=True)
        props.done()
        return Claim(
            claim_id=_id_of(node, Claim),
            subject=_local_of(s, ENTITY, "an entity"),
            predicate=_local_of(p, PREDICATE, "a predicate"),
            object=_term_of(o),
            scope=None if scope is None else _literal(scope, "string"),
            valid_time=ValidTime(None if start is None else _literal(start),
                                 None if end is None else _literal(end),
                                 None if expression is None else _literal(expression, "string")),
            version=version)
    if len(types) != 1:
        raise RdfError(f"{node}: expected exactly one entry type, got {types}")
    (kind,) = types
    if kind == G["Attribution"]:
        entry = Attribution(
            attribution_id=_id_of(node, Attribution),
            claim_id=_id_of(props.take(G["about"]), Claim),
            speaker=_local_of(props.take(PROV_ATTRIBUTED), ENTITY, "a speaker"),
            function=_concept(props.take(G["function"]), CommunicativeFunction),
            report_mode=_concept(props.take(G["reportMode"]), ReportMode),
            polarity=_concept(props.take(G["polarity"]), Polarity),
            certainty=_concept(props.take(G["certainty"]), Certainty),
            derived=_literal(props.take(G["derived"]), "boolean") == "true",
            message_id=_local_of(props.take(PROV_DERIVED), MESSAGE, "a message"),
            version=version)
    elif kind == G["EvidenceLink"]:
        selector = props.take(OA_SELECTOR, optional=True)
        span = None
        if selector is not None:
            if selector != _n(node.value + "/selector"):
                raise RdfError(f"{node}: unexpected selector {selector}")
            sel = _Props(selector, by_subject.get(selector, []))
            if sel.values.pop(A, []) != [OA_TPS]:
                raise RdfError(f"{selector}: must be exactly an oa:TextPositionSelector")
            span = Span(int(_literal(sel.take(OA_START), "integer")),
                        int(_literal(sel.take(OA_END), "integer")))
            sel.done()
        entry = EvidenceLink(
            evidence_id=_id_of(node, EvidenceLink),
            claim_id=_id_of(props.take(G["supports"]), Claim),
            message_id=_local_of(props.take(PROV_DERIVED), MESSAGE, "a message"),
            span=span, version=version)
    elif kind == G["Supersession"]:
        replacing = props.take(G["replacedBy"], optional=True)
        valid_end = props.take(G["validEnd"], optional=True)
        entry = Supersession(
            supersession_id=_id_of(node, Supersession),
            claim_id=_id_of(props.take(G["supersedes"]), Claim),
            kind=_concept(props.take(G["kind"]), SupersessionKind),
            valid_end=None if valid_end is None else _literal(valid_end),
            replacing_claim_id=None if replacing is None else _id_of(replacing, Claim),
            attribution_id=_id_of(props.take(G["licensedBy"]), Attribution),
            version=version)
    elif kind == G["EntityEquivalence"]:
        entry = EntityEquivalence(
            equivalence_id=_id_of(node, EntityEquivalence),
            entity_a=_local_of(props.take(G["entityA"]), ENTITY, "an entity"),
            entity_b=_local_of(props.take(G["entityB"]), ENTITY, "an entity"),
            version=version)
    elif kind == G["EntityLabel"]:
        entry = EntityLabel(
            label_id=_id_of(node, EntityLabel),
            entity=_local_of(props.take(G["labelOf"]), ENTITY, "an entity"),
            label=_literal(props.take(RDFS_LABEL), "string"),
            version=version)
    else:
        raise RdfError(f"{node}: unknown entry type {kind}")
    props.done()
    return entry


def changesets_from_triples(triples: Iterable[ox.Triple | ox.Quad], history_id: str,
                            vocabulary_versions: dict[int, str | None] | None = None
                            ) -> list[ChangeSet]:
    """Group parsed entries into change sets by version (canonical order).

    RDF does not carry the history ID or the vocabulary version; the caller supplies them.
    """
    groups: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    field_of = {Claim: "claims", Attribution: "attributions", EvidenceLink: "evidence_links",
                Supersession: "supersessions", EntityEquivalence: "entity_merges",
                EntityLabel: "entity_labels"}
    for entry in entries_from_triples(triples):
        groups[entry.version][field_of[type(entry)]].append(entry)
    versions = vocabulary_versions or {}
    return [ChangeSet(history_id, v, vocabulary_version=versions.get(v),
                      **{k: tuple(items) for k, items in groups[v].items()}).canonical()
            for v in sorted(groups)]


# ---------------------------------------------------------------------------------------------
# Text serialisations


def to_ntriples(triples: Iterable[ox.Triple]) -> str:
    """Canonical N-Triples, one triple per line, lines sorted: a stable text form for fixtures."""
    text = ox.serialize(list(triples), format=ox.RdfFormat.N_TRIPLES).decode("utf-8")
    return "".join(sorted(set(text.splitlines(keepends=True))))


def to_turtle(triples: Iterable[ox.Triple]) -> str:
    return ox.serialize(list(triples), format=ox.RdfFormat.TURTLE,
                        prefixes=PREFIXES).decode("utf-8")


def parse(text: str | bytes, fmt: ox.RdfFormat = ox.RdfFormat.N_TRIPLES) -> list[ox.Triple]:
    return [ox.Triple(q.subject, q.predicate, q.object) for q in ox.parse(text, format=fmt)]


def convert(triples: Iterable[ox.Triple], mode: Mode) -> list[ox.Triple]:
    """Re-serialise parsed entries under another mode."""
    return [t for e in entries_from_triples(triples) for t in entry_triples(e, mode)]
