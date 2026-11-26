"""Tie-break of the effective valid end (contracts.md, "Claim graph"; formalisation.md, A6).

Two change supersessions of one claim in one change set may both state a valid end. The claim
graph (`GraphState.valid_end`), the compiled query (`end(?c)` filters and `AT(valid=)`) and the
change matcher (`matching.Index.valid_end`) must take the same one, or the matcher can decide a
local `end()` filter false while the query holds it true: a missed mark.

The supersession IDs `s0` and `s:2` reorder under the percent-encoding of entry IRIs (`s0` <
`s:2`, but `s%3A2` < `s0`), so a tie-break by ID or by IRI would split the implementations. The
rule is by value: among the change supersessions with the earliest stamp that state a valid end,
the earliest valid end.
"""

from __future__ import annotations

import unittest

from grace.context.memory.graph.changeset import ChangeSet
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
    Supersession,
    SupersessionKind,
    ValidTime,
    effective_change_end,
)
from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.query.execute import run
from grace.context.pipeline.query.grammar import parse
from grace.context.views.dependencies import dependency_patterns
from grace.context.views.staleness.matching import Index, triggers

H = "valid-end-tiebreak"
MODES = ("rdf11", "rdf12")
EARLY, LATE = "2023-01-01", "2024-01-01"
BETWEEN = "2023-06-01"  # EARLY <= BETWEEN < LATE
END_LE = ('SELECT ?x WHERE { (user, livesIn, ?x) AS ?c FILTER(end(?c) <= "%s"^^date) } '
          'AT(state=historical)')
AT_VALID = 'SELECT ?x WHERE { (user, livesIn, ?x) } AT(valid="%s"^^date, state=historical)'


def att(aid, cid, v, polarity=Polarity.POSITIVE):
    return Attribution(aid, cid, "user", CommunicativeFunction.INFORM, ReportMode.OWN, polarity,
                       Certainty.CERTAIN, False, f"m{v}", v)


def change(sid, end, licence, v=2, cid="c1"):
    return Supersession(sid, cid, SupersessionKind.CHANGE, end, None, licence, v)


def history(ends: dict[str, str]) -> list[ChangeSet]:
    """c1 (user livesIn Munich, open end) at 1; at 2, one change removal per (ID, valid end)."""
    first = ChangeSet(H, 1, (Claim("c1", "user", "livesIn", Entity("Munich"), None,
                                   ValidTime("2020-01-01"), 1),),
                      (att("a1", "c1", 1),), (EvidenceLink("e1", "c1", "m1", None, 1),))
    licences = tuple(att(f"n{i}", "c1", 2, Polarity.NEGATIVE) for i in range(len(ends)))
    sups = tuple(change(sid, end, f"n{i}") for i, (sid, end) in enumerate(ends.items()))
    return [first, ChangeSet(H, 2, attributions=licences, supersessions=sups)]


def store(changesets, mode):
    s = ClaimStore(H, mode)
    for cs in changesets:
        s.commit(cs)
    return s


def answers(text, s, version):
    return {a.values for a in run(parse(text), s, version).answers}


# Both assignments of the two ends to the two IDs: whichever ID or IRI order is used, one of
# them puts the later end first.
CASES = {"s0 late": {"s0": LATE, "s:2": EARLY}, "s0 early": {"s0": EARLY, "s:2": LATE}}


class TieBreakTest(unittest.TestCase):
    def test_ids_reorder_under_percent_encoding(self):
        from urllib.parse import quote

        self.assertLess("s0", "s:2")
        self.assertLess(quote("s:2", safe=""), quote("s0", safe=""))

    def test_graph_state_takes_the_earliest_valid_end(self):
        for name, ends in CASES.items():
            with self.subTest(name):
                for mode in MODES:
                    st = store(history(ends), mode)
                    self.assertIsNone(st.state(1).valid_end("c1"))
                    self.assertEqual(st.state(2).valid_end("c1"), EARLY)

    def test_compiled_query_agrees_with_graph_state(self):
        """`end(?c) <= d` holds iff the graph state's end is <= d; `AT(valid=d)` drops the
        claim iff its end is <= d. Checked at d between, before and after the two ends."""
        munich = {(Entity("Munich"),)}
        for name, ends in CASES.items():
            for mode in MODES:
                st = store(history(ends), mode)
                end = st.state(2).valid_end("c1")
                for d in ("2022-06-01", EARLY, BETWEEN, LATE, "2024-06-01"):
                    with self.subTest(name, mode=mode, d=d):
                        self.assertEqual(answers(END_LE % d, st, 2),
                                         munich if end <= d else set())
                        self.assertEqual(answers(AT_VALID % d, st, 2),
                                         set() if end <= d else munich)

    def test_matcher_agrees_with_graph_state(self):
        for name, ends in CASES.items():
            with self.subTest(name):
                changesets = history(ends)
                index = Index()
                for cs in changesets:
                    index.add(cs)
                c1 = changesets[0].claims[0]
                self.assertIsNone(index.valid_end(c1, 1))
                self.assertEqual(index.valid_end(c1, 2),
                                 store(changesets, "rdf11").state(2).valid_end("c1"))

    def test_local_end_filter_view_is_marked_when_the_query_changes(self):
        """No missed mark: if the answers at 2 differ from those at 1 (read-time re-query), the
        matcher raises a trigger for the view's local `end()` filter."""
        query = parse(END_LE % BETWEEN)
        dependencies = dependency_patterns(query)
        self.assertEqual(len(dependencies[0].filters), 1)
        for name, ends in CASES.items():
            with self.subTest(name):
                changesets = history(ends)
                st = store(changesets, "rdf11")
                changed = answers(END_LE % BETWEEN, st, 1) != answers(END_LE % BETWEEN, st, 2)
                self.assertTrue(changed)
                index = Index()
                index.add(changesets[0])
                index.add(changesets[1])
                found = {t.entry for t in triggers(dependencies, changesets[1], index)}
                self.assertEqual(found, {"s0", "s:2"})


class TotalOrderTest(unittest.TestCase):
    """Same-stamp valid ends on one claim must be comparable, so that "earliest" is defined in
    SPARQL as in Python (a date and a dateTime, or a zoned and an unzoned dateTime, are not)."""

    def cs(self, *sups):
        return ChangeSet(H, 2, supersessions=sups)

    def test_incomparable_same_stamp_ends_are_rejected(self):
        for a, b in (("2023-01-01", "2023-01-01T00:00:00"),
                     ("2023-01-01T00:00:00", "2023-01-01T00:00:00Z")):
            with self.subTest(a=a, b=b), self.assertRaises(EntryError):
                self.cs(change("s1", a, "n1"), change("s2", b, "n2"))

    def test_comparable_or_separate_ends_are_accepted(self):
        self.cs(change("s1", "2023-01-01T00:00:00Z", "n1"),
                change("s2", "2023-01-01T05:00:00+02:00", "n2"))
        self.cs(change("s1", "2023-01-01", "n1"), change("s2", "2023-01-01T00:00:00", "n2",
                                                         cid="c2"))
        self.cs(change("s1", "2023-01-01", "n1"),
                Supersession("s2", "c1", SupersessionKind.CHANGE, None, None, "n2", 2))

    def test_equal_instants_pick_one_lexical_form(self):
        sups = (change("s1", "2023-01-01T02:00:00+02:00", "n1"),
                change("s2", "2023-01-01T00:00:00Z", "n2"))
        self.assertEqual(effective_change_end(sups), "2023-01-01T00:00:00Z")
        self.assertEqual(effective_change_end(reversed(sups)), "2023-01-01T00:00:00Z")

    def test_earliest_stamp_wins_over_an_earlier_value(self):
        sups = (change("s1", LATE, "n1", v=2), change("s2", EARLY, "n2", v=3))
        self.assertEqual(effective_change_end(sups), LATE)
        self.assertIsNone(effective_change_end(()))


if __name__ == "__main__":
    unittest.main()
