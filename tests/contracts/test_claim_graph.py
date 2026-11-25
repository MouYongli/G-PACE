"""Contract tests for the "Claim graph" section of docs/research/contracts.md (T014).

Covers the four entry kinds, change-set records, append-only commits, idempotent retry,
time-travel stability, save and restore. The fixture is the worked example of
docs/research/change-sequences.md (section 6.5), extended by a removal without a replacing claim
(G2(ii)), a hypothetical stance and an entity merge.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from grace.context.memory.graph import rdf
from grace.context.memory.graph.changeset import RECORD_FIELDS, ChangeSet
from grace.context.memory.graph.entities import EntityEquivalence, representatives
from grace.context.memory.graph.entries import (
    Attribution,
    Certainty,
    Claim,
    CommunicativeFunction,
    Entity,
    EntryError,
    EvidenceLink,
    Polarity,
    ReportMode,
    Span,
    Supersession,
    SupersessionKind,
    ValidTime,
    Value,
)
from grace.context.memory.graph.store import ClaimStore, CommitConflict, CommitError
from grace.context.memory.graph.vocabulary import VocabularyError, load_vocabulary

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "graph" / "worked-example"
HISTORY = "change-seq-worked-example"
EXPERIMENT_RUN_FIELDS = {"history_id", "version", "entries", "vocabulary_version",
                         "entity_merges"}


def fixture_records() -> list[dict]:
    lines = (FIXTURE / "changesets.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def fixture_changesets() -> list[ChangeSet]:
    return [ChangeSet.from_record(r) for r in fixture_records()]


def built_store(mode="rdf11", upto=None) -> ClaimStore:
    store = ClaimStore(HISTORY, mode)
    for cs in fixture_changesets():
        if upto is None or cs.version <= upto:
            store.commit(cs)
    return store


def claim(cid, s, p, o, v, **kw):
    return Claim(cid, s, p, o, kw.get("scope"), kw.get("valid_time", ValidTime()), v)


def att(aid, cid, v, speaker="user", fn=CommunicativeFunction.INFORM, pol=Polarity.POSITIVE,
        msg=None):
    return Attribution(aid, cid, speaker, fn, ReportMode.OWN, pol, Certainty.CERTAIN, False,
                       msg or f"m{v}", v)


def ev(eid, cid, v):
    return EvidenceLink(eid, cid, f"m{v}", None, v)


class EntryKindsTest(unittest.TestCase):
    def test_each_kind_round_trips_through_its_record(self):
        seen = set()
        for cs in fixture_changesets():
            for entry in cs.all_entries():
                seen.add(type(entry))
                self.assertEqual(type(entry).from_record(entry.to_record()), entry)
        self.assertEqual(seen, {Claim, Attribution, EvidenceLink, Supersession,
                                EntityEquivalence})

    def test_fixture_covers_every_value_of_the_entry_fields_that_matter(self):
        entries = [e for cs in fixture_changesets() for e in cs.entries()]
        kinds = {e.kind for e in entries if isinstance(e, Supersession)}
        self.assertEqual(kinds, set(SupersessionKind))
        self.assertTrue(any(isinstance(e, Supersession) and e.replacing_claim_id is None
                            for e in entries))
        self.assertTrue(any(isinstance(e, Attribution) and e.derived for e in entries))
        self.assertTrue(any(isinstance(e, Attribution) and e.polarity is Polarity.NEGATIVE
                            for e in entries))
        self.assertTrue(any(isinstance(e, EvidenceLink) and e.span for e in entries))

    def test_invalid_entries_are_rejected(self):
        cases = {
            "version 0": lambda: claim("c", "x", "livesIn", Entity("y"), 0),
            "bool version": lambda: claim("c", "x", "livesIn", Entity("y"), True),
            "empty id": lambda: claim("", "x", "livesIn", Entity("y"), 1),
            "padded id": lambda: claim(" c", "x", "livesIn", Entity("y"), 1),
            "string object": lambda: claim("c", "x", "livesIn", "y", 1),
            "non-canonical integer": lambda: Value("03", "integer"),
            "time without seconds": lambda: Value("18:00", "time"),
            "unknown datatype": lambda: Value("1.5", "decimal"),
            "invalid date": lambda: Value("2023-02-30", "date"),
            "empty interval": lambda: ValidTime("2023-10-20", "2023-10-20"),
            "mixed bounds": lambda: ValidTime("2023-10-20", "2023-10-21T00:00:00"),
            "string function": lambda: Attribution("a", "c", "u", "inform", ReportMode.OWN,
                                                   Polarity.POSITIVE, Certainty.CERTAIN,
                                                   False, "m", 1),
            "empty span": lambda: Span(3, 3),
            "negative span": lambda: Span(-1, 3),
            "correction with valid end": lambda: Supersession(
                "s", "c", SupersessionKind.CORRECTION, "2023-10-20", None, "a", 2),
            "self replacement": lambda: Supersession(
                "s", "c", SupersessionKind.CHANGE, None, "c", "a", 2),
            "self equivalence": lambda: EntityEquivalence("q", "x", "x", 1),
        }
        for name, make in cases.items():
            with self.subTest(case=name), self.assertRaises(EntryError):
                make()

    def test_records_reject_unknown_missing_and_bad_enum_fields(self):
        record = fixture_records()[0]["entries"]["attributions"][0]
        for change in ({"extra": 1}, {"function": "suggest"}):
            with self.subTest(change=change), self.assertRaises(EntryError):
                Attribution.from_record({**record, **change})
        missing = dict(record)
        del missing["polarity"]
        with self.assertRaises(EntryError):
            Attribution.from_record(missing)


class ChangeSetRecordTest(unittest.TestCase):
    def test_fixture_records_are_canonical(self):
        for record in fixture_records():
            self.assertEqual(ChangeSet.from_record(record).to_record(), record)

    def test_record_fields_match_the_experiment_run_contract(self):
        self.assertEqual(set(RECORD_FIELDS), EXPERIMENT_RUN_FIELDS)
        for cs in fixture_changesets():
            record = cs.to_record()
            self.assertEqual(set(record), EXPERIMENT_RUN_FIELDS)
            self.assertEqual(list(record["entries"]),
                             ["claims", "attributions", "evidence_links", "supersessions"])

    def test_entries_must_carry_the_change_set_version(self):
        with self.assertRaises(EntryError):
            ChangeSet(HISTORY, 2, claims=(claim("c", "x", "livesIn", Entity("y"), 1),))

    def test_entry_ids_are_unique_across_kinds(self):
        with self.assertRaises(EntryError):
            ChangeSet(HISTORY, 1, claims=(claim("x1", "x", "livesIn", Entity("y"), 1),),
                      attributions=(att("x1", "x1", 1),))

    def test_malformed_records_are_rejected(self):
        record = fixture_records()[0]
        bad = [{**record, "extra": 1}, {**record, "entries": {"claims": []}},
               {k: v for k, v in record.items() if k != "entity_merges"}]
        for item in bad:
            with self.subTest(record=sorted(item)), self.assertRaises(EntryError):
                ChangeSet.from_record(item)


class AppendOnlyTest(unittest.TestCase):
    def test_graph_grows_monotonically_and_stamps_are_bounded(self):
        for mode in rdf.MODES:
            store = ClaimStore(HISTORY, mode)
            previous: set = set()
            for cs in fixture_changesets():
                store.commit(cs)
                current = set(store.graph)
                self.assertTrue(previous <= current, f"{mode}: G_r not a subset at {cs.version}")
                previous = current
                state = store.state(cs.version)
                for group in (state.claims, state.attributions, state.evidence_links,
                              state.supersessions, state.equivalences):
                    self.assertTrue(all(e.version <= cs.version for e in group.values()))
                new = {e.entry_id for e in cs.all_entries()}
                older = store.state(cs.version - 1)
                for group in (older.claims, older.attributions, older.evidence_links,
                              older.supersessions, older.equivalences):
                    self.assertFalse(new & group.keys())

    def test_reified_triples_are_never_asserted(self):
        for mode in rdf.MODES:
            store = built_store(mode)
            asserted = [q for q in store.graph
                        if q.predicate.value.startswith(rdf.PREDICATE)]
            self.assertEqual(asserted, [], mode)

    def assert_rejected(self, store, cs, error=CommitError):
        before_head, before = store.head, set(store.graph)
        with self.assertRaises(error):
            store.commit(cs)
        self.assertEqual(store.head, before_head)
        self.assertEqual(set(store.graph), before)

    def test_past_versions_cannot_be_rewritten(self):
        store = built_store()
        changed = copy.deepcopy(fixture_records()[3])
        changed["entries"]["attributions"][0]["function"] = "reject"
        self.assert_rejected(store, ChangeSet.from_record(changed), CommitConflict)
        sparse = ClaimStore(HISTORY)
        sparse.commit(fixture_changesets()[0])
        sparse.commit(ChangeSet(HISTORY, 3))
        self.assert_rejected(sparse, ChangeSet(HISTORY, 2), CommitConflict)

    def test_commit_rules(self):
        store = built_store(upto=8)
        v = 9
        cases = {
            "other history": ChangeSet("other", v),
            "reused id": ChangeSet(HISTORY, v, attributions=(att("a1", "c1", v),)),
            "dangling claim": ChangeSet(HISTORY, v, evidence_links=(ev("e99", "c99", v),)),
            "attribution named as claim": ChangeSet(HISTORY, v,
                                                    evidence_links=(ev("e99", "a1", v),)),
            "repeated current proposition": ChangeSet(
                HISTORY, v, claims=(claim("c99", "user", "playsInstrument", Entity("violin"),
                                          v),)),
            "licence on another claim": ChangeSet(
                HISTORY, v, attributions=(att("a99", "c6", v, pol=Polarity.NEGATIVE),),
                supersessions=(Supersession("s99", "c8", SupersessionKind.CHANGE, None, None,
                                            "a99", v),)),
            "replacement with another predicate": ChangeSet(
                HISTORY, v, claims=(claim("c99", "user", "playsInstrument", Entity("oboe"),
                                          v),),
                attributions=(att("a99", "c99", v),),
                supersessions=(Supersession("s99", "c8", SupersessionKind.CHANGE, None, "c99",
                                            "a99", v),)),
        }
        for name, cs in cases.items():
            with self.subTest(case=name):
                self.assert_rejected(store, cs)

    def test_a_superseded_proposition_may_be_stated_again(self):
        store = built_store()
        back = ChangeSet(HISTORY, 11, claims=(claim("c10", "user", "livesIn", Entity("Munich"),
                                                    11),),
                         attributions=(att("a13", "c10", 11),), evidence_links=(ev("e13", "c10",
                                                                                   11),))
        self.assertEqual(store.commit(back).version, 11)


class IdempotentRetryTest(unittest.TestCase):
    def test_retry_of_a_committed_change_set_is_a_no_op(self):
        for mode in rdf.MODES:
            store = built_store(mode)
            before = set(store.graph)
            for cs in fixture_changesets():
                self.assertEqual(store.commit(cs), cs.canonical())
                reordered = ChangeSet(cs.history_id, cs.version, cs.claims[::-1],
                                      cs.attributions[::-1], cs.evidence_links[::-1],
                                      cs.supersessions[::-1], cs.vocabulary_version,
                                      cs.entity_merges)
                store.commit(reordered)
            self.assertEqual(set(store.graph), before)
            self.assertEqual(store.head, 10)


CURRENT = """
SELECT ?c ?o (COUNT(DISTINCT ?e) AS ?n) WHERE {
  ?c a g:Claim ; g:knownFrom ?k . FILTER(?k <= %r%)
  { ?c rdf:object ?o } UNION { ?c rdf:reifies ?t . BIND(OBJECT(?t) AS ?o) }
  ?e g:supports ?c ; g:knownFrom ?ek . FILTER(?ek <= %r%)
  FILTER NOT EXISTS { ?s g:supersedes ?c ; g:knownFrom ?sv . FILTER(?sv <= %r%) }
} GROUP BY ?c ?o ORDER BY ?c
"""

# The current-choice template of plan 5.3, written for each serialisation.
CHOICE = {
    "rdf11": """
SELECT ?train ?arrives WHERE {
  ?c rdf:subject ge:k1 ; rdf:predicate gp:selectedService ; rdf:object ?train ; g:knownFrom ?r1 .
  ?att g:about ?c ; g:function gf:accept ; prov:wasAttributedTo ge:user ; g:knownFrom ?r2 .
  ?a rdf:subject ?train ; rdf:predicate gp:scheduledArrival ; rdf:object ?arrives ;
     g:knownFrom ?r3 .
  FILTER(?r1 <= %r% && ?r2 <= %r% && ?r3 <= %r%)
  FILTER NOT EXISTS { ?s1 g:supersedes ?c ; g:knownFrom ?v1 . FILTER(?v1 <= %r%) }
  FILTER NOT EXISTS { ?s2 g:supersedes ?a ; g:knownFrom ?v2 . FILTER(?v2 <= %r%) }
}""",
    "rdf12": """
SELECT ?train ?arrives WHERE {
  ?c rdf:reifies <<( ge:k1 gp:selectedService ?train )>> ; g:knownFrom ?r1 .
  ?att g:about ?c ; g:function gf:accept ; prov:wasAttributedTo ge:user ; g:knownFrom ?r2 .
  ?a rdf:reifies <<( ?train gp:scheduledArrival ?arrives )>> ; g:knownFrom ?r3 .
  FILTER(?r1 <= %r% && ?r2 <= %r% && ?r3 <= %r%)
  FILTER NOT EXISTS { ?s1 g:supersedes ?c ; g:knownFrom ?v1 . FILTER(?v1 <= %r%) }
  FILTER NOT EXISTS { ?s2 g:supersedes ?a ; g:knownFrom ?v2 . FILTER(?v2 <= %r%) }
}""",
}


def rows(results) -> list[tuple]:
    return [tuple(str(s[v]) for v in results.variables) for s in results]


class TimeTravelTest(unittest.TestCase):
    def test_reads_at_a_past_version_do_not_change_after_later_commits(self):
        for mode in rdf.MODES:
            store = ClaimStore(HISTORY, mode)
            then, then_state = {}, {}
            for cs in fixture_changesets():
                store.commit(cs)
                then[cs.version] = rows(store.query(CURRENT, cs.version))
                then_state[cs.version] = store.state(cs.version)
            for r0, expected in then.items():
                with self.subTest(mode=mode, version=r0):
                    self.assertEqual(rows(store.query(CURRENT, r0)), expected)
                    self.assertEqual(store.state(r0), then_state[r0])

    def test_both_serialisations_answer_alike(self):
        stores = {mode: built_store(mode) for mode in rdf.MODES}
        for r in range(0, 11):
            results = {m: rows(s.query(CURRENT, r)) for m, s in stores.items()}
            self.assertEqual(results["rdf11"], results["rdf12"], r)
            choice = {m: rows(s.query(CHOICE[m], r)) for m, s in stores.items()}
            self.assertEqual(choice["rdf11"], choice["rdf12"], r)
            expected = [] if r < 4 else [("<https://example.org/grace/entity/ICE947>",
                                          '"17:25:00"^^<http://www.w3.org/2001/XMLSchema#time>')]
            self.assertEqual(choice["rdf11"], expected, r)

    def test_query_needs_a_version_for_the_cutoff_placeholder(self):
        with self.assertRaises(ValueError):
            built_store().query(CURRENT)

    def test_supersession_semantics_at_cutoffs(self):
        store = built_store()
        s6, s7, s8, s9 = (store.state(v) for v in (6, 7, 8, 9))
        self.assertTrue(s6.is_current("c1"))
        self.assertIsNone(s6.valid_end("c1"))
        self.assertFalse(s7.is_current("c1"))
        self.assertFalse(s7.is_corrected("c1"))
        self.assertEqual(s7.valid_end("c1"), "2023-11-01")
        self.assertTrue(s7.is_current("c7"))
        self.assertTrue(s8.is_corrected("c7"))
        self.assertTrue(s8.is_current("c8"))
        # Removal without a replacing claim (G2(ii)): no longer current, still past state.
        self.assertFalse(s9.is_current("c6"))
        self.assertFalse(s9.is_corrected("c6"))
        self.assertIsNone(s9.valid_end("c6"))
        self.assertEqual([a.attribution_id for a in s9.attributions_on("c6")], ["a7", "a11"])

    def test_entity_representatives(self):
        store = built_store()
        self.assertEqual(store.state(9).representatives(), {})
        self.assertEqual(store.state(10).representatives(),
                         {"ICE 947": "ICE 947", "ICE947": "ICE 947"})
        eqs = [EntityEquivalence("q1", "b", "c", 1), EntityEquivalence("q2", "a", "b", 2)]
        self.assertEqual(representatives(eqs, 2), representatives(eqs[::-1], 2))
        self.assertEqual(representatives(eqs, 1), {"b": "b", "c": "b"})


class SaveRestoreTest(unittest.TestCase):
    def test_save_and_restore(self):
        for mode in rdf.MODES:
            store = built_store(mode)
            with tempfile.TemporaryDirectory() as tmp:
                store.save(Path(tmp) / "snap")
                restored = ClaimStore.restore(Path(tmp) / "snap")
                self.assertEqual(set(restored.graph), set(store.graph))
                self.assertEqual(restored.changesets(), store.changesets())
                self.assertEqual(restored.mode, mode)
                with self.assertRaises(FileExistsError):
                    store.save(Path(tmp) / "snap")
                graph = Path(tmp) / "snap" / "graph.nt"
                graph.write_text(graph.read_text(encoding="utf-8")[:-200], encoding="utf-8")
                with self.assertRaises(ValueError):
                    ClaimStore.restore(Path(tmp) / "snap")


class VocabularyTest(unittest.TestCase):
    def test_seed_vocabulary(self):
        vocab = load_vocabulary()
        self.assertEqual(vocab.version, "v1")
        self.assertTrue(vocab.is_exclusive("livesIn"))
        self.assertFalse(vocab.is_exclusive("playsInstrument"))
        self.assertEqual(vocab.resolve("No  later THAN"), "arriveBy")
        with self.assertRaises(VocabularyError):
            vocab.resolve("ownsPet")
        for cs in fixture_changesets():
            for c in cs.claims:
                self.assertIn(c.predicate, vocab)

    def test_extension_makes_a_new_version_and_keeps_old_definitions(self):
        vocab = load_vocabulary()
        new = vocab.extend("v2", {"ownsPet": False}, {"has a pet": "ownsPet"})
        self.assertEqual(new.resolve("has a pet"), "ownsPet")
        self.assertNotIn("ownsPet", vocab)
        for bad in (lambda: vocab.extend("v1", {"x": True}),
                    lambda: vocab.extend("v2", {"livesIn": False}),
                    lambda: vocab.extend("v2", aliases={"plays": "livesIn"}),
                    lambda: vocab.extend("v2", aliases={"x": "unknown"})):
            with self.assertRaises(VocabularyError):
                bad()


if __name__ == "__main__":
    unittest.main()
