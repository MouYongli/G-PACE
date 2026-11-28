"""E012 (ablation D) arm configs: every engine config parses and differs from the main
configuration only in its retrieval or assembly component, whose files load."""

from __future__ import annotations

import unittest

import yaml

from grace.config.paths import REPO_ROOT
from grace.context.pipeline.assembly.assemble import AssemblyConfig
from grace.context.pipeline.retrieval.retrieve import RetrievalConfig

ARMS = REPO_ROOT / "configs" / "experiments" / "E012"
MAIN = REPO_ROOT / "configs" / "engines" / "grace.yaml"


class E012ConfigTest(unittest.TestCase):
    def test_arms_differ_only_in_read_side_components(self):
        main = yaml.safe_load(MAIN.read_text(encoding="utf-8"))
        experiment = yaml.safe_load((REPO_ROOT / "configs" / "experiments" /
                                     "E012-ablation-d-channels.yaml").read_text("utf-8"))
        paths = sorted(ARMS.glob("*.yaml"))
        self.assertEqual(len(paths), len(experiment["arms"]) - 1)
        for path in paths:
            with self.subTest(arm=path.name):
                arm = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(arm["description"], str)
                for key in ("engine", "writer_model", "embedding"):
                    self.assertEqual(arm[key], main[key])
                changed = {k for k in main["params"] if arm["params"][k] != main["params"][k]}
                self.assertTrue(changed)
                self.assertLessEqual(changed, {"retrieval", "assembly"})
                RetrievalConfig.load(REPO_ROOT / arm["params"]["retrieval"])
                AssemblyConfig.load(REPO_ROOT / arm["params"]["assembly"])


if __name__ == "__main__":
    unittest.main()
