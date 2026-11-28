"""GRACE variants of T027, built by injecting components into GraceEngine: template
serialisation, append-only memory with query-time resolution, and the ablation-B slot table."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grace.config import registry
from grace.config.paths import REPO_ROOT
from grace.context import api
from grace.context.engine import Components, GraceEngine, NoViews, ObservedClient, Views
from grace.context.pipeline.assembly.assemble import AssemblyConfig
from grace.context.pipeline.retrieval.retrieve import RetrievalConfig
from grace.context.pipeline.update.updater import WriterConfig, llm_writer
from grace.context.views.store import ViewStore
from grace.context.views.template_families import load_view_config
from grace.eval.runner.harness.drive import build_engine, load_engine_config
from grace.eval.runner.harness.models import FakeBackend, RecordingModel, fake_responder
from grace.llm.client import ChatClient, Endpoint
from grace.llm.records import CallLedger
from tests.integration.test_grace_engine import CITY, WRITER_SCRIPT, ScriptedPlanner, city_messages
from tests.integration.writer_fixture import ScriptedTransport, history_info
from tests.llm.fakes import WordCounter

ENGINES = REPO_ROOT / "configs" / "engines"
VARIANTS = ("grace-template", "grace-append-only", "grace-slots", "grace-slots-noguard",
            "grace-slots-single", "grace-slots-noguard-single")
LIVES_IN = "SELECT ?x WHERE { (user, livesIn, ?x) }"
CURRENT_VIEW = ("SELECT ?value WHERE { (user, livesIn, ?value) [_, inform] AS ?c "
                'FILTER(end(?c) > "9999-12-31"^^date) } LATEST BY version OF ?c '
                "AT(known=r, state=current)")   # the query of the `current` family's binding
SLOT_SCRIPT = [
    {"entries": [{"message": 1, "slot": "person.location", "subject": "user", "value": "Paris",
                  "function": "inform", "valid_from": "2023-05-01"}]},
    {"entries": [{"message": 1, "slot": "person.location", "subject": "user", "value": "Berlin",
                  "function": "correct", "correction": True},
                 {"message": 2, "slot": "person.location", "subject": "user",
                  "value": "Hamburg", "function": "offer"},
                 {"message": 3, "slot": "person.preference", "subject": "user",
                  "value": "coffee", "function": "inform"}]},
]


class Rig:
    """A scripted writer client and planner over the city history of the T026 engine test."""

    def __init__(self, test: unittest.TestCase, script):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.messages = city_messages()
        self.info = history_info(CITY, self.messages)
        self.ledger = CallLedger(self.tmp / "calls.jsonl", "T027-20261128T000000Z-0001")
        self.transport = ScriptedTransport(script)
        client = ChatClient(Endpoint("http://fake/v1", "writer", "writer@1"), self.ledger,
                            WordCounter(), max_attempts=1, backoff_s=0.0,
                            transport=self.transport, sleep=lambda s: None)
        self.client = ObservedClient(client, None)
        self.writer = WriterConfig()
        self.planner = ScriptedPlanner()

    def components(self, *, views=None, extension=None) -> Components:
        writer, client = self.writer, self.client

        def default_views(h, v):
            return Views(ViewStore(h.history_id, vocabulary=v), "push_confirm",
                         local_filters=True)
        extra = {"extension": extension} if extension is not None else {}
        return Components(count=lambda t: len(t.split()),
                          extractor=lambda h: llm_writer(writer, client, h),
                          planner=self.planner,
                          retrieval=RetrievalConfig(channels=("bm25", "graph")),
                          assembly=AssemblyConfig(), writer=writer,
                          views=views or default_views, **extra)

    def task(self, version: int) -> api.ReadTask:
        return api.ReadTask("fixture", "dev", CITY, f"q@{version}", "q", version, "question",
                            "Where do I live?", None, None, None)

    def ingest(self, engine: GraceEngine) -> GraceEngine:
        engine.open(self.info)
        engine.write(self.messages[0])
        engine.read(self.task(1), 256)
        engine.end_read(self.task(1))
        for m in self.messages[1:]:
            engine.write(m)
        engine.updater.finish()
        return engine

    def snapshot(self, engine: GraceEngine, components: Components) -> GraceEngine:
        directory = self.tmp / "snapshot"
        directory.mkdir()
        engine.save(directory)
        again = GraceEngine(components)
        again.restore(directory)
        return again


class ConfigTest(unittest.TestCase):
    def test_variant_configs_build_through_the_registry_with_their_components(self):
        self.assertEqual(set(registry.COMPONENTS),
                         {"serialised-views", "query-time-resolution", "slot-table"})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ledger = CallLedger(Path(tmp.name) / "calls.jsonl", "T027-20261128T000000Z-0002")
        model = RecordingModel(FakeBackend(fake_responder), ledger)
        for name in VARIANTS:
            with self.subTest(config=name):
                config = load_engine_config(ENGINES / f"{name}.yaml")
                engine = build_engine(config, model, allow_no_client=True)
                self.assertIsInstance(engine, GraceEngine)
                ext = engine.c.extension(history_info(CITY, city_messages()))
                if name == "grace-template":
                    views = engine.c.views(history_info(CITY, city_messages()), None)
                    self.assertEqual(type(views).__name__, "SerialisedViews")
                elif name == "grace-append-only":
                    self.assertIsNotNone(ext.deferred)
                else:
                    self.assertEqual((ext.table.guard, ext.table.time),
                                     ("noguard" not in name, "single" if "single" in name
                                      else "bitemporal"))
        with self.assertRaises(ValueError):
            GraceEngine.from_port(model, allow_no_client=True,
                                  components={"planner": {"factory": "slot-table"}})


class TemplateSerialisationTest(unittest.TestCase):
    def test_view_built_at_the_read_and_never_stored(self):
        rig = Rig(self, WRITER_SCRIPT)
        make = registry.load_component("serialised-views")(
            writer=rig.writer, client=rig.client,
            view_config=load_view_config(REPO_ROOT / "configs/views/default.yaml"))
        engine = rig.ingest(GraceEngine(rig.components(views=make)))
        rig.planner.query = CURRENT_VIEW
        result = engine.read(rig.task(4), 256)
        self.assertEqual(result.trace.view_hits, ("current:user:livesIn",))
        self.assertIn("Currently, user lives in Berlin.", result.context.text)
        self.assertEqual(len(engine.views.events), 1)   # one template build, at this read
        self.assertFalse(engine.views.events[0].call_ids)  # no rendering call
        self.assertEqual(engine.views.save(rig.tmp), [])  # nothing cached


class QueryTimeResolutionTest(unittest.TestCase):
    def build(self, rig):
        factory = registry.load_component("query-time-resolution")(writer=rig.writer)
        return rig.components(views=lambda h, v: NoViews(), extension=factory)

    def test_no_supersession_stored_conflict_resolved_at_each_read(self):
        rig = Rig(self, WRITER_SCRIPT)
        engine = rig.ingest(GraceEngine(self.build(rig)))
        self.assertEqual(len(engine.store.state(4).supersessions), 0)
        log = engine.extension.deferred
        self.assertEqual(sum(h.correction for h in log.claims.values()), 1)
        graph = engine.extension.read_graph(engine.store, 4)
        self.assertEqual(len(graph.state(4).supersessions), 1)
        self.assertIsNot(graph, engine.extension.read_graph(engine.store, 4))  # not cached
        rig.planner.query = LIVES_IN
        result = engine.read(rig.task(4), 256)
        self.assertIn("x = Berlin", result.context.text)
        self.assertNotIn("x = Paris", result.context.text)
        engine.end_read(rig.task(4))
        rig.planner.query = ("SELECT ?x WHERE { (user, livesIn, ?x) } "
                             "AT(known=1, state=current)")
        past = engine.read(rig.task(4), 256)
        self.assertIn("x = Paris", past.context.text)

    def test_save_and_restore(self):
        rig = Rig(self, WRITER_SCRIPT)
        engine = rig.ingest(GraceEngine(self.build(rig)))
        rig.planner.query = LIVES_IN
        before = engine.read(rig.task(4), 256)
        engine.end_read(rig.task(4))
        again = rig.snapshot(engine, self.build(rig))
        self.assertEqual(again.extension.deferred, engine.extension.deferred)
        self.assertIs(again.updater.deferred, again.extension.deferred)
        self.assertEqual(again.read(rig.task(4), 256).context.text, before.context.text)


class SlotTableTest(unittest.TestCase):
    def build(self, rig, **options):
        factory = registry.load_component("slot-table")(writer=rig.writer, client=rig.client,
                                                        **options)
        return rig.components(views=lambda h, v: NoViews(), extension=factory)

    def read_text(self, **options) -> tuple[GraceEngine, str]:
        rig = Rig(self, json.loads(json.dumps(SLOT_SCRIPT)))
        engine = rig.ingest(GraceEngine(self.build(rig, **options)))
        return engine, engine.read(rig.task(4), 1024).context.text

    def test_slot_values_are_state_items_and_the_graph_stays_empty(self):
        engine, text = self.read_text()
        self.assertEqual(len(engine.store.state(4).claims), 0)
        self.assertEqual(len(engine.extension.table.rows), 4)
        self.assertIn("person.location = Berlin", text)
        self.assertIn("person.location = Hamburg", text)   # an offer: kept beside, guard on
        self.assertNotIn("person.location = Paris", text)  # corrected
        calls = [c for c in engine.extension.writer.client.ledger.records]
        self.assertTrue(all(c.call_type == "extract" and c.category == "W" for c in calls))

    def test_guard_off_lets_the_offer_supersede(self):
        _, text = self.read_text(guard=False)
        self.assertIn("person.location = Hamburg", text)
        self.assertNotIn("person.location = Berlin", text)

    def test_no_look_ahead_and_save_restore(self):
        rig = Rig(self, json.loads(json.dumps(SLOT_SCRIPT)))
        engine = GraceEngine(self.build(rig))
        engine.open(rig.info)
        engine.write(rig.messages[0])
        early = engine.read(rig.task(1), 256)
        self.assertIn("Paris", early.context.text)
        self.assertTrue(set(early.context.context_ids) <= {rig.messages[0].message_id}
                        | {f.fragment_id for f in early.context.fragments})
        engine.end_read(rig.task(1))
        for m in rig.messages[1:]:
            engine.write(m)
        engine.updater.finish()
        before = engine.read(rig.task(4), 1024)
        engine.end_read(rig.task(4))
        again = rig.snapshot(engine, self.build(rig))
        self.assertEqual(again.extension.table.rows, engine.extension.table.rows)
        self.assertEqual(again.read(rig.task(4), 1024).context.text, before.context.text)


if __name__ == "__main__":
    unittest.main()
