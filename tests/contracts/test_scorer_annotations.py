"""Every annotation the scorer registry names exists for its benchmark (contracts.md, Gold).

Gold `annotation` is the data version of the benchmark config, one of its further annotations
(`extra_manifests`), or a derived gold named on the benchmark card. A mismatch makes a metric
score nothing, so it is caught here rather than at scoring time.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "configs" / "common" / "scorers.yaml"
# Derived gold named on the benchmark cards (contracts.md, Gold; T006 builds the MultiWOZ one).
# change-seq: the generator's gold, the only annotation of the adapter
# (src/grace/eval/datasets/benchmarks/changeseq.py), while configs/benchmarks/change-seq.yaml
# is not bound yet.
DERIVED = {"multiwoz": {"2.4-current-choice"}, "change-seq": {"generator"}}


def known_annotations(slug: str) -> set[str]:
    config = yaml.safe_load((ROOT / "configs" / "benchmarks" / f"{slug}.yaml").read_text("utf-8"))
    names = {str(config["version"])} if config.get("version") is not None else set()
    names |= {str(k) for k in (config.get("extra_manifests") or {})}
    return names | DERIVED.get(slug, set())


class ScorerAnnotationTest(unittest.TestCase):
    def test_annotations_exist(self):
        registry = yaml.safe_load(REGISTRY.read_text("utf-8"))
        for slug, entry in registry["benchmarks"].items():
            if not (ROOT / "configs" / "benchmarks" / f"{slug}.yaml").is_file():
                continue
            known = known_annotations(slug)
            for metric in entry["metrics"]:
                names = metric.get("annotations") or [metric.get("annotation")]
                for name in names:
                    if name is None:
                        continue
                    with self.subTest(benchmark=slug, metric=metric["name"], annotation=name):
                        self.assertIn(str(name), known)


if __name__ == "__main__":
    unittest.main()
