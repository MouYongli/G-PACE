"""E007 (ablation G) pieces on fixtures: arm configs, extraction items and writer statistics.

Synthetic messages and a scripted writer only; no model server and no benchmark data.
"""

from __future__ import annotations

import json
import unittest

import yaml

from grace.cli.writer_ablation import arm_pin, arm_writer_config, extraction_items
from grace.config.paths import REPO_ROOT
from grace.context.pipeline.update.updater import WriterConfig
from grace.eval.analysis.metrics import writer as metric

CONFIG = REPO_ROOT / "configs" / "experiments" / "E007-ablation-g-writer.yaml"


class ArmConfigTest(unittest.TestCase):
    def test_every_arm_resolves_and_shares_the_base(self):
        config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        base = WriterConfig.load(REPO_ROOT / config["writer_config"])
        seen = set()
        for name, arm in config["arms"].items():
            with self.subTest(arm=name):
                wc = arm_writer_config(base, arm)
                self.assertEqual((wc.prompt, wc.schema, wc.decoding["temperature"],
                                  wc.decoding["seed"]), (base.prompt, base.schema, 0.0, 0))
                self.assertIn(arm["model"], config["models"])
                pin = arm_pin(REPO_ROOT / config["models"][arm["model"]]["model_config"],
                              arm["thinking"])
                self.assertEqual(pin.template_kwargs["enable_thinking"], arm["thinking"])
                seen.add((arm["model"], wc.granularity.name, arm["thinking"]))
        for model in ("qwen3-8b", "qwen3-32b"):
            for g in ("message", "segment-8", "session"):
                self.assertIn((model, g, False), seen)

    def test_unknown_arm_key_is_refused(self):
        with self.assertRaises(ValueError):
            arm_writer_config(WriterConfig(), {"model": "m", "thinking": False,
                                               "granularity": {"unit": "message"}, "seed": 1})


class ExtractionItemsTest(unittest.TestCase):
    def test_items_are_anchored_to_message_ids(self):
        raw = json.dumps({"claims": [{"message": 2, "subject": "Tom", "predicate": "adopted",
                                      "object": "Rex"}],
                          "stances": [{"message": 1, "claim": "k1", "function": "confirm"}]})
        update = {"status": "ok", "raw_output": raw, "message_ids": ["m4", "m5"],
                  "history_id": "h", "first_version": 4, "last_version": 5}
        items = extraction_items(update, {"m4": "Ana", "m5": "Tom"}, "g", "seg")
        self.assertEqual([(i["kind"], i["message_id"], i["speaker"]) for i in items],
                         [("claim", "m5", "Tom"), ("stance", "m4", "Ana")])
        self.assertEqual(extraction_items({**update, "status": "invalid_output"}, {}, "g", "s"),
                         [])


def unit(status, first, last, raw=None, claims=0):
    return {"history_id": "h", "status": status, "first_version": first, "last_version": last,
            "message_ids": [f"m{v}" for v in range(first, last + 1)], "partial": False,
            "entries": {"claims": claims, "attributions": claims}, "dropped": [], "notes": {},
            "conflicts": [], "blocked": [], "commit_errors": [], "raw_output": raw}


class WriterStatsTest(unittest.TestCase):
    def test_empty_patches_and_repair(self):
        empty = json.dumps({"claims": [], "stances": [], "same_as": []})
        full = json.dumps({"claims": [{"message": 1}], "stances": []})
        updates = [unit("ok", 1, 2, empty), unit("ok", 3, 4, full, claims=1),
                   unit("ok", 5, 5, full),                       # all dropped: empty commit
                   unit("split", 6, 9), unit("ok", 6, 7, full, 1), unit("split", 8, 9),
                   unit("ok", 8, 8, full, 1), unit("invalid_output", 9, 9),
                   unit("split", 10, 11), unit("ok", 10, 10, empty), unit("ok", 11, 11, full, 1),
                   unit("invalid_output", 12, 12)]
        stats = metric.unit_stats(updates)
        self.assertEqual((stats["empty_patches"], stats["empty_commits"]), (2, 3))
        self.assertEqual(stats["repair"], {"split_roots": 2, "repaired": 1, "repair_rate": 0.5,
                                           "invalid_single_units": 1})


if __name__ == "__main__":
    unittest.main()
