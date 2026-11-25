"""Serialisation and SHACL tests for the "Claim graph" section of docs/research/contracts.md (T014).

- RDF 1.1 standard reification and RDF 1.2 reifiers both round-trip on the worked-example fixture,
  through N-Triples and Turtle, and convert into each other.
- SHACL validates only the claims a change set touches.
"""

import unittest

import pyoxigraph as ox
import rdflib

from grace.context.memory.graph import rdf, shacl
from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entries import Entity
from grace.context.memory.graph.store import ClaimStore, CommitError
from tests.contracts.test_claim_graph import (
    FIXTURE,
    HISTORY,
    att,
    built_store,
    claim,
    ev,
    fixture_changesets,
)

VOCAB_VERSIONS = {v: "v1" for v in range(1, 11)}


class RoundTripTest(unittest.TestCase):
    def setUp(self):
        self.changesets = [cs.canonical() for cs in fixture_changesets()]
        self.entries = sorted((e for cs in self.changesets for e in cs.all_entries()),
                              key=lambda e: (type(e).__name__, e.entry_id))

    def triples(self, mode):
        return [t for cs in self.changesets for t in rdf.changeset_triples(cs, mode)]

    def parsed(self, triples):
        return sorted(rdf.entries_from_triples(triples),
                      key=lambda e: (type(e).__name__, e.entry_id))

    def test_golden_files_match_the_mapping(self):
        for mode in rdf.MODES:
            golden = (FIXTURE / f"{mode}.nt").read_text(encoding="utf-8")
            self.assertEqual(rdf.to_ntriples(self.triples(mode)), golden, mode)

    def test_both_serialisations_round_trip(self):
        for mode in rdf.MODES:
            for fmt, text in (
                    (ox.RdfFormat.N_TRIPLES, rdf.to_ntriples(self.triples(mode))),
                    (ox.RdfFormat.TURTLE, rdf.to_turtle(self.triples(mode)))):
                with self.subTest(mode=mode, fmt=str(fmt)):
                    parsed = rdf.parse(text, fmt)
                    self.assertEqual(self.parsed(parsed), self.entries)
                    back = rdf.changesets_from_triples(parsed, HISTORY, VOCAB_VERSIONS)
                    self.assertEqual(back, self.changesets)

    def test_golden_files_parse_to_the_fixture(self):
        for mode in rdf.MODES:
            text = (FIXTURE / f"{mode}.nt").read_text(encoding="utf-8")
            back = rdf.changesets_from_triples(rdf.parse(text), HISTORY, VOCAB_VERSIONS)
            self.assertEqual(back, self.changesets, mode)

    def test_serialisations_convert_into_each_other(self):
        rdf11, rdf12 = self.triples("rdf11"), self.triples("rdf12")
        self.assertEqual(set(rdf.convert(rdf11, "rdf12")), set(rdf12))
        self.assertEqual(set(rdf.convert(rdf12, "rdf11")), set(rdf11))
        self.assertTrue(any(isinstance(t.object, ox.Triple) for t in rdf12))
        self.assertFalse(any(t.predicate == rdf.RDF_REIFIES for t in rdf11))

    def test_the_serialisations_differ_only_in_the_proposition_triples(self):
        proposition = {rdf.RDF_SUBJECT, rdf.RDF_PREDICATE, rdf.RDF_OBJECT, rdf.RDF_REIFIES}

        def rest(triples):
            return {t for t in triples if t.predicate not in proposition
                    and t.object != rdf.RDF_STATEMENT}

        self.assertEqual(rest(self.triples("rdf11")), rest(self.triples("rdf12")))

    def test_parser_rejects_triples_the_mapping_does_not_produce(self):
        base = self.triples("rdf11")
        claim_node = rdf.entry_iri(type(self.changesets[0].claims[0]), "c1")
        extra = [
            ox.Triple(claim_node, rdf.RDF_OBJECT, ox.Literal("x")),         # second object
            ox.Triple(claim_node, ox.NamedNode("https://example.org/p"), ox.Literal("x")),
            ox.Triple(rdf.entity_iri("user"), rdf.predicate_node("livesIn"),
                      rdf.entity_iri("Munich")),                             # asserted triple
        ]
        for triple in extra:
            with self.subTest(triple=str(triple)), self.assertRaises(rdf.RdfError):
                rdf.entries_from_triples([*base, triple])
        missing = [t for t in base if not (t.subject == claim_node
                                           and t.predicate == rdf.KNOWN_FROM)]
        with self.assertRaises(rdf.RdfError):
            rdf.entries_from_triples(missing)


SHAPES_PREFIXES = """
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix oa:   <http://www.w3.org/ns/oa#> .
@prefix g:    <https://example.org/grace/ns#> .
@prefix gf:   <https://example.org/grace/function#> .
@prefix gx:   <https://example.org/grace/entry/> .
@prefix ge:   <https://example.org/grace/entity/> .
@prefix gm:   <https://example.org/grace/message/> .
"""


class ShaclTest(unittest.TestCase):
    def test_fixture_conforms_at_every_version(self):
        store = ClaimStore(HISTORY)
        for cs in fixture_changesets():
            report = store.validate(cs)
            self.assertTrue(report.conforms, report.text)
            store.commit(cs, validate=True)

    def test_only_claims_touched_by_the_patch_are_validated(self):
        store = ClaimStore(HISTORY)
        # Version 1: a claim with evidence but no attribution, committed without validation.
        bad = ChangeSet(HISTORY, 1, claims=(claim("bad", "x", "livesIn", Entity("y"), 1),),
                        evidence_links=(ev("e-bad", "bad", 1),))
        self.assertFalse(store.validate(bad).conforms)
        store.commit(bad)
        # Version 2 touches another claim only: the invalid claim is not looked at.
        good = ChangeSet(HISTORY, 2, claims=(claim("ok", "x", "playsInstrument",
                                                   Entity("violin"), 2),),
                         attributions=(att("a-ok", "ok", 2),),
                         evidence_links=(ev("e-ok", "ok", 2),))
        report = store.validate(good)
        self.assertTrue(report.conforms, report.text)
        self.assertNotIn(rdf.entry_iri(type(bad.claims[0]), "bad").value, report.focus_nodes)
        store.commit(good, validate=True)
        # Version 3 adds evidence to the invalid claim: now it is touched and reported.
        touch = ChangeSet(HISTORY, 3, evidence_links=(ev("e-bad2", "bad", 3),))
        report = store.validate(touch)
        self.assertFalse(report.conforms)
        self.assertIn("at least one attribution", report.text)
        with self.assertRaises(CommitError):
            store.commit(touch, validate=True)
        self.assertEqual(store.head, 2)
        # Adding the missing attribution repairs it.
        fix = ChangeSet(HISTORY, 3, attributions=(att("a-bad", "bad", 3),))
        self.assertTrue(store.validate(fix).conforms)

    def test_focus_is_the_touched_claims_and_the_new_entries(self):
        store = built_store(upto=8)
        cs = fixture_changesets()[8]
        report = store.validate(cs)
        names = {f.rsplit("/", 2)[-2] + "/" + f.rsplit("/", 1)[-1] for f in report.focus_nodes}
        self.assertEqual(names, {"claim/c6", "attribution/a11", "evidence/e11",
                                 "supersession/s3"})

    def violations(self, turtle: str) -> str:
        data = rdflib.Graph().parse(data=SHAPES_PREFIXES + turtle, format="turtle")
        import pyshacl
        conforms, _, text = pyshacl.validate(data, shacl_graph=shacl._shapes(shacl.SHAPES_FILE),
                                             inference="none")
        return "" if conforms else text

    VALID = """
gx:claim\\/c a g:Claim, rdf:Statement ; g:knownFrom 1 ; rdf:subject ge:x ;
    rdf:predicate <https://example.org/grace/predicate/livesIn> ; rdf:object ge:y .
gx:claim\\/d a g:Claim, rdf:Statement ; g:knownFrom 2 ; rdf:subject ge:x ;
    rdf:predicate <https://example.org/grace/predicate/livesIn> ; rdf:object ge:z .
gx:attribution\\/a a g:Attribution ; g:knownFrom 1 ; g:about gx:claim\\/c ;
    prov:wasAttributedTo ge:u ; g:function gf:inform ; g:reportMode g:OwnStatement ;
    g:polarity g:Positive ; g:certainty g:Certain ; g:derived false ;
    prov:wasDerivedFrom gm:m1 .
gx:attribution\\/b a g:Attribution ; g:knownFrom 2 ; g:about gx:claim\\/d ;
    prov:wasAttributedTo ge:u ; g:function gf:inform ; g:reportMode g:OwnStatement ;
    g:polarity g:Positive ; g:certainty g:Certain ; g:derived false ;
    prov:wasDerivedFrom gm:m2 .
gx:evidence\\/e a g:EvidenceLink ; g:knownFrom 1 ; g:supports gx:claim\\/c ;
    prov:wasDerivedFrom gm:m1 ; oa:hasSelector gx:evidence\\/e\\/selector .
gx:evidence\\/e\\/selector a oa:TextPositionSelector ; oa:start 0 ; oa:end 4 .
gx:evidence\\/f a g:EvidenceLink ; g:knownFrom 2 ; g:supports gx:claim\\/d ;
    prov:wasDerivedFrom gm:m2 .
gx:supersession\\/s a g:Supersession ; g:knownFrom 2 ; g:supersedes gx:claim\\/c ;
    g:kind g:Change ; g:licensedBy gx:attribution\\/b ; g:replacedBy gx:claim\\/d ;
    g:validEnd "2023-11-01"^^xsd:date .
"""

    def test_shapes_accept_a_valid_graph_and_reject_broken_ones(self):
        self.assertEqual(self.violations(self.VALID), "")
        broken = {
            "correction with valid end": ("g:kind g:Change", "g:kind g:Correction"),
            "unknown function": ("g:function gf:inform", "g:function gf:suggest"),
            "empty span": ("oa:start 0 ; oa:end 4", "oa:start 4 ; oa:end 4"),
            "attribution older than claim": ("g:knownFrom 2 ; g:about gx:claim\\/d",
                                             "g:knownFrom 1 ; g:about gx:claim\\/d"),
            "licence on an unrelated claim": (" g:replacedBy gx:claim\\/d ;", ""),
            "two version stamps": ("rdf:Statement ; g:knownFrom 1 ;",
                                   "rdf:Statement ; g:knownFrom 1, 3 ;"),
            "claim without attribution": ("g:knownFrom 2 ; g:about gx:claim\\/d",
                                          "g:knownFrom 2 ; g:about gx:claim\\/c"),
            "claim without evidence": ("gx:evidence\\/f a g:EvidenceLink ; g:knownFrom 2 ; "
                                       "g:supports gx:claim\\/d ;\n    prov:wasDerivedFrom gm:m2 .",
                                       ""),
            "string version": ("g:Change ; g:licensedBy",
                               "g:Change ; g:knownFrom \"2\" ; g:licensedBy"),
        }
        messages = {"attribution older than claim": "cannot be older than its claim",
                    "licence on an unrelated claim": "licensing attribution",
                    "claim without evidence": "at least one evidence link",
                    "claim without attribution": "at least one attribution"}
        for name, (old, new) in broken.items():
            with self.subTest(case=name):
                self.assertIn(old, self.VALID)
                text = self.violations(self.VALID.replace(old, new, 1))
                self.assertNotEqual(text, "")
                self.assertIn(messages.get(name, "Constraint Violation"), text)


if __name__ == "__main__":
    unittest.main()
