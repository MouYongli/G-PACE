import json
import unittest
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "benchmarks"


def read_index(path):
    rows = {}
    for line in path.read_text().splitlines():
        item = json.loads(line)
        key = tuple(item[field] for field in ("benchmark", "split", "sample_id"))
        if key in rows:
            raise ValueError(f"duplicate key {key}")
        rows[key] = item
    return rows


class FixtureTest(unittest.TestCase):
    def test_reordered_predictions(self):
        for benchmark in ("bench-a", "bench-b", "bench-c"):
            with self.subTest(benchmark=benchmark):
                samples = read_index(FIXTURES / benchmark / "samples.jsonl")
                predictions = read_index(FIXTURES / benchmark / "predictions.jsonl")
                self.assertEqual(len(samples), 2)
                self.assertEqual(samples.keys(), predictions.keys())
                self.assertNotEqual(list(samples), list(predictions))
                for key, sample in samples.items():
                    self.assertEqual(sample["reference"], predictions[key]["prediction"])
