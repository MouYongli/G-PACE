"""T022 follow-up: the writer driver over a history, writer statistics from run files, and the
extracted graph as input of the T025 graph channel (scripted writer output, no model server)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from grace.cli import retrieval_recall as cli
from grace.config.paths import REPO_ROOT
from grace.context.api import ReadTask
from grace.context.pipeline.query.planner import Planner, PlannerConfig
from grace.context.pipeline.retrieval.retrieve import RetrievalConfig
from grace.context.pipeline.update.updater import llm_writer
from grace.eval.analysis.metrics import writer as metric
from grace.eval.runner.probes import retrieval_recall as probe
from grace.eval.runner.probes.writer_extract import drive_history
from tests.integration.writer_fixture import (
    MELANIE_DATES,
    MELANIE_SCRIPT,
    Rig,
    melanie_messages,
)
from tests.unit.test_retrieval import fake_embed

RECALL_CONFIG = REPO_ROOT / "configs" / "experiments" / "T022-writer-smoke-recall.yaml"
SMOKE_CONFIG = REPO_ROOT / "configs" / "experiments" / "T022-writer-smoke.yaml"


class DriveTest(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(melanie_messages(), MELANIE_SCRIPT, dates=MELANIE_DATES)
        self.addCleanup(self.rig.close)
        self.out = Path(self.rig.tmp.name) / "run"

    def drive(self, limit=None):
        writer = llm_writer(self.rig.config, self.rig.client, self.rig.info)
        return drive_history(self.rig.info, self.rig.messages, writer, self.rig.config,
                             self.out, limit=limit)

    def test_drive_saves_graph_and_state(self):
        updates = self.drive()
        self.assertEqual([u["status"] for u in updates], ["ok", "ok"])
        base = self.out / "graphs" / self.rig.info.history_id
        state = json.loads((base / "writer.json").read_text(encoding="utf-8"))
        self.assertEqual(state["head"], 4)
        graphs = probe.load_extracted_graphs(self.out, [self.rig.info.history_id])
        graph = graphs[self.rig.info.history_id]
        self.assertEqual(graph.store.head, 4)
        self.assertEqual(graph.predicate_uses, {"playsInstrument": 2})
        self.assertEqual(graph.predicate_specs, {"playsInstrument": False})
        self.assertEqual(graph.speakers, ("Melanie",))
        preds, ents = graph.fragment("Which instruments does Melanie play?")
        self.assertEqual([p.name for p in preds], ["playsInstrument"])
        self.assertEqual(ents[0].id, "Melanie")
        self.assertEqual(ents[0].kind, "speaker")
        self.assertEqual({e.id for e in ents[1:]}, {"violin", "clarinet"})

    def test_limit_cuts_history(self):
        updates = self.drive(limit=1)
        self.assertEqual(len(updates), 1)
        self.assertTrue(updates[0]["partial"] is False)
        graphs = probe.load_extracted_graphs(self.out, [self.rig.info.history_id])
        self.assertEqual(graphs[self.rig.info.history_id].store.head, 1)

    def test_statistics_from_files(self):
        updates = self.drive()
        calls = [json.loads(line) for line in
                 (Path(self.rig.tmp.name) / "calls.jsonl").read_text().splitlines()]
        units = metric.unit_stats(updates)
        self.assertEqual(units["by_status"]["ok"], 2)
        self.assertEqual(units["messages"], 4)
        self.assertEqual(units["messages_given_up"], 0)
        self.assertEqual(units["entries"]["claims"], 2)
        self.assertGreaterEqual(units["notes"].get("repeated_mention", 0), 1)
        stats = metric.call_stats(calls)
        self.assertEqual(stats["calls"], 2)
        self.assertEqual(stats["by_status"], {"ok": 2})
        self.assertEqual(stats["invalid_output_rate"], 0.0)
        hid = self.rig.info.history_id
        changesets = {hid: metric.read_jsonl(self.out / "graphs" / hid / "store"
                                             / "changesets.jsonl")}
        messages = {(m.history_id, m.message_id): m.to_record() for m in self.rig.messages}
        graph = metric.graph_stats(changesets[hid])
        self.assertEqual((graph["claims"], graph["catch_all_claims"], graph["removals"],
                          graph["unsafe_entity_ids"]), (2, 0, 0, 0))
        self.assertEqual(graph["top_predicates"], {"playsInstrument": 2})
        samples = metric.sample_units(updates, changesets, messages, 5, 0)
        self.assertEqual(len(samples), 2)
        first = samples[0]
        self.assertEqual(first["versions"], [1, 1])
        self.assertIn("Melanie | playsInstrument | violin", first["committed"][0]["claims"])

    def test_graph_channel_on_extracted_graph(self):
        self.drive()
        hid = self.rig.info.history_id
        graph = probe.load_extracted_graphs(self.out, [hid])[hid]
        experiment = yaml.safe_load(RECALL_CONFIG.read_text(encoding="utf-8"))
        conditions = [probe.Condition.from_dict(n, c)
                      for n, c in experiment["conditions"].items()]
        base = RetrievalConfig.load(REPO_ROOT / experiment["retrieval_config"])
        task = ReadTask(benchmark="fixture", split="dev", history_id=hid, read_id="q0@4",
                        task_id="q0", version=4, kind="question",
                        question="Which instruments does Melanie play?", state_schema=None,
                        asked_at=None, asked_at_raw=None)
        rows = probe.probe_history(
            hid, self.rig.messages, [task], base=base, conditions=conditions, cutoffs=[1, 3],
            depth=3, embed=lambda texts, context: [fake_embed(t) for t in texts],
            embed_batch=4, graph=graph, planner=Planner(PlannerConfig()), benchmark="fixture")
        self.assertEqual(len(rows), 1)
        self.assertIn("graph", rows[0]["rankings"])
        self.assertIn("graph", rows[0]["conditions"])


class WriterRunCheckTest(unittest.TestCase):
    def write_run(self, root: Path, status="completed", dirty=False, limit=None) -> Path:
        path = root / "T022-x"
        path.mkdir()
        (path / "run.json").write_text(json.dumps(
            {"run_id": "T022-x", "stage": "probe", "status": status, "code_dirty": dirty}))
        (path / "resolved-config.yaml").write_text(yaml.safe_dump({"limit": limit}))
        return path

    def test_accepts_complete_clean_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = cli.check_writer_run(self.write_run(Path(tmp)))
            self.assertEqual(record["run_id"], "T022-x")
            self.assertEqual(len(record["run_json_sha256"]), 64)

    def test_refuses_failed_dirty_or_limited_runs(self):
        for kwargs in ({"status": "failed"}, {"dirty": True}, {"limit": 16}):
            with tempfile.TemporaryDirectory() as tmp, self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    cli.check_writer_run(self.write_run(Path(tmp), **kwargs))


class ConfigTest(unittest.TestCase):
    def test_configs_are_development_only(self):
        paths = sorted((REPO_ROOT / "configs" / "experiments").glob("T022-*.yaml"))
        self.assertIn(SMOKE_CONFIG, paths)
        self.assertIn(RECALL_CONFIG, paths)
        for path in paths:
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(config["experiment"], "T022")
            for entry in config["benchmarks"]:
                bc = cli.benchmark_config(entry)
                self.assertEqual(bc.splits[entry["split"]].kind, "development")


if __name__ == "__main__":
    unittest.main()
