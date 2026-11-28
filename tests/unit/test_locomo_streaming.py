"""LoCoMo streaming (T031): the schedule built from the committed read-point list, read selection,
and the consistency of v(q) and N answers against the same gold."""

from __future__ import annotations

import unittest

from grace.eval.analysis.metrics import streaming as metric
from grace.eval.analysis.metrics.align import Aligned
from grace.eval.datasets.benchmarks import locomo_read_points as rp
from tests.unit.test_locomo_read_points import QUESTIONS, SESSIONS, build


def committed(**changes) -> dict:
    """The read-point list that matches the synthetic history `h` (N = 6)."""
    config = {"benchmark": "locomo", "version": "v1",
              "histories": {"h": {"split": "fixture", "n_messages": 6,
                                  "v": {"h:q0": 5, "h:q1": 2, "h:q2": 6, "h:q5": 2,
                                        "h:q6": 2}}},
              "excluded": {"h:q3": "evidence_missing", "h:q4": "evidence_unresolved",
                           "other:q1": "evidence_missing"},
              "reported_separately": {"h:q5": "audit_wrong_citation"}}
    config.update(changes)
    return config


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.records = build(SESSIONS, QUESTIONS)

    def test_each_question_is_read_at_v_and_n_and_excluded_ones_never(self):
        rows = rp.streaming_schedule(self.records, committed(), "v1")
        reads = {(r["task_id"], r["version"]) for r in rows}
        self.assertEqual(reads, {("h:q0", 5), ("h:q0", 6), ("h:q1", 2), ("h:q1", 6),
                                 ("h:q2", 6), ("h:q5", 2), ("h:q5", 6), ("h:q6", 2),
                                 ("h:q6", 6)})
        self.assertEqual(len({r["read_id"] for r in rows}), len(rows))
        for row in rows:
            self.assertEqual(row["read_id"], f"{row['task_id']}@{row['version']}")
            self.assertNotIn("metadata", row)  # nothing about evidence or audit is visible

    def test_a_list_that_disagrees_with_the_data_is_refused(self):
        bad_v = committed()
        bad_v["histories"]["h"]["v"]["h:q0"] = 2
        bad_x = committed(excluded={"h:q3": "evidence_missing"})
        bad_n = committed()
        bad_n["histories"]["h"]["n_messages"] = 7
        for config in (bad_v, bad_x, bad_n, committed(histories={})):
            with self.subTest(config=config), self.assertRaises(rp.ReadPointError):
                rp.streaming_schedule(self.records, config, "v1")
        with self.assertRaises(rp.ReadPointError):
            rp.streaming_schedule(self.records, committed(), "v2")


def aligned(task_id: str, version: int, output: str, prediction) -> Aligned:
    task = {"read_id": f"{task_id}@{version}", "task_id": task_id, "history_id": "h",
            "version": version}
    return Aligned(task, {"output": output, "prediction": prediction})


class ConsistencyTest(unittest.TestCase):
    def test_pairs_are_scored_against_the_same_gold(self):
        gold = {t: {"reference": ref, "labels": {"category": 4}}
                for t, ref in (("h:a", "Paris"), ("h:b", "red"), ("h:c", "tea"),
                               ("h:d", "cat"))}
        items = [aligned("h:a", 2, "answer", "Paris"), aligned("h:a", 6, "answer", "paris."),
                 aligned("h:b", 2, "answer", "red"), aligned("h:b", 6, "answer", "blue"),
                 aligned("h:c", 3, "unknown", None), aligned("h:c", 6, "answer", "tea"),
                 aligned("h:d", 6, "answer", "cat")]
        rows = metric.pair_rows({a.read_id: a for a in items}, gold, {"h": 6}, {"h:b"})
        by = {r["task_id"]: r for r in rows}
        self.assertFalse(by["h:a"]["answer_changed"])          # same after normalisation
        self.assertEqual((by["h:a"]["f1_v"], by["h:a"]["f1_n"]), (1.0, 1.0))
        self.assertTrue(by["h:b"]["answer_changed"])
        self.assertEqual(by["h:b"]["delta"], -1.0)
        self.assertEqual(by["h:b"]["group"], metric.SEPARATE)
        self.assertEqual(by["h:c"]["delta"], 1.0)
        self.assertFalse(by["h:d"]["paired"])                  # v(q) = N: one read
        summary = metric.summarize(rows)
        self.assertEqual(summary["all"]["paired"], 3)
        self.assertEqual(summary["all"]["final_only"], 1)
        self.assertEqual(summary["all"]["answer_changed"], 2)
        self.assertEqual(summary["all"]["worse_at_n"], 1)
        self.assertEqual(summary["all"]["better_at_n"], 1)
        self.assertEqual(summary[metric.STREAMING]["paired"], 2)
        self.assertEqual(summary[metric.SEPARATE]["mean_f1_v"], 1.0)

    def test_a_task_without_its_read_at_n_is_refused(self):
        gold = {"h:a": {"reference": "x", "labels": {"category": 4}}}
        item = aligned("h:a", 2, "answer", "x")
        with self.assertRaises(ValueError):
            metric.pair_rows({item.read_id: item}, gold, {"h": 6})


if __name__ == "__main__":
    unittest.main()
