"""Contract tests for the Evaluation section of docs/research/contracts.md.

The required regression tests: empty prediction file, duplicate key, missing key, extra key, mixed
splits, shuffled order, unparsable prediction; plus snapshot mismatches, the invalid-output
policies and the metrics.json record. Run against grace.eval.analysis.metrics on the fixtures.
"""

import copy
import json
import random
import tempfile
import unittest
from pathlib import Path

from grace.eval.analysis.metrics.align import EvaluationError, align, gold_index, read_jsonl
from grace.eval.analysis.metrics.answer import judged_values, locomo_score
from grace.eval.analysis.metrics.dst import joint_goal
from grace.eval.analysis.metrics.record import MetricRecord, aggregate, write_metrics

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "benchmarks"
SLUGS = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


def load(slug):
    d = FIXTURES / slug
    return (read_jsonl(d / "read_tasks.jsonl"), read_jsonl(d / "messages.jsonl"),
            read_jsonl(d / "gold.jsonl"), read_jsonl(d / "predictions.jsonl"))


class AlignmentTest(unittest.TestCase):
    def assert_aborts(self, slug, mutate, category):
        tasks, messages, gold, predictions = load(slug)
        predictions = mutate(copy.deepcopy(predictions))
        with self.assertRaises(EvaluationError) as caught:
            align(tasks, messages, gold, predictions)
        self.assertIn(category, caught.exception.problems)
        self.assertIn(category, str(caught.exception))

    def test_fixture_predictions_align(self):
        for slug in SLUGS:
            with self.subTest(slug=slug):
                tasks, messages, gold, predictions = load(slug)
                aligned = align(tasks, messages, gold, predictions)
                self.assertEqual(list(aligned), [t["read_id"] for t in tasks])

    def test_shuffled_order_gives_the_same_alignment(self):
        for slug in SLUGS:
            tasks, messages, gold, predictions = load(slug)
            shuffled = predictions[:]
            random.Random(7).shuffle(shuffled)
            self.assertEqual(align(tasks, messages, gold, shuffled),
                             align(tasks, messages, gold, predictions))

    def test_empty_prediction_file(self):
        self.assert_aborts("locomo", lambda rows: [], "empty_file")

    def test_duplicate_key(self):
        self.assert_aborts("locomo", lambda rows: rows + rows[:1], "duplicate_key")

    def test_missing_key(self):
        self.assert_aborts("locomo", lambda rows: rows[1:], "missing_key")

    def test_extra_key(self):
        def extra(rows):
            row = dict(rows[0], read_id="conv-syn-1:q99@9")
            return rows + [row]
        self.assert_aborts("locomo", extra, "extra_key")

    def test_missing_and_unknown_fields(self):
        def drop(rows):
            del rows[0]["cited_ids"]
            return rows
        self.assert_aborts("locomo", drop, "missing_field")

        def add(rows):
            rows[0]["engine"] = "grace"
            return rows
        self.assert_aborts("locomo", add, "unknown_field")

    def test_mixed_splits(self):
        def mix(rows):
            rows[0]["split"] = "dev"
            return rows
        self.assert_aborts("locomo", mix, "mixed_scope")

    def test_other_split_than_the_read_tasks(self):
        def other(rows):
            for row in rows:
                row["split"] = "dev"
            return rows
        self.assert_aborts("locomo", other, "scope_mismatch")

    def test_unparsable_prediction_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "predictions.jsonl"
            lines = (FIXTURES / "locomo" / "predictions.jsonl").read_text("utf-8").splitlines()
            path.write_text("\n".join(lines[:1] + ['{"read_id": '] + lines[1:]) + "\n", "utf-8")
            with self.assertRaises(EvaluationError) as caught:
                read_jsonl(path)
            self.assertIn("unparsable_line", caught.exception.problems)

    def test_output_and_prediction_must_agree(self):
        def unknown_with_value(rows):
            next(r for r in rows if r["output"] == "answer")["output"] = "unknown"
            return rows
        self.assert_aborts("locomo", unknown_with_value, "bad_value")

        def answer_without_value(rows):
            next(r for r in rows if r["output"] == "answer")["prediction"] = None
            return rows
        self.assert_aborts("locomo", answer_without_value, "bad_value")

    def test_citation_after_the_read_version(self):
        tested = 0
        for slug in SLUGS:
            tasks, messages, gold, predictions = load(slug)
            later = {}
            for row in predictions:
                after = [m for m in messages if m["history_id"] == row["history_id"]
                         and m["version"] > row["version"]]
                if after:
                    later[row["read_id"]] = after[0]["message_id"]
            if not later:
                continue
            tested += 1

            def future_citation(rows, later=later):
                row = next(r for r in rows if r["read_id"] in later)
                row["cited_ids"] = [later[row["read_id"]]]
                return rows
            with self.subTest(slug=slug):
                self.assert_aborts(slug, future_citation, "snapshot_mismatch")
        self.assertGreater(tested, 0, "no fixture reads before the end of a history")

    def test_snapshot_mismatches(self):
        def unknown_message(rows):
            rows[0]["context_ids"] = rows[0]["context_ids"] + ["D99:1"]
            return rows
        self.assert_aborts("locomo", unknown_message, "snapshot_mismatch")

        def wrong_version(rows):
            rows[0]["version"] += 1
            return rows
        self.assert_aborts("locomo", wrong_version, "snapshot_mismatch")


class PolicyTest(unittest.TestCase):
    def test_invalid_output_policies(self):
        values = {"a": 1.0, "b": 0.0, "c": None, "d": 1.0}
        outputs = {"a": "answer", "b": "answer", "c": "invalid", "d": "unknown"}
        wrong = aggregate(values, outputs, "count_as_wrong")
        self.assertEqual((wrong.value, wrong.n_total, wrong.n_scored, wrong.n_invalid,
                          wrong.n_unknown), (0.5, 4, 4, 1, 1))
        excluded = aggregate(values, outputs, "exclude_and_report")
        self.assertAlmostEqual(excluded.value, 2 / 3)
        self.assertEqual((excluded.n_scored, excluded.n_invalid), (3, 1))
        with self.assertRaises(ValueError):
            aggregate({"a": None}, {"a": "answer"}, "count_as_wrong")
        empty = aggregate({"c": None}, {"c": "invalid"}, "exclude_and_report")
        self.assertIsNone(empty.value)

    def test_locomo_unknown_and_invalid(self):
        tasks, messages, gold, predictions = load("locomo")
        aligned = align(tasks, messages, gold, predictions)
        refs = gold_index(gold, "3eb6f2c")
        values, outputs = {}, {}
        for rid, item in aligned.items():
            g = refs[item.read_task["task_id"]]
            outputs[rid] = item.output
            values[rid] = (None if item.output == "invalid" else
                           locomo_score(g["labels"]["category"], item.output,
                                        item.prediction["prediction"], g["reference"]))
        tally = aggregate(values, outputs, "count_as_wrong")
        self.assertEqual(tally.n_total, len(tasks))
        self.assertIsNotNone(tally.value)

    def test_judged_unknown_is_scored_by_the_abstention_rule(self):
        values, judge_invalid = judged_values(
            {"a": "correct", "b": "invalid"},
            {"a": "answer", "b": "answer", "c": "unknown", "d": "unknown", "e": "invalid"},
            {"a": False, "b": False, "c": True, "d": False, "e": False})
        self.assertEqual(values, {"a": 1.0, "b": None, "c": 1.0, "d": 0.0, "e": None})
        tally = aggregate(values, {"a": "answer", "b": "answer", "c": "unknown",
                                   "d": "unknown", "e": "invalid"}, "count_as_wrong",
                          judge_invalid)
        self.assertEqual((tally.n_scored, tally.n_judge_invalid, tally.value), (4, 1, 0.5))
        with self.assertRaises(ValueError):
            judged_values({}, {"a": "answer"}, {"a": False})

    def test_multiwoz_scored_against_each_annotation(self):
        tasks, messages, gold, predictions = load("multiwoz")
        aligned = align(tasks, messages, gold, predictions)
        annotations = sorted({g["annotation"] for g in gold})
        for annotation in annotations:
            refs = gold_index(gold, annotation)
            covered = [a for a in aligned.values() if a.read_task["task_id"] in refs]
            for item in covered:
                value = joint_goal(item.prediction["prediction"],
                                   refs[item.read_task["task_id"]]["reference"])
                self.assertIn(value, (0.0, 1.0))
        with self.assertRaises(EvaluationError):
            gold_index(gold, "9.9")


class MetricsFileTest(unittest.TestCase):
    def record(self, **overrides):
        fields = dict(benchmark="locomo", split="fixture", schedule="read_tasks.jsonl",
                      annotation="3eb6f2c", metric="f1", direction="higher", stratum=None,
                      seed=0, value=0.5, n_total=4, n_scored=4, n_invalid=1, n_unknown=0,
                      n_judge_invalid=0, invalid_policy="count_as_wrong", scorer="locomo/f1",
                      evaluator_version="0" * 40)
        fields.update(overrides)
        return MetricRecord(**fields)

    def test_metrics_json_is_written_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.json"
            write_metrics(path, [self.record(), self.record(stratum="category=1")])
            data = json.loads(path.read_text("utf-8"))
            self.assertEqual(len(data["metrics"]), 2)
            self.assertEqual(set(data["metrics"][0]), set(MetricRecord.__dataclass_fields__))
            with self.assertRaises(FileExistsError):
                write_metrics(path, [self.record()])

    def test_inconsistent_records_are_refused(self):
        for overrides in ({"invalid_policy": "drop"}, {"n_scored": 5}, {"value": None},
                          {"n_scored": 0}, {"direction": "up"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.record(**overrides)


if __name__ == "__main__":
    unittest.main()
