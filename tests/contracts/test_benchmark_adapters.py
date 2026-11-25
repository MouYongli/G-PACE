"""Contract tests of the benchmark adapters (task T002) on synthetic sources.

Each adapter converts a made-up release in the source format
(tests/contracts/benchmark_sources.py) through `splits.load_split`; the written records must pass
the reference checks of tests/contracts/records.py, keep every masked or excluded value out of the visible files, and
count their exclusions. The guard tests cover held-out refusal, manifest and count mismatches.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from grace.eval.datasets.benchmarks.base import (
    DataError,
    RecordError,
    SplitSpec,
    load_config,
    validate,
    write_records,
)
from grace.eval.datasets.benchmarks.records import Gold
from grace.eval.datasets.benchmarks.splits import HeldOutLocked, load_split
from tests.contracts.benchmark_sources import BUILDERS, SENTINEL, build
from tests.contracts.records import load_benchmark

VISIBLE = ("histories.jsonl", "messages.jsonl", "read_tasks.jsonl")


def unlocked() -> bool:
    return True


def locked() -> bool:
    return False


class AdapterTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def load(self, slug, split="dev", tag_exists=locked, **changes):
        config = build(slug, self.root)
        if changes:
            config = replace(config, **changes)
        return load_split(slug, split, config=config, data_root=self.root, tag_exists=tag_exists)

    def convert(self, slug):
        records = self.load(slug)
        out = self.root / "out" / slug
        write_records(records, out)
        return records, out, load_benchmark(out)


class EveryAdapterTest(AdapterTestCase):
    def test_records_pass_the_reference_contract_checks(self):
        for slug in BUILDERS:
            with self.subTest(slug=slug):
                records, out, checked = self.convert(slug)
                self.assertEqual(len(checked["histories"]), records.counts()["histories"])
                self.assertEqual(len(checked["gold"]), records.counts()["gold"])
                self.assertTrue((out / "exclusions.json").is_file())
                self.assertTrue(all(h.split == "dev" for h in records.histories))

    def test_masked_and_excluded_values_never_reach_visible_files(self):
        for slug in BUILDERS:
            with self.subTest(slug=slug):
                _, out, _ = self.convert(slug)
                for name in VISIBLE:
                    self.assertNotIn(SENTINEL, (out / name).read_text(encoding="utf-8"), name)
                for name in VISIBLE:
                    for line in (out / name).read_text(encoding="utf-8").splitlines():
                        self.assertNotIn("has_answer", json.loads(line).get("metadata", {}))

    def test_held_out_split_is_refused_before_the_preregistration_tag(self):
        for slug in BUILDERS:
            with self.subTest(slug=slug):
                with self.assertRaises(HeldOutLocked):
                    self.load(slug, "held-out", tag_exists=locked)
                records = self.load(slug, "held-out", tag_exists=unlocked)
                self.assertTrue(records.histories)
                self.assertTrue(all(h.split == "held-out" for h in records.histories))

    def test_dev_and_held_out_are_disjoint(self):
        for slug in BUILDERS:
            with self.subTest(slug=slug):
                dev = {t.task_id for t in self.load(slug).read_tasks}
                held = {t.task_id for t in self.load(slug, "held-out", unlocked).read_tasks}
                self.assertTrue(dev and held)
                self.assertFalse(dev & held)


class GuardTest(AdapterTestCase):
    def test_manifest_checksum_mismatch(self):
        with self.assertRaisesRegex(DataError, "does not match the config"):
            self.load("locomo", manifest_sha256="0" * 64)

    def test_source_file_changed_after_the_manifest(self):
        config = build("locomo", self.root)
        path = self.root / "data/locomo/v1/locomo10.json"
        path.chmod(0o644)
        path.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(DataError, "do not match the manifest"):
            load_split("locomo", "dev", config=config, data_root=self.root, tag_exists=locked)

    def test_count_mismatch(self):
        config = build("locomo", self.root)
        spec = config.splits["dev"]
        bad = replace(spec, counts={**spec.counts, "read_tasks": 4})
        config = replace(config, splits={**config.splits, "dev": bad})
        with self.assertRaisesRegex(DataError, "read_tasks: expected 4, got 3"):
            load_split("locomo", "dev", config=config, data_root=self.root, tag_exists=locked)

    def test_unknown_split_and_unknown_history(self):
        with self.assertRaises(DataError):
            self.load("locomo", "test")
        config = build("locomo", self.root)
        spec = SplitSpec("dev", "development", histories=frozenset({"conv-missing"}))
        config = replace(config, splits={"dev": spec})
        with self.assertRaisesRegex(RecordError, "unknown histories"):
            load_split("locomo", "dev", config=config, data_root=self.root, tag_exists=locked)

    def test_validate_rejects_duplicate_messages_and_bad_evidence(self):
        records = self.load("locomo")
        broken = copy.deepcopy(records)
        broken.messages.append(broken.messages[0])
        with self.assertRaisesRegex(RecordError, "duplicate_message"):
            validate(broken)
        broken = copy.deepcopy(records)
        gold = broken.gold[0]
        broken.gold[0] = replace(gold, evidence_ids=("D7:7",))
        with self.assertRaisesRegex(RecordError, "unknown_evidence"):
            validate(broken)
        broken = copy.deepcopy(records)
        broken.gold.append(broken.gold[0])
        with self.assertRaisesRegex(RecordError, "duplicate_gold"):
            validate(broken)

    def test_gold_rejects_unknown_fields(self):
        record = self.load("locomo").gold[0].to_record()
        Gold.from_record(record)
        with self.assertRaises(RecordError):
            Gold.from_record({**record, "question": "leak"})


class PerBenchmarkTest(AdapterTestCase):
    def test_locomo_exclusions_and_evidence(self):
        records = self.load("locomo")
        self.assertEqual(records.exclusions["category_5"], 1)
        self.assertEqual(records.exclusions["image_fields_removed_from_turn"], 1)
        self.assertEqual(records.exclusions["session_date_without_session"], 1)
        self.assertEqual(records.exclusions["summary:session_summary"], 1)
        gold = {g.task_id: g for g in records.gold}
        self.assertEqual(gold["conv-syn-1:q0"].evidence_ids, ("D1:1", "D2:1"))
        self.assertEqual(gold["conv-syn-1:q1"].evidence_unresolved, ("D1:1; D9:9",))
        self.assertEqual(gold["conv-syn-1:q1"].reference, "2023")
        self.assertEqual(gold["conv-syn-1:q2"].metadata["evidence_status"], "missing")
        history = records.histories[0]
        self.assertEqual(history.segments[0].timestamp, "2023-05-08T13:56")
        self.assertTrue(all(t.version == history.n_messages for t in records.read_tasks))

    def test_longmemeval_masks_evidence_and_renames_repeated_sessions(self):
        records = self.load("longmemeval-s")
        history = records.histories[0]
        self.assertEqual([s.segment_id for s in history.segments], ["sess_a", "sess_b", "sess_a#2"])
        self.assertEqual(records.exclusions["empty_text"], 1)
        (gold,) = records.gold
        self.assertEqual(gold.evidence_ids, ("sess_b:0",))
        self.assertEqual(gold.evidence_segment_ids, ("sess_b",))
        self.assertEqual(gold.labels, {"question_type": "knowledge-update", "abstention": False})
        (task,) = records.read_tasks
        self.assertEqual(task.asked_at, "2023-06-01T10:00")
        self.assertEqual([m.role for m in records.messages][:2], ["user", "agent"])

    def test_halumem_reads_at_session_end_and_writes_memory_points(self):
        records = self.load("halumem-medium")
        (task,) = records.read_tasks
        self.assertEqual(task.version, records.histories[0].segments[0].last_version)
        self.assertEqual(task.task_id, "user-1:session_1:q0")
        (gold,) = records.gold
        self.assertIsNone(gold.evidence_ids)
        self.assertTrue(gold.metadata["evidence_memory_points"])
        self.assertEqual(len(records.scoring["memory_points.jsonl"]), 2)
        self.assertEqual(records.exclusions["user_field:persona_info"], 1)
        self.assertEqual(records.messages[0].timestamp, "2025-09-19T08:32:00")

    def test_memoryagentbench_chunks_and_subsets(self):
        records = self.load("memoryagentbench")
        subsets = {h.history_id: h.subset for h in records.histories}
        self.assertEqual(subsets, {"longmemeval_s*:0": "longmemeval-s-star",
                                   "factconsolidation_sh_6k:0": "factconsolidation-sh-6k"})
        self.assertTrue(all(m.role == "document" and m.speaker is None for m in records.messages))
        fc = [m for m in records.messages if m.history_id.startswith("fact")]
        self.assertEqual([m.text.count("\n") + 1 for m in fc], [2, 2, 1])
        self.assertEqual(records.exclusions["fact_context_header"], 1)
        self.assertEqual(records.exclusions["subset_not_in_plan:eventqa_full"], 1)
        gold = {g.task_id: g for g in records.gold}
        lme = gold["longmemeval_s*:0:longmemeval_s*_no0"]
        self.assertEqual(lme.labels["competency"], "accurate_retrieval")
        self.assertIsInstance(lme.reference, list)

    def test_multiwoz_states_under_three_annotations(self):
        records = self.load("multiwoz")
        self.assertEqual([t.version for t in records.read_tasks], [1, 3])
        self.assertTrue(all(t.kind == "state" for t in records.read_tasks))
        gold = {(g.annotation, g.task_id): g for g in records.gold}
        for annotation in ("2.4", "2.2", "2.1"):
            self.assertEqual(gold[(annotation, "SYN0001.json:0")].reference,
                             {"train-destination": "cambridge"})
        self.assertEqual(records.exclusions["slot_outside_inventory:hospital-department"], 2)
        self.assertEqual(records.exclusions["goal"], 1)
        acts = gold[("2.4", "SYN0001.json:2")].metadata["dialogue_acts"]
        self.assertEqual(acts["system"], {"Train-Inform": [["Leave", "9:00"]]})


class RealConfigTest(unittest.TestCase):
    """The committed configs: split lists and counts as the plan states them (no data needed)."""

    SLUGS = ("locomo", "longmemeval-s", "halumem-medium", "memoryagentbench", "multiwoz")

    def test_configs_load_and_splits_are_disjoint(self):
        for slug in self.SLUGS:
            with self.subTest(slug=slug):
                config = load_config(slug)
                self.assertEqual({s.kind for s in config.splits.values()},
                                 {"development", "held-out"})
                dev, held = config.splits["dev"], config.splits["held-out"]
                for attr in ("histories", "tasks"):
                    a, b = getattr(dev, attr), getattr(held, attr)
                    if a is not None:
                        self.assertFalse(a & b)

    def test_locomo_split_follows_plan_6_5(self):
        config = load_config("locomo")
        self.assertEqual(config.splits["dev"].histories, {"conv-26", "conv-49"})
        self.assertEqual(len(config.splits["held-out"].histories), 8)
        self.assertEqual(config.splits["dev"].counts["read_tasks"], 308)
        self.assertEqual(config.splits["held-out"].counts["read_tasks"], 1232)

    def test_longmemeval_split_is_about_one_fifth(self):
        config = load_config("longmemeval-s")
        dev, held = config.splits["dev"].histories, config.splits["held-out"].histories
        self.assertEqual(len(dev | held), 500)
        self.assertEqual(len(dev), 98)

    def test_multiwoz_held_out_is_the_test_set(self):
        counts = load_config("multiwoz").splits["held-out"].counts
        self.assertEqual((counts["histories"], counts["read_tasks"]), (1000, 7372))


if __name__ == "__main__":
    unittest.main()
