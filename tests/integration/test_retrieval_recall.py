"""T025 recall probe on synthetic records: channel rankings, graph channel through the planner
and a claim graph, conditions at fixed totals, and recall from the written rows."""

from __future__ import annotations

import json
import unittest

import yaml

from grace.config.paths import REPO_ROOT
from grace.context.api import Message, ReadTask
from grace.context.pipeline.query.planner import Planner, PlannerConfig
from grace.context.pipeline.retrieval.retrieve import RetrievalConfig
from grace.eval.analysis.metrics import retrieval as metric
from grace.eval.runner.probes import retrieval_recall as probe
from tests.unit.test_query_planner import ENTITIES, PREDICATES, build_store
from tests.unit.test_retrieval import fake_embed

TEXTS = ["I live in Bremen now", "The weather is grey", "We moved, I live in Cologne",
         "Back in 2010 I lived in Hamburg", "I can offer you the Kia Ceed",
         "Great, I take the Kia", "We went on trips in May and July", "Nice soup today",
         "The bakery opens early"]
CONFIG = REPO_ROOT / "configs" / "experiments" / "T025-retrieval-recall.yaml"


def msg(i: int) -> Message:
    return Message(benchmark="t", split="dev", history_id="h1", version=i, message_id=f"m{i}",
                   segment_id=None, speaker="user", role="user", text=TEXTS[i - 1],
                   timestamp="2026-03-01", timestamp_raw=None)


def task(n: int, question: str, version: int) -> ReadTask:
    return ReadTask(benchmark="t", split="dev", history_id="h1", read_id=f"q{n}@{version}",
                    task_id=f"q{n}", version=version, kind="question", question=question,
                    state_schema=None, asked_at="2026-03-10", asked_at_raw=None)


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def embed(texts, context):
            self.calls.append((context.call_type, context.trigger, len(texts)))
            return [fake_embed(t) for t in texts]
        self.embed = embed
        experiment = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        self.conditions = [probe.Condition.from_dict(n, c)
                           for n, c in experiment["conditions"].items()]
        self.base = RetrievalConfig.load(REPO_ROOT / experiment["retrieval_config"])
        self.messages = [msg(i) for i in range(1, 10)]
        self.tasks = [task(1, "Where do I live?", 9), task(2, "Where do I live?", 2),
                      task(3, "What soup did we have?", 9)]

    def run_probe(self, graph):
        return probe.probe_history(
            "h1", self.messages, self.tasks, base=self.base, conditions=self.conditions,
            cutoffs=[1, 3, 5], depth=5, embed=self.embed, embed_batch=4, graph=graph,
            planner=Planner(PlannerConfig()) if graph else None, benchmark="t")

    def test_text_only(self):
        rows = self.run_probe(None)
        self.assertEqual(len(rows), 3)
        writes = [c for c in self.calls if c[1] == "write"]
        self.assertEqual([n for *_, n in writes], [4, 4, 1])  # batches of 4 messages
        self.assertEqual(sum(1 for c in self.calls if c[1] == "read"), 3)
        for row in rows:
            self.assertFalse(row["graph_available"])
            self.assertNotIn("graph", row["rankings"])
            self.assertNotIn("graph", row["conditions"])  # graph alone needs a graph
            for name, by_cut in row["conditions"].items():
                for cut, entry in by_cut.items():
                    self.assertLessEqual(len(entry["ids"]), int(cut))
                    versions = [int(e[1:]) for e in entry["ids"]]
                    self.assertTrue(all(v <= row["version"] for v in versions), name)
        early = rows[1]
        self.assertTrue(all(len(e["ids"]) <= 2 for c in early["conditions"].values()
                            for e in c.values()))
        # total fixed: with enough messages every fused condition fills each cut-off.
        for name in ("rrf-all", "rrf-no-bm25", "rrf-no-dense", "rrf-no-graph", "bm25", "dense"):
            self.assertEqual(len(rows[0]["conditions"][name]["5"]["ids"]), 5, name)

    def test_graph_channel_and_recall(self):
        graph = probe.GoldGraph(build_store(), PREDICATES, ENTITIES)
        rows = self.run_probe(graph)
        first = rows[0]
        self.assertTrue(first["graph_available"])
        self.assertEqual(first["plan"]["route"], "rule")
        self.assertEqual(first["rankings"]["graph"][0][0], "m3")
        self.assertEqual(first["conditions"]["graph"]["1"]["ids"], ["m3"])
        self.assertEqual(rows[1]["conditions"]["graph"]["1"]["ids"], ["m1"])  # read at v2
        self.assertFalse(rows[2]["graph_available"])  # no rule, no LLM: fallback
        self.assertEqual(rows[2]["plan"]["route"], "fallback")
        self.assertEqual(rows[2]["conditions"]["graph"]["5"]["ids"], [])
        json.dumps(rows)  # the records are JSON

        gold_rows = [
            {"task_id": "q1", "history_id": "h1", "annotation": "a", "evidence_ids": ["m3"],
             "labels": {"type": "current"}},
            {"task_id": "q2", "history_id": "h1", "annotation": "a",
             "evidence_ids": ["m1#char=0,4", "m99"], "labels": {"type": "current"}},
            {"task_id": "q3", "history_id": "h1", "annotation": "a", "evidence_ids": [],
             "labels": {"type": "other"}}]
        gold = metric.gold_sets(gold_rows, [m.to_record() for m in self.messages])
        self.assertEqual(gold["q2"]["evidence"], {"m1"})
        self.assertEqual(gold["q2"]["unresolved"], 1)
        result = metric.score(rows, gold, ["type"])
        cell = result["conditions"]["graph"]["1"]
        self.assertEqual((cell["recall"], cell["full"], cell["hit"]), (1.0, 1.0, 1.0))
        self.assertEqual((cell["n_total"], cell["n_scored"], cell["n_excluded"]), (3, 2, 1))
        self.assertEqual(result["n_gold_unresolved"], 1)
        self.assertIn("type=current", result["strata"])

    def test_recall_definitions(self):
        rows = [{"task_id": "t", "version": 5,
                 "conditions": {"c": {"2": {"ids": ["a", "x"]}}}}]
        gold = {"t": {"evidence": {"a", "b"}, "unresolved": 0, "versions": {"a": 1, "b": 9},
                      "labels": {}}}
        cell = metric.score(rows, gold)["conditions"]["c"]["2"]
        self.assertEqual((cell["recall"], cell["full"], cell["hit"]), (0.5, 0.0, 1.0))
        self.assertEqual(metric.score(rows, gold)["n_gold_after_read"], 1)
        with self.assertRaises(ValueError):
            metric.score(rows, {})

    def test_condition_keys(self):
        with self.assertRaises(ValueError):
            probe.Condition.from_dict("x", {"channels": ["bm25"], "depth": 3})

    def test_changeseq_vocabulary(self):
        from grace.eval.datasets.changeseq.template_families import load_family

        family = load_family("train-travel")
        preds, ents = probe.changeseq_vocabulary(
            family, {"companion": "Jonas", "tasks": {"k1": "the train booking A"}})
        names = {p.name for p in preds}
        self.assertIn(family.multi.predicate, names)
        self.assertIn(family.task.catalogue.predicate, names)
        self.assertIn("k1", {e.id for e in ents})
        self.assertIn("Jonas", {e.id for e in ents})


if __name__ == "__main__":
    unittest.main()
