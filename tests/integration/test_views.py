"""Views on a fixture history (T018; plan 3.4, 5.4).

Acceptance of T018:

- rebuilt views equal a full rebuild on fixtures (`RebuildEqualsFullBuildTest`), in both
  rendering modes and both claim serialisations, maintained at every version and at every third;
- citation repair makes no LLM call, and the ledger shows it (`CitationRepairTest`).

The other tests cover the view contents of the six families, LLM rendering through
`grace.llm.client.ChatClient` with its ledger records, the rendering check and template fallback,
the instantiation threshold, resident versus temporary views, whole-history invalidation and
save/restore.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entities import EntityEquivalence
from grace.context.memory.graph.vocabulary import load_vocabulary
from grace.context.pipeline.query.compile import absolutize
from grace.context.pipeline.query.grammar import parse
from grace.context.views.dependencies import NEGATED, POSITIVE
from grace.context.views.render import PROMPT, LLMRenderer, TemplateRenderer, display
from grace.context.views.store import (
    ADVANCE,
    BUILD,
    CITATION_REPAIR,
    FULL_REBUILD,
    LOCAL_REBUILD,
    ViewStore,
)
from grace.context.views.template_families import ViewConfig, load_view_config
from grace.context.views.view import Lifecycle, ViewError
from grace.llm.client import ChatClient, Endpoint
from grace.llm.prompts import load_pinned
from grace.llm.records import CallLedger, read_calls
from tests.integration.views_fixture import HEAD, HISTORY, FakeTransport, build_store
from tests.llm.fakes import WordCounter

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "configs" / "common" / "prompts.yaml"
VOCABULARY = load_vocabulary()


def llm_renderer(ledger: CallLedger, transport=None, **kw) -> LLMRenderer:
    endpoint = Endpoint("http://fake.invalid/v1", "fake", "fake@T018")
    client = ChatClient(endpoint, ledger, WordCounter(), max_attempts=1,
                        transport=transport or FakeTransport(), sleep=lambda s: None)
    return LLMRenderer(client, load_pinned(PROMPT, REGISTRY), {"temperature": 0.0}, **kw)


def answers(view) -> list[tuple[str, ...]]:
    return [tuple(display(v) for v in r.values) for r in view.rows if not r.aggregate] + \
        [tuple(display(v) for v in r.values) for r in view.rows if r.aggregate]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = CallLedger(Path(self.tmp.name) / "calls.jsonl", "run-t018")

    def store(self, renderer=None, **config) -> ViewStore:
        return ViewStore(HISTORY, renderer or TemplateRenderer(),
                         config=ViewConfig(**config), vocabulary=VOCABULARY)

    def calls(self):
        path = Path(self.tmp.name) / "calls.jsonl"
        return read_calls(path) if path.exists() else []


class RebuildEqualsFullBuildTest(Fixture):
    """Maintained views equal views built from scratch at the same version."""

    def run_sequence(self, mode: str, renderer_kind: str, step: int):
        graph = build_store(mode)
        make = (lambda: TemplateRenderer()) if renderer_kind == "template" else \
            (lambda: llm_renderer(self.ledger))
        incremental = self.store(make())
        actions = set()
        compared = 0
        for r in range(1, HEAD + 1):
            incremental.materialise(graph, r)
            if r % step and r != HEAD:
                continue
            for view in incremental.views():
                if view.cutoff < r:
                    actions.add(incremental.maintain(view.view_id, graph, r).action)
            reference = self.store(make())
            for view in incremental.views():
                full = reference.build(view.binding, graph, r)
                self.assertEqual(view.to_record(), full.to_record(),
                                 f"{view.view_id} at version {r} ({mode}, {renderer_kind})")
                compared += 1
        return actions, compared, incremental

    def test_every_version_and_every_third(self):
        for mode in ("rdf11", "rdf12"):
            for kind in ("template", "llm"):
                for step in (1, 3):
                    with self.subTest(mode=mode, renderer=kind, step=step):
                        actions, compared, _ = self.run_sequence(mode, kind, step)
                        self.assertGreater(compared, 40)
                        self.assertLessEqual({LOCAL_REBUILD, ADVANCE}, actions)
                        if step == 1:
                            self.assertIn(CITATION_REPAIR, actions)

    def test_local_rebuild_renders_only_changed_units(self):
        graph = build_store()
        store = self.store()
        store.materialise(graph, 7)
        view = store.get("list:melanie:playsInstrument")
        self.assertEqual(len(view.sentences), 2)
        violin = next(s for s in view.sentences if "violin" in s.text)
        store.materialise(graph, 10)
        store.maintain("list:lina:maintains", graph, 9)
        event = store.maintain("list:lina:maintains", graph, 10)
        self.assertEqual((event.action, event.units_rendered, event.sentences_kept),
                         (LOCAL_REBUILD, 1, 1))
        # The violin sentence of the melanie list survives a repeated mention unchanged.
        store.maintain("list:melanie:playsInstrument", graph, 8)
        again = next(s for s in store.get("list:melanie:playsInstrument").sentences
                     if "violin" in s.text)
        self.assertEqual(again.text, violin.text)
        self.assertEqual(again.evidence, ("m2", "m8"))


class ContentTest(Fixture):
    """What the six families state at chosen versions (derived by hand from the fixture)."""

    def view_at(self, view_id: str, version: int):
        graph = build_store()
        store = self.store()
        store.materialise(graph, version)
        return store.get(view_id)

    def test_families(self):
        cases = [
            ("list:melanie:playsInstrument", 7, [("clarinet",), ("violin",)]),
            ("count:melanie:playsInstrument", 7, [("clarinet",), ("violin",), ("2",)]),
            ("current:lina:livesIn", 1, [("Berlin",)]),
            ("current:lina:livesIn", 14, [("Munich",)]),  # Hamburg has a valid end
            ("list:lina:maintains", 10, [("Atlas",), ("Boreal",)]),
            ("constraints:request1", 5, [("arrive by", "20:45"), ("destination", "Vienna")]),
            ("pending:request1", 5, [("TR7143",), ("TR9999",)]),
            ("pending:request1", 6, [("TR9999",)]),
            ("pending:request1", 13, []),
            ("choice:request1", 6, [("TR7143", "scheduled arrival", "20:38")]),
            ("choice:request1", 11, [("TR7143", "scheduled arrival", "20:40")]),
            ("choice:request1", 12, []),
            ("choice:request1", 13, [("TR9999", "scheduled arrival", "21:10")]),
        ]
        for view_id, version, expected in cases:
            with self.subTest(view=view_id, version=version):
                graph = build_store()
                store = self.store()
                for r in range(1, version + 1):
                    store.materialise(graph, r)
                if store.get(view_id).cutoff < version:
                    store.maintain(view_id, graph, version)
                self.assertEqual(answers(store.get(view_id)), expected)

    def test_sentences_cite_row_evidence_and_scope_notes_are_read_time(self):
        view = self.view_at("count:melanie:playsInstrument", 8)
        self.assertEqual(len(view.sentences), 1)
        sentence = view.sentences[0]
        self.assertEqual(sentence.text, "Number of distinct values of melanie plays instrument: 2.")
        self.assertEqual(len(sentence.rows), 3)  # the aggregate row and its two members
        self.assertEqual(sentence.evidence, ("m2", "m7", "m8"))
        self.assertIn("Counted within the scope observed up to version 12.", view.text(12))
        self.assertNotIn("version 12", str(view.to_record()))
        choice = self.view_at("choice:request1", 6)
        self.assertEqual(choice.text(),
                         "Current choice for request1: TR7143, scheduled arrival 20:38. "
                         "[m4, m6]")

    def test_dependency_patterns(self):
        pending = self.view_at("pending:request1", 5)
        roles = [d.role for d in pending.dependencies]
        self.assertEqual(roles, [POSITIVE, NEGATED])
        neg = pending.dependencies[1].to_record()
        self.assertEqual(neg["attribution"], {"speaker": {"entity": "user"}, "function": None,
                                              "report_mode": "own", "polarity": "positive",
                                              "derived": False})
        count = self.view_at("count:melanie:playsInstrument", 7)
        self.assertTrue(all(d.aggregated for d in count.dependencies))
        choice = self.view_at("choice:request1", 6)
        self.assertEqual([d.selected for d in choice.dependencies], [True, False, False])
        current = self.view_at("current:lina:livesIn", 1)
        self.assertEqual(len(current.dependencies[0].filters), 1)
        self.assertEqual(current.used_claims(), {"c_berlin"})
        self.assertEqual(current.used_attributions(), {"a_berlin"})


class CitationRepairTest(Fixture):
    """Citation repair makes no LLM call; the ledger shows it."""

    def test_repeated_mention_is_patched_without_a_call(self):
        graph = build_store()
        store = self.store(llm_renderer(self.ledger))
        store.materialise(graph, 7)
        view_id = "list:melanie:playsInstrument"
        built = [e for e in store.events if e.view_id == view_id]
        self.assertEqual(len(built), 1)
        self.assertEqual(len(built[0].call_ids), 1)  # the build rendered through the LLM
        before = self.calls()
        self.assertTrue(before)
        self.assertTrue(all(c.call_type == "render" and c.category == "W" for c in before))
        old = store.get(view_id)

        store.mark(view_id, citation=True)
        event = store.maintain(view_id, graph, 8, read_id="q1")
        self.assertEqual(event.action, CITATION_REPAIR)
        self.assertEqual(event.call_ids, ())
        self.assertEqual(event.units_rendered, 0)
        self.assertEqual(self.calls(), before)  # calls.jsonl: no new record
        new = store.get(view_id)
        self.assertEqual([s.text for s in new.sentences], [s.text for s in old.sentences])
        violin = next(s for s in new.sentences if "violin" in s.text)
        self.assertEqual(violin.evidence, ("m2", "m8"))
        self.assertEqual(new.cutoff, 8)
        self.assertNotEqual(new.fingerprints["witnesses"], old.fingerprints["witnesses"])
        self.assertEqual(new.fingerprints["answers"], old.fingerprints["answers"])

    def test_repair_never_touches_the_renderer(self):
        class Refuse(TemplateRenderer):
            def render(self, *args, **kwargs):
                raise AssertionError("citation repair called the renderer")

        graph = build_store()
        store = self.store()
        store.materialise(graph, 14)
        store.renderer = Refuse()
        for view_id in ("list:melanie:playsInstrument", "count:melanie:playsInstrument"):
            with self.subTest(view=view_id):
                self.assertEqual(store.maintain(view_id, graph, 15).action, CITATION_REPAIR)
        self.assertIn("m15", store.get("count:melanie:playsInstrument").sentences[0].evidence)


class LLMRenderingTest(Fixture):
    def test_calls_are_recorded_as_render_W_with_the_pinned_prompt(self):
        graph = build_store()
        store = self.store(llm_renderer(self.ledger))
        store.materialise(graph, 6)
        prompt = load_pinned(PROMPT, REGISTRY)
        write = self.calls()
        self.assertTrue(write)
        for c in write:
            self.assertEqual((c.call_type, c.trigger, c.category, c.read_id, c.history_id),
                             ("render", "write", "W", None, HISTORY))
            self.assertEqual(c.prompt_sha256, prompt.sha256)
        self.assertTrue(all(s.source == "llm" for v in store.views() for s in v.sentences))
        # A lazy rebuild at read time is still W, with trigger read.
        n = len(self.calls())
        event = store.maintain("pending:request1", graph, 7, read_id="q7")
        self.assertEqual((event.action, event.call_ids), (ADVANCE, ()))
        event = store.maintain("list:lina:maintains", graph, 10, read_id="q10")
        self.assertEqual((event.action, event.units_rendered), (LOCAL_REBUILD, 1))
        late = self.calls()[n:]
        self.assertEqual([(c.trigger, c.category, c.read_id, c.version) for c in late],
                         [("read", "W", "q10", 10)])
        self.assertEqual(event.call_ids, tuple(c.call_id for c in late))

    def test_failed_sentences_fall_back_to_the_template(self):
        def corrupt(sentences, user):
            for s in sentences:
                if "violin" in s["text"]:
                    s["text"] = "Melanie plays the viola."          # value missing
                if "clarinet" in s["text"]:
                    s["text"] = "clarinet, like the violin."        # another row's value
            return sentences

        graph = build_store()
        store = self.store(llm_renderer(self.ledger, FakeTransport(corrupt)))
        store.materialise(graph, 7)
        view = store.get("list:melanie:playsInstrument")
        self.assertEqual({s.source for s in view.sentences}, {"fallback"})
        self.assertEqual({s.text for s in view.sentences},
                         {"melanie plays instrument violin.", "melanie plays instrument clarinet."})
        event = next(e for e in store.events if e.view_id == view.view_id)
        self.assertEqual((event.llm_sentences, event.failed_sentences, event.fallback_units),
                         (0, 2, 2))

    def test_sentence_without_the_binding_subject_falls_back(self):
        def drop_subject(sentences, user):
            if "View: constraints requested for request1" in user:
                for s in sentences:
                    s["text"] = s["text"].rsplit(" (", 1)[0] + "."   # values only
            return sentences

        graph = build_store()
        store = self.store(llm_renderer(self.ledger, FakeTransport(drop_subject)))
        store.materialise(graph, 7)
        view = store.get("constraints:request1")
        self.assertTrue(view.sentences)
        self.assertEqual({s.source for s in view.sentences}, {"fallback"})
        self.assertTrue(all("request1" in s.text for s in view.sentences))
        event = next(e for e in store.events if e.view_id == view.view_id)
        n = len(view.sentences)
        self.assertEqual((event.llm_sentences, event.failed_sentences, event.fallback_units),
                         (0, n, n))
        listed = store.get("list:melanie:playsInstrument")
        self.assertEqual({s.source for s in listed.sentences}, {"llm"})

    def test_extra_numbers_and_unknown_rows_fail(self):
        def corrupt(sentences, user):
            if "count = " in user:
                return [{"rows": sentences[0]["rows"], "text": "Melanie plays 2 of 3."}]
            return [{"rows": ["r-unknown"], "text": "x."}, *sentences]

        graph = build_store()
        store = self.store(llm_renderer(self.ledger, FakeTransport(corrupt)))
        store.materialise(graph, 7)
        count = store.get("count:melanie:playsInstrument")
        self.assertEqual(count.sentences[0].source, "fallback")
        listed = store.get("list:melanie:playsInstrument")
        self.assertEqual({s.source for s in listed.sentences}, {"llm"})

    def test_invalid_output_is_recorded_and_falls_back(self):
        graph = build_store()
        store = self.store(llm_renderer(self.ledger, FakeTransport(lambda s, u: "not json")))
        store.materialise(graph, 2)
        view = store.get("list:melanie:playsInstrument")
        self.assertEqual([s.source for s in view.sentences], ["fallback"])
        self.assertTrue(self.calls())
        self.assertEqual({c.status for c in self.calls()}, {"invalid_output"})

    def test_rows_are_chunked(self):
        transport = FakeTransport()
        graph = build_store()
        store = self.store(llm_renderer(self.ledger, transport, max_rows_per_call=1))
        store.materialise(graph, 7)
        self.assertEqual(len(store.get("list:melanie:playsInstrument").sentences), 2)
        rows_per_request = [p["messages"][-1]["content"].count("\n[") for p in transport.requests]
        self.assertLessEqual(max(rows_per_request), 1)


class LifecycleTest(Fixture):
    def test_instantiation_threshold(self):
        graph = build_store()
        store = self.store(instantiation_threshold=2)
        store.materialise(graph, 2)
        self.assertNotIn("list:melanie:playsInstrument", store)
        self.assertIn("constraints:request1", store.materialise(graph, 3))
        store.materialise(graph, 7)
        self.assertIn("list:melanie:playsInstrument", store)
        self.assertNotIn("current:lina:livesIn", store)  # one current claim at a time
        override = self.store(thresholds={"current": 1})
        override.materialise(graph, 1)
        self.assertIn("current:lina:livesIn", override)

    def test_resident_views_stay_once_instantiated(self):
        graph = build_store()
        store = self.store()
        store.materialise(graph, 5)
        self.assertIn("pending:request1", store)
        store.materialise(graph, 13)
        store.maintain("pending:request1", graph, 13)
        self.assertEqual(store.get("pending:request1").rows, ())
        self.assertIn("No matching claim within the scope observed up to version 13.",
                      store.get("pending:request1").text())

    def test_temporary_views_are_discarded(self):
        graph = build_store()
        store = self.store()
        store.materialise(graph, HEAD)
        resident = len(store)
        query = parse("SELECT ?x WHERE { (lina, livesIn, ?x) AS ?c } AT(state=historical)")
        with store.question("q1") as temporary:
            view = temporary.build(query, graph, HEAD)
            self.assertIs(view.lifecycle, Lifecycle.TEMPORARY)
            self.assertEqual(sorted(a[0] for a in answers(view)), ["Berlin", "Hamburg", "Munich"])
        self.assertEqual(len(store), resident)
        self.assertNotIn(view.view_id, store)
        with self.assertRaises(ViewError):
            temporary.build(query, graph, HEAD)
        relative = absolutize(parse("SELECT ?x WHERE { (lina, livesIn, ?x) AS ?c "
                                    "FILTER(start(?c) >= now(-7)) }", check=False),
                              __import__("datetime").date(2023, 3, 5))
        self.assertTrue(relative.temporary)
        with store.question("q2") as temporary:
            self.assertEqual(answers(temporary.build(relative, graph, HEAD)), [("Munich",)])
        with self.assertRaises(ViewError):
            store._store_built(store.get("list:lina:maintains").binding, "t", relative, None,
                               HEAD, None, 0.0, BUILD)

    def test_entity_merge_and_vocabulary_change_invalidate_everything(self):
        graph = build_store(upto=8)
        store = self.store()
        store.materialise(graph, 8)
        merge = ChangeSet(HISTORY, 9, entity_merges=(
            EntityEquivalence("q_mel", "melanie", "mel", 9),))
        self.assertTrue(store.note_changeset(merge))
        graph.commit(merge)
        self.assertTrue(all(store.flags(v.view_id).invalid for v in store.views()))
        event = store.maintain("list:melanie:playsInstrument", graph, 9)
        self.assertEqual(event.action, FULL_REBUILD)
        self.assertIsNone(store.flags("list:melanie:playsInstrument").invalid)
        self.assertFalse(store.note_changeset(ChangeSet(HISTORY, 10, vocabulary_version="v1")))
        self.assertTrue(store.note_changeset(ChangeSet(HISTORY, 11, vocabulary_version="v2")))

    def test_unconfirmed_answer_stale_mark_rebuilds_in_full(self):
        graph = build_store()
        store = self.store()
        store.materialise(graph, 7)
        store.mark("list:lina:maintains", answer=True)
        event = store.maintain("list:lina:maintains", graph, 8, confirm=False)
        self.assertEqual((event.action, event.units_rendered), (FULL_REBUILD, 1))
        store.mark("list:lina:maintains", answer=True)
        self.assertEqual(store.maintain("list:lina:maintains", graph, 8).action, ADVANCE)

    def test_save_and_restore(self):
        graph = build_store()
        store = self.store()
        for r in range(1, HEAD + 1):
            store.materialise(graph, r)
        store.mark("choice:request1", answer=True)
        directory = Path(self.tmp.name) / "views"
        store.save(directory)
        restored = ViewStore.restore(directory, HISTORY, TemplateRenderer(),
                                     config=ViewConfig(), vocabulary=VOCABULARY)
        self.assertEqual([v.to_record() for v in restored.views()],
                         [v.to_record() for v in store.views()])
        self.assertTrue(restored.flags("choice:request1").answer_stale)
        self.assertEqual(restored.events, store.events)

    def test_default_config_loads(self):
        config = load_view_config()
        self.assertEqual(len(config.families), 6)
        self.assertEqual(config.rendering.prompt, PROMPT)


if __name__ == "__main__":
    unittest.main()
