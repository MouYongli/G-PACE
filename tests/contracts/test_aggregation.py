"""The scorer registry carries the aggregation rules of decision D002 (Evaluation section)."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "configs" / "common" / "scorers.yaml"


class AggregationTest(unittest.TestCase):
    def setUp(self):
        self.registry = yaml.safe_load(REGISTRY.read_text("utf-8"))

    def test_rules_of_d002(self):
        rules = self.registry["aggregation"]
        self.assertEqual(rules["cross_benchmark"], "none")
        self.assertEqual(rules["point_estimate"], "micro")
        self.assertEqual(rules["overall_vs_strata"], "pooled")
        self.assertEqual(rules["invalid_policy"], "count_as_wrong")
        self.assertEqual(rules["failed_runs"], "missing")
        self.assertEqual(rules["interval"], "cluster-bootstrap-95")
        self.assertGreaterEqual(rules["bootstrap_resamples"], 1000)

    def test_every_benchmark_names_its_cluster_unit(self):
        for slug, entry in self.registry["benchmarks"].items():
            with self.subTest(benchmark=slug):
                self.assertTrue(entry.get("cluster_unit"))

    def test_every_metric_counts_invalid_as_wrong(self):
        for slug, entry in self.registry["benchmarks"].items():
            for metric in entry["metrics"]:
                with self.subTest(benchmark=slug, metric=metric["name"]):
                    self.assertEqual(metric["invalid_policy"], "count_as_wrong")


if __name__ == "__main__":
    unittest.main()
