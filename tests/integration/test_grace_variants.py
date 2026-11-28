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

    def components(self, *, views=None, extension=None,
                   channels=("bm25", "graph")) -> Components:
        writer, client = self.writer, self.client

        def default_views(h, v):
            return Views(ViewStore(h.history_id, vocabulary=v), "push_confirm",
                         local_filters=True)
        extra = {"extension": extension} if extension is not None else {}
        return Components(count=lambda t: len(t.split()),
                          extractor=lambda h: llm_writer(writer, client, h),
                          planner=self.planner,
                          retrieval=RetrievalConfig(channels=channels),
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


MOVE = "t027-move"
MOVE_SCRIPT = [{"claims": [
    {"id": "n1", "message": 1, "subject": "user", "predicate": "playsInstrument",
     "object": "piano", "object_type": "entity", "function": "inform", "exclusive": False,
     "quote": "I play the piano"},
    {"message": 1, "subject": "user", "predicate": "livesIn", "object": "Lisbon",
     "object_type": "entity", "function": "inform", "exclusive": True,
     "quote": "I live in Lisbon"},
    {"message": 2, "subject": "user", "predicate": "livesIn", "object": "Porto",
     "object_type": "entity", "function": "offer", "exclusive": True,
     "quote": "you live in Porto"},
    {"message": 3, "subject": "user", "predicate": "livesIn", "object": "Madrid",
     "object_type": "entity", "function": "inform", "exclusive": True,
     "valid_from": "2023-03-01", "quote": "I moved to Madrid"},
    {"message": 4, "subject": "user", "predicate": "livesIn", "object": "Madrid",
     "object_type": "entity", "function": "inform", "exclusive": True,
     "valid_from": "2023-03-01", "quote": "I still live in Madrid"},
    {"message": 4, "subject": "user", "predicate": "likes", "object": "tapas",
     "object_type": "entity", "function": "inform", "exclusive": False,
     "quote": "I like tapas"}],
    "stances": [{"message": 4, "claim": "n1", "function": "inform", "polarity": "negative",
                 "ends": "change", "valid_until": "2023-06-01",
                 "quote": "stopped playing the piano"}]}]


def move_messages():
    from tests.integration.writer_fixture import message
    return [message(MOVE, 1, "user", "I live in Lisbon and I play the piano.",
                    timestamp="2023-01-01T10:00:00"),
            message(MOVE, 2, "assistant", "So you live in Porto?",
                    timestamp="2023-01-01T10:01:00"),
            message(MOVE, 3, "user", "No. I moved to Madrid in March.",
                    timestamp="2023-04-01T10:00:00"),
            message(MOVE, 4, "user", "I stopped playing the piano in June. I still live in "
                    "Madrid, and I like tapas.", timestamp="2023-07-01T10:00:00")]


class WriteTimeEquivalenceTest(unittest.TestCase):
    """Main config (supersessions committed at write) and append-only (derived at read) give the
    same supersessions at every version: exclusive replacement without correction, an offer
    against a statement (conflict under the guard), an ending stance with a valid end, several
    attributions in one version, a correction (city script), guard on and off."""

    @staticmethod
    def key(s):
        return (s.claim_id, str(s.kind), s.valid_end, s.replacing_claim_id, s.version)

    def run_pair(self, script, messages, guard: bool, flush_first: bool = False):
        out = []
        for append_only in (False, True):
            rig = Rig(self, json.loads(json.dumps(script)))
            rig.messages, rig.info = messages, history_info(messages[0].history_id, messages)
            rig.writer = WriterConfig(guard=guard)
            extension = (registry.load_component("query-time-resolution")(writer=rig.writer)
                         if append_only else None)
            engine = GraceEngine(rig.components(views=lambda h, v: NoViews(),
                                                extension=extension))
            engine.open(rig.info)
            for m in messages:
                engine.write(m)
                if flush_first and m.version == 1:
                    engine.updater.flush(1)  # the city script's first unit is message 1
            engine.updater.finish()
            self.assertFalse(rig.transport.script)
            per_version = {}
            for v in range(1, engine.version + 1):
                graph = engine.extension.read_graph(engine.store, v)
                per_version[v] = sorted(self.key(s)
                                        for s in graph.state(v).supersessions.values())
            out.append((per_version, sorted(engine.store.state(engine.version).claims)))
        return out

    def test_same_supersessions_per_version(self):
        cases = [(MOVE_SCRIPT, move_messages(), False), (WRITER_SCRIPT, city_messages(), True)]
        for (script, messages, flush), guard in [(c, g) for c in cases for g in (True, False)]:
            with self.subTest(history=messages[0].history_id, guard=guard):
                (main, main_claims), (deferred, deferred_claims) = self.run_pair(
                    script, messages, guard, flush)
                self.assertEqual(main_claims, deferred_claims)
                self.assertEqual(main, deferred)
        (main, _), _ = self.run_pair(MOVE_SCRIPT, move_messages(), True)
        kinds = {(k[1], k[2] is not None, k[3] is None) for k in main[4]}
        self.assertIn(("change", True, False), kinds)   # Lisbon -> Madrid, valid end 2023-03-01
        self.assertIn(("change", True, True), kinds)    # piano ended, valid end 2023-06-01
        (loose, _), _ = self.run_pair(MOVE_SCRIPT, move_messages(), False)
        self.assertGreater(len(loose[4]), len(main[4]))  # guard off: the offer supersedes too


class DeferredNotesTest(unittest.TestCase):
    def test_a_rejected_change_set_leaves_no_hint(self):
        from unittest import mock

        from grace.context.pipeline.update import updater as updater_module
        real = updater_module.commit_version

        def reject_version_3(store, builder, *, validate):
            if builder.version == 3:
                builder.claims.clear()
                builder.attributions.clear()
                builder.evidence.clear()
                cs, _ = real(store, builder, validate=validate)
                return cs, "CommitError: rejected for the test"
            return real(store, builder, validate=validate)

        rig = Rig(self, json.loads(json.dumps(MOVE_SCRIPT)))
        rig.messages, rig.info = move_messages(), history_info(MOVE, move_messages())
        factory = registry.load_component("query-time-resolution")(writer=rig.writer)
        engine = GraceEngine(rig.components(views=lambda h, v: NoViews(), extension=factory))
        with mock.patch.object(updater_module, "commit_version", reject_version_3):
            engine.open(rig.info)
            for m in rig.messages:
                engine.write(m)
            engine.updater.finish()
        stored = set(engine.store.state(engine.version).claims)
        self.assertTrue(set(engine.extension.deferred.claims) <= stored)
        self.assertFalse(any(c.startswith("c3.") for c in engine.extension.deferred.claims))
        log = engine.extension.deferred
        log.note_claim("c1.1", exclusive=False)          # the same inputs again: accepted
        with self.assertRaises(ValueError):
            log.note_claim("c1.1", exclusive=True)       # other inputs: refused


HISTORY_SCRIPT = [
    {"entries": [{"message": 1, "slot": "person.location", "subject": "user", "value": "Lisbon",
                  "function": "inform", "valid_from": "2019-01-01"},
                 {"message": 2, "slot": "person.location", "subject": "user", "value": "Porto",
                  "function": "inform", "valid_from": "2022-03-01"}]}]


class WindowPlanner:
    """A historical plan with the window "in 2021" ("where did I live in 2021?")."""

    def plan(self, ctx):
        from grace.context.pipeline.query.compile import compile_query
        from grace.context.pipeline.query.grammar import parse
        from grace.context.pipeline.query.planner import Plan
        from grace.context.pipeline.query.timeexpr import Window
        q = parse("SELECT ?x WHERE { (user, livesIn, ?x) } AT(known=r, state=historical)")
        return Plan(ctx.read_id, "llm", query=q, compiled=compile_query(q, "rdf11"),
                    window=Window("in 2021", "2021-01-01", "2022-01-01", False),
                    variables=(("?x", "where the user lived in 2021"),))


class SlotTableTest(unittest.TestCase):
    def build(self, rig, channels=("bm25", "graph"), **options):
        factory = registry.load_component("slot-table")(writer=rig.writer, client=rig.client,
                                                        **options)
        return rig.components(views=lambda h, v: NoViews(), extension=factory,
                              channels=channels)

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

    def test_time_factor_where_did_i_live_in_2021(self):
        from tests.integration.writer_fixture import message
        messages = [message("t027-hist", 1, "user", "I have lived in Lisbon since 2019.",
                            timestamp="2021-06-01T10:00:00"),
                    message("t027-hist", 2, "user", "I moved to Porto in March 2022.",
                            timestamp="2022-04-01T10:00:00")]
        texts = {}
        for time in ("bitemporal", "single"):
            rig = Rig(self, json.loads(json.dumps(HISTORY_SCRIPT)))
            rig.messages, rig.info = messages, history_info("t027-hist", messages)
            rig.planner = WindowPlanner()
            # Graph channel only: the raw messages would otherwise cover the same evidence and
            # the assembler skips an item that adds no new message.
            engine = GraceEngine(self.build(rig, channels=("graph",), time=time))
            engine.open(rig.info)
            for m in messages:
                engine.write(m)
            task = api.ReadTask("fixture", "dev", "t027-hist", "q@2", "q", 2, "question",
                                "Where did I live in 2021?", None, None, None)
            texts[time] = engine.read(task, 1024).context.text
        self.assertIn("person.location = Lisbon", texts["bitemporal"])
        self.assertNotIn("person.location = Porto", texts["bitemporal"])  # outside the window
        self.assertNotIn("person.location = Lisbon", texts["single"])     # no past state
        self.assertIn("person.location = Porto", texts["single"])

    def test_adapter_records_real_statuses_and_restore_checks_the_arm(self):
        rig = Rig(self, ["not json"])
        memory = registry.load_component("slot-table")(writer=rig.writer,
                                                       client=rig.client)(rig.info)
        from grace.context.pipeline.update.candidates import Candidates
        from grace.context.pipeline.update.extract import WriterInput
        request = WriterInput(CITY, (rig.messages[0],), (), Candidates((), (), ()), ("user",))
        extraction = memory.extractor(None).extract(request)
        self.assertEqual((extraction.status, extraction.statuses),
                         ("invalid_output", ("invalid_output",)))
        directory = rig.tmp / "slots"
        memory.save(directory)
        memory.restore(directory)  # same arm
        other = registry.load_component("slot-table")(writer=rig.writer, client=rig.client,
                                                      guard=False)(rig.info)
        with self.assertRaises(ValueError):
            other.restore(directory)

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
