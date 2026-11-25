"""Generator invalidation truth against the T017 compiler (T015 acceptance item 3).

`grace.cli.data.changeseq_crosscheck` compiles the six view templates to the T017 IR and executes
them on the gold graph at every version. These tests run it on the hand-written worked example of
design section 6.5, on a generated development sequence, and on two small extensions of the worked
example that pin down the two known compiler-side gaps (`expectedFailure`: when T017 closes a gap
the test reports an unexpected success and must be updated). Negative controls show that a broken
IR template is caught.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from grace.cli.data.changeseq_crosscheck import (
    check_sequence,
    explain,
    own_positive,
    reserialised,
    view_query,
)
from grace.context.pipeline.query.ir import CommunicativeFunction, Query
from grace.eval.datasets.changeseq import gold
from grace.eval.datasets.changeseq.build import generate_sequence
from grace.eval.datasets.changeseq.events import NewClaim, Stance
from grace.eval.datasets.changeseq.invalidation import gold_staleness
from grace.eval.datasets.changeseq.template_families import CellConfig, load_split
from tests.unit.test_changeseq_worked_example import BINDINGS, WORLD, worked_example

MODES = ("rdf11", "rdf12")


def checks(log, world, bindings, mode="rdf11", template=view_query):
    """(full, own-positive) `SequenceCheck`s of an event log."""
    truth = gold_staleness(log, world, bindings)
    labels = {(x["binding_id"], x["version"]): (x["answer_stale"], x["citation_stale"])
              for x in truth.labels}
    store = reserialised(gold.build_store(log, "crosscheck-test", validate=None), mode)
    return tuple(check_sequence(s, bindings, world, truth.values, labels, sequence_id="test",
                                graph=g, template=template)
                 for g, s in (("full", store), ("own-positive", own_positive(store))))


def extended(*records):
    """The worked example with further messages appended at t = 9, 10, ..."""
    log = worked_example()
    for i, (speaker, events) in enumerate(records, start=9):
        log.append(replace(log[-1], version=i, message_id=f"m{i}", speaker=speaker,
                           timestamp="2026-11-04", events=tuple(events)))
    return log


class WorkedExampleTest(unittest.TestCase):
    def test_compiler_reproduces_the_reference_at_every_version(self):
        for mode in MODES:
            for c in checks(worked_example(), WORLD, BINDINGS, mode):
                with self.subTest(mode=mode, graph=c.graph):
                    self.assertEqual(c.mismatches, [])
                    self.assertEqual(c.v3_raw_witness_mismatch, 0)   # one member at most
                    self.assertEqual(sum(c.by_template.values()), 6 * 9)


class GeneratedSequenceTest(unittest.TestCase):
    """One development-family sequence with a high revision density."""

    @classmethod
    def setUpClass(cls):
        family = load_split().development[0]
        cell = CellConfig(family=family, length=80, density=30.0, mention_rate=20.0)
        cls.bundle = generate_sequence(family, cell, 7, "crosscheck-dev", validate=None)
        cls.full, cls.projected = checks(cls.bundle.plan.log, cls.bundle.plan.world,
                                         cls.bundle.plan.bindings())

    def test_staleness_labels_agree_on_the_own_positive_graph(self):
        self.assertEqual(dict(self.projected.label_mismatch), {})

    def test_only_the_latest_witness_gap_remains_on_the_own_positive_graph(self):
        self.assertLessEqual(set(self.projected.component), {"V2/wit"})

    def test_full_graph_mismatches_are_v1_to_v3_or_explained(self):
        self.assertLessEqual(set(self.full.value_mismatch), {"V1", "V2", "V3"})
        explained, unexplained = explain(self.full, self.projected)
        self.assertEqual(unexplained, self.projected.component.get("V2/wit", 0))
        self.assertEqual(explained + unexplained, sum(self.full.value_mismatch.values()))


class KnownGapTest(unittest.TestCase):
    def test_non_own_attributions_are_dropped_by_the_projection(self):
        # t=9: the user quotes someone else ("my friend says I play the cello").
        log = extended(("user", [NewClaim("c9", "user", "playsInstrument", "cello", "string"),
                                 Stance("a11", "c9", "inform", report_mode="quote")]))
        full, projected = checks(log, WORLD, BINDINGS)
        self.assertEqual(projected.mismatches, [])
        self.assertEqual(set(full.value_mismatch), {"V1", "V3"})
        self.assertEqual(explain(full, projected), (2, 0))

    @unittest.expectedFailure
    def test_gap_attribution_constraint_ignores_report_mode(self):
        """[u, f] matches speaker and function only (query-ir.md 6, 7.2); the design's V1-V3
        require report mode own, positive polarity and not derived (change-sequences.md 6.2)."""
        log = extended(("user", [NewClaim("c9", "user", "playsInstrument", "cello", "string"),
                                 Stance("a11", "c9", "inform", report_mode="quote")]))
        self.assertEqual(checks(log, WORLD, BINDINGS)[0].mismatches, [])

    @unittest.expectedFailure
    def test_gap_latest_keeps_only_the_latest_confirmation(self):
        """LATEST keys each row on max(claim, attribution) version, so a restatement of the
        selected claim drops its earlier witness; plan 3.4 and design 6.2 (V2) keep every
        witness of the selected claim."""
        log = extended(("user", [Stance("a11", "c8", "inform")]))   # "Yes, Cologne."
        full, projected = checks(log, WORLD, BINDINGS)
        self.assertEqual(projected.mismatches, [])


class NegativeControlTest(unittest.TestCase):
    def broken(self, template, change):
        def make(b, world):
            q = view_query(b, world)
            return change(q) if b.template == template else q
        return make

    def test_dropped_negation_is_caught(self):
        template = self.broken("V5", lambda q: replace(q, negation=None))
        full, _ = checks(worked_example(), WORLD, BINDINGS, template=template)
        self.assertEqual(set(full.value_mismatch), {"V5"})
        self.assertIn("V5", full.label_mismatch)

    def test_wrong_attribution_function_is_caught(self):
        def offer(q: Query) -> Query:
            p = q.where[0]
            att = replace(p.attribution, function=CommunicativeFunction.OFFER)
            return replace(q, where=(replace(p, attribution=att),))
        full, _ = checks(worked_example(), WORLD, BINDINGS, template=self.broken("V4", offer))
        self.assertEqual(set(full.value_mismatch), {"V4"})


if __name__ == "__main__":
    unittest.main()
