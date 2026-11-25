"""The harness's real model path (`ClientModel` over grace.llm) and its input guard (T003).

Uses the fake OpenAI-compatible server of tests/llm/fakes.py: no GPU, no network beyond loopback.
"""

import json
import tempfile
import unittest
from pathlib import Path

from grace.eval.engines.baselines.base import CallTag
from grace.eval.engines.baselines.raw import RawText
from grace.eval.engines.baselines.retrieval import Retrieval
from grace.eval.runner.harness.answer import answer
from grace.eval.runner.harness.inputs import load_dev, load_fixture
from grace.eval.runner.harness.models import ClientModel
from grace.llm.client import ChatClient, Endpoint
from grace.llm.embeddings import EmbeddingClient
from grace.llm.records import CallLedger, read_calls
from tests.contracts.records import read_jsonl
from tests.contracts.test_cost_ledger import check_calls
from tests.llm.fakes import FakeServer, WordCounter, completion

ROOT = Path(__file__).resolve().parents[2]
LOCOMO = ROOT / "tests" / "fixtures" / "benchmarks" / "locomo"
RUN = "T003-20261125T000000Z-0000"


class ClientModelTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.calls = Path(tmp.name) / "calls.jsonl"
        self.ledger = CallLedger(self.calls, RUN)
        self.item = load_fixture(LOCOMO).histories[0]

    def model(self, server, embed_server=None):
        endpoint = Endpoint(base_url=server.base_url, served_model="m",
                            model_label="org/m@" + "0" * 40, timeout_s=5.0,
                            chat_template_kwargs={"enable_thinking": False})
        client = ChatClient(endpoint, self.ledger, WordCounter(), sleep=lambda s: None)
        embedder = None
        if embed_server is not None:
            embedder = EmbeddingClient(
                Endpoint(base_url=embed_server.base_url, served_model="e",
                         model_label="org/e@" + "0" * 40, timeout_s=5.0),
                self.ledger, lambda t: len(t.split()), sleep=lambda s: None)
        return ClientModel(client, WordCounter(), decoding={"temperature": 0.0, "top_p": 1.0},
                           embedder=embedder)

    def test_answer_through_the_client(self):
        reply = json.dumps({"output": "answer", "answer": "Pip", "cited_ids": ["D1:2"]})
        with FakeServer([(200, "not json"), (200, completion("no json here")),
                         (200, completion(reply))]) as srv:
            model = self.model(srv)
            engine = RawText(model)
            engine.open(self.item.history)
            for m in self.item.messages:
                engine.write(m)
            task = self.item.reads[0]
            result = answer(engine, task, None, model, {m.message_id for m in self.item.messages},
                            max_tokens=256)
        self.assertEqual((result.output, result.prediction, result.cited_ids),
                         ("answer", "Pip", ["D1:2"]))
        body = srv.requests[0]["body"]
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual((body["temperature"], body["max_tokens"]), (0.0, 256))
        self.assertEqual(len(model.observed), 2)  # system and user message of the answer call
        records = read_calls(self.calls)
        # transport failure, then invalid output (a logical call), then a new logical call
        self.assertEqual([(r.status, r.attempt) for r in records],
                         [("failed", 1), ("invalid_output", 2), ("ok", 1)])
        self.assertEqual(set(result.trace.call_ids), {r.call_id for r in records})
        self.assertTrue(all(r.read_id == task.read_id and r.category == "A" for r in records))
        check_calls(read_jsonl(self.calls))

    def test_response_format_is_merged_into_decoding_and_none_changes_nothing(self):
        """T034: the optional structured-output request (Graphiti's json_schema mode)."""
        tag = CallTag("external", "write", "h", 1)
        schema = {"type": "json_schema",
                  "json_schema": {"name": "R", "schema": {"type": "object"}}}
        with FakeServer([(200, completion("{}"))] * 3) as srv:
            model = self.model(srv)
            messages = [{"role": "user", "content": "hi"}]
            model.chat(messages, tag, max_tokens=8)
            model.chat(messages, tag, max_tokens=8, response_format=None)
            model.chat(messages, tag, max_tokens=8, response_format=schema)
        plain, explicit_none, structured = (r["body"] for r in srv.requests)
        self.assertEqual(plain, explicit_none)
        self.assertNotIn("response_format", plain)
        self.assertEqual(structured, {**plain, "response_format": schema})
        self.assertEqual(model.decoding, {"temperature": 0.0, "top_p": 1.0})  # not mutated

    def test_transport_failure_is_not_ok_and_embeddings_are_recorded(self):
        with FakeServer([(500, {})] * 3) as srv:
            result = self.model(srv).chat([{"role": "user", "content": "hi"}],
                                          CallTag("answer", "read", "h", 1, "t@1"))
        self.assertFalse(result.ok)
        self.assertEqual(len(result.call_ids), 3)
        vectors = {"data": [{"index": 0, "embedding": [1.0, 0.0]}],
                   "usage": {"prompt_tokens": 5}}
        with FakeServer([]) as srv, FakeServer([(200, vectors)] * 10) as emb:
            engine = Retrieval(self.model(srv, emb), channel="dense", top_k=2,
                               query_instruction="find it")
            engine.open(self.item.history)
            task = self.item.reads[0]
            for m in self.item.messages[:task.version]:
                engine.write(m)
            engine.read(task, None)
        self.assertEqual(emb.requests[0]["path"], "/v1/embeddings")
        embeds = [r for r in read_calls(self.calls) if r.call_type == "embed"]
        self.assertTrue(embeds and all(r.input_tokens == 5 for r in embeds))
        *writes, query = [r["body"]["input"][0] for r in emb.requests]
        self.assertTrue(query.startswith("Instruct: find it\nQuery: "))
        self.assertFalse(any(w.startswith("Instruct:") for w in writes))


class DevInputGuardTest(unittest.TestCase):
    def test_only_development_splits(self):
        with self.assertRaises(ValueError):
            load_dev("locomo", "held-out")
        with self.assertRaises(ValueError):
            load_dev("locomo", "no-such-split")


if __name__ == "__main__":
    unittest.main()
