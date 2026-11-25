"""The T023 planner development subset: annotation checks and the rules-only planner on it.

Every case's annotated IR is executed on the case's gold graph (change-seq: regenerated with the
generator; LoCoMo: the hand-built partial graph). On the endorsement-filtered graph (gap F1,
`planner_dev.endorsed_store`) it must reproduce the gold answer of every case, and its
attribution and time signatures must equal the annotated expectations. The cases that only the
filtered graph answers correctly are the F1 cases; their number is pinned so that a change of
the generator or of the gap is noticed.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from grace.context.pipeline.query.planner import Planner, PlannerConfig, summarize
from tests.integration import planner_dev as pd

F1_CASES = 26  # gold IR wrong only on the unfiltered graph: [u, f] cannot require own/positive


class PlannerDevSubsetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.subset = pd.load_subset()
        cls.cases = cls.subset["cases"]
        cls.graphs = pd.graphs(cls.cases)

    def test_header_names_the_agent_annotator_and_development_data(self):
        self.assertEqual(self.subset["annotator"], "agent-m01-T023")
        self.assertIn("not a human annotator", self.subset["annotator_kind"])
        locomo = {c["history_id"] for c in self.cases if c["source"] == "locomo"}
        self.assertLessEqual(locomo, {"conv-26", "conv-49"})
        raw = yaml.safe_load(pd.LOCOMO_FILE.read_text(encoding="utf-8"))
        self.assertEqual(set(raw["histories"]), {"conv-26", "conv-49"})
        self.assertEqual(len({c["case_id"] for c in self.cases}), len(self.cases))

    def test_subset_file_is_reproduced_by_the_builder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subset.yaml"
            sequences = pd.generate_changeseq()
            cases = pd.build_changeseq_cases(sequences)
            locomo = yaml.safe_load(pd.LOCOMO_FILE.read_text(encoding="utf-8"))["cases"]
            pd.write_subset(cases, locomo, path)
            self.assertEqual(path.read_text(encoding="utf-8"),
                             pd.SUBSET_FILE.read_text(encoding="utf-8"))

    def test_annotated_ir_matches_expectations_and_gold(self):
        records = [pd.check_case(c, pd.gold_plan(c), self.graphs[c["history_id"]])
                   for c in self.cases]
        for r in records:
            with self.subTest(case=r["case_id"]):
                self.assertTrue(r["attribution_ok"], r["attribution"])
                self.assertTrue(r["time_ok"], r["time"])
                self.assertTrue(r["execution_ok_endorsed"],
                                (r["answer_endorsed"], r["gold_answer"]))
        self.assertEqual(sum(r["f1_explained"] for r in records), F1_CASES)
        self.assertTrue(all(r["execution_ok"] for r in records if r["source"] == "locomo"))

    def test_rules_only_planner_on_the_subset(self):
        planner = Planner(PlannerConfig())
        plans, records = [], []
        for c in self.cases:
            graph = self.graphs[c["history_id"]]
            plan = planner.plan(pd.context_of(c, graph))
            plans.append(plan)
            records.append(pd.check_case(c, plan, graph))
        summary = summarize(plans)
        self.assertEqual(summary["reads"], len(self.cases))
        self.assertEqual(summary["llm_calls"], 0)
        self.assertEqual(set(summary["fallback_reasons"]), {"no_llm"})
        rule = [r for r in records if r["route"] == "rule"]
        self.assertGreater(len(rule), 0)
        # every rule-planned read is correct in attribution and time and, on the filtered
        # graph, in its result
        for r in rule:
            with self.subTest(case=r["case_id"]):
                self.assertTrue(r["attribution_ok"] and r["time_ok"])
                self.assertTrue(r["execution_ok_endorsed"])


if __name__ == "__main__":
    unittest.main()
