"""Read-time view content sources of ablation C on extracted graphs (E010, `views/readtime.py`)."""

import json
import unittest

from grace.context import api
from grace.context.memory.graph.vocabulary import load_vocabulary
from grace.context.pipeline.assembly import layout
from grace.context.pipeline.assembly.assemble import AssemblyConfig
from grace.context.pipeline.assembly.items import Item
from grace.context.pipeline.query.compile import compile_query
from grace.context.pipeline.query.execute import execute as execute_query
from grace.context.pipeline.query.grammar import parse
from grace.context.pipeline.query.planner import Plan
from grace.context.views import readtime
from grace.context.views.readtime import ReadTimeViews
from grace.context.views.store import ViewStore
from grace.context.views.template_families import ViewConfig
from grace.llm.client import ChatClient, Endpoint
from grace.llm.records import CallLedger
from tests.integration.views_fixture import HEAD, HISTORY, FakeTransport, build_store, completion
from tests.llm.fakes import WordCounter

VOCABULARY = load_vocabulary()


def client(tmp, transport):
    ledger = CallLedger(tmp / "calls.jsonl", "run")
    return ChatClient(Endpoint("http://fake.invalid/v1", "fake", "fake@E010"), ledger,
                      WordCounter(), max_attempts=1, transport=transport, sleep=lambda s: None)


def message(mid: str) -> api.Message:
    version = int(mid[1:])
    return api.Message("b", "dev", HISTORY, version, mid, None, "user", "user",
                       f"text of {mid}", None, None)


def plan_of(query):
    return Plan("r", "llm", query=query, compiled=compile_query(query, "rdf11"))


class Sink:
    def __enter__(self):
        self.records = []
        readtime.EVENT_SINK = self.records.append
        return self

    def __exit__(self, *exc):
        readtime.EVENT_SINK = None


class ReadTimeViewsTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.graph = build_store()
        self.reference = ViewStore(HISTORY, config=ViewConfig(), vocabulary=VOCABULARY)
        self.reference.materialise(self.graph, HEAD)

    def tearDown(self):
        self._tmp.cleanup()

    def present(self, views, view):
        plan = plan_of(view.query)
        result = execute_query(plan.compiled, self.graph, HEAD)
        return views.present(plan, result, self.graph, HEAD, "r", message), result

    def test_template_hit_equals_the_resident_view(self):
        views = ReadTimeViews(HISTORY, ViewConfig(), VOCABULARY, "template")
        with Sink() as sink:
            for view in self.reference.views():
                with self.subTest(view=view.view_id):
                    shown, result = self.present(views, view)
                    self.assertEqual(shown.view_id, view.view_id)
                    self.assertEqual(sorted(t for t, _, _ in shown.sentences),
                                     sorted(s.text for s in view.sentences))
                    self.assertEqual(shown.call_ids, ())
                    for _, rows, evidence in shown.sentences:
                        self.assertTrue(rows)
                        self.assertTrue(evidence)
        self.assertEqual(len(sink.records), len(self.reference.views()))
        self.assertTrue(all(r["view_id"] for r in sink.records))

    def test_a_query_outside_the_families_is_a_temporary_view(self):
        from grace.context.pipeline.query.grammar import to_text
        views = ReadTimeViews(HISTORY, ViewConfig(), VOCABULARY, "template")
        view = next(v for v in self.reference.views() if v.view_id == "list:lina:maintains")
        text = to_text(view.query)
        for changed, kind in ((text.replace("?value", "?thing"), "variable_names"),
                              (text.replace("[_, inform]", "[user, inform]"), "attribution")):
            with self.subTest(kind=kind):
                plan = plan_of(parse(changed))
                result = execute_query(plan.compiled, self.graph, HEAD)
                with Sink() as sink:
                    shown = views.present(plan, result, self.graph, HEAD, "r", message)
                self.assertIsNone(shown.view_id)
                record = sink.records[0]
                self.assertIsNone(record["view_id"])
                self.assertIn(view.view_id, record["near"])
                self.assertEqual(record["near_class"], kind)
                self.assertEqual(record["near_query"], text)

    def test_llm_source_renders_and_books_calls(self):
        views = ReadTimeViews(HISTORY, ViewConfig(), VOCABULARY, "llm",
                              client(self.tmp, FakeTransport()))
        view = self.reference.views()[0]
        shown, _ = self.present(views, view)
        self.assertEqual(shown.view_id, view.view_id)
        self.assertTrue(shown.call_ids)

    def test_rewrite_drops_foreign_sources_and_counts_them(self):
        view = next(v for v in self.reference.views() if v.rows and not v.is_count)
        given = sorted({e.split("#")[0] for r in view.rows for e in r.evidence})

        def transport(url, payload, headers, timeout):
            return completion(json.dumps({"sentences": [
                {"sources": [given[0], "m999"], "text": "A rewritten fact."},
                {"sources": ["m998"], "text": "A fact from nowhere."}]}))
        views = ReadTimeViews(HISTORY, ViewConfig(), VOCABULARY, "rewrite",
                              client(self.tmp, transport))
        with Sink() as sink:
            shown, _ = self.present(views, view)
        self.assertEqual([(t, r, e) for t, r, e in shown.sentences],
                         [("A rewritten fact.", (), (given[0],))])
        record = sink.records[0]
        self.assertEqual(record["wrong_citations"], 2)
        self.assertEqual(record["rewrite_sources"], 3)
        self.assertEqual(record["dropped_sentences"], 1)
        self.assertEqual(record["fallback_units"], 0)

    def test_rewrite_falls_back_to_the_template_when_nothing_is_kept(self):
        view = next(v for v in self.reference.views() if v.rows and not v.is_count)

        def transport(url, payload, headers, timeout):
            return completion(json.dumps({"sentences": [{"sources": ["m999"], "text": "x"}]}))
        views = ReadTimeViews(HISTORY, ViewConfig(), VOCABULARY, "rewrite",
                              client(self.tmp, transport))
        with Sink() as sink:
            shown, _ = self.present(views, view)
        self.assertEqual(sorted(t for t, _, _ in shown.sentences),
                         sorted(s.text for s in view.sentences))
        self.assertEqual(sink.records[0]["fallback_units"], sink.records[0]["units"])

    def test_factory_rejects_unknown_sources(self):
        with self.assertRaises(ValueError):
            readtime.read_time_views(source="summary")
        with self.assertRaises(TypeError):
            readtime.read_time_views(source="template", cache=True)


class StateCitationsTest(unittest.TestCase):
    def test_state_lines_lose_their_message_ids_only(self):
        state = Item("v#1", "view", "Melanie plays the violin.", ("m3#char=0,5",))
        raw = Item("m3", "message", "user: violin", ("m3",), ("m3",))
        self.assertEqual(layout.line(state), "[m3] Melanie plays the violin.")
        self.assertEqual(layout.line(state, False), "Melanie plays the violin.")
        self.assertEqual(layout.line(raw, False), layout.line(raw))
        text = layout.serialise([state, raw], (), False).text
        self.assertNotIn("[m3] Melanie", text)
        frags = layout.fragments(layout.serialise([state], (), False), len)
        self.assertEqual(frags[0].evidence_ids, ("m3",))

    def test_config_key(self):
        config = AssemblyConfig.from_dict({"version": 1, "state_citations": False})
        self.assertFalse(config.state_citations)
        self.assertTrue(AssemblyConfig().state_citations)


if __name__ == "__main__":
    unittest.main()
