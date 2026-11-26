"""grace.llm.embeddings: the /embeddings client and its call records (added by T003)."""

import tempfile
import unittest
from pathlib import Path

from grace.llm.client import Endpoint, LLMCallFailed
from grace.llm.embeddings import EmbeddingClient
from grace.llm.records import CallContext, CallLedger, read_calls
from tests.contracts.records import read_jsonl
from tests.contracts.test_cost_ledger import check_calls
from tests.llm.fakes import FakeServer

RUN = "T003-20261125T000000Z-abcd"
WRITE = CallContext("embed", "write", history_id="h1", version=3)


def vectors(*rows, prompt_tokens=None):
    body = {"data": [{"index": i, "embedding": row} for i, row in reversed(list(enumerate(rows)))]}
    if prompt_tokens is not None:
        body["usage"] = {"prompt_tokens": prompt_tokens}
    return body


class EmbeddingClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = Path(self.tmp.name) / "calls.jsonl"
        self.ledger = CallLedger(self.calls, RUN)

    def client(self, server):
        endpoint = Endpoint(base_url=server.base_url, served_model="embedder",
                            model_label="org/embedder@" + "0" * 40, timeout_s=5.0)
        return EmbeddingClient(endpoint, self.ledger, lambda t: len(t.split()),
                               sleep=lambda s: None)

    def test_vectors_in_input_order_and_server_token_count(self):
        with FakeServer([(200, vectors([1, 0], [0, 1], prompt_tokens=7))]) as srv:
            result = self.client(srv).embed(["a b", "c"], WRITE)
        self.assertEqual(result.vectors, [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(srv.requests[0]["path"], "/v1/embeddings")
        self.assertEqual(srv.requests[0]["body"], {"model": "embedder", "input": ["a b", "c"]})
        [record] = read_calls(self.calls)
        self.assertEqual((record.call_type, record.category, record.trigger), ("embed",
                                                                              "embedding", "write"))
        self.assertEqual((record.input_tokens, record.output_tokens, record.status), (7, 0, "ok"))
        check_calls(read_jsonl(self.calls))

    def test_failures_are_recorded_with_the_local_count(self):
        replies = [(500, {"error": "boom"}), (200, vectors([1.0])), (200, vectors([1.0], [2.0]))]
        with FakeServer(replies) as srv:
            result = self.client(srv).embed(["a b", "c"], WRITE)  # 2nd reply: 1 vector for 2
        self.assertEqual(len(result.vectors), 2)
        records = read_calls(self.calls)
        self.assertEqual([r.status for r in records], ["failed", "failed", "ok"])
        self.assertEqual([r.attempt for r in records], [1, 2, 3])
        self.assertEqual(records[0].input_tokens, 3)
        with FakeServer([(500, {})] * 3) as srv, self.assertRaises(LLMCallFailed):
            self.client(srv).embed(["x"], WRITE)

    def test_only_embed_calls(self):
        with FakeServer([]) as srv, self.assertRaises(ValueError):
            self.client(srv).embed(["x"], CallContext("answer", "read", read_id="q@1"))


if __name__ == "__main__":
    unittest.main()
