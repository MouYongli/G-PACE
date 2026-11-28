"""E007 (ablation G) pieces on fixtures: arm configs, the segment driver and writer statistics.

Synthetic messages and a scripted writer only; no model server and no benchmark data.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from grace.cli.writer_ablation import arm_pin, arm_writer_config, extraction_items
from grace.config.paths import REPO_ROOT
from grace.context.pipeline.update.segment import Granularity
from grace.context.pipeline.update.updater import WriterConfig, llm_writer
from grace.eval.analysis.metrics import writer as metric
from grace.eval.runner.probes.writer_extract import drive_segment
from tests.integration.writer_fixture import Rig, message

CONFIG = REPO_ROOT / "configs" / "experiments" / "E007-ablation-g-writer.yaml"


def messages():
    h = "e007-seg"
    return [message(h, 1, "Ana", "Hi Tom!"),
            message(h, 2, "Tom", "Hi Ana, I moved to Porto last month."),
            message(h, 3, "Ana", "Wow, nice!"),
            message(h, 4, "Tom", "I also adopted a dog called Rex."),
            message(h, 5, "Ana", "Catch you later!")]


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


class DriveSegmentTest(unittest.TestCase):
    def test_only_the_segment_is_extracted_from_an_empty_graph(self):
        msgs = messages()
        reply = {"claims": [{"message": 1, "subject": "Tom", "predicate": "adopted",
                             "object": "Rex", "object_type": "entity", "function": "inform",
                             "quote": "adopted a dog called Rex"}], "stances": []}
        config = WriterConfig(granularity=Granularity("session", None))
        rig = Rig(msgs, [reply, {"claims": [], "stances": []}], config=config)
        self.addCleanup(rig.close)
        with tempfile.TemporaryDirectory() as tmp:
            writer = llm_writer(config, rig.client, rig.info)
            records = drive_segment(rig.info, msgs, 4, 4, writer, config, Path(tmp), "seg")
            self.assertEqual([(r["first_version"], r["last_version"], r["status"])
                              for r in records], [(4, 4, "ok")])
            # earlier context: the messages before the segment, as configured (2)
            prompt = rig.transport.requests[0]["messages"][-1]["content"]
            self.assertIn("Wow, nice!", prompt)
            self.assertIn("moved to Porto", prompt)
            self.assertNotIn("Catch you later", prompt)
            store = json.loads((Path(tmp) / "graphs" / "seg" / "writer.json").read_text())
            self.assertEqual(store["head"], 4)
            items = extraction_items(records[0], {msgs[3].message_id: "Tom"}, "seg", "k")
            self.assertEqual([(i["kind"], i["message_id"], i["speaker"]) for i in items],
                             [("claim", msgs[3].message_id, "Tom")])

    def test_range_is_checked(self):
        msgs = messages()
        rig = Rig(msgs, [])
        self.addCleanup(rig.close)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            drive_segment(rig.info, msgs, 4, 9, llm_writer(WriterConfig(), rig.client), rig.config,
                          Path(tmp), "seg")


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
