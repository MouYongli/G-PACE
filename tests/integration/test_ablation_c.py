"""E005 driver on a generated development dataset (fake models; no network, no real score).

A tiny dataset of two development-family sequences is generated into a temporary PROJECT_ROOT
(template renderer), and the three arms run end to end: system (template views, LLM-rendered
views through a deterministic fake renderer, raw-text window), score and compare. Also checked:
the oracle's views on the relabelled gold graph state exactly the gold answers of every question
about the read version, and the two view arms see the same rows in the same order.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grace.cli import ablation_c as ac
from grace.config.paths import REPO_ROOT
from grace.context.views.render import display
from grace.context.views.store import ViewStore
from grace.eval.analysis.metrics.changeseq import tokens
from grace.eval.datasets.changeseq.build import DatasetConfig, build_dataset, sha256_file
from grace.eval.runner.harness import rundir
from grace.eval.runner.harness.models import fake_responder
from grace.llm.records import read_calls

CONFIG_PATH = REPO_ROOT / "configs" / "experiments" / "E005-ablation-c-gold.yaml"
DATASET = {
    "dataset": "e005-test", "seed": 5,
    "cells": [{"families": ["car-rental", "flight-travel"], "density": [30], "length": 60,
               "schedules": ["U4"], "primary_schedule": "U4", "sequences_per_family": 1}],
}
_ROW = re.compile(r"^\[(?P<id>[^\]]+)\] (?P<values>.*)$")


def responder(messages):
    """Fake model: renders each row as 'Noted: <values>.'; answers like the harness fake."""
    system, user = messages[0]["content"], messages[-1]["content"]
    if system.startswith("You turn the result rows"):
        sentences = []
        for line in user.split("Rows:\n", 1)[1].splitlines():
            match = _ROW.match(line)
            if match:
                values = [kv.split(" = ", 1)[1] for kv in match["values"].split("; ")]
                sentences.append({"rows": [match["id"]], "text": "Noted: " + ", ".join(values)
                                  + "."})
        return json.dumps({"sentences": sentences})
    return fake_responder(messages)


class AblationCTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        version = cls.root / "data" / "change-seq" / "v0"
        dataset = build_dataset(DatasetConfig.from_dict(DATASET), version, "0" * 40)
        cls.ids = [s["sequence_id"] for s in dataset["sequences"]]
        cls.config = copy.deepcopy(ac.load_experiment(CONFIG_PATH))
        cls.config["benchmark"]["config"] = {
            "benchmark": "change-seq", "version": "v0", "data_root": "data/change-seq",
            "manifest_sha256": sha256_file(version / "MANIFEST.sha256"),
            "splits": {"dev": {"kind": "development", "histories": cls.ids}}}
        (cls.root / "runs").mkdir()
        cls.env = mock.patch.dict(os.environ, {"PROJECT_ROOT": str(cls.root)})
        cls.env.start()
        cls.clean = mock.patch.object(rundir, "code_state",
                                      lambda root=None: rundir.CodeState("0" * 40, False))
        cls.clean.start()
        served = ac.Served(fake_responder=responder)
        cls.systems = {
            "template": ac.run_views(cls.config, CONFIG_PATH, "template", 1024, served,
                                     command="test"),
            "llm": ac.run_views(cls.config, CONFIG_PATH, "llm", 1024, served, command="test"),
            "raw": ac.run_raw(cls.config, 1024, served, command="test")}
        cls.scores = {arm: ac.run_score(cls.config, CONFIG_PATH, r.run_dir, command="test")
                      for arm, r in cls.systems.items()}
        cls.summary = ac.compare(cls.config, 1024, cls.scores, cls.root / "runs" / "summary",
                                 exclude_templates=["V4"])

    @classmethod
    def tearDownClass(cls):
        cls.clean.stop()
        cls.env.stop()
        cls._tmp.cleanup()

    def rows(self, run, name):
        return [json.loads(line) for line in (run.run_dir / name).read_text().splitlines()]

    def test_runs_complete_with_every_read(self):
        for arm, run in self.systems.items():
            self.assertEqual(run.status, "completed", (arm, run.failure))
            predictions = self.rows(run, "predictions.jsonl")
            self.assertEqual(len(predictions), run.n_reads)
            for c in self.rows(run, "contexts.jsonl"):
                self.assertLessEqual(c["tokens"], 1024)
        for arm, score in self.scores.items():
            run = json.loads((score / "run.json").read_text())
            self.assertEqual((run["status"], run["stage"]), ("completed", "score"), arm)
            self.assertTrue((score / "metrics.json").is_file())

    def test_view_arms_show_the_same_views_in_the_same_order(self):
        a = self.rows(self.systems["template"], "contexts.jsonl")
        b = self.rows(self.systems["llm"], "contexts.jsonl")
        self.assertEqual([[f["fragment_id"] for f in x["fragments"]] for x in a],
                         [[f["fragment_id"] for f in x["fragments"]] for x in b])
        self.assertEqual([[f["evidence_ids"] for f in x["fragments"]] for x in a],
                         [[f["evidence_ids"] for f in x["fragments"]] for x in b])
        self.assertTrue(any("Noted:" in x["text"] for x in b))
        self.assertFalse(any("Noted:" in x["text"] for x in a))

    def test_rendering_is_booked_to_W_at_read_time(self):
        calls = read_calls(self.systems["llm"].run_dir / "calls.jsonl")
        render = [c for c in calls if c.call_type == "render"]
        self.assertTrue(render)
        self.assertEqual({c.category for c in render}, {"W"})
        # Read-time rebuilds, plus the initial build before the first message (the count views
        # state a count of 0 at version 0).
        self.assertIn("read", {c.trigger for c in render})
        self.assertEqual({c.version for c in render if c.trigger == "write"}, {0})
        self.assertFalse([c for c in read_calls(self.systems["template"].run_dir / "calls.jsonl")
                          if c.call_type == "render"])
        stats = self.summary["arms"]["llm"]["rendering"]
        self.assertGreater(stats["llm_sentences"], 0)
        self.assertEqual(stats["calls"]["render"]["calls"], len(render))

    def test_summary_pairs(self):
        self.assertIn("llm-template", self.summary["paired"])
        self.assertIn("template-raw", self.summary["paired"])
        pair = self.summary["paired"]["llm-template"]["family"]
        paired = self.summary["paired"]["llm-template"]
        self.assertTrue(set(paired["by_template"]) <= {"V1", "V2", "V3", "V4", "V5", "V6"})
        sens = paired["sensitivity_excluding_V4"]
        self.assertEqual(sens["n_reads"], pair["n_reads"]
                         - paired["by_template"].get("V4", {"n_reads": 0})["n_reads"])
        self.assertIn("sensitivity", sens["kind"])
        self.assertEqual(pair["n_clusters"], 2)
        self.assertTrue(json.loads((self.root / "runs" / "summary" / "summary.json")
                                   .read_text())["inputs"]["llm"]["system_run"])

    def test_oracle_views_state_the_gold_answers(self):
        population = set(self.config["population"]["include_types"])
        dirs = ac.sequence_dirs(ac.benchmark_config(self.config))
        checked = 0
        for sid in self.ids:
            gold = ac.load_gold_views(dirs[sid])
            self.assertFalse(any(b.subject.startswith("k") and b.subject[1:].isdigit()
                                 for b in gold.bindings))
            store = ViewStore(sid, config=ac.view_config(self.config, "template"))
            for b in gold.bindings:
                store.build(b, gold.graph, 0)
            by_gold = dict(zip([json.loads(x)["binding_id"] for x in
                                (dirs[sid] / "bindings.jsonl").read_text().splitlines()],
                               [b.view_id for b in gold.bindings], strict=True))
            questions = [json.loads(x) for x in (dirs[sid] / "schedules" / "U4.jsonl")
                         .read_text().splitlines()]
            for q in sorted(questions, key=lambda q: q["read_version"]):
                if q["type"] not in population:
                    continue
                view = store.get(by_gold[q["binding_id"]])
                if view.cutoff < q["read_version"]:
                    store.maintain(view.view_id, gold.graph, q["read_version"])
                    view = store.get(view.view_id)
                got = self.answer_of(view, q["template"])
                want = sorted(" ".join(tokens(" ".join(a if isinstance(a, list) else [a])))
                              for a in q["answer_text"])
                if q["template"] == "V4":
                    want = sorted(" ".join(tokens(a[1])) for a in q["answer_text"])
                self.assertEqual(got, want, (sid, q["question_id"]))
                checked += 1
        self.assertGreater(checked, 10)

    @staticmethod
    def answer_of(view, template):
        if view.is_count:
            return [" ".join(tokens(display(r.values[-1]))) for r in view.rows if r.aggregate]
        values = [[display(v) for v in r.values] for r in view.rows]
        if template == "V4":
            return sorted(" ".join(tokens(v[1])) for v in values)
        if template == "V6":
            return sorted(" ".join(tokens(f"{v[0]} {v[2]}")) for v in values)
        return sorted(" ".join(tokens(" ".join(v))) for v in values)


if __name__ == "__main__":
    unittest.main()
