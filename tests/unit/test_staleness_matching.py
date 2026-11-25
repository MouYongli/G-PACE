"""Dependency patterns and change-set matching of the staleness strategies (T019; plan 3.4, 5.4).

The patterns come from the T018 template families bound like the change-sequence views; the
change sets are written by hand, so every expected trigger is stated here, not computed.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

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
    Supersession,
    SupersessionKind,
    ValidTime,
    Value,
)
from grace.context.pipeline.query.ir import Var
from grace.context.views.dependencies import NEGATED, POSITIVE, dependency_patterns
from grace.context.views.staleness.matching import (
    ANSWER,
    CITATION,
    Index,
    Options,
    triggers,
)
from grace.context.views.template_families import ViewConfig, load_families
from grace.context.views.view import Binding

H = "t019-unit"
DEFAULT = Options()
CONFIG = ViewConfig(state_speaker="user")
FAMILIES = load_families()


def deps(family, subject, predicate=None):
    return dependency_patterns(FAMILIES[family].bind(Binding(family, subject, predicate), CONFIG))


def claim(cid, s, p, o, v, start=None, end=None):
    obj = o if isinstance(o, Value) else Entity(o)
    return Claim(cid, s, p, obj, None, ValidTime(start, end), v)


def att(aid, cid, v, speaker="user", fn="inform", mode=ReportMode.OWN,
        polarity=Polarity.POSITIVE, derived=False):
    return Attribution(aid, cid, speaker, CommunicativeFunction(fn), mode, polarity,
                       Certainty.CERTAIN, derived, f"m{v}", v)


def relax(dependencies, **fields):
    """The dependency patterns with the given attribution fields relaxed (set to None)."""
    return tuple(replace(d, pattern=replace(d.pattern, attribution=replace(
        d.pattern.attribution, **dict.fromkeys(fields, None)))) for d in dependencies)


def ev(eid, cid, v):
    return EvidenceLink(eid, cid, f"m{v}", None, v)


def cs(v, claims=(), atts=(), evs=(), sups=(), merges=()):
    return ChangeSet(H, v, tuple(claims), tuple(atts), tuple(evs), tuple(sups),
                     entity_merges=tuple(merges))


class Matcher:
    def __init__(self):
        self.index = Index()

    def __call__(self, dependencies, changeset, options=DEFAULT):
        self.index.add(changeset)
        return {(t.level, t.entry, t.role) for t in triggers(dependencies, changeset,
                                                             self.index, options)}


class DependencyPatternsTest(unittest.TestCase):
    def test_negated_pattern_with_its_attribution_constraint(self):
        d = deps("pending", "k1")
        self.assertEqual([x.role for x in d], [POSITIVE, NEGATED])
        neg = d[1].pattern
        self.assertEqual(neg.attribution.speaker, Entity("user"))
        self.assertIsNone(neg.attribution.function)
        self.assertEqual(d[0].pattern.attribution.function, CommunicativeFunction.OFFER)

    def test_aggregated_and_selected_patterns(self):
        self.assertTrue(all(x.aggregated for x in deps("count", "user", "plays")))
        choice = deps("choice", "k1")
        self.assertEqual([(x.role, x.selected) for x in choice],
                         [(POSITIVE, True), (POSITIVE, False), (NEGATED, False)])
        self.assertIsInstance(choice[1].pattern.predicate, Var)

    def test_local_filter_on_the_valid_end(self):
        (current,) = deps("current", "user", "livesIn")
        self.assertEqual(len(current.filters), 1)
        self.assertEqual(current.to_record()["filters"][0]["op"], ">")

    def test_record_keeps_the_attribution_defaults_and_relaxations(self):
        (d,) = deps("list", "user", "plays")
        self.assertEqual(d.to_record()["attribution"],
                         {"speaker": {"entity": "user"}, "function": "inform",
                          "report_mode": "own", "polarity": "positive", "derived": False})
        (loose,) = relax((d,), report_mode=1, polarity=1, derived=1)
        self.assertEqual(loose.to_record()["attribution"],
                         {"speaker": {"entity": "user"}, "function": "inform",
                          "report_mode": None, "polarity": None, "derived": None})


class TriggerTest(unittest.TestCase):
    def test_new_claim_matches_through_its_attribution(self):
        m, d = Matcher(), deps("list", "user", "plays")
        found = m(d, cs(1, [claim("c1", "user", "plays", Value("violin"), 1)],
                        [att("a1", "c1", 1)], [ev("e1", "c1", 1)]))
        self.assertEqual(found, {(ANSWER, "a1", POSITIVE), (CITATION, "e1", POSITIVE)})

    def test_attribution_by_another_speaker_does_not_match(self):
        m, d = Matcher(), deps("list", "user", "plays")
        found = m(d, cs(1, [claim("c1", "user", "plays", Value("violin"), 1)],
                        [att("a1", "c1", 1, speaker="assistant")], [ev("e1", "c1", 1)]))
        self.assertEqual(found, set())
        # A later endorsing attribution on the existing claim matches (plan 3.3).
        self.assertEqual(m(d, cs(2, atts=[att("a2", "c1", 2)])), {(ANSWER, "a2", POSITIVE)})
        # Without attribution constraints the bare claim pattern matches the claim itself.
        m2 = Matcher()
        loose = m2(d, cs(1, [claim("c1", "user", "plays", Value("violin"), 1)],
                         [att("a1", "c1", 1, speaker="assistant")]),
                   Options(attribution=False))
        self.assertEqual(loose, {(ANSWER, "c1", POSITIVE)})

    def test_attribution_defaults_own_positive_not_derived(self):
        """F1 (plan 3.3): a quote, hypothetical, denial or derived attribution does not satisfy
        a default constraint, so it marks nothing; with that field relaxed it marks again."""
        cases = {"quote": ("report_mode", {"mode": ReportMode.QUOTE}),
                 "hypothetical": ("report_mode", {"mode": ReportMode.HYPOTHETICAL}),
                 "denial": ("polarity", {"polarity": Polarity.NEGATIVE}),
                 "derived": ("derived", {"derived": True})}
        d = deps("list", "user", "plays")
        for name, (field, kwargs) in cases.items():
            for dependencies, expected in ((d, set()),
                                           (relax(d, **{field: 1}), {(ANSWER, "a2", POSITIVE)})):
                with self.subTest(case=name, relaxed=dependencies is not d):
                    m = Matcher()
                    # A new claim carrying only that attribution ...
                    first = m(dependencies, cs(1, [claim("c1", "user", "plays",
                                                         Value("violin"), 1)],
                                               [att("a1", "c1", 1, **kwargs)],
                                               [ev("e1", "c1", 1)]))
                    self.assertEqual(first, {(ANSWER, "a1", POSITIVE), (CITATION, "e1", POSITIVE)}
                                     if expected else set())
                    # ... and a later such attribution on an existing claim.
                    m2 = Matcher()
                    m2(dependencies, cs(1, [claim("c2", "user", "plays", Value("cello"), 1)]))
                    self.assertEqual(m2(dependencies, cs(2, atts=[att("a2", "c2", 2, **kwargs)])),
                                     expected)

    def test_relaxing_one_field_keeps_the_other_defaults(self):
        d = relax(deps("list", "user", "plays"), report_mode=1)
        m = Matcher()
        m(d, cs(1, [claim("c1", "user", "plays", Value("violin"), 1)]))
        quoted_denial = att("a2", "c1", 2, mode=ReportMode.QUOTE, polarity=Polarity.NEGATIVE)
        self.assertEqual(m(d, cs(2, atts=[quoted_denial])), set())

    def test_other_subject_or_predicate_does_not_match(self):
        m, d = Matcher(), deps("list", "user", "plays")
        self.assertEqual(m(d, cs(1, [claim("c1", "user", "likes", Value("jazz"), 1),
                                     claim("c2", "bob", "plays", Value("drums"), 1)],
                                 [att("a1", "c1", 1), att("a2", "c2", 1)])), set())

    def test_acceptance_hits_the_negated_pattern_and_supersedes_nothing(self):
        m, d = Matcher(), deps("pending", "k1")
        offer = claim("c4", "k1", "selectedService", "ICE947", 1)
        first = m(d, cs(1, [offer], [att("a4", "c4", 1, "assistant", "offer")],
                        [ev("e4", "c4", 1)]))
        self.assertEqual(first, {(ANSWER, "a4", POSITIVE), (CITATION, "e4", POSITIVE)})
        accept = m(d, cs(2, atts=[att("a6", "c4", 2, "user", "accept")],
                         evs=[ev("e6", "c4", 2)]))
        # The acceptance matches the negated pattern; its evidence link is citation level only,
        # through the positive pattern (negated patterns contribute no witness).
        self.assertEqual(accept, {(ANSWER, "a6", NEGATED), (CITATION, "e6", POSITIVE)})

    def test_supersession_of_a_matching_claim(self):
        m, d = Matcher(), deps("current", "user", "livesIn")
        m(d, cs(1, [claim("c1", "user", "livesIn", Value("Munich"), 1),
                    claim("c9", "user", "worksAt", Value("Acme"), 1)],
                [att("a1", "c1", 1), att("a9", "c9", 1)]))
        found = m(d, cs(2, [claim("c7", "user", "livesIn", Value("Cologne"), 2,
                                  start="2026-11-01")],
                        [att("a7", "c7", 2)],
                        sups=[Supersession("s1", "c1", SupersessionKind.CHANGE, "2026-11-01",
                                           "c7", "a7", 2)]))
        self.assertEqual(found, {(ANSWER, "a7", POSITIVE), (ANSWER, "s1", POSITIVE)})

    def test_local_filter_separates_a_past_dated_claim(self):
        """The `m-past` probe: a claim with a stated valid end never enters the current state."""
        d = deps("current", "user", "livesIn")
        past = cs(1, [claim("c1", "user", "livesIn", Value("Hamburg"), 1, start="2010-01-01",
                            end="2015-01-01")], [att("a1", "c1", 1)])
        self.assertEqual(Matcher()(d, past, Options(local_filters=True)), set())
        self.assertEqual(Matcher()(d, past, Options(local_filters=False)),
                         {(ANSWER, "a1", POSITIVE)})

    def test_supersession_filters_use_the_end_before_the_change(self):
        """A change supersession sets end(?c); the claim matched before it, so it triggers."""
        m, d = Matcher(), deps("current", "user", "livesIn")
        m(d, cs(1, [claim("c1", "user", "livesIn", Value("Munich"), 1)], [att("a1", "c1", 1)]))
        found = m(d, cs(2, [claim("c2", "user", "livesIn", Value("Berlin"), 2,
                                  start="2020-01-01", end="2021-01-01")],
                        [att("a2", "c2", 2)],
                        sups=[Supersession("s1", "c1", SupersessionKind.CHANGE, "2026-01-01",
                                           None, "a2", 2)]))
        self.assertEqual(found, {(ANSWER, "s1", POSITIVE)})

    def test_entity_constants_match_class_members_after_a_merge(self):
        m, d = Matcher(), deps("list", "lina", "maintains")
        m(d, cs(1, merges=[EntityEquivalence("q1", "lina", "lina_b", 1)]))
        found = m(d, cs(2, [claim("c1", "lina_b", "maintains", "Boreal", 2)],
                        [att("a1", "c1", 2)]))
        self.assertEqual(found, {(ANSWER, "a1", POSITIVE)})

    def test_predicate_variable_of_the_choice_join(self):
        m, d = Matcher(), deps("choice", "k1")
        found = m(d, cs(1, [claim("c5", "ICE947", "scheduledArrival", Value("17:25:00", "time"),
                                  1)], [att("a5", "c5", 1, "assistant", "inform")]))
        self.assertEqual(found, {(ANSWER, "a5", POSITIVE)})

    def test_change_sets_must_come_in_order(self):
        index = Index()
        index.add(cs(2))
        with self.assertRaises(ValueError):
            index.add(cs(2))


if __name__ == "__main__":
    unittest.main()
