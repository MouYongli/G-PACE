"""Mem0 adapter (T029): calls through the model port, the date patch, evidence fragments, failures.

Runs on the synthetic LoCoMo fixture with the deterministic fake backend; no score is real.
"""

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grace.eval.engines.baselines import mem0 as adapter
from grace.eval.engines.baselines.base import EMPTY_CONTEXT
from grace.eval.engines.baselines.mem0 import Mem0
from grace.eval.runner.harness.inputs import load_fixture as load
from grace.eval.runner.harness.models import FakeBackend, RecordingModel, fake_responder
from grace.llm.records import CallLedger

ROOT = Path(__file__).resolve().parents[2]
LOCOMO = ROOT / "tests" / "fixtures" / "benchmarks" / "locomo"


def is_extraction(messages):
    return "## New Messages\n" in messages[-1]["content"]


class Mem0Test(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.ledger = CallLedger(self.dir / "calls.jsonl", "T029-20261125T000000Z-0000")
        self.item = load(LOCOMO, "streaming").histories[0]
        self.prompts = []

    def engine(self, responder=fake_responder, **params):
        def recording(messages):
            self.prompts.append(messages)
            return responder(messages)
        model = RecordingModel(FakeBackend(recording), self.ledger)
        engine = Mem0(model, **params)
        engine.open(self.item.history)
        return engine

    def ingest(self, engine, upto=None):
        for message in self.item.messages[:upto]:
            engine.write(message)
        return engine

    def read_at(self, version):
        return next(t for t in self.item.reads if t.version == version)

    def test_every_call_goes_through_the_port_and_no_socket_is_opened(self):
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")):
            engine = self.ingest(self.engine())
            read = engine.read(self.read_at(5), None)
        records = self.ledger.records
        n = len(self.item.messages)
        writes = [r for r in records if r.trigger == "write"]
        self.assertEqual(sum(r.call_type == "external" for r in writes), n)
        self.assertTrue(all(r.category == "W" for r in writes if r.call_type == "external"))
        # Mem0 embeds the new message (search) and the extracted memory (add) per write; the
        # adapter's dimension probe is reused for the first call, so it adds no record.
        self.assertEqual(sum(r.call_type == "embed" for r in writes), 2 * n)
        self.assertEqual({(r.history_id, r.version) for r in writes},
                         {(m.history_id, m.version) for m in self.item.messages})
        reads = [r for r in records if r.trigger == "read"]
        self.assertEqual([(r.call_type, r.read_id) for r in reads],
                         [("embed", self.read_at(5).read_id)])
        self.assertEqual(set(read.trace.call_ids), {r.call_id for r in reads})
        extraction = [r for r in records if r.call_type == "external"]
        self.assertEqual(len({r.prompt_sha256 for r in extraction}), 1)

    def test_extraction_prompt_carries_the_message_time(self):
        self.ingest(self.engine(), upto=1)
        message = self.item.messages[0]
        when = adapter.message_time(message, self.item.history)
        self.assertIsNotNone(when)
        user = next(p for p in self.prompts if is_extraction(p))[-1]["content"]
        self.assertIn(f"## Observation Date\n{when}", user)
        self.assertIn(f"## Current Date\n{when}", user)
        self.assertIn(f"{message.speaker}: {message.text}", user)

    def test_fragments_cite_their_source_messages_within_the_budget(self):
        engine = self.ingest(self.engine(threshold=0.0), upto=3)
        context = engine.read(self.read_at(3), None).context
        self.assertTrue(context.fragments)
        visible = {m.message_id for m in self.item.messages[:3]}
        for fragment in context.fragments:
            self.assertEqual(fragment.kind, "retrieved")
            self.assertEqual(len(fragment.evidence_ids), 1)
            self.assertTrue(set(fragment.evidence_ids) <= visible)
            self.assertTrue(fragment.text.startswith(f"[{fragment.evidence_ids[0]}]"))
        small = engine.read(self.read_at(3), 12).context
        self.assertLessEqual(small.tokens, 12)
        self.assertLess(len(small.fragments), len(context.fragments))

    def test_further_retrieval_appends_only_new_memories(self):
        engine = self.ingest(self.engine(top_k=1, threshold=0.0))
        task = self.read_at(5)
        first = engine.read(task, None).context
        further = engine.further_retrieval(task, "clarinet", None)
        self.assertEqual(further.context.fragments[0], first.fragments[0])
        self.assertLessEqual(len(further.context.fragments), 2)
        self.assertTrue(further.trace.further_retrieval)

    def test_unparsable_extraction_is_retried_and_stores_nothing(self):
        def broken(messages):
            return "no json here" if is_extraction(messages) else fake_responder(messages)
        engine = self.ingest(self.engine(broken, threshold=0.0))
        extraction = [r for r in self.ledger.records if r.call_type == "external"]
        self.assertEqual(len(extraction), 2 * len(self.item.messages))
        self.assertTrue(all(r.status == "invalid_output" for r in extraction))
        self.assertEqual(engine.read(self.read_at(5), None).context.text, EMPTY_CONTEXT)

    def test_a_failed_extraction_call_does_not_stop_ingestion(self):
        def flaky(messages):
            if is_extraction(messages) and "violin" in messages[-1]["content"].split(
                    "## New Messages\n", 1)[1]:
                raise RuntimeError("server down")
            return fake_responder(messages)
        engine = self.ingest(self.engine(flaky, threshold=0.0))
        failed = [r for r in self.ledger.records if r.status == "failed"]
        self.assertEqual([(r.version, r.attempt) for r in failed], [(1, 1), (1, 2)])
        self.assertEqual(engine.version, len(self.item.messages))
        cited = {i for f in engine.read(self.read_at(5), None).context.fragments
                 for i in f.evidence_ids}
        self.assertNotIn("D1:1", cited)
        self.assertTrue(cited)

    def test_save_and_restore_keep_memories_and_recent_messages(self):
        engine = self.ingest(self.engine(threshold=0.0), upto=3)
        saved = self.dir / "saved"
        saved.mkdir()
        engine.save(saved)
        state = json.loads((saved / "state.json").read_text(encoding="utf-8"))["state"]
        self.assertEqual(len(state["points"]), 3)
        self.assertEqual(len(state["last_messages"]), 3)
        restored = Mem0(RecordingModel(FakeBackend(), self.ledger), threshold=0.0)
        restored.restore(saved)
        for message in self.item.messages[3:]:
            engine.write(message)
            restored.write(message)
        task = self.read_at(5)
        self.assertEqual(restored.read(task, None).context, engine.read(task, None).context)
        prompts = [p[-1]["content"] for p in self.prompts if is_extraction(p)]
        self.assertIn(self.item.messages[0].text, prompts[-1])  # the last ten messages survive

    def test_telemetry_is_off_and_optional_packages_are_refused(self):
        self.engine()
        from mem0.memory import telemetry
        self.assertFalse(telemetry.MEM0_TELEMETRY)
        self.assertEqual(adapter.features()["mem0ai"], adapter.MEM0_VERSION)
        with mock.patch.object(adapter, "features",
                               return_value={"mem0ai": "2.2.1", "spacy": True,
                                             "fastembed": False}):
            with self.assertRaises(RuntimeError):
                Mem0(RecordingModel(FakeBackend(), self.ledger))


if __name__ == "__main__":
    unittest.main()
