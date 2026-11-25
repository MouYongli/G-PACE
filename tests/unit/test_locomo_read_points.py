"""LoCoMo evidence-anchored read points (task T007) on synthetic records, and the shape of the
committed read-point config. No benchmark data is read."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from grace.cli.data.locomo_read_points import READ_POINTS_CONFIG, streaming_tasks
from grace.eval.datasets.benchmarks import locomo_read_points as rp
from grace.eval.datasets.benchmarks.base import HistoryBuilder, Records
from grace.eval.datasets.benchmarks.records import Gold, ReadTask


def build(sessions: dict[str, list[tuple[str, str]]], questions: list[tuple]) -> Records:
    """One history `h`; sessions map segment ID -> [(dia_id, text)]; questions are
    (index, category, evidence_ids, evidence_unresolved, status)."""
    records = Records("locomo", "fixture")
    builder = HistoryBuilder("locomo", "fixture", "h")
    for segment, turns in sessions.items():
        builder.segment(segment)
        for dia, text in turns:
            builder.message(dia, "A", "peer", text)
    history = records.add(builder)
    for index, category, evidence, unresolved, status in questions:
        task_id = f"h:q{index}"
        records.read_tasks.append(ReadTask.from_record({
            "benchmark": "locomo", "split": "fixture", "history_id": "h",
            "read_id": f"{task_id}@{history.n_messages}", "task_id": task_id,
            "version": history.n_messages, "kind": "question", "question": f"Q{index}?",
            "state_schema": None, "asked_at": None, "asked_at_raw": None}))
        records.gold.append(Gold(
            benchmark="locomo", split="fixture", history_id="h", task_id=task_id,
            annotation="v1", reference="x", evidence_ids=tuple(evidence),
            evidence_segment_ids=None, evidence_unresolved=tuple(unresolved),
            labels={"category": category}, metadata={"evidence_status": status}))
    return records


SESSIONS = {
    "session_1": [("D1:1", "one two"), ("D1:2", "three")],                   # versions 1-2
    "session_2": [("D2:1", "four five six"), ("D2:2", "seven"), ("D2:3", "eight")],  # 3-5
    "session_3": [("D3:1", "nine ten")],                                      # 6
}
QUESTIONS = [
    (0, 1, ["D2:1", "D1:1"], [], "complete"),     # latest evidence D2:1 -> v = 5
    (1, 4, ["D1:2"], [], "complete"),             # v = 2
    (2, 2, ["D3:1"], [], "complete"),             # v = N = 6
    (3, 3, [], [], "missing"),
    (4, 1, ["D1:1"], ["D9:9"], "unresolved"),
    (5, 4, ["D1:1"], [], "complete"),             # audit WRONG_CITATION, corrected D2:2 -> 5
    (6, 4, ["D1:2"], [], "complete"),             # audit answer error only -> streaming
]
AUDIT = {
    "h:q5": rp.AuditEntry("h:q5", "WRONG_CITATION", ("D1:1",), ("D2:2",)),
    "h:q6": rp.AuditEntry("h:q6", "HALLUCINATION", ("D1:2",), ("D1:2",)),
    "h:q4": rp.AuditEntry("h:q4", "WRONG_CITATION", ("D1:1",), ("D1:2",)),
}


class ReadPointTest(unittest.TestCase):
    def setUp(self):
        self.records = build(SESSIONS, QUESTIONS)
        self.points = {p.task_id: p for p in rp.compute_read_points(self.records, AUDIT)}

    def test_v_is_the_end_of_the_session_of_the_latest_evidence_turn(self):
        self.assertEqual(self.points["h:q0"].v, 5)
        self.assertEqual(self.points["h:q0"].latest_evidence, "D2:1")
        self.assertEqual(self.points["h:q0"].session, "session_2")
        self.assertEqual(self.points["h:q0"].session_index, 2)
        self.assertEqual(self.points["h:q1"].v, 2)
        self.assertTrue(self.points["h:q1"].before_final)
        self.assertEqual(self.points["h:q2"].v, 6)
        self.assertFalse(self.points["h:q2"].before_final)
        self.assertAlmostEqual(self.points["h:q1"].relative, 2 / 6)

    def test_missing_and_unresolved_evidence_get_no_read_point(self):
        for task, reason in (("h:q3", "evidence_missing"), ("h:q4", "evidence_unresolved")):
            point = self.points[task]
            self.assertEqual(point.status, rp.EXCLUDED)
            self.assertEqual(point.reason, reason)
            self.assertIsNone(point.v)
        # exclusion wins over the audit's evidence-error list
        self.assertEqual(self.points["h:q4"].audit_error, "WRONG_CITATION")

    def test_audit_evidence_errors_are_separate_and_answer_errors_are_labels(self):
        q5 = self.points["h:q5"]
        self.assertEqual((q5.status, q5.reason, q5.v, q5.v_audit),
                         (rp.SEPARATE, "audit_wrong_citation", 2, 5))
        q6 = self.points["h:q6"]
        self.assertEqual((q6.status, q6.audit_error), (rp.STREAMING, "HALLUCINATION"))

    def test_complete_evidence_that_does_not_resolve_is_an_error(self):
        records = build(SESSIONS, [(0, 1, ["D7:7"], [], "complete")])
        with self.assertRaises(rp.ReadPointError):
            rp.compute_read_points(records, {})

    def test_history_spacing_counts_messages_and_tokens_between_read_points(self):
        index = rp.index_histories(self.records)["h"]
        stats = rp.history_stats(index, list(self.points.values()), rp.whitespace_tokens)
        # streaming questions: q0 (5), q1 (2), q2 (6), q6 (2); N = 6 is always a read point
        self.assertEqual(stats.read_points, [2, 5, 6])
        self.assertEqual(stats.questions_per_read_point, {2: 2, 5: 1, 6: 1})
        self.assertEqual(stats.n_questions, 4)
        self.assertEqual(stats.n_before_final, 3)
        self.assertEqual((stats.prefix_messages, stats.prefix_tokens), (2, 3))
        self.assertEqual(stats.gaps_messages, [3, 1])
        self.assertEqual(stats.gaps_tokens, [5, 2])
        self.assertEqual(stats.gaps_sessions, [1, 1])
        self.assertEqual(stats.n_tokens, 10)
        self.assertEqual(stats.session_lengths, [2, 3, 1])
        self.assertAlmostEqual(stats.share_written_after_first_read, 4 / 6, places=5)

    def test_summary_and_exclusions(self):
        index = rp.index_histories(self.records)["h"]
        points = list(self.points.values())
        stats = [rp.history_stats(index, points, rp.whitespace_tokens)]
        summary = rp.summarize(points, stats)
        self.assertEqual(summary["status_counts"],
                         {rp.EXCLUDED: 2, rp.SEPARATE: 1, rp.STREAMING: 4})
        self.assertEqual(summary["streaming"]["share_before_final"], 0.75)
        self.assertEqual(summary["reported_separately"]["v_audit_later_than_v"], 1)
        self.assertEqual(summary["read_points"]["gap_messages"]["median"], 2.0)
        self.assertEqual(summary["answer_error_label"], {"questions": 1, "streaming": 1})
        excl = rp.exclusions(points)
        self.assertEqual(excl["excluded"]["by_reason"],
                         {"evidence_missing": 1, "evidence_unresolved": 1})
        self.assertEqual(excl["reported_separately"]["count"], 1)
        self.assertEqual(excl["audit_answer_error_label"]["task_ids"], ["h:q6"])

    def test_streaming_schedule_reads_each_question_at_v_and_n(self):
        rows = streaming_tasks(self.records, list(self.points.values()))
        ids = [r["read_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("h:q0@5", ids)
        self.assertIn("h:q0@6", ids)
        self.assertIn("h:q2@6", ids)
        self.assertNotIn("h:q2@5", ids)
        self.assertFalse([i for i in ids if i.startswith(("h:q3@", "h:q4@"))])
        for row in rows:
            ReadTask.from_record(row)


class StatisticsTest(unittest.TestCase):
    def test_quantiles_interpolate(self):
        q = rp.quantiles([1, 2, 3, 4])
        self.assertEqual((q["min"], q["median"], q["max"]), (1, 2.5, 4))
        self.assertEqual(rp.quantiles([7])["p90"], 7)
        self.assertIsNone(rp.quantiles([]))

    def test_threshold_requires_every_criterion(self):
        summary = {"streaming": {"share_before_final": 0.6},
                   "read_points": {"distinct_per_history": {"median": 5.0},
                                   "gap_tokens": {"median": 300.0}}}
        threshold = rp.Threshold.from_config({"min_share_before_final": 0.5,
                                              "min_median_distinct_read_points": 5,
                                              "min_median_gap_tokens": 256})
        self.assertTrue(rp.evaluate_threshold(summary, threshold)["promote_to_main_text"])
        summary["read_points"]["gap_tokens"]["median"] = 200.0
        result = rp.evaluate_threshold(summary, threshold)
        self.assertFalse(result["promote_to_main_text"])
        self.assertEqual(result["checks"]["median_gap_tokens"], False)
        with self.assertRaises(rp.ReadPointError):
            rp.Threshold.from_config({"min_share_before_final": 0.5})


class AuditTest(unittest.TestCase):
    def write(self, directory: Path, index: int, rows: list[dict]) -> None:
        (directory / f"errors_conv_{index}.json").write_text(json.dumps(rows), encoding="utf-8")

    def test_question_ids_map_to_zero_based_qa_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.write(d, 0, [{"question_id": "locomo_0_qa3", "question": "Q3?",
                               "error_type": "WRONG_CITATION", "cited_evidence": ["D1:1"],
                               "correct_evidence": ["D1:2"]}])
            self.write(d, 1, [{"question_id": "locomo_1_qa0", "question": "R0?",
                               "error_type": "TEMPORAL_ERROR"}])
            audit = rp.load_audit(d, ["a", "b"], {"a:q3": "Q3?", "b:q0": "R0?"})
            self.assertEqual(sorted(audit), ["a:q3", "b:q0"])
            self.assertEqual(audit["a:q3"].correct_evidence, ("D1:2",))
            self.assertEqual(audit["b:q0"].correct_evidence, ())
            only = rp.load_audit(d, ["a", "b", "c"], include={"a"})  # c has no file: skipped
            self.assertEqual(sorted(only), ["a:q3"])
            with self.assertRaises(rp.ReadPointError):
                rp.load_audit(d, ["a", "b"], {"a:q3": "Other?", "b:q0": "R0?"})
            with self.assertRaises(rp.ReadPointError):
                rp.load_audit(d, ["a", "b", "c"])

    def test_unknown_error_type_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(Path(tmp), 0, [{"question_id": "locomo_0_qa0", "question": "Q?",
                                       "error_type": "TYPO"}])
            with self.assertRaises(rp.ReadPointError):
                rp.load_audit(Path(tmp), ["a"])


class CommittedConfigTest(unittest.TestCase):
    """The tracked read-point list is internally consistent (no data needed)."""

    def setUp(self):
        self.config = yaml.safe_load(READ_POINTS_CONFIG.read_text(encoding="utf-8"))

    def test_threshold_parses(self):
        rp.Threshold.from_config(self.config["promotion_threshold"])

    def test_every_read_point_is_a_session_end(self):
        for hid, history in self.config["histories"].items():
            with self.subTest(history=hid):
                ends = history["session_ends"]
                self.assertEqual(ends, sorted(ends))
                self.assertEqual(ends[-1], history["n_messages"])
                self.assertIn(history["n_messages"], history["read_points"])
                self.assertTrue(set(history["read_points"]) <= set(ends))
                for task_id, v in history["v"].items():
                    self.assertTrue(task_id.startswith(f"{hid}:q"))
                    self.assertIn(v, ends)
                listed = set(history["v"])
                self.assertFalse(listed & set(self.config["excluded"]))

    def test_separately_reported_questions_keep_a_read_point(self):
        with_v = {t for h in self.config["histories"].values() for t in h["v"]}
        self.assertTrue(set(self.config["reported_separately"]) <= with_v)


if __name__ == "__main__":
    unittest.main()
