"""Tagged hybrid retrieval (T027, plan 7.2): tags from writer-model calls, charged to W."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from grace.eval.engines.baselines.retrieval import Retrieval
from grace.eval.engines.baselines.tagged import TaggedRetrieval, tag_prefix, writer_functions
from grace.eval.runner.harness.inputs import load_fixture as load
from grace.eval.runner.harness.models import FakeBackend, RecordingModel, fake_responder
from grace.llm.records import CallLedger

ROOT = Path(__file__).resolve().parents[2]
LOCOMO = ROOT / "tests" / "fixtures" / "benchmarks" / "locomo"
NUMBERED = re.compile(r"^\[(\d+)\] ", re.MULTILINE)


def tagger(messages):
    """Tag every message of the unit with `inform`; the last one also with `question`."""
    if "dialogue acts" in messages[0]["content"]:
        new = messages[-1]["content"].split("New messages:\n", 1)[1]
        numbers = [int(n) for n in NUMBERED.findall(new)]
        return json.dumps({"tags": [{"message": n, "acts": ["inform"] + (
            ["question"] if n == numbers[-1] else [])} for n in numbers]})
    return fake_responder(messages)


class TaggedRetrievalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = CallLedger(Path(tmp.name) / "calls.jsonl", "T027-20261128T000000Z-0000")
        self.item = load(LOCOMO, "streaming").histories[0]

    def engine(self, responder=tagger, **params):
        model = RecordingModel(FakeBackend(responder), self.ledger)
        engine = TaggedRetrieval(model, channel="rrf", top_k=5, **params)
        engine.open(self.item.history)
        return engine

    def test_labels_are_the_writers(self):
        self.assertIn("inform", writer_functions())
        self.assertEqual(len(writer_functions()), 8)

    def test_units_are_tagged_at_write_and_flushed_at_read(self):
        engine = self.engine(unit_size=2)
        for message in self.item.messages:
            engine.write(message)
        extract = [r for r in self.ledger.records if r.call_type == "extract"]
        n = len(self.item.messages)
        self.assertEqual(len(extract), n // 2)
        self.assertTrue(all(r.category == "W" and r.trigger == "write" for r in extract))
        self.assertEqual(len(engine.pending), n % 2)
        task = next(t for t in self.item.reads if t.version == n)
        result = engine.read(task, None)
        if n % 2:
            read_calls = [r for r in self.ledger.records if r.trigger == "read"
                          and r.call_type == "extract"]
            self.assertEqual(len(read_calls), 1)
            self.assertEqual(read_calls[0].read_id, task.read_id)
        self.assertEqual(engine.pending, [])
        for fragment in result.context.fragments:
            self.assertRegex(fragment.text, r"^\[[^\]]+\]( \([^)]*\))? \[speaker: [^;]+; acts: "
                                            r"inform")
        self.assertTrue(set(result.context.context_ids) <= {m.message_id
                                                            for m in self.item.messages})

    def test_tags_reach_the_index_and_the_context(self):
        engine = self.engine(unit_size=1)
        for message in self.item.messages:
            engine.write(message)
        first = self.item.messages[0]
        speaker = first.speaker or first.role
        self.assertEqual(engine.tags[first.message_id], ["inform", "question"])
        chunk = engine.bm25.chunks[0]
        self.assertTrue(chunk.text.startswith(tag_prefix(speaker, ["inform", "question"])))
        embeds = [r for r in self.ledger.records if r.call_type == "embed"]
        self.assertTrue(embeds and all(r.category == "embedding" for r in embeds))

    def test_failed_tagging_marks_unknown_and_still_indexes(self):
        engine = self.engine(responder=fake_responder, unit_size=3)
        for message in self.item.messages[:3]:
            engine.write(message)
        self.assertTrue(all(engine.tags[m.message_id] is None for m in self.item.messages[:3]))
        statuses = {r.status for r in self.ledger.records if r.call_type == "extract"}
        self.assertEqual(statuses, {"invalid_output"})
        self.assertEqual(len(engine.indexed), 3)
        task = next(t for t in self.item.reads if t.version == 3)
        text = engine.read(task, None).context.text
        self.assertIn("acts: unknown", text)

    def test_out_of_range_message_numbers_are_invalid(self):
        def bad(messages):
            if "dialogue acts" in messages[0]["content"]:
                return json.dumps({"tags": [{"message": 9, "acts": ["inform"]}]})
            return fake_responder(messages)
        engine = self.engine(responder=bad, unit_size=1)
        engine.write(self.item.messages[0])
        self.assertIsNone(engine.tags[self.item.messages[0].message_id])

    def test_same_retrieval_settings_as_rrf(self):
        model = RecordingModel(FakeBackend(tagger), self.ledger)
        plain = Retrieval(model, channel="rrf", top_k=5)
        tagged = TaggedRetrieval(model, channel="rrf", top_k=5)
        self.assertEqual((plain.top_k, plain.rrf_k, plain.order),
                         (tagged.top_k, tagged.rrf_k, tagged.order))
        with self.assertRaises(ValueError):
            TaggedRetrieval(model, channel="rrf", unit_size=17)


if __name__ == "__main__":
    unittest.main()
