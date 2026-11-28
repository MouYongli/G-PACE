"""The committed graph-quality sample (task T024) is reproduced from the benchmark store.

Skipped where the data is absent. Redraws the 40 segments from the LoCoMo and LongMemEval-S
development splits through `load_split` and compares the sample record with
docs/research/annotations/graph-quality/sample.json byte for byte.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grace.config.paths import project_root
from grace.eval.datasets.benchmarks import graph_quality_sample as sample
from grace.eval.datasets.benchmarks.base import load_config

RECORD = (Path(__file__).resolve().parents[2] / "docs" / "research" / "annotations"
          / "graph-quality" / "sample.json")


def data_present() -> bool:
    try:
        return all(load_config(slug).source_dir(project_root()).is_dir()
                   for slug in ("locomo", "longmemeval-s"))
    except RuntimeError:
        return False


@unittest.skipUnless(data_present(), "no LoCoMo or LongMemEval-S data under PROJECT_ROOT")
class GraphQualitySampleTest(unittest.TestCase):
    def test_sample_is_reproducible(self):
        record, rows = sample.draw()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sample.json"
            sample.write(record, rows, out, Path(tmp) / "segments.jsonl")
            self.assertEqual(out.read_bytes(), RECORD.read_bytes())
        self.assertEqual(record["n_segments"], 40)
        by_benchmark = {}
        for s in record["segments"]:
            by_benchmark[s["benchmark"]] = by_benchmark.get(s["benchmark"], 0) + 1
        self.assertEqual(by_benchmark, {"locomo": 16, "longmemeval-s": 24})
        evidence = [r for r in rows if r["kind"] == "evidence"]
        self.assertEqual(len(evidence), 12)


if __name__ == "__main__":
    unittest.main()
