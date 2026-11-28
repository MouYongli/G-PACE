"""E006 on controlled sequences (`eval/analysis/metrics/graph_sequences.py`): occurrences, the
task-entity subject rule, endings and ending-stance false drops on a synthetic gold graph."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grace.eval.analysis.metrics import graph_sequences as gs
from grace.eval.analysis.metrics.graph import PredicateMatcher, WriterGraph


def att(aid, cid, mid, function="inform", polarity="positive"):
    return {"attribution_id": aid, "claim_id": cid, "message_id": mid, "function": function,
            "polarity": polarity, "speaker": "user"}


def claim(cid, subject, predicate, value, entity=False):
    obj = {"entity": value} if entity else {"datatype": "string", "value": value}
    return {"claim_id": cid, "subject": subject, "predicate": predicate, "object": obj}


GOLD = [
    {"claims": [claim("c1", "user", "livesIn", "Paris")], "attributions": [att("a1", "c1", "m1")],
     "supersessions": []},
    {"claims": [claim("c2", "k1", "arriveBy", "12:00")],
     "attributions": [att("a2", "c2", "m2", "request")], "supersessions": []},
    {"claims": [claim("c3", "user", "livesIn", "Berlin")], "attributions": [att("a3", "c3", "m3")],
     "supersessions": [{"attribution_id": "a3", "claim_id": "c1", "kind": "change"}]},
]


class SequenceScoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "seq"
        (self.dir / "graph").mkdir(parents=True)
        with (self.dir / "graph" / "changesets.jsonl").open("w") as f:
            for v, entries in enumerate(GOLD, start=1):
                f.write(json.dumps({"version": v, "entries": entries}) + "\n")

    def writer(self, ended: bool) -> WriterGraph:
        g = WriterGraph("seq")
        g.claims = {"w1": claim("w1", "e_user", "residesIn", "Paris"),
                    "w2": claim("w2", "e_trip", "arriveBy", "12:00"),
                    "w3": claim("w3", "e_user", "livesIn", "Berlin"),
                    "w4": claim("w4", "e_user", "likes", "tea")}
        g.labels = {"e_user": "user", "e_trip": "the train trip"}
        g.attributions = [att("x1", "w1", "m1"), att("x2", "w2", "m2", "inform"),
                          att("x3", "w3", "m3"), att("x4", "w4", "m3")]
        g.supersessions = [{"attribution_id": "x3", "claim_id": "w1"}] if ended else []
        return g

    def test_occurrences_endings_and_drops(self):
        matcher = PredicateMatcher("lexical")
        updates = [{"history_id": "seq", "message_ids": ["m3"],
                    "dropped": [{"item": "stance", "reason": "ended_without_evidence",
                                 "detail": "w1"}]}]
        counts, rows = gs.score_sequence("seq", self.dir, self.writer(False), updates, matcher)
        self.assertEqual((counts["gold"], counts["writer"]), (3, 4))
        self.assertEqual(counts["anchor"], 3)        # the task subject k1 matches any subject
        self.assertEqual(counts["loose"], 2)         # residesIn vs livesIn is not lexical
        self.assertEqual(counts["function:equal"], 1)  # request vs inform on m2
        self.assertEqual((counts["gold_endings"], counts["endings_matched"]), (1, 0))
        self.assertEqual((counts["drops"], counts["false_drops"]), (1, 1))
        self.assertEqual(counts["gold_endings_lost_to_drops"], 1)
        summary = gs.summarise({"seq": counts}, rows)
        self.assertAlmostEqual(summary["all"]["loose"]["precision"], 0.5)
        self.assertEqual(summary["all"]["ending_drops"]["false_drop_rate"], 1.0)
        counts, _ = gs.score_sequence("seq", self.dir, self.writer(True), [], matcher)
        self.assertEqual((counts["endings_matched"], counts["writer_endings"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
