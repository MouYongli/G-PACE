"""Checks of the exactness proposition of the formalisation (T020; supplement S4).

`paper/latex/supplement/exactness.tex` proves that the claim-pattern decision with local filters
marks a view only if its answers, witnesses or evidence change, for queries that satisfy
(Q1)-(Q4) and changes that satisfy (D1)-(D3). Soundness (no misses) is T019's acceptance
(`test_staleness.py`). This module checks the converse in two ways:

- `ConstructedTest` builds one small change per condition, with the decision computed by
  `matching.triggers` and the result by the compiled query at both cut-offs: each of (D1), (D2),
  (D3) and a (Q4) `end()` filter produces an over-mark, explained by the condition it violates;
  and parts (a) and (b) are shown on changes that satisfy every condition.
- `ReplayTest` replays the claim-pattern-with-filters arm on the T019 fixtures and checks, for
  every view whose query satisfies (Q1)-(Q4) as decided by `query_conditions`, that every
  answer-level mark without a violated (D1)-(D3) comes with a change of answers or witnesses, and
  that every over-mark violates (D1)-(D3). On these fixtures no over-mark occurs, so the second
  check is exercised only by `ConstructedTest`.

The (D3) check compares per answer, as the evidence fingerprint does (`QueryResult.fingerprints`):
a new link on a claim repeats an identifier only if that identifier is already in the evidence of
an answer whose witnesses contain the claim (supplement S1.4, `ev_t`).

The evaluation at an old cut-off is recomputed after the fact, which time-travel stability allows
(supplement S2).
"""

from __future__ import annotations

import unittest

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entries import (
    Attribution,
    Certainty,
    Claim,
    CommunicativeFunction,
    EvidenceLink,
    Polarity,
    ReportMode,
    Supersession,
    SupersessionKind,
    ValidTime,
    Value,
)
from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.query.execute import run
from grace.context.pipeline.query.grammar import parse
from grace.context.pipeline.query.ir import Bound, Query, State, ValidBound, Var
from grace.context.pipeline.query.result import QueryResult
from grace.context.views.dependencies import dependency_patterns
from grace.context.views.staleness.matching import ANSWER, CITATION, Index, Options, triggers
from grace.eval.datasets.changeseq.template_families import load_split
from tests.integration.staleness_replay import Sequence, replay
from tests.integration.test_staleness import generated, projected, worked


def query_conditions(query: Query) -> list[str]:
    """The conditions (Q1)-(Q4) of supplement S4 that `query` violates (empty: all hold).

    A distinct count is allowed (Remark 1). The data part of (Q4), decidable filters, is not a
    property of the query and is not checked here.
    """
    out = []
    if len(query.where) != 1 or query.negation is not None or query.latest is not None \
            or not query.provenance:
        out.append("Q1")
    if query.at.state is not State.CURRENT or query.at.valid is not None:
        out.append("Q2")
    if len(query.where) == 1:
        p = query.where[0]
        terms = [p.subject, p.predicate, p.object, p.scope,
                 p.attribution.speaker if p.attribution else None]
        names = [t for t in terms if isinstance(t, Var)]
        if len(names) != len(set(names)) or isinstance(p.scope, Var):
            out.append("Q3")
    filters = list(query.filters) + list(query.negation.filters if query.negation else ())
    if any(isinstance(f.left, ValidBound) and f.left.bound is Bound.END for f in filters):
        out.append("Q4")
    return out


def _unified(link) -> str:
    if link.span is None:
        return link.message_id
    return f"{link.message_id}#char={link.span.start},{link.span.end}"


def _parse(trigger: str) -> tuple[str, str]:
    """`<kind>:<entry id>@<pattern>/<role>` -> (kind, entry id)."""
    kind, rest = trigger.split(":", 1)
    return kind, rest.rsplit("@", 1)[0]


def evidence_by_claim(result: QueryResult) -> dict[str, frozenset[str]]:
    """For each witness claim, the union of `ev_t` over the answers `t` whose witnesses contain it.

    An identifier is in this set for claim `c` iff it is in `ev_t` for some answer `t` with `c` in
    its witnesses, which is the repetition test of (D3).
    """
    out: dict[str, set[str]] = {}
    for answer in result.answers:
        for claim_id in {c for w in answer.witnesses for c in w.claims}:
            out.setdefault(claim_id, set()).update(answer.evidence)
    return {c: frozenset(ids) for c, ids in out.items()}


def violations(graph: ClaimStore, entries: set[tuple[str, str]], r0: int, r: int,
               evidence_r0: dict[str, frozenset[str]]) -> list[str]:
    """The trigger entries `(kind, id)` that violate (D1), (D2) or (D3) between r0 and r.

    `evidence_r0` is `evidence_by_claim` of the result at r0.
    """
    old, new = graph.state(r0), graph.state(r)

    def superseded(state, claim_id: str) -> bool:
        return bool(state.supersessions_of(claim_id))

    out = []
    for kind, entry in sorted(entries):
        if kind == "claim" and superseded(new, entry):
            out.append(f"D1 {entry}")
        elif kind == "attribution" and superseded(new, new.attributions[entry].claim_id):
            out.append(f"D1 {entry}")
        elif kind == "supersession" and superseded(old, new.supersessions[entry].claim_id):
            out.append(f"D2 {entry}")
        elif kind == "evidence":
            link = new.evidence_links[entry]
            if superseded(new, link.claim_id) \
                    or _unified(link) in evidence_r0.get(link.claim_id, frozenset()):
                out.append(f"D3 {entry}")
    return out


# ---------------------------------------------------------------------------------------------
# Constructed changes

H = "t020-exactness"
LIST = "SELECT ?v WHERE { (melanie, plays, ?v) [user, inform] }"
END_FILTER = ('SELECT ?v WHERE { (melanie, plays, ?v) [user, inform] AS ?c '
              'FILTER(end(?c) < "2024-01-01"^^date) }')


def claim(cid, obj, v):
    return Claim(cid, "melanie", "plays", Value(obj), None, ValidTime(None, None), v)


def att(aid, cid, v, polarity=Polarity.POSITIVE):
    return Attribution(aid, cid, "user", CommunicativeFunction.INFORM, ReportMode.OWN, polarity,
                       Certainty.CERTAIN, False, f"m{v}", v)


def ev(eid, cid, v, message=None):
    return EvidenceLink(eid, cid, message or f"m{v}", None, v)


def sup(sid, cid, v, licence, kind=SupersessionKind.CORRECTION, valid_end=None):
    return Supersession(sid, cid, kind, valid_end, None, licence, v)


def cs(v, claims=(), atts=(), evs=(), sups=()):
    return ChangeSet(H, v, tuple(claims), tuple(atts), tuple(evs), tuple(sups))


BASE = cs(1, [claim("c1", "violin", 1)], [att("a1", "c1", 1)], [ev("e1", "c1", 1)])


class Decision:
    """The decision D of supplement S4 for one query over a list of change sets."""

    def __init__(self, text: str, changesets: list[ChangeSet]):
        self.query = parse(text)
        self.deps = dependency_patterns(self.query)
        self.graph = ClaimStore(H)
        self.index = Index()
        self.marks: dict[int, list] = {}
        for c in changesets:
            self.graph.commit(c)
            self.index.add(c)
            self.marks[c.version] = triggers(self.deps, c, self.index, Options())

    def between(self, r0: int, r: int):
        found = [t for v, ts in self.marks.items() if r0 < v <= r for t in ts]
        before, after = run(self.query, self.graph, r0), run(self.query, self.graph, r)
        entries = {(t.kind, t.entry) for t in found}
        explained = violations(self.graph, entries, r0, r, evidence_by_claim(before))
        return found, before.fingerprints(), after.fingerprints(), explained


class ConstructedTest(unittest.TestCase):
    def assert_over_mark(self, d: Decision, r0: int, r: int, condition: str):
        found, fb, fa, explained = d.between(r0, r)
        self.assertTrue(found, "the decision must mark the view")
        self.assertEqual(fb, fa, "nothing may change: this is an over-mark")
        self.assertTrue(any(x.startswith(condition) for x in explained),
                        f"expected a {condition} violation, got {explained}")

    def test_d1_new_claim_superseded_within_the_change(self):
        d = Decision(LIST, [BASE,
                            cs(2, [claim("c2", "clarinet", 2)], [att("a2", "c2", 2)],
                               [ev("e2", "c2", 2)]),
                            cs(3, sups=[sup("s2", "c2", 3, "a2")])])
        self.assertEqual(query_conditions(d.query), [])
        self.assert_over_mark(d, 1, 3, "D1")

    def test_d1_acceptance_of_a_superseded_claim(self):
        d = Decision(LIST, [BASE, cs(2, sups=[sup("s1", "c1", 2, "a1")]),
                            cs(3, atts=[att("a3", "c1", 3)])])
        self.assert_over_mark(d, 2, 3, "D1")

    def test_d2_second_supersession(self):
        d = Decision(LIST, [BASE, cs(2, sups=[sup("s1", "c1", 2, "a1")]),
                            cs(3, sups=[sup("s3", "c1", 3, "a1")])])
        self.assert_over_mark(d, 2, 3, "D2")

    def test_d3_evidence_on_a_superseded_claim(self):
        d = Decision(LIST, [BASE, cs(2, sups=[sup("s1", "c1", 2, "a1")]),
                            cs(3, evs=[ev("e3", "c1", 3)])])
        self.assert_over_mark(d, 2, 3, "D3")

    def test_d3_repeated_span(self):
        d = Decision(LIST, [BASE, cs(2, evs=[ev("e2", "c1", 2, message="m1")])])
        self.assert_over_mark(d, 1, 2, "D3")

    def test_q4_end_filter_on_a_supersession(self):
        """The open-ended claim fails `end(?c) < 2024`; a change ending it in 2023 passes the
        filter after the change, so the matcher marks, but the current-state query drops the
        superseded claim anyway. No (D) condition is violated: (Q4) explains the over-mark."""
        d = Decision(END_FILTER, [BASE, cs(2, sups=[sup("s1", "c1", 2, "a1",
                                                        SupersessionKind.CHANGE,
                                                        "2023-06-01")])])
        self.assertEqual(query_conditions(d.query), ["Q4"])
        found, fb, fa, explained = d.between(1, 2)
        self.assertTrue(found)
        self.assertEqual(fb, fa)
        self.assertEqual(explained, [])

    def test_part_a_new_match(self):
        d = Decision(LIST, [BASE, cs(2, [claim("c2", "clarinet", 2)], [att("a2", "c2", 2)],
                                     [ev("e2", "c2", 2)])])
        found, fb, fa, explained = d.between(1, 2)
        self.assertEqual(explained, [])
        self.assertTrue(any(t.level == ANSWER for t in found))
        self.assertNotEqual(fb["answers"], fa["answers"])

    def test_part_a_second_acceptance_changes_only_witnesses(self):
        """Supplement Example 8: an answer-level mark for a citation-stale view."""
        d = Decision(LIST, [BASE, cs(2, atts=[att("a2", "c1", 2)])])
        found, fb, fa, explained = d.between(1, 2)
        self.assertEqual(explained, [])
        self.assertTrue(any(t.level == ANSWER for t in found))
        self.assertEqual(fb["answers"], fa["answers"])
        self.assertNotEqual(fb["witnesses"], fa["witnesses"])

    def test_part_b_fresh_evidence_is_citation_level_only(self):
        d = Decision(LIST, [BASE, cs(2, evs=[ev("e2", "c1", 2)])])
        found, fb, fa, explained = d.between(1, 2)
        self.assertEqual(explained, [])
        self.assertTrue(found)
        self.assertTrue(all(t.level == CITATION for t in found))
        self.assertEqual((fb["answers"], fb["witnesses"]), (fa["answers"], fa["witnesses"]))
        self.assertNotEqual(fb["evidence"], fa["evidence"])

    def test_part_b_span_cited_for_another_answer_is_fresh(self):
        """A new link on c2 cites m1, which only the violin answer cites. Per answer this violates
        no condition and changes the evidence of the clarinet answer (a flat evidence set over
        all answers would not change)."""
        d = Decision(LIST, [BASE, cs(2, [claim("c2", "clarinet", 2)], [att("a2", "c2", 2)],
                                     [ev("e2", "c2", 2)]),
                            cs(3, evs=[ev("e3", "c2", 3, message="m1")])])
        found, fb, fa, explained = d.between(2, 3)
        self.assertEqual(explained, [])
        self.assertTrue(found)
        self.assertTrue(all(t.level == CITATION for t in found))
        self.assertEqual((fb["answers"], fb["witnesses"]), (fa["answers"], fa["witnesses"]))
        self.assertNotEqual(fb["evidence"], fa["evidence"])
        before, after = run(d.query, d.graph, 2), run(d.query, d.graph, 3)
        self.assertEqual(before.evidence_set(), after.evidence_set())

    def test_conditions_reject_queries_outside_the_proposition(self):
        cases = {
            "Q1": "SELECT ?v WHERE { (melanie, plays, ?v) [user, inform] AS ?c } "
                  "LATEST BY version OF ?c",
            "Q2": "SELECT ?v WHERE { (melanie, plays, ?v) } AT(state=historical)",
            "Q3": "SELECT ?v WHERE { (?v, plays, ?v) }",
        }
        for condition, text in cases.items():
            with self.subTest(condition=condition):
                self.assertIn(condition, query_conditions(parse(text)))
        self.assertIn("Q3", query_conditions(parse("SELECT ?v WHERE { (melanie, plays, ?v, ?s) }")))
        self.assertEqual(query_conditions(parse(
            "SELECT COUNT(DISTINCT ?v) WHERE { (melanie, plays, ?v) [user, inform] }")), [])


# ---------------------------------------------------------------------------------------------
# Replay on the T019 fixtures


def check_replay(test: unittest.TestCase, seq: Sequence, label: str, counts) -> None:
    run_ = replay(seq, "claim_pattern_filters", read_every=1)
    store, graph = run_.store, run_.graph
    marks: dict[str, list[tuple[int, str, set[str]]]] = {}
    for w in run_.strategy.log.writes():
        for m in w.marks:
            marks.setdefault(m.view_id, []).append((w.version, m.level, set(m.triggers)))
    for read in run_.strategy.log.reads():
        r = read.version
        for c in read.checks:
            view = store.get(c.view_id)
            if query_conditions(view.query):
                continue
            counts["families"].add(view.binding.family if view.binding else "?")
            r0 = c.cutoff
            raised = [(lvl, t) for v, lvl, t in marks.get(c.view_id, ()) if r0 < v <= r]
            if not raised:
                continue
            counts["marked"] += 1
            before, _ = store.evaluate(c.view_id, graph, r0)
            after, _ = store.evaluate(c.view_id, graph, r)
            fb, fa = before.result.fingerprints(), after.result.fingerprints()
            entries = {_parse(n) for _, t in raised for n in t}
            explained = violations(graph, entries, r0, r,
                                   evidence_by_claim(before.result))
            counts["violating"] += bool(explained)
            counts["over"] += fb == fa
            with test.subTest(sequence=label, view=c.view_id, r0=r0, r=r):
                if fb == fa:
                    test.assertTrue(explained, f"over-mark without a violated condition; "
                                               f"triggers {sorted(entries)}")
                if not explained and any(lvl == ANSWER for lvl, _ in raised):
                    test.assertTrue(fb["answers"] != fa["answers"]
                                    or fb["witnesses"] != fa["witnesses"],
                                    "answer-level mark without a change of answers or "
                                    "witnesses")


class ReplayTest(unittest.TestCase):
    def test_fixtures(self):
        counts = {"marked": 0, "violating": 0, "over": 0, "families": set()}
        check_replay(self, worked(), "worked", counts)
        split = load_split()
        for family, seed in ((split.development[0], 11), (split.development[2], 12),
                             (split.development[4], 13)):
            seq, bundle = generated(family, seed)
            check_replay(self, seq, f"{family}-{seed}", counts)
            check_replay(self, projected(seq, bundle), f"{family}-{seed}-own-positive", counts)
        # The conditions select the list, constraints and count families and nothing else.
        self.assertEqual(counts["families"], {"list", "constraints", "count"})
        self.assertGreater(counts["marked"], 0)
        # Recorded in docs/research/formalisation.md: no over-mark occurs on these fixtures.
        self.assertEqual(counts["over"], 0)


if __name__ == "__main__":
    unittest.main()
