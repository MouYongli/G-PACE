"""Compiled queries on fixture claim graphs (T017; plan 3.3, 3.4, 5.3).

The fixture history is built with the T014 store and change-set APIs. It combines the three
running examples of plan 3.5 (offer and acceptance, a multi-valued predicate, a repeated mention)
with a state change that states a valid end, a late correction and scoped claims. Every gold
answer and witness below was derived by hand from the change sets in `build_store`.

Each test runs against both claim serialisations (`rdf11`, `rdf12`).
"""

from __future__ import annotations

import datetime as dt
import unittest

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entities import EntityEquivalence
from grace.context.memory.graph.entries import (
    Attribution,
    Certainty,
    Claim,
    CommunicativeFunction,
    Entity,
    EvidenceLink,
    Polarity,
    ReportMode,
    Span,
    Supersession,
    SupersessionKind,
    ValidTime,
    Value,
)
from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.query.compile import absolutize, compile_query
from grace.context.pipeline.query.execute import execute, run
from grace.context.pipeline.query.grammar import parse
from grace.context.pipeline.query.ir import At, Predicate, Query
from grace.context.pipeline.query.result import Witness, scope_note

HISTORY = "t017-fixture"
MODES = ("rdf11", "rdf12")


def claim(cid, s, p, o, v, start=None, end=None, scope=None):
    obj = o if isinstance(o, Value) else Entity(o)
    return Claim(cid, s, p, obj, scope, ValidTime(start, end), v)


def att(aid, cid, v, speaker, fn, msg=None):
    return Attribution(aid, cid, speaker, CommunicativeFunction(fn), ReportMode.OWN,
                       Polarity.POSITIVE, Certainty.CERTAIN, False, msg or f"m{v}", v)


def ev(eid, cid, v, span=None, msg=None):
    return EvidenceLink(eid, cid, msg or f"m{v}", Span(*span) if span else None, v)


def time(text):
    return Value(text, "time")


def changesets() -> list[ChangeSet]:
    """The fixture history, one change set per version."""
    return [
        ChangeSet(HISTORY, 1,
                  claims=(claim("c_atlas", "lina", "responsibleFor", "Atlas", 1),
                          claim("c_berlin", "lina", "livesIn", "Berlin", 1, start="2020-01-01"),
                          claim("c_tea", "lina", "prefers", "tea", 1, scope="work"),
                          claim("c_coffee", "lina", "prefers", "coffee", 1)),
                  attributions=(att("a_atlas", "c_atlas", 1, "user", "inform"),
                                att("a_berlin", "c_berlin", 1, "user", "inform"),
                                att("a_tea", "c_tea", 1, "user", "inform"),
                                att("a_coffee", "c_coffee", 1, "user", "inform")),
                  evidence_links=(ev("e_atlas", "c_atlas", 1), ev("e_berlin", "c_berlin", 1),
                                  ev("e_tea", "c_tea", 1), ev("e_coffee", "c_coffee", 1))),
        ChangeSet(HISTORY, 2,
                  claims=(claim("c_violin", "melanie", "playsInstrument", "violin", 2,
                                start="2023-05-25"),),
                  attributions=(att("a_violin", "c_violin", 2, "melanie", "inform"),),
                  evidence_links=(ev("e_violin", "c_violin", 2, span=(4, 30)),)),
        ChangeSet(HISTORY, 3,
                  claims=(claim("c_req", "request1", "arriveBy", time("20:45:00"), 3),),
                  attributions=(att("a_req", "c_req", 3, "user", "request"),),
                  evidence_links=(ev("e_req", "c_req", 3),)),
        ChangeSet(HISTORY, 4,
                  claims=(claim("c_offer", "request1", "selectedService", "TR7143", 4),
                          claim("c_arr", "TR7143", "scheduledArrival", time("20:38:00"), 4)),
                  attributions=(att("a_offer", "c_offer", 4, "system", "offer"),
                                att("a_arr", "c_arr", 4, "system", "inform")),
                  evidence_links=(ev("e_offer", "c_offer", 4), ev("e_arr", "c_arr", 4))),
        ChangeSet(HISTORY, 5,
                  claims=(claim("c_offer2", "request1", "selectedService", "TR9999", 5),),
                  attributions=(att("a_acc", "c_offer", 5, "user", "accept"),
                                att("a_offer2", "c_offer2", 5, "system", "offer")),
                  evidence_links=(ev("e_acc", "c_offer", 5), ev("e_offer2", "c_offer2", 5))),
        ChangeSet(HISTORY, 6,
                  claims=(claim("c_clarinet", "melanie", "playsInstrument", "clarinet", 6,
                                start="2023-08-28"),),
                  attributions=(att("a_clarinet", "c_clarinet", 6, "melanie", "inform"),
                                att("a_violin2", "c_violin", 6, "melanie", "inform")),
                  evidence_links=(ev("e_clarinet", "c_clarinet", 6),
                                  ev("e_violin2", "c_violin", 6))),
        ChangeSet(HISTORY, 7,
                  claims=(claim("c_munich", "lina", "livesIn", "Munich", 7, start="2023-03-01"),),
                  attributions=(att("a_munich", "c_munich", 7, "user", "inform"),),
                  evidence_links=(ev("e_munich", "c_munich", 7),),
                  supersessions=(Supersession("s_berlin", "c_berlin", SupersessionKind.CHANGE,
                                              "2023-03-01", "c_munich", "a_munich", 7),)),
        ChangeSet(HISTORY, 8,
                  claims=(claim("c_arr2", "TR7143", "scheduledArrival", time("20:40:00"), 8),),
                  attributions=(att("a_arr2", "c_arr2", 8, "system", "inform"),),
                  evidence_links=(ev("e_arr2", "c_arr2", 8),),
                  supersessions=(Supersession("s_arr", "c_arr", SupersessionKind.CORRECTION,
                                              None, "c_arr2", "a_arr2", 8),)),
    ]


HEAD = 8


def build_store(mode="rdf11", upto=HEAD) -> ClaimStore:
    store = ClaimStore(HISTORY, mode)
    for cs in changesets():
        if cs.version <= upto:
            store.commit(cs)
    return store


def W(*ids) -> Witness:
    return Witness.of([i for i in ids if i.startswith("c_")],
                      [i for i in ids if i.startswith("a_")])


E = Entity
ACCEPTED = """SELECT ?train ?arr WHERE {
  (request1, selectedService, ?train) [user, accept] .
  (?train, scheduledArrival, ?arr)
}"""
ACCEPTED_3 = """SELECT ?train ?arr ?req WHERE {
  (request1, arriveBy, ?req) [user, request] .
  (request1, selectedService, ?train) [user, accept] .
  (?train, scheduledArrival, ?arr)
}"""
OPEN_OFFERS = """SELECT ?train WHERE {
  (request1, selectedService, ?train) [system, offer]
  NOT EXISTS { (request1, selectedService, ?train) [user, accept] }
}"""
INSTRUMENTS = "SELECT ?i WHERE { (melanie, playsInstrument, ?i) }"
COUNT = "SELECT COUNT(DISTINCT ?i) WHERE { (melanie, playsInstrument, ?i) }"
COUNT_BY = "SELECT ?p COUNT(DISTINCT ?i) WHERE { (?p, playsInstrument, ?i) }"
LATEST_OFFER = """SELECT ?train WHERE { (request1, selectedService, ?train) [system, offer] AS ?c }
LATEST BY version OF ?c"""
LATEST_CHOICE = """SELECT ?train WHERE { (request1, selectedService, ?train) [user, accept] AS ?c }
LATEST BY version OF ?c"""
LATEST_INSTRUMENT = """SELECT ?i WHERE { (melanie, playsInstrument, ?i) AS ?c }
LATEST BY valid OF ?c"""
CITY = "SELECT ?city WHERE { (lina, livesIn, ?city) }"
ARRIVAL = "SELECT ?a WHERE { (TR7143, scheduledArrival, ?a) }"

# Every query of the suite, used by the time-travel tests.
SUITE = (ACCEPTED, ACCEPTED_3, OPEN_OFFERS, INSTRUMENTS, COUNT, COUNT_BY, LATEST_OFFER,
         LATEST_CHOICE, LATEST_INSTRUMENT, CITY, ARRIVAL,
         CITY + " AT(state=historical)",
         CITY + ' AT(valid="2022-06-01"^^date, state=historical)',
         ARRIVAL + " AT(state=historical)",
         'SELECT ?t WHERE { (?t, scheduledArrival, ?a) FILTER(?a <= "20:39:00"^^time) }',
         'SELECT ?i WHERE { (melanie, playsInstrument, ?i) AS ?c '
         'FILTER(start(?c) >= "2023-06-01"^^date) }',
         'SELECT ?city WHERE { (lina, livesIn, ?city) AS ?c FILTER(end(?c) <= "2023-06-01"^^date) }'
         ' AT(state=historical)',
         "SELECT ?x WHERE { (lina, prefers, ?x, default) }",
         "SELECT ?p WHERE { (lina, ?p, Atlas) }")


class ModeTest(unittest.TestCase):
    """Runs every test once per serialisation mode."""

    def setUp(self):
        self.stores = {mode: build_store(mode) for mode in MODES}

    def answers(self, text, version=HEAD, mode=None):
        """{answer values: witnesses} of the query; the same in both modes."""
        out = None
        for m in ([mode] if mode else MODES):
            result = run(parse(text), self.stores[m], version)
            got = {a.values: a.witnesses for a in result.answers}
            if out is not None:
                self.assertEqual(got, out, f"modes disagree on {text}")
            out = got
        return out

    def result(self, text, version=HEAD, mode="rdf11"):
        return run(parse(text), self.stores[mode], version)


class FilterAndJoinTest(ModeTest):
    def test_filter_against_a_constant(self):
        text = 'SELECT ?t WHERE { (?t, scheduledArrival, ?a) FILTER(?a <= "20:39:00"^^time) }'
        self.assertEqual(self.answers(text, 4), {(E("TR7143"),): (W("c_arr"),)})
        # The 20:38 claim was corrected to 20:40 at version 8: no answer any more.
        self.assertEqual(self.answers(text, 8), {})

    def test_filter_on_valid_time_start(self):
        text = ('SELECT ?i WHERE { (melanie, playsInstrument, ?i) AS ?c '
                'FILTER(start(?c) >= "2023-06-01"^^date) }')
        self.assertEqual(self.answers(text, 6), {(E("clarinet"),): (W("c_clarinet"),)})

    def test_filter_on_effective_valid_end(self):
        before = ('SELECT ?city WHERE { (lina, livesIn, ?city) AS ?c '
                  'FILTER(end(?c) <= "2023-06-01"^^date) } AT(state=historical)')
        after = before.replace("<=", ">")
        # Before version 7 Berlin's end is open; the change supersession states 2023-03-01.
        self.assertEqual(self.answers(before, 6), {})
        self.assertEqual(self.answers(before, 7), {(E("Berlin"),): (W("c_berlin"),)})
        self.assertEqual(self.answers(after, 6), {(E("Berlin"),): (W("c_berlin"),)})
        self.assertEqual(self.answers(after, 7), {(E("Munich"),): (W("c_munich"),)})

    def test_entity_filters(self):
        eq = 'SELECT ?city WHERE { (lina, livesIn, ?city) FILTER(?city = Berlin) } ' \
             'AT(state=historical)'
        self.assertEqual(self.answers(eq, 7), {(E("Berlin"),): (W("c_berlin"),)})
        ne = eq.replace("?city = Berlin", "?city != Berlin")
        self.assertEqual(self.answers(ne, 7), {(E("Munich"),): (W("c_munich"),)})

    def test_join_of_two_patterns_with_attribution_constraint(self):
        self.assertEqual(self.answers(ACCEPTED, 4), {})
        self.assertEqual(self.answers(ACCEPTED, 5),
                         {(E("TR7143"), time("20:38:00")): (W("c_offer", "a_acc", "c_arr"),)})
        # After the correction the answer and its witness change.
        self.assertEqual(self.answers(ACCEPTED, 8),
                         {(E("TR7143"), time("20:40:00")): (W("c_offer", "a_acc", "c_arr2"),)})

    def test_join_of_three_patterns(self):
        self.assertEqual(
            self.answers(ACCEPTED_3, 5),
            {(E("TR7143"), time("20:38:00"), time("20:45:00")):
             (W("c_req", "a_req", "c_offer", "a_acc", "c_arr"),)})

    def test_one_answer_has_several_minimal_witnesses(self):
        # Two acceptances of the same claim are two minimal witnesses of one answer.
        store = build_store()
        store.commit(ChangeSet(HISTORY, 9, attributions=(att("a_acc2", "c_offer", 9, "user",
                                                             "accept"),),
                               evidence_links=(ev("e_acc2", "c_offer", 9),)))
        result = run(parse("SELECT ?t WHERE { (request1, selectedService, ?t) [user, accept] }"),
                     store, 9)
        self.assertEqual([a.witnesses for a in result.answers],
                         [(W("c_offer", "a_acc"), W("c_offer", "a_acc2"))])

    def test_witnesses_are_minimal_when_patterns_share_a_claim(self):
        text = ("SELECT ?t WHERE { (request1, selectedService, ?t) . "
                "(request1, selectedService, ?t) [user, accept] }")
        # Row 1 binds both patterns to c_offer: {c_offer, a_acc} is the only minimal witness.
        self.assertEqual(self.answers(text, 5), {(E("TR7143"),): (W("c_offer", "a_acc"),)})

    def test_scope_positions(self):
        any_scope = "SELECT ?x WHERE { (lina, prefers, ?x) }"
        self.assertEqual(set(self.answers(any_scope)), {(E("coffee"),), (E("tea"),)})
        default = "SELECT ?x WHERE { (lina, prefers, ?x, default) }"
        self.assertEqual(self.answers(default), {(E("coffee"),): (W("c_coffee"),)})
        constant = 'SELECT ?x WHERE { (lina, prefers, ?x, "work") }'
        self.assertEqual(self.answers(constant), {(E("tea"),): (W("c_tea"),)})
        variable = "SELECT ?x ?s WHERE { (lina, prefers, ?x, ?s) }"
        self.assertEqual(self.answers(variable), {(E("tea"), Value("work")): (W("c_tea"),)})

    def test_predicate_variable(self):
        self.assertEqual(self.answers("SELECT ?p WHERE { (lina, ?p, Atlas) }"),
                         {(Predicate("responsibleFor"),): (W("c_atlas"),)})


class NegationTest(ModeTest):
    def test_offered_and_not_yet_accepted(self):
        self.assertEqual(self.answers(OPEN_OFFERS, 4), {(E("TR7143"),): (W("c_offer", "a_offer"),)})
        # The acceptance supersedes nothing but empties the old answer; TR9999 is a new match.
        self.assertEqual(self.answers(OPEN_OFFERS, 5),
                         {(E("TR9999"),): (W("c_offer2", "a_offer2"),)})

    def test_negated_pattern_contributes_no_witness(self):
        result = self.result(OPEN_OFFERS, 5)
        claims = {c for a in result.answers for w in a.witnesses for c in w.claims}
        atts = {x for a in result.answers for w in a.witnesses for x in w.attributions}
        self.assertNotIn("a_acc", atts)
        self.assertEqual(claims, {"c_offer2"})

    def test_negation_with_local_filter(self):
        # Offered trains not known to arrive after a limit; ?a is local to the negation.
        text = """SELECT ?t WHERE { (request1, selectedService, ?t) [system, offer]
          NOT EXISTS { (?t, scheduledArrival, ?a) FILTER(?a > "{}"^^time) } }"""
        self.assertEqual(set(self.answers(text.replace("{}", "20:45:00"), 5)),
                         {(E("TR7143"),), (E("TR9999"),)})
        self.assertEqual(self.answers(text.replace("{}", "20:30:00"), 5),
                         {(E("TR9999"),): (W("c_offer2", "a_offer2"),)})


class CountTest(ModeTest):
    def test_distinct_count_and_union_witness(self):
        self.assertEqual(self.answers(COUNT, 2), {(Value("1", "integer"),): (W("c_violin"),)})
        self.assertEqual(self.answers(COUNT, 6),
                         {(Value("2", "integer"),): (W("c_violin", "c_clarinet"),)})

    def test_count_of_nothing_is_zero_with_scope_note(self):
        result = self.result(COUNT, 1)
        self.assertEqual([a.values for a in result.answers], [(Value("0", "integer"),)])
        self.assertEqual(result.answers[0].witnesses, ())
        self.assertEqual(scope_note(result), "Counted within the scope observed up to version 1.")

    def test_grouped_count(self):
        self.assertEqual(self.answers(COUNT_BY, 6),
                         {(E("melanie"), Value("2", "integer")): (W("c_violin", "c_clarinet"),)})

    def test_sparql_aggregate_agrees_with_member_count(self):
        for mode, store in self.stores.items():
            for text in (COUNT, COUNT_BY):
                compiled = compile_query(parse(text), mode)
                for version in range(1, HEAD + 1):
                    _, count = compiled.bind()
                    sparql = [int(row["_count"].value) for row in store.query(count, version)]
                    ours = [int(a.values[-1].lexical) for a in
                            execute(compiled, store, version).answers]
                    self.assertEqual(sorted(sparql), sorted(ours), (mode, text, version))


class LatestTest(ModeTest):
    def test_latest_by_version(self):
        self.assertEqual(self.answers(LATEST_OFFER, 4),
                         {(E("TR7143"),): (W("c_offer", "a_offer"),)})
        self.assertEqual(self.answers(LATEST_OFFER, 5),
                         {(E("TR9999"),): (W("c_offer2", "a_offer2"),)})

    def test_latest_confirmed_uses_the_version_of_the_confirmation(self):
        self.assertEqual(self.answers(LATEST_CHOICE, 4), {})
        self.assertEqual(self.answers(LATEST_CHOICE, 5), {(E("TR7143"),): (W("c_offer", "a_acc"),)})

    def test_latest_by_valid_time(self):
        self.assertEqual(self.answers(LATEST_INSTRUMENT, 2), {(E("violin"),): (W("c_violin"),)})
        self.assertEqual(self.answers(LATEST_INSTRUMENT, 6),
                         {(E("clarinet"),): (W("c_clarinet"),)})

    def test_ties_keep_every_tied_answer(self):
        text = """SELECT ?p WHERE { (lina, prefers, ?p) AS ?c } LATEST BY version OF ?c"""
        self.assertEqual(set(self.answers(text)), {(E("coffee"),), (E("tea"),)})


class StateTest(ModeTest):
    def test_current_state_excludes_both_kinds(self):
        self.assertEqual(self.answers(CITY, 6), {(E("Berlin"),): (W("c_berlin"),)})
        self.assertEqual(self.answers(CITY, 7), {(E("Munich"),): (W("c_munich"),)})
        self.assertEqual(self.answers(ARRIVAL, 8), {(time("20:40:00"),): (W("c_arr2"),)})

    def test_historical_state_keeps_changes_and_drops_corrections(self):
        hist = CITY + " AT(state=historical)"
        self.assertEqual(set(self.answers(hist, 7)), {(E("Berlin"),), (E("Munich"),)})
        arrival = ARRIVAL + " AT(state=historical)"
        self.assertEqual(set(self.answers(arrival, 7)), {(time("20:38:00"),)})
        self.assertEqual(set(self.answers(arrival, 8)), {(time("20:40:00"),)})

    def test_valid_time_parameter(self):
        q = CITY + ' AT(valid="%s"^^date, state=historical)'
        self.assertEqual(set(self.answers(q % "2022-06-01", 7)), {(E("Berlin"),)})
        self.assertEqual(set(self.answers(q % "2023-06-01", 7)), {(E("Munich"),)})
        # Known at version 6, Berlin had no end: "what was known then".
        self.assertEqual(set(self.answers(q % "2023-06-01", 6)), {(E("Berlin"),)})
        # Before Berlin's start nothing is known to hold.
        self.assertEqual(self.answers(q % "2019-01-01", 7), {})

    def test_valid_time_with_unknown_bounds_is_not_excluded(self):
        q = 'SELECT ?x WHERE { (lina, responsibleFor, ?x) } AT(valid="1999-01-01"^^date)'
        self.assertEqual(set(self.answers(q)), {(E("Atlas"),)})


class ProvenanceTest(ModeTest):
    def test_evidence_of_witness_claims(self):
        r2 = self.result(INSTRUMENTS, 2)
        self.assertEqual([a.evidence for a in r2.answers], [("m2#char=4,30",)])
        r6 = self.result(INSTRUMENTS, 6)
        by_value = {a.values: a.evidence for a in r6.answers}
        # The repeated mention adds one evidence link: same answer and witness, new citation.
        self.assertEqual(by_value[(E("violin"),)], ("m2#char=4,30", "m6"))
        self.assertEqual(by_value[(E("clarinet"),)], ("m6",))
        self.assertEqual(r6.evidence["c_violin"], ("m2#char=4,30", "m6"))

    def test_evidence_of_a_join_covers_offer_and_acceptance(self):
        result = self.result(ACCEPTED, 5)
        self.assertEqual(result.answers[0].evidence, ("m4", "m5"))

    def test_fingerprints_separate_answer_and_citation_staleness(self):
        f2 = self.result(INSTRUMENTS, 2).fingerprints()
        violin_only = 'SELECT ?i WHERE { (melanie, playsInstrument, ?i) FILTER(?i = violin) }'
        a = self.result(violin_only, 2).fingerprints()
        b = self.result(violin_only, 6).fingerprints()
        self.assertEqual(a["answers"], b["answers"])
        self.assertEqual(a["witnesses"], b["witnesses"])
        self.assertNotEqual(a["evidence"], b["evidence"])
        self.assertNotEqual(f2["answers"], self.result(INSTRUMENTS, 6).fingerprints()["answers"])

    def test_without_provenance_skips_the_evidence_query(self):
        result = self.result(INSTRUMENTS + " WITHOUT PROVENANCE", 6)
        self.assertEqual(dict(result.evidence), {})
        self.assertTrue(all(a.evidence == () and a.witnesses for a in result.answers))

    def test_empty_result_scope_note(self):
        result = self.result(ACCEPTED, 4)
        self.assertTrue(result.empty)
        self.assertEqual(scope_note(result),
                         "No matching claim within the scope observed up to version 4.")
        self.assertIsNone(scope_note(self.result(ACCEPTED, 5)))
        self.assertNotIn("scope", self.result(ACCEPTED, 4).to_record())


class TimeTravelTest(unittest.TestCase):
    """Q[r0] on G_r equals Q[r0] on G_r0 for every r >= r0 (plan 3.3)."""

    def test_fixed_cutoff_reads_are_unchanged_by_later_appends(self):
        for mode in MODES:
            full = build_store(mode)
            for text in SUITE:
                query = parse(text)
                for r0 in range(0, HEAD + 1):
                    past = build_store(mode, upto=r0)
                    expected = run(query, past, r0)
                    fixed = Query(query.select, query.where, query.filters, query.negation,
                                  query.count, query.latest,
                                  At(r0, query.at.valid, query.at.state), query.provenance)
                    for version in range(r0, HEAD + 1):
                        got = run(fixed, full, version)
                        self.assertEqual(got.answers, expected.answers, (mode, text, r0, version))
                        self.assertEqual(got.fingerprints(), expected.fingerprints())

    def test_result_at_a_past_version_survives_appends_to_the_same_store(self):
        store = build_store(upto=5)
        compiled = [compile_query(parse(text)) for text in SUITE]
        before = [execute(c, store, 5) for c in compiled]
        for cs in changesets():
            if cs.version > 5:
                store.commit(cs)
        for c, b in zip(compiled, before, strict=True):
            fixed = compile_query(Query(c.query.select, c.query.where, c.query.filters,
                                        c.query.negation, c.query.count, c.query.latest,
                                        At(5, c.query.at.valid, c.query.at.state)))
            self.assertEqual(execute(fixed, store, HEAD).answers, b.answers)
            self.assertEqual(execute(c, store, 5).answers, b.answers)

    def test_cutoff_after_the_read_version_is_refused(self):
        store = build_store(upto=3)
        with self.assertRaises(ValueError):
            run(parse(CITY + " AT(known=5)"), store, 3)


class EntityMergeTest(unittest.TestCase):
    def test_constants_match_the_class_and_answers_use_the_representative(self):
        store = ClaimStore("merge")
        store.commit(ChangeSet("merge", 1,
                               claims=(claim("c1", "train7143", "scheduledArrival",
                                             time("20:38:00"), 1),
                                       claim("c2", "request1", "selectedService", "train7143", 1)),
                               attributions=(att("a1", "c1", 1, "system", "inform"),
                                             att("a2", "c2", 1, "system", "offer")),
                               evidence_links=(ev("e1", "c1", 1), ev("e2", "c2", 1))))
        store.commit(ChangeSet("merge", 2, entity_merges=(
            EntityEquivalence("q1", "TR7143", "train7143", 2),)))
        by_constant = parse("SELECT ?a WHERE { (TR7143, scheduledArrival, ?a) }")
        self.assertEqual(run(by_constant, store, 1).answers, ())
        self.assertEqual([a.values for a in run(by_constant, store, 2).answers],
                         [(time("20:38:00"),)])
        answer = parse("SELECT ?t WHERE { (request1, selectedService, ?t) }")
        self.assertEqual([a.values for a in run(answer, store, 1).answers], [(E("train7143"),)])
        self.assertEqual([a.values for a in run(answer, store, 2).answers], [(E("TR7143"),)])


class RelativeTimeTest(ModeTest):
    def test_absolutized_query_runs_and_is_temporary(self):
        text = ('SELECT ?i WHERE { (melanie, playsInstrument, ?i) AS ?c '
                'FILTER(start(?c) >= now(-30)) }')
        query = absolutize(parse(text, check=False), dt.date(2023, 9, 1))
        self.assertTrue(query.temporary)
        result = run(query, self.stores["rdf11"], 6)
        self.assertTrue(result.temporary)
        self.assertEqual([a.values for a in result.answers], [(E("clarinet"),)])


if __name__ == "__main__":
    unittest.main()
