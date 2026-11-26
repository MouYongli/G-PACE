"""Empirical check of the exactness proposition of the formalisation (T020; supplement S4).

`paper/latex/supplement/exactness.tex` proves that the claim-pattern decision with local filters
marks a view only if its answers, witnesses or evidence change, for queries that satisfy
(Q1)-(Q4) and changes that satisfy (D1)-(D3). Soundness (no misses) is T019's acceptance
(`test_staleness.py`); this test checks the converse on the same fixtures: every over-mark of a
view whose query satisfies (Q1)-(Q4) must come with a trigger that violates (D1), (D2) or (D3),
and an answer-level mark without such a violation must change the answers or the witnesses
(part (a)). The template families `list` and `constraints` satisfy (Q1)-(Q4); `count` is covered
by Remark S4 (distinct count). The other families (negation, selection, end filter) lie outside
the conditions and are not checked here.

The evaluation at the view's old cut-off is recomputed after the fact, which time-travel
stability allows (supplement S2).
"""

from __future__ import annotations

import unittest

from grace.context.memory.graph.store import ClaimStore
from grace.context.views.staleness.matching import ANSWER
from grace.eval.datasets.changeseq.template_families import load_split
from tests.integration.staleness_replay import Sequence, replay
from tests.integration.test_staleness import generated, projected, worked

EXACT_FAMILIES = ("list", "constraints", "count")


def _unified(link) -> str:
    if link.span is None:
        return link.message_id
    return f"{link.message_id}#char={link.span.start},{link.span.end}"


def _parse(trigger: str) -> tuple[str, str]:
    """`<kind>:<entry id>@<pattern>/<role>` -> (kind, entry id)."""
    kind, rest = trigger.split(":", 1)
    return kind, rest.rsplit("@", 1)[0]


def _violations(graph: ClaimStore, triggers: set[str], r0: int, r: int,
                evidence_r0: frozenset[str]) -> list[str]:
    """The triggers that violate (D1), (D2) or (D3) for the change between r0 and r."""
    old, new = graph.state(r0), graph.state(r)

    def superseded(state, claim_id: str) -> bool:
        return bool(state.supersessions_of(claim_id))

    out = []
    for name in sorted(triggers):
        kind, entry = _parse(name)
        if kind == "claim" and superseded(new, entry):
            out.append(f"D1 {name}")
        elif kind == "attribution" and superseded(new, new.attributions[entry].claim_id):
            out.append(f"D1 {name}")
        elif kind == "supersession" and superseded(old, new.supersessions[entry].claim_id):
            out.append(f"D2 {name}")
        elif kind == "evidence":
            link = new.evidence_links[entry]
            if superseded(new, link.claim_id) or _unified(link) in evidence_r0:
                out.append(f"D3 {name}")
    return out


def check_exactness(test: unittest.TestCase, seq: Sequence, label: str) -> int:
    """Replay the claim-pattern-with-filters arm at every version; return the marks checked."""
    run = replay(seq, "claim_pattern_filters", read_every=1)
    store, graph = run.store, run.graph
    marks: dict[str, list[tuple[int, str, set[str]]]] = {}
    for w in run.strategy.log.writes():
        for m in w.marks:
            marks.setdefault(m.view_id, []).append((w.version, m.level, set(m.triggers)))
    checked = 0
    for read in run.strategy.log.reads():
        r = read.version
        for c in read.checks:
            view = store.get(c.view_id)
            if view.binding is None or view.binding.family not in EXACT_FAMILIES:
                continue
            r0 = c.cutoff
            raised = [(lvl, t) for v, lvl, t in marks.get(c.view_id, ()) if r0 < v <= r]
            if not raised:
                continue
            checked += 1
            before, _ = store.evaluate(c.view_id, graph, r0)
            after, _ = store.evaluate(c.view_id, graph, r)
            fb, fa = before.result.fingerprints(), after.result.fingerprints()
            triggers = set().union(*(t for _, t in raised))
            violations = _violations(graph, triggers, r0, r, before.result.evidence_set())
            with test.subTest(sequence=label, view=c.view_id, r0=r0, r=r):
                if fb == fa:  # over-mark: (D1)-(D3) must be violated
                    test.assertTrue(violations, f"over-mark without a violated condition; "
                                                f"triggers {sorted(triggers)}")
                if not violations and any(lvl == ANSWER for lvl, _ in raised):
                    test.assertTrue(fb["answers"] != fa["answers"]
                                    or fb["witnesses"] != fa["witnesses"],
                                    "answer-level mark without a change of answers or "
                                    "witnesses")
    return checked


class ExactnessTest(unittest.TestCase):
    def test_worked_example(self):
        self.assertGreater(check_exactness(self, worked(), "worked"), 0)

    def test_generated_sequences(self):
        split = load_split()
        checked = 0
        for family, seed in ((split.development[0], 11), (split.development[2], 12),
                             (split.development[4], 13)):
            seq, bundle = generated(family, seed)
            checked += check_exactness(self, seq, f"{family}-{seed}")
            checked += check_exactness(self, projected(seq, bundle),
                                       f"{family}-{seed}-own-positive")
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
