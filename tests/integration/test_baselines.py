"""Behaviour of the individual baselines, the answering step and the call recorder (T003)."""

import json
import tempfile
import unittest
from pathlib import Path

from grace.context import api
from grace.context.memory.index.bm25 import BM25Index
from grace.context.memory.index.chunking import Chunk, tokenize
from grace.eval.engines.baselines.base import CallTag, Packer
from grace.eval.engines.baselines.raw import RawText
from grace.eval.engines.baselines.retrieval import Retrieval, rrf
from grace.eval.engines.baselines.slots import SlotTable
from grace.eval.engines.baselines.summary import RollingSummary
from grace.eval.runner.harness.answer import answer, parse_reply
from grace.eval.runner.harness.inputs import load_fixture as load
from grace.eval.runner.harness.models import FakeBackend, RecordingModel, fake_responder
from grace.llm.records import CallLedger

ROOT = Path(__file__).resolve().parents[2]
LOCOMO = ROOT / "tests" / "fixtures" / "benchmarks" / "locomo"
MULTIWOZ = ROOT / "tests" / "fixtures" / "benchmarks" / "multiwoz"


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = CallLedger(Path(tmp.name) / "calls.jsonl", "T003-20261125T000000Z-0000")
        self.item = load(LOCOMO).histories[0]
        self.task = self.item.reads[0]

    def model(self, responder=fake_responder, caching=False, attempts=2):
        return RecordingModel(FakeBackend(responder, prefix_caching=caching), self.ledger,
                              max_attempts=attempts)

    def ingest(self, engine, item=None):
        item = item or self.item
        engine.open(item.history)
        for message in item.messages:
            engine.write(message)
        return engine


class IndexTest(Base):
    def test_bm25_ranks_the_matching_message_first_and_respects_the_cut_off(self):
        index = BM25Index()
        for m in self.item.messages:
            index.add(Chunk(m.message_id, (m.message_id,), m.version, m.text))
        hits = index.search("cat named Pip", 5)
        self.assertEqual(hits[0][0].chunk_id, "D1:2")
        self.assertTrue(all(c.version <= 2 for c, _ in index.search("clarinet violin", 2)))
        self.assertEqual(tokenize("Pip's CAT!"), ["pip", "s", "cat"])

    def test_rrf(self):
        a, b, c = (Chunk(i, (i,), v, i) for v, i in enumerate("abc", start=1))
        fused = rrf([[a, b], [b, c]], 60)
        self.assertEqual([x.chunk_id for x, _ in fused], ["b", "a", "c"])


class RawTextTest(Base):
    def test_full_history_and_budget_truncation_keep_the_newest(self):
        engine = self.ingest(RawText(self.model()))
        full = engine.read(self.task, None).context
        self.assertEqual(full.context_ids, [m.message_id for m in self.item.messages])
        self.assertIsNone(full.budget_tokens)
        cut = engine.read(self.task, 20).context
        self.assertLessEqual(cut.tokens, 20)
        self.assertEqual(cut.context_ids, ["D2:1", "D2:2"])

    def test_last_k(self):
        engine = self.ingest(RawText(self.model(), last_k=1))
        self.assertEqual(engine.read(self.task, None).context.context_ids, ["D2:2"])

    def test_window_overflow_is_disclosed(self):
        engine = self.ingest(RawText(self.model(), window_tokens=30))
        context = engine.read(self.task, None).context
        self.assertLessEqual(context.tokens, 30)
        self.assertIn("earlier messages omitted", context.text)
        self.assertEqual(context.fragments[0].kind, "other")
        self.assertIsNone(context.budget_tokens)


class RetrievalTest(Base):
    def test_channels(self):
        cat = next(t for t in self.item.reads if "cat" in t.question)
        for channel in ("bm25", "dense", "rrf"):
            with self.subTest(channel=channel):
                engine = self.ingest(Retrieval(self.model(), channel=channel, top_k=2))
                result = engine.read(cat, None)
                self.assertIn("D1:2", result.context.context_ids)
                self.assertLessEqual(len(result.context.fragments), 2)
                channels = {c.channel for c in result.trace.candidates}
                self.assertIn(channel, channels)
                embeds = [r for r in self.ledger.records if r.call_type == "embed"]
                if channel == "bm25":
                    self.assertEqual(embeds, [])
                else:
                    self.assertTrue(all(r.category == "embedding" for r in embeds))
                self.ledger.records.clear()

    def test_further_retrieval_brings_in_the_request(self):
        engine = self.ingest(Retrieval(self.model(), channel="bm25", top_k=1))
        cat = next(t for t in self.item.reads if "cat" in t.question)
        more = engine.further_retrieval(cat, "clarinet", None)
        self.assertTrue(more.trace.further_retrieval)
        self.assertIn("D2:1", more.context.context_ids)


class SummaryTest(Base):
    def test_rewrite_calls_on_every_eviction_reuse_in_blocks(self):
        for mode, expected in (("rewrite", 4), ("reuse", 2)):
            with self.subTest(mode=mode):
                self.ledger.records.clear()
                engine = self.ingest(RollingSummary(self.model(), mode=mode, recent_k=1,
                                                    block_size=2))
                calls = [r for r in self.ledger.records if r.call_type == "summary"]
                self.assertEqual(len(calls), expected)
                self.assertTrue(all(r.category == "W" and r.trigger == "write" for r in calls))
                context = engine.read(self.task, None).context
                kinds = [f.kind for f in context.fragments]
                self.assertEqual(kinds[-1], "message")
                self.assertIn("summary", kinds)
                summary = next(f for f in context.fragments if f.kind == "summary")
                self.assertEqual(summary.source_ids, ())
                self.assertTrue(summary.evidence_ids)
                n_blocks = kinds.count("summary")
                self.assertEqual(n_blocks, 1 if mode == "rewrite" else 2)

    def test_failed_summary_keeps_messages_raw(self):
        engine = self.ingest(RollingSummary(self.model(lambda m: "  "), mode="rewrite",
                                            recent_k=1))
        statuses = {r.status for r in self.ledger.records}
        self.assertEqual(statuses, {"invalid_output"})
        context = engine.read(self.task, None).context
        self.assertEqual(len(context.context_ids), 5)


class SlotTableTest(Base):
    SCHEMA = {"slots": {"person.possession": "owned things", "person.activity": "hobbies"},
              "functions": ["inform", "other"]}

    def test_rows_carry_speaker_function_and_provenance(self):
        def responder(messages):
            text = messages[-1]["content"]
            if "cat named Pip" in text.split("New message", 1)[-1]:
                return json.dumps({"entries": [{"slot": "person.possession", "value": "cat Pip",
                                                "function": "inform"}]})
            if "violin" in text.split("New message", 1)[-1]:
                return '{"entries": [{"slot": "bogus", "value": "x", "function": "inform"}]}'
            return '{"entries": []}'
        engine = self.ingest(SlotTable(self.model(responder), **self.SCHEMA))
        context = engine.read(self.task, None).context
        self.assertEqual(len(context.fragments), 1)
        row = context.fragments[0]
        self.assertEqual(row.evidence_ids, ("D1:2",))
        self.assertEqual(row.source_ids, ())
        self.assertIn("speaker: Caro", row.text)
        self.assertIn("function: inform", row.text)
        invalid = [r for r in self.ledger.records if r.status == "invalid_output"]
        self.assertEqual(len(invalid), 2)  # the off-schema output, retried once
        self.assertTrue(all(r.call_type == "extract" and r.category == "W"
                            for r in self.ledger.records))


class RecorderTest(Base):
    def test_prefix_caching_and_failed_attempts(self):
        model = self.model(caching=True)
        tag = CallTag("answer", "read", "h", 1, "t@1")
        messages = [{"role": "system", "content": "fixed prefix " * 5},
                    {"role": "user", "content": "question one"}]
        model.chat(messages, tag)
        model.chat([messages[0], {"role": "user", "content": "question two"}], tag)
        first, second = self.ledger.records
        self.assertEqual(first.cached_input_tokens, 0)
        self.assertGreater(second.cached_input_tokens, 0)
        self.assertLessEqual(second.cached_input_tokens, second.input_tokens)

        def broken(messages):
            raise RuntimeError("server down")
        result = self.model(broken).chat(messages, tag)
        self.assertFalse(result.ok)
        failed = self.ledger.records[-2:]
        self.assertEqual([r.status for r in failed], ["failed", "failed"])
        self.assertEqual([r.attempt for r in failed], [1, 2])
        with self.assertRaises(ValueError):
            model.chat(messages, CallTag("answer", "write", "h", 1, "t@1"))


class AnswerTest(Base):
    def test_parse_reply(self):
        state = load(MULTIWOZ).histories[0].reads[0]
        self.assertEqual(parse_reply('{"output": "unknown", "cited_ids": []}', self.task,
                                     allow_retrieve=False).output, "unknown")
        reply = parse_reply('```json\n{"output": "state", "state": {"a": "b"}, "cited_ids": []}'
                            '\n```', state, allow_retrieve=False)
        self.assertEqual(reply.value, {"a": "b"})
        retrieve = parse_reply('{"output": "retrieve", "query": "x"}', self.task,
                               allow_retrieve=True)
        self.assertEqual(retrieve.request, "x")
        bad = ['{"output": "state", "state": {}, "cited_ids": []}',
               '{"output": "answer", "answer": "", "cited_ids": ["D1:1"]}',
               '{"output": "answer", "answer": "Pip", "cited_ids": []}',
               '{"output": "retrieve", "query": "x"}', "no json", '{"output": "maybe"}',
               'x {"output": "unknown", "cited_ids": []} y']
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_reply(text, self.task, allow_retrieve=False)

    def test_one_further_retrieval_then_final(self):
        def always_retrieve(messages):
            return json.dumps({"output": "retrieve", "query": "clarinet"})
        engine = self.ingest(Retrieval(self.model(), channel="bm25", top_k=1))
        result = answer(engine, self.task, None, self.model(always_retrieve),
                        {m.message_id for m in self.item.messages})
        self.assertEqual(result.output, "invalid")
        self.assertTrue(result.trace.further_retrieval)
        answers = [r for r in self.ledger.records if r.call_type == "answer"]
        self.assertEqual(len(answers), 3)  # first call, then the final call and its retry

    def test_citations_outside_the_snapshot_are_dropped(self):
        def cites(messages):
            return json.dumps({"output": "answer", "answer": "Pip",
                               "cited_ids": ["D1:2", "D9:9", "D1:2"]})
        engine = self.ingest(RawText(self.model()))
        result = answer(engine, self.task, None, self.model(cites),
                        {m.message_id for m in self.item.messages})
        self.assertEqual(result.cited_ids, ["D1:2"])
        self.assertEqual(result.dropped_citations, ["D9:9"])
        self.assertEqual(result.trace.included_ids, tuple(result.context.context_ids))


class PackerTest(unittest.TestCase):
    def test_skips_what_does_not_fit_and_marks_an_empty_context(self):
        packer = Packer(lambda text: len(text.split()))
        task = api.ReadTask("b", "s", "h", "t@1", "t", 1, "question", "q?", None, None, None)
        big = packer.fragment("a", "message", "one two three four", ["a"], ["a"])
        small = packer.fragment("b", "message", "five", ["b"], ["b"])
        context = packer.pack(task, 2, [big, small])
        self.assertEqual(context.context_ids, ["b"])
        empty = packer.pack(task, 5, [])
        self.assertEqual(empty.text, "[no memory]")
        self.assertEqual(empty.fragments, ())


if __name__ == "__main__":
    unittest.main()
