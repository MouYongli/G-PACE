"""Development splits of the real benchmark store (task T002); skipped where the data is absent.

Loads every development split through `splits.load_split`, which checks the manifests and the
counts in configs/benchmarks/, and asserts that held-out splits stay locked. Only counts are
compared; no benchmark text enters the test.
"""

from __future__ import annotations

import unittest

from grace.config.paths import project_root
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.splits import (
    HeldOutLocked,
    load_split,
    preregistration_tag_exists,
)

SLUGS = ("locomo", "longmemeval-s", "halumem-medium", "memoryagentbench", "multiwoz")


def data_present(slug: str) -> bool:
    try:
        config = load_config(slug)
        return all(config.source_dir(project_root(), v).is_dir() for v in config.manifests())
    except RuntimeError:
        return False


class DevelopmentSplitsTest(unittest.TestCase):
    def test_dev_splits_reproduce_the_configured_counts(self):
        for slug in SLUGS:
            with self.subTest(slug=slug):
                if not data_present(slug):
                    self.skipTest(f"{slug}: no data under PROJECT_ROOT")
                records = load_split(slug, "dev")
                self.assertEqual(records.counts(), dict(load_config(slug).splits["dev"].counts))

    @unittest.skipIf(preregistration_tag_exists(), "the preregistration tag exists")
    def test_held_out_splits_are_locked(self):
        for slug in SLUGS:
            with self.subTest(slug=slug), self.assertRaises(HeldOutLocked):
                load_split(slug, "held-out")


if __name__ == "__main__":
    unittest.main()
