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
