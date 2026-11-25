"""Official LoCoMo F1, DST metrics and human-label agreement on hand-computed cases.

The LoCoMo cases follow the rules of task_eval/evaluation.py (snap-research/locomo) and are
hand-computed; exact agreement with upstream's code is tested in test_upstream_scorers.py.
"""

import tempfile
import unittest
from pathlib import Path

from grace.eval.analysis.judging.human import cohen_kappa, judge_agreement, read_labels
from grace.eval.analysis.metrics.answer import (
    locomo_score,
    multi_answer_f1,
    normalize_answer,
    token_f1,
)
from grace.eval.analysis.metrics.dst import joint_goal, normalise_state, slot_f1


class LocomoF1Test(unittest.TestCase):
    def test_normalisation(self):
        self.assertEqual(normalize_answer("The violin, and a Clarinet!"), "violin clarinet")
        self.assertEqual(normalize_answer("7 May, 2023"), "7 may 2023")
        self.assertEqual(normalize_answer("Theatre"), "theatre")  # articles only as words

    def test_token_f1(self):
        self.assertEqual(token_f1("The violin and a clarinet", "violin and clarinet"), 1.0)
        self.assertAlmostEqual(token_f1("running fast", "run"), 2 / 3)  # Porter: running -> run
        self.assertEqual(token_f1("7 May, 2023", "7 May 2023"), 1.0)
        self.assertEqual(token_f1("", "Paris"), 0.0)
        self.assertEqual(token_f1("Berlin", "Paris"), 0.0)
        # 6 prediction tokens, 1 shared: P = 1/6, R = 1, F1 = 2/7
        self.assertAlmostEqual(token_f1("she went to Paris in May", "Paris"), 2 / 7)

    def test_multi_hop_splits_on_commas(self):
        self.assertEqual(multi_answer_f1("Paris, London", "London, Berlin"), 0.5)
        self.assertEqual(locomo_score(1, "answer", ["violin", "clarinet"], "clarinet, violin"),
                         1.0)

    def test_category_rules(self):
        self.assertEqual(locomo_score(3, "answer", "yes", "Yes; she likes dogs"), 1.0)
        # category 4 keeps the whole reference: P = 1, R = 1/4, F1 = 0.4
        self.assertAlmostEqual(locomo_score(4, "answer", "yes", "Yes; she likes dogs"), 0.4)
        self.assertEqual(locomo_score(5, "answer", "Not mentioned in the conversation", "x"), 1.0)
        self.assertEqual(locomo_score(5, "answer", "Paris", "x"), 0.0)
        self.assertEqual(locomo_score(5, "unknown", None, "x"), 1.0)
        self.assertEqual(locomo_score(2, "unknown", None, "May 2023"), 0.0)
        with self.assertRaises(ValueError):
            locomo_score(6, "answer", "x", "x")


class DialogueStateTest(unittest.TestCase):
    def test_normalisation_drops_none(self):
        self.assertEqual(normalise_state({"Train-Day": " Monday ", "hotel-area": "none",
                                          "hotel-name": "", "hotel-parking": "dontcare"}),
                         {"train-day": "monday", "hotel-parking": "dontcare"})
        with self.assertRaises(ValueError):
            normalise_state({"train-day": 1})

    def test_jga_and_slot_f1(self):
        gold = {"train-day": "monday", "train-destination": "cambridge"}
        self.assertEqual(joint_goal({"train-destination": "Cambridge", "train-day": "monday"},
                                    gold), 1.0)
        self.assertEqual(joint_goal({"train-day": "monday"}, gold), 0.0)
        self.assertEqual(slot_f1({"a": "1", "b": "2"}, {"a": "1", "c": "3"}), 0.5)
        self.assertEqual(slot_f1(None, {}), 1.0)
        self.assertEqual(slot_f1({}, gold), 0.0)


class HumanAgreementTest(unittest.TestCase):
    def test_kappa(self):
        a = {"1": "correct", "2": "correct", "3": "incorrect", "4": "incorrect"}
        b = {"1": "correct", "2": "incorrect", "3": "incorrect", "4": "incorrect", "5": "correct"}
        result = cohen_kappa(a, b)
        self.assertEqual((result.n, result.observed), (4, 0.75))
        self.assertAlmostEqual(result.kappa, 0.5)
        self.assertIsNone(cohen_kappa({"1": "correct"}, {"1": "correct"}).kappa)
        with self.assertRaises(ValueError):
            cohen_kappa({"1": "correct"}, {"2": "correct"})

    def test_label_file_and_judge_agreement(self):
        rows = []
        for annotator, verdicts in {"ann1": "ccii", "ann2": "ciii",
                                    "adjudicated": "ccii"}.items():
            for i, v in enumerate(verdicts):
                verdict = "correct" if v == "c" else "incorrect"
                rows.append(f'{{"read_id": "r{i}", "task_id": "t{i}", "annotation": "a", '
                            f'"annotator": "{annotator}", "verdict": "{verdict}"}}')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "human-labels.jsonl"
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            labels = read_labels(path)
            path.write_text("\n".join(rows + rows[:1]) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_labels(path)
        report = judge_agreement({"r0": "correct", "r1": "correct", "r2": "incorrect",
                                  "r3": "invalid"}, labels)
        self.assertEqual(report["judge_vs_adjudicated"].n, 3)
        self.assertEqual(report["judge_vs_adjudicated"].observed, 1.0)
        self.assertEqual(report["judge_invalid"], 1)
        self.assertAlmostEqual(report["between_annotators"].kappa, 0.5)
        with self.assertRaises(ValueError):
            judge_agreement({"r0": "correct"}, labels)


if __name__ == "__main__":
    unittest.main()
