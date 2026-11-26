"""Regression against upstream scorers: GRACE reproduces upstream's outputs exactly.

The expected values in tests/fixtures/upstream/ were produced by running upstream's own code at
the commit pinned in configs/common/scorers.yaml and configs/judges/longmemeval-official.yaml on
synthetic cases (provenance and licences in each fixture). The full comparison on development
splits is in runs/T004/artifacts/scorer-upstream/ (T004 acceptance item 2).
"""

import json
import unittest
from pathlib import Path

import yaml

from grace.config.paths import REPO_ROOT
from grace.eval.analysis.judging.official import TEMPLATES, template_for
from grace.eval.analysis.metrics.answer import locomo_score
from grace.llm.prompts import load_prompt

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "upstream"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class LocomoUpstreamTest(unittest.TestCase):
    def test_scores_equal_upstream_exactly(self):
        data = fixture("locomo_f1.json")
        self.assertGreaterEqual(len(data["cases"]), 200)
        for case in data["cases"]:
            with self.subTest(case=case):
                got = locomo_score(case["category"], "answer", case["prediction"],
                                   case["reference"])
                self.assertEqual(got, case["upstream_score"])  # exact, not approximate

    def test_fixture_revision_is_the_registered_one(self):
        registry = yaml.safe_load((REPO_ROOT / "configs/common/scorers.yaml").read_text())
        revision = fixture("locomo_f1.json")["provenance"]["revision"]
        for metric in registry["benchmarks"]["locomo"]["metrics"]:
            upstream = metric.get("upstream")
            if upstream:
                self.assertEqual(upstream["revision"], revision)
                self.assertTrue(upstream["verified"])


class LongMemEvalUpstreamTest(unittest.TestCase):
    def test_rendered_prompt_is_upstream_byte_for_byte(self):
        data = fixture("longmemeval_judge.json")
        prompts = {name: load_prompt(f"judge-longmemeval-{name}") for name in TEMPLATES}
        seen = set()
        for case in data["cases"]:
            with self.subTest(question_id=case["question_id"]):
                labels = {"question_type": case["question_type"],
                          "abstention": "_abs" in case["question_id"]}
                name = template_for(labels, case["question_id"])
                seen.add(name)
                messages = prompts[name].render(question=case["question"],
                                                reference=case["answer"],
                                                response=case["hypothesis"])
                self.assertEqual(messages, [{"role": "user", "content": case["upstream_prompt"]}])
        self.assertEqual(seen, set(TEMPLATES))

    def test_fixture_revision_is_the_registered_one(self):
        config = yaml.safe_load(
            (REPO_ROOT / "configs/judges/longmemeval-official.yaml").read_text())
        self.assertEqual(config["upstream"]["revision"],
                         fixture("longmemeval_judge.json")["provenance"]["revision"])
        self.assertTrue(config["upstream"]["verified"])


if __name__ == "__main__":
    unittest.main()
