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
        engine = build_engine(load_engine_config(CONFIG), model, allow_no_client=True)
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

    def test_no_client_fails_unless_allowed(self):
        with self.assertRaises(ValueError):
            build_engine(load_engine_config(CONFIG), self.model())
        settings = GraceEngine.resolved_settings(load_engine_config(CONFIG)["params"], 7,
                                                 allow_no_client=True)
        self.assertEqual(settings["writer_decoding"]["seed"], 7)
        self.assertEqual(settings["planner_decoding"]["seed"], 7)
        self.assertTrue(settings["allow_no_client"])

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
            self.assertEqual(len(r.trace.call_ids), len(set(r.trace.call_ids)))
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


# ---------------------------------------------------------------------------------------------
# A scripted writer and planner: a graph, a supersession, a vocabulary change and views

CITY = "t026-city"
WRITER_SCRIPT = [
    {"claims": [{"message": 1, "subject": "user", "predicate": "livesIn", "object": "Paris",
                 "object_type": "entity", "function": "inform", "exclusive": True,
                 "quote": "live in Paris"}], "stances": []},
    {"claims": [{"message": 1, "subject": "user", "predicate": "livesIn", "object": "Berlin",
                 "object_type": "entity", "function": "inform", "exclusive": True,
                 "correction": True, "quote": "live in Berlin"},
                {"message": 3, "subject": "user", "predicate": "prefersDrink",
                 "object": "coffee", "object_type": "entity", "function": "inform",
                 "exclusive": True, "quote": "I prefer coffee"}], "stances": []},
]


def city_messages():
    from tests.integration.writer_fixture import message
    return [message(CITY, 1, "user", "I live in Paris now.", timestamp="2023-05-01T10:00:00"),
            message(CITY, 2, "user", "Correction: I actually live in Berlin, not Paris.",
                    timestamp="2023-05-02T10:00:00"),
            message(CITY, 3, "assistant", "Noted, Berlin. Tea or coffee?",
                    timestamp="2023-05-02T10:01:00"),
            message(CITY, 4, "user", "I prefer coffee.", timestamp="2023-05-02T10:02:00")]


class ScriptedPlanner:
    """Returns a fallback plan, or a compiled plan of `query` (an IR text or a parsed query)."""

    def __init__(self):
        self.query = None

    def plan(self, ctx):
        from grace.context.pipeline.query.compile import compile_query
        if self.query is None:
            return Plan(ctx.read_id, "fallback")
        q = parse(self.query) if isinstance(self.query, str) else self.query
        return Plan(ctx.read_id, "llm", query=q, compiled=compile_query(q, "rdf11"),
                    variables=(("?x", "where the user lives"),))


class ScriptedEngineTest(unittest.TestCase):
    def setUp(self):
        from grace.context.engine import Components, Views
        from grace.context.pipeline.assembly.assemble import AssemblyConfig
        from grace.context.pipeline.retrieval.retrieve import RetrievalConfig
        from grace.context.pipeline.update.updater import WriterConfig, llm_writer
        from grace.context.views.store import ViewStore
        from grace.llm.client import ChatClient, Endpoint
        from tests.integration.writer_fixture import ScriptedTransport, history_info
        from tests.llm.fakes import WordCounter

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.messages = city_messages()
        self.info = history_info(CITY, self.messages)
        ledger = CallLedger(self.tmp / "calls.jsonl", "T026-20261128T000000Z-0001")
        self.transport = ScriptedTransport(WRITER_SCRIPT)
        client = ChatClient(Endpoint("http://fake/v1", "writer", "writer@1"), ledger,
                            WordCounter(), max_attempts=1, backoff_s=0.0,
                            transport=self.transport, sleep=lambda s: None)
        self.observed: list[str] = []
        from grace.context.engine import ObservedClient
        observed_client = ObservedClient(client, self.observed.extend)
        writer = WriterConfig()
        self.planner = ScriptedPlanner()

        def components():
            return Components(
                count=lambda t: len(t.split()),
                extractor=lambda h: llm_writer(writer, observed_client, h),
                planner=self.planner, retrieval=RetrievalConfig(channels=("bm25", "graph")),
                assembly=AssemblyConfig(), writer=writer,
                views=lambda h, v: Views(ViewStore(h.history_id, vocabulary=v),
                                         "push_confirm", local_filters=True))
        self.components = components
        self.engine = GraceEngine(components())
        self.engine.open(self.info)

    def task(self, version: int) -> api.ReadTask:
        return api.ReadTask("fixture", "dev", CITY, f"q@{version}", "q", version, "question",
                            "Where do I live?", None, None, None)

    def ingest(self):
        e = self.engine
        e.write(self.messages[0])
        self.assertEqual(e.store.head, 0)  # the unit (segment of 8) is still open
        first = e.read(self.task(1), 256)
        e.end_read(self.task(1))
        self.assertEqual(e.store.head, 1)  # flushed before the read (write cost W)
        self.assertEqual(len(first.trace.call_ids), 1)
        for m in self.messages[1:]:
            e.write(m)
        e.updater.finish()
        return first

    def test_flush_vocabulary_views_and_sentinel_audit(self):
        self.ingest()
        e = self.engine
        self.assertEqual(e.store.head, 4)
        self.assertNotEqual(e.updater.vocabulary.version, "v1")  # prefersDrink is local
        views = {v.view_id: v for v in e.views.store.views()}
        self.assertIn("current:user:livesIn", views)
        self.assertTrue(any("I live in Paris now." in t for t in self.observed))
        self.planner.query = views["current:user:livesIn"].query
        result = e.read(self.task(4), 256)
        self.assertEqual(result.trace.view_hits, ("current:user:livesIn",))
        self.assertIn("Berlin", result.context.text)
        self.assertTrue(result.trace.staleness_decisions)  # vocabulary change: full rebuild

    def test_a_fallback_plan_issues_no_query_and_lists_no_open_item(self):
        # E013 decisions 3 and 4: for a fallback plan the demand is the request itself; the
        # assembler neither re-queries it nor lists it as "not found in memory".
        self.ingest()
        task = api.ReadTask("fixture", "dev", CITY, "qb@4", "qb", 4, "question",
                            "What colour is the bicycle?", None, None, None)
        result = self.engine.read(task, 256)
        assembly = self.engine._reads["qb@4"].assembly
        self.assertEqual(self.engine._reads["qb@4"].plan.route, "fallback")
        self.assertTrue(assembly.demand.fallback)
        self.assertEqual([v.name for v in assembly.open], ["answer"])
        self.assertIsNone(assembly.expansion)
        self.assertFalse(result.trace.retrieval_used)
        self.assertEqual(result.trace.expansions_used, 0)
        self.assertNotIn("Open items", result.context.text)

    def test_time_travel_read_keeps_the_retired_answer(self):
        self.ingest()
        e = self.engine
        state = e.store.state(4)
        self.assertEqual(len(state.supersessions), 1)
        self.planner.query = "SELECT ?x WHERE { (user, livesIn, ?x) } AT(known=1, state=current)"
        result = e.read(self.task(4), 256)
        claims = [i for i in e._reads["q@4"].items if i.kind == "claim"]
        self.assertEqual([(i.version, i.retired) for i in claims], [(1, 2)])
        self.assertIn("x = Paris", result.context.text)
        self.assertFalse(e._reads["q@4"].constraints.current_only)

    def test_save_and_restore_with_a_graph_and_views(self):
        self.ingest()
        e = self.engine
        self.planner.query = e.views.store.views()[0].query
        before = e.read(self.task(4), 256)
        e.end_read(self.task(4))
        directory = self.tmp / "snapshot"
        directory.mkdir()
        e.save(directory)
        again = GraceEngine(self.components())
        again.restore(directory)
        self.assertEqual(again.store.head, 4)
        self.assertEqual(len(again.views.store.views()), len(e.views.store.views()))
        self.assertEqual(again.updater.vocabulary.version, e.updater.vocabulary.version)
        after = again.read(self.task(4), 256)
        self.assertEqual(after.context.text, before.context.text)
        self.assertEqual(after.trace.view_hits, before.trace.view_hits)
        self.assertFalse(self.transport.script)  # the restored engine made no writer call


if __name__ == "__main__":
    unittest.main()
