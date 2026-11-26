"""Contract test of the change-seq adapter (task T015) on a generated development dataset.

A tiny dataset of two development-family sequences is generated into a temporary directory with
its manifest and loaded through `splits.load_split` under a temporary config; the written records
must pass the reference checks of tests/contracts/records.py, keep gold out of the visible files
and honour the held-out guard. No held-out family is generated: the "held-out" split of the
temporary config names a development-family sequence.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grace.eval.datasets.benchmarks.base import BenchmarkConfig, write_records
from grace.eval.datasets.benchmarks.splits import HeldOutLocked, load_split
from grace.eval.datasets.changeseq.build import DatasetConfig, build_dataset, sha256_file
from tests.contracts.records import load_benchmark

CONFIG = {
    "dataset": "adapter-test", "seed": 3,
    "cells": [{"families": ["train-travel", "hotel-stay"], "density": [30], "length": 60,
               "schedules": ["A6d1", "U4"], "primary_schedule": "A6d1",
               "sequences_per_family": 1}],
}


class ChangeSeqAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        version_dir = cls.root / "data" / "change-seq" / "v0"
        dataset = build_dataset(DatasetConfig.from_dict(CONFIG), version_dir, "0" * 40)
        cls.ids = [s["sequence_id"] for s in dataset["sequences"]]
        cls.config = BenchmarkConfig.from_dict({
            "benchmark": "change-seq", "version": "v0", "data_root": "data/change-seq",
            "manifest_sha256": sha256_file(version_dir / "MANIFEST.sha256"),
            "splits": {"dev": {"kind": "development", "histories": [cls.ids[0]]},
                       "held-out": {"kind": "held-out", "histories": [cls.ids[1]]}}})

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def load(self, split="dev", tag=False):
        return load_split("change-seq", split, config=self.config, data_root=self.root,
                          tag_exists=lambda: tag)

    def test_records_pass_the_reference_contract_checks(self):
        records = self.load()
        out = self.root / "out"
        write_records(records, out)
        checked = load_benchmark(out)
        self.assertEqual(len(checked["histories"]), 1)
        self.assertEqual(records.histories[0].history_id, self.ids[0])
        self.assertIn("read_tasks.U4.jsonl", records.schedules)
        self.assertEqual(len(records.gold), sum(len(t) for t in records.schedules.values()))
        roles = {m.role for m in records.messages}
        self.assertEqual(roles, {"user", "agent"})
        self.assertTrue(records.histories[0].segments)

    def test_gold_fields(self):
        records = self.load()
        tasks = {t.task_id: t for ts in records.schedules.values() for t in ts}
        for g in records.gold:
            self.assertIn(g.labels["change_type"], {"none", "mixed", "C1", "C2", "C3", "C4",
                                                    "C5", "C6", "C7"})
            self.assertEqual(g.labels["expected_abstention"], not g.reference)
            self.assertTrue(g.task_id.startswith(self.ids[0] + ":"))
            self.assertIn(g.task_id, tasks)
        pairs = [g for g in records.gold if g.labels["pair_id"]]
        self.assertTrue(all(g.labels["pair_role"] in ("known-then", "seen-from-now")
                            for g in pairs))

    def test_visible_records_carry_no_gold(self):
        out = self.root / "visible"
        write_records(self.load(), out)
        for name in ("histories.jsonl", "messages.jsonl", "read_tasks.jsonl",
                     "read_tasks.U4.jsonl"):
            for line in (out / name).read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                for key in ("reference", "labels", "evidence_ids", "answer", "witnesses"):
                    self.assertNotIn(key, row)
                self.assertNotIn("change_type", json.dumps(row.get("metadata", {})))

    def test_held_out_split_is_refused_before_the_preregistration_tag(self):
        with self.assertRaises(HeldOutLocked):
            self.load("held-out", tag=False)
        records = self.load("held-out", tag=True)
        self.assertEqual([h.history_id for h in records.histories], [self.ids[1]])


if __name__ == "__main__":
    unittest.main()
