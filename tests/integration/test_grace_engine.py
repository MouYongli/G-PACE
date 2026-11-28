"""GraceEngine (T026): built from configs/engines/grace.yaml through the registry, driven by the
shared answering step on the LoCoMo fixture with the deterministic fake backend (no writer LLM,
rule-only planner), plus the read constraints of time-travel queries."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grace.config import registry
from grace.config.paths import REPO_ROOT
from grace.context import api
from grace.context.engine import GraceEngine, _constraints
from grace.context.pipeline.query.grammar import parse
from grace.context.pipeline.query.planner import Plan
from grace.context.pipeline.query.timeexpr import Window
from grace.eval.runner.harness.answer import answer, is_final_call
from grace.eval.runner.harness.drive import build_engine, load_engine_config
from grace.eval.runner.harness.inputs import load_fixture
from grace.eval.runner.harness.models import FakeBackend, RecordingModel, fake_responder
from grace.llm.records import CallLedger

LOCOMO = REPO_ROOT / "tests" / "fixtures" / "benchmarks" / "locomo"
CONFIG = REPO_ROOT / "configs" / "engines" / "grace.yaml"


def task_at(version: int) -> api.ReadTask:
    return api.ReadTask("locomo", "dev", "h", f"q@{version}", "q", version, "question", "x?",
                        None, None, None)


class ConstraintsTest(unittest.TestCase):
    def test_time_travel_reads_keep_retired_items(self):
        q = "SELECT ?x WHERE { (a, p, ?x) }"
        moving = Plan("q@5", "llm", query=parse(q))
        self.assertTrue(_constraints(task_at(5), moving).current_only)
        travel = Plan("q@5", "llm", query=parse(q + " AT(known=2, state=current)"))
        self.assertFalse(_constraints(task_at(5), travel).current_only)
        historical = Plan("q@5", "llm", query=parse(q + " AT(known=r, state=historical)"))
        self.assertFalse(_constraints(task_at(5), historical).current_only)
        windowed = Plan("q@5", "llm", query=parse(q),
                        window=Window("in May", "2023-05-01", "2023-06-01", False))
        self.assertEqual(_constraints(task_at(5), windowed).valid, ("2023-05-01", "2023-06-01"))
        self.assertTrue(_constraints(task_at(5), Plan("q@5", "fallback")).current_only)


class EngineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ledger = CallLedger(self.tmp / "calls.jsonl", "T026-20261128T000000Z-0000")
        self.item = load_fixture(LOCOMO).histories[0]

    def model(self, responder=fake_responder):
        return RecordingModel(FakeBackend(responder), self.ledger)

    def build(self, model) -> GraceEngine:
        engine = build_engine(load_engine_config(CONFIG), model)
        self.assertIsInstance(engine, GraceEngine)
        return engine

    def drive(self, responder, budget):
        model = self.model(responder)
        engine = self.build(model)
        engine.open(self.item.history)
        visible, reads, out = set(), list(self.item.reads), []
        for message in self.item.messages:
            result = engine.write(message)
            self.assertEqual(result.trace.message_ids, (message.message_id,))
            visible.add(message.message_id)
            while reads and reads[0].version == message.version:
                task = reads.pop(0)
                out.append(answer(engine, task, budget, model, visible))
                engine.end_read(task)
        return engine, out

    def test_registry_names_the_engine(self):
        self.assertIs(registry.load_engine("grace"), GraceEngine)

    def test_traces_carry_the_new_fields_and_respect_the_budget(self):
        for budget in (256, 512, 1024, None):
            with self.subTest(budget=budget):
                _, results = self.drive(fake_responder, budget)
                self.assertTrue(results)
                for r in results:
                    record = r.trace.to_record()
                    for key in ("retrieval_used", "utilisation", "expansions_used"):
                        self.assertIn(key, record)
                    if budget is None:
                        self.assertIsNone(record["utilisation"])
                    else:
                        self.assertLessEqual(r.context.tokens, budget)
                        self.assertAlmostEqual(record["utilisation"], r.context.tokens / budget)
                    self.assertLessEqual(record["expansions_used"], 1)
                    self.assertEqual(list(r.trace.included_ids), r.context.context_ids)

    def test_at_most_one_extra_retrieval_per_read(self):
        def always_retrieve(messages):
            if is_final_call(messages):
                return json.dumps({"output": "unknown", "cited_ids": []})
            return json.dumps({"output": "retrieve", "query": "violin lessons"})
        _, results = self.drive(always_retrieve, 256)
        for r in results:
            self.assertEqual(r.output, "unknown")
            if r.retrieve_refused:  # the engine's own query expansion spent the retrieval
                self.assertFalse(r.trace.further_retrieval)
            else:
                self.assertTrue(r.trace.further_retrieval)
            self.assertTrue(r.trace.retrieval_used)
        answers = [c for c in self.ledger.records if c.call_type == "answer"]
        expected = sum(1 if r.retrieve_refused else 2 for r in results)
        self.assertEqual(len(answers), expected)

    def test_save_and_restore_give_the_same_context(self):
        model = self.model()
        engine = self.build(model)
        engine.open(self.item.history)
        for message in self.item.messages:
            engine.write(message)
        task = next(t for t in self.item.reads if t.version == engine.version) \
            if any(t.version == engine.version for t in self.item.reads) else \
            api.ReadTask(**{**self.item.reads[0].__dict__, "version": engine.version,
                            "read_id": f"{self.item.reads[0].task_id}@{engine.version}"})
        before = engine.read(task, 256).context
        directory = self.tmp / "snapshot"
        directory.mkdir()
        files = engine.save(directory)
        self.assertTrue(all(Path(f).exists() for f in files))
        again = self.build(model)
        again.restore(directory)
        self.assertEqual(again.version, engine.version)
        after = again.read(task, 256).context
        self.assertEqual(after.text, before.text)


if __name__ == "__main__":
    unittest.main()
