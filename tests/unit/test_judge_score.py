"""cli/judge_score.py: registered judged metrics, population, abstention and judge-invalid reads."""

import unittest
from types import SimpleNamespace

from grace.cli import judge_score
from grace.eval.analysis.metrics.record import aggregate


def aligned(read_id, task_id, output):
    return SimpleNamespace(read_task={"task_id": task_id}, output=output)


class JudgedMetricsTest(unittest.TestCase):
    def test_registry_names_the_blind_judge_metrics(self):
        names = {m["name"] for m in judge_score.judged_metrics("longmemeval-s", "blind")}
        self.assertEqual(names, {"judge-accuracy"})
        (locomo,) = judge_score.judged_metrics("locomo", "blind")
        self.assertEqual(locomo["population"]["include"]["in"], [1, 2, 3, 4])

    def test_score_applies_population_abstention_and_judge_invalid(self):
        metric = {"code": "grace.eval.analysis.metrics.answer:judged_values",
                  "population": {"include": {"label": "category", "in": [1, 2]}},
                  "abstention": {"label": "abstain", "value": True},
                  "invalid_policy": "count_as_wrong"}
        reads = {"r1": aligned("r1", "t1", "answer"), "r2": aligned("r2", "t2", "answer"),
                 "r3": aligned("r3", "t3", "unknown"), "r4": aligned("r4", "t4", "invalid"),
                 "r5": aligned("r5", "t5", "answer"), "r6": aligned("r6", "t6", "answer")}
        gold = {"t1": {"labels": {"category": 1}}, "t2": {"labels": {"category": 2}},
                "t3": {"labels": {"category": 1, "abstain": True}},
                "t4": {"labels": {"category": 2}}, "t5": {"labels": {"category": 1}},
                "t6": {"labels": {"category": 5}}}
        verdicts = {"r1": "correct", "r2": "incorrect", "r5": "invalid", "r6": "correct"}
        values, outputs, labels, judge_invalid = judge_score.score(reads, gold, verdicts, metric)
        self.assertNotIn("r6", values)  # outside the population
        self.assertEqual(judge_invalid, frozenset({"r5"}))
        self.assertEqual(values["r3"], 1.0)  # unknown on an abstention task
        tally = aggregate(values, outputs, "count_as_wrong", judge_invalid)
        # r1 1, r2 0, r3 1, r4 0 (invalid counted as wrong); r5 excluded
        self.assertEqual((tally.n_total, tally.n_scored, tally.n_judge_invalid), (5, 4, 1))
        self.assertAlmostEqual(tally.value, 0.5)


if __name__ == "__main__":
    unittest.main()
