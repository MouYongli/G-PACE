"""Template-serialisation variant (T027): views rebuilt at every read, nothing cached."""

import unittest

from grace.context.memory.graph.vocabulary import load_vocabulary
from grace.context.views.serialise import serialise_at_read
from grace.context.views.store import ViewStore
from grace.context.views.template_families import ViewConfig
from tests.integration.views_fixture import HISTORY, build_store

VOCABULARY = load_vocabulary()


class SerialiseTest(unittest.TestCase):
    def test_same_views_as_a_fresh_resident_build_and_no_model_calls(self):
        graph = build_store()
        for version in (7, 10, 15):
            with self.subTest(version=version):
                out = serialise_at_read(graph, version, config=ViewConfig(),
                                        vocabulary=VOCABULARY)
                store = ViewStore(HISTORY, config=ViewConfig(), vocabulary=VOCABULARY)
                ids = store.materialise(graph, version)
                self.assertEqual([v.view_id for v in out.views], ids)
                self.assertEqual([v.text() for v in out.views],
                                 [store.get(i).text() for i in ids])
                self.assertTrue(all(not e.call_ids for e in out.events))
                self.assertEqual(len(out.events), len(out.views))

    def test_each_read_reflects_its_own_version(self):
        graph = build_store()
        early = serialise_at_read(graph, 7, vocabulary=VOCABULARY)
        late = serialise_at_read(graph, 15, vocabulary=VOCABULARY)
        self.assertTrue(all(v.cutoff == 7 for v in early.views))
        self.assertTrue(all(v.cutoff == 15 for v in late.views))
        self.assertNotEqual([v.text() for v in early.views], [v.text() for v in late.views])


if __name__ == "__main__":
    unittest.main()


class ThresholdTest(unittest.TestCase):
    """`SerialisedViews.hit` admits exactly the views `ViewStore.materialise` would hold."""

    def test_hits_follow_the_instantiation_threshold(self):
        from grace.context.pipeline.query.compile import compile_query
        from grace.context.pipeline.query.planner import Plan
        from grace.context.views.serialise import SerialisedViews

        graph = build_store()
        for threshold in (1, 2, 3):
            with self.subTest(threshold=threshold):
                config = ViewConfig(instantiation_threshold=threshold)
                resident = ViewStore(HISTORY, config=config, vocabulary=VOCABULARY)
                held = set(resident.materialise(graph, 15))
                reference = ViewStore(HISTORY, config=ViewConfig(), vocabulary=VOCABULARY)
                reference.materialise(graph, 15)
                if threshold > 1:
                    self.assertLess(len(held), len(reference.views()))
                views = SerialisedViews(HISTORY, config, VOCABULARY)
                for view in reference.views():
                    views.on_read(graph, 15, "r")
                    plan = Plan("r", "llm", query=view.query,
                                compiled=compile_query(view.query, "rdf11"))
                    hit = views.hit(plan)
                    self.assertEqual(hit is not None, view.view_id in held, view.view_id)
                    self.assertEqual(bool(views.events), hit is not None)
