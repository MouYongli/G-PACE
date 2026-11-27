"""Graph-quality annotation (task T024): sampling helpers, label checks, agreement and merge.

Synthetic segments and labels only; no benchmark data.
"""

from __future__ import annotations

import unittest

from grace.eval.analysis.annotation import graph_quality as gq
from grace.eval.datasets.benchmarks import graph_quality_sample as sample

SEG = "locomo:h1:s1:1-3"
SEGMENTS = {
    SEG: gq.SegmentText(SEG, "locomo", {
        "m1": {"message_id": "m1", "role": "peer", "text": "I moved to Porto last month."},
        "m2": {"message_id": "m2", "role": "peer", "text": "My sister Ana plays the cello."},
        "m3": {"message_id": "m3", "role": "peer", "text": "Wow, that's cool!"},
    }),
    "longmemeval-s:h2:s9:1-1": gq.SegmentText("longmemeval-s:h2:s9:1-1", "longmemeval-s", {
        "x1": {"message_id": "x1", "role": "user", "text": "Hi there."},
    }),
}


def claim(cid, mid, subject, predicate, obj, quote, annotator="A", **extra):
    record = {"segment": SEG, "annotator": annotator, "kind": "claim", "id": cid,
              "message_id": mid, "subject": subject, "predicate": predicate, "object": obj,
              "object_type": "entity", "speaker": "Ben", "function": "inform",
              "report_mode": "own", "polarity": "positive", "certainty": "certain",
              "derived": False, "correction": False, "time_expression": None,
              "valid_from": None, "valid_until": None, "quote": quote}
    record.update(extra)
    return record


def done(segment, annotator="A"):
    return {"segment": segment, "annotator": annotator, "kind": "segment_done", "minutes": None}


def labels_a():
    return [
        claim("c1", "m1", "Ben", "livesIn", "Porto", "I moved to Porto",
              time_expression="last month"),
        claim("c2", "m2", "Ben", "hasSibling", "Ana", "My sister Ana"),
        claim("c3", "m2", "Ana", "playsInstrument", "the cello", "plays the cello"),
        {"segment": SEG, "annotator": "A", "kind": "stance", "message_id": "m3", "claim": "c1",
         "speaker": "Cy", "function": "confirm", "polarity": "positive", "derived": False,
         "ends": None, "valid_until": None, "quote": "cool"},
        done(SEG), done("longmemeval-s:h2:s9:1-1"),
    ]


def labels_b():
    return [
        claim("c1", "m1", "Ben", "movedTo", "Porto", "moved to Porto", annotator="B",
              time_expression="last month"),
        claim("c2", "m2", "Ana", "playsInstrument", "cello", "plays the cello", annotator="B"),
        claim("c3", "m2", "Ana", "hasSibling", "Ben", "My sister Ana", annotator="B"),
        done(SEG, "B"), done("longmemeval-s:h2:s9:1-1", "B"),
    ]


class SamplingHelpersTest(unittest.TestCase):
    def test_allocate_is_largest_remainder(self):
        sizes = {"KU": 15, "TR": 26, "MS": 26, "SSU": 14, "SSA": 11, "SSP": 6}
        quota = sample.allocate(sizes, 24)
        self.assertEqual(sum(quota.values()), 24)
        self.assertEqual(quota, {"KU": 4, "TR": 6, "MS": 6, "SSU": 3, "SSA": 3, "SSP": 2})

    def test_allocate_rejects_too_many_slots(self):
        with self.assertRaises(sample.SampleError):
            sample.allocate({"a": 2}, 3)

    def test_window_whole_short_session_and_seeded_long_one(self):
        self.assertEqual(sample.window(24, "p", "k"), (0, 24))
        start, end = sample.window(39, "p", "k")
        self.assertEqual(end - start, sample.WINDOW)
        self.assertEqual(sample.window(39, "p", "k"), (start, end))

    def test_window_holds_the_required_message(self):
        for hold in (0, 17, 38):
            start, end = sample.window(39, "p", "k", must_hold=hold)
            self.assertTrue(start <= hold < end)


class CheckTest(unittest.TestCase):
    def test_valid_files_pass(self):
        self.assertEqual(gq.check(labels_a(), SEGMENTS), [])
        self.assertEqual(gq.check(labels_b(), SEGMENTS), [])

    def test_problems_are_reported(self):
        bad = labels_a()
        bad[0] = dict(bad[0], quote="moved to Lisbon")             # not verbatim
        bad[1] = dict(bad[1], predicate="Has sibling")              # not lowerCamelCase
        bad[2] = dict(bad[2], function="tell", valid_from="May")    # closed list, date
        bad[3] = dict(bad[3], claim="c9")                           # unknown claim
        bad = bad[:-1]                                              # missing segment_done
        problems = "\n".join(gq.check(bad, SEGMENTS))
        for expected in ("quote does not occur", "lowerCamelCase", "function 'tell'",
                         "valid_from 'May'", "unknown claim 'c9'", "no segment_done"):
            self.assertIn(expected, problems)

    def test_message_outside_segment_is_rejected(self):
        bad = labels_a()
        bad[0] = dict(bad[0], message_id="x1")
        self.assertIn("is not in", "\n".join(gq.check(bad, SEGMENTS)))


class AgreementTest(unittest.TestCase):
    def test_normalisation(self):
        self.assertTrue(gq.same_name("the cello", "Cello"))
        self.assertTrue(gq.same_name("Ana's dog", "Ana dog"))
        self.assertTrue(gq.same_name("LGBTQ support group", "support group"))
        self.assertFalse(gq.same_name("Porto", "Lisbon"))
        self.assertEqual(gq.norm_predicate("playsInstrument"), "plays instrument")

    def test_anchor_and_strict_matches(self):
        report = gq.agreement(labels_a(), labels_b(), SEGMENTS)
        overall = report["all"]
        # c1/c1: anchor only (livesIn vs movedTo); c3/c2: strict; hasSibling pairs differ in
        # subject and object (Ben-Ana vs Ana-Ben), so they do not match.
        self.assertEqual(overall["claims_a"], 3)
        self.assertEqual(overall["claims_b"], 3)
        self.assertEqual(overall["matched_anchor"], 2)
        self.assertEqual(overall["matched_strict"], 1)
        self.assertAlmostEqual(overall["dice_anchor"], round(4 / 6, 4))
        self.assertEqual(overall["field_agreement_on_anchor_pairs"]["predicate"], 0.5)
        self.assertEqual(overall["field_agreement_on_anchor_pairs"]["time_expression"], 1.0)
        self.assertEqual(overall["segments_empty_both"], 1)
        self.assertEqual(report["longmemeval-s"]["claims_a"], 0)

    def test_matching_is_one_to_one(self):
        a = [claim("c1", "m2", "Ana", "playsInstrument", "cello", "cello")]
        b = [claim("c1", "m2", "Ana", "playsInstrument", "cello", "cello"),
             claim("c2", "m2", "Ana", "plays", "cello", "cello")]
        self.assertEqual(gq.match(a, b), [(0, 0, True)])

    def test_merge_lists_pairs_and_singles(self):
        merged = gq.merge(labels_a(), labels_b(), SEGMENTS, "A", "B")
        kinds = sorted(r["agreement"] for r in merged)
        self.assertEqual(kinds, ["A_only", "B_only", "both", "both"])
        pair = next(r for r in merged if r["agreement"] == "both" and not r["strict"])
        self.assertEqual(pair["differs"], ["predicate"])
        self.assertEqual([r["message_id"] for r in merged][0], "m1")


if __name__ == "__main__":
    unittest.main()
