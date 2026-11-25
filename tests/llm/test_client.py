"""ChatClient against a fake OpenAI-compatible server: records, retries, failures, accounting."""

import dataclasses
import tempfile
import unittest
from pathlib import Path

from grace.llm.client import ChatClient, Endpoint, LLMCallFailed
from grace.llm.records import CallContext, CallLedger, read_calls
from grace.llm.tokens import TokenizerPin
from tests.contracts.records import read_jsonl
from tests.contracts.test_cost_ledger import check_calls
from tests.llm.fakes import FakeServer, WordCounter, completion

RUN = "E000-20261125T000000Z-abcd"
MODELS = Path(__file__).resolve().parents[2] / "configs" / "models"
MESSAGES = [{"role": "system", "content": "fixed prefix"},
            {"role": "user", "content": "what is my commute now"}]  # 4+2 + 4+5 = 15 words
READ = CallContext("answer", "read", history_id="h1", read_id="q1@4", version=4)


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = Path(self.tmp.name) / "calls.jsonl"
        self.ledger = CallLedger(self.calls, RUN)

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, server, **kwargs):
        endpoint = Endpoint(base_url=server.base_url, served_model="served-model",
                            model_label="org/model@" + "0" * 40, timeout_s=5.0,
                            **kwargs.pop("endpoint", {}))
        return ChatClient(endpoint, self.ledger, WordCounter(), sleep=lambda s: None, **kwargs)

    def test_ok_call_is_recorded_with_local_input_count_and_server_cache(self):
        with FakeServer([(200, completion("15 minutes", 4, prompt_tokens=16, cached=8))]) as srv:
            result = self.client(srv).chat(MESSAGES, READ, prompt_sha256="a" * 64,
                                           decoding={"temperature": 0.0, "max_tokens": 32})
        self.assertEqual((result.text, result.status, result.error), ("15 minutes", "ok", None))
        self.assertEqual(result.server_input_tokens, 16)
        self.assertTrue(result.cache_reported)
        sent = srv.requests[0]
        self.assertEqual(sent["path"], "/v1/chat/completions")
        self.assertEqual(sent["body"]["model"], "served-model")
        self.assertEqual(sent["body"]["temperature"], 0.0)
        [record] = read_calls(self.calls)
        self.assertEqual((record.input_tokens, record.output_tokens, record.cached_input_tokens),
                         (15, 4, 8))
        self.assertEqual((record.category, record.attempt, record.status), ("A", 1, "ok"))
        self.assertIsNone(record.gpu_seconds)
        self.assertEqual(record.prompt_sha256, "a" * 64)
        check_calls(read_jsonl(self.calls))

    def test_failed_attempts_are_records_and_count_in_full(self):
        replies = [(500, {"error": "boom"}), (200, "not json"),
                   (200, completion("ok", 2))]
        with FakeServer(replies) as srv:
            result = self.client(srv).chat(MESSAGES, READ, prompt_sha256=None)
        records = read_calls(self.calls)
        self.assertEqual([r.status for r in records], ["failed", "failed", "ok"])
        self.assertEqual([r.attempt for r in records], [1, 2, 3])
        self.assertEqual([r.input_tokens for r in records], [15, 15, 15])
        self.assertEqual(len({r.call_id for r in records}), 3)
        self.assertEqual(result.call_id, records[-1].call_id)
        self.assertFalse(result.cache_reported)
        check_calls(read_jsonl(self.calls))

    def test_all_attempts_failing_raises_after_recording(self):
        with FakeServer([(503, {})] * 2) as srv:
            with self.assertRaises(LLMCallFailed) as caught:
                self.client(srv, max_attempts=2).chat(MESSAGES, READ, prompt_sha256=None)
        self.assertEqual(len(caught.exception.records), 2)
        self.assertEqual([r.status for r in read_calls(self.calls)], ["failed", "failed"])

    def test_invalid_output_goes_back_to_the_caller_without_retry(self):
        with FakeServer([(200, completion("maybe"))]) as srv:
            result = self.client(srv).chat(
                MESSAGES, READ, prompt_sha256=None,
                validate=lambda text: None if text.startswith("{") else "not JSON")
        self.assertEqual((result.status, result.error), ("invalid_output", "not JSON"))
        self.assertEqual(len(srv.requests), 1)
        self.assertEqual(read_calls(self.calls)[0].status, "invalid_output")

    def test_wall_clock_gpu_accounting_and_api_key(self):
        ticks = iter([0.0, 2.0])
        import os

        os.environ["GRACE_TEST_KEY"] = "secret"
        try:
            with FakeServer([(200, completion("x"))]) as srv:
                client = self.client(srv, endpoint={"gpu_accounting": "wall_clock", "gpus": 2,
                                                    "api_key_env": "GRACE_TEST_KEY"},
                                     clock=lambda: next(ticks))
                client.chat(MESSAGES, READ, prompt_sha256=None)
        finally:
            del os.environ["GRACE_TEST_KEY"]
        record = read_calls(self.calls)[0]
        self.assertEqual((record.gpu_seconds, record.latency_ms), (4.0, 2000.0))
        self.assertEqual(srv.requests[0]["auth"], "Bearer secret")

    def test_azure_api_key_header(self):
        import os

        os.environ["GRACE_TEST_KEY"] = "secret"
        try:
            with FakeServer([(200, completion("x"))]) as srv:
                client = self.client(srv, endpoint={"api_key_env": "GRACE_TEST_KEY",
                                                    "auth_header": "api-key"})
                client.chat(MESSAGES, READ, prompt_sha256=None)
        finally:
            del os.environ["GRACE_TEST_KEY"]
        self.assertEqual((srv.requests[0]["api_key"], srv.requests[0]["auth"]), ("secret", None))
        with self.assertRaises(ValueError):
            Endpoint(base_url="http://x/v1", served_model="m", model_label="m", auth_header="basic")

    def test_template_kwargs_of_the_pin_reach_the_server(self):
        pin = TokenizerPin.from_file(MODELS / "qwen3.5-9b.yaml")
        with FakeServer([(200, completion("x"))]) as srv:
            endpoint = Endpoint.for_model(pin, srv.base_url, "served", timeout_s=5.0)
            ChatClient(endpoint, self.ledger, WordCounter()).chat(MESSAGES, READ,
                                                                  prompt_sha256=None)
        self.assertEqual(srv.requests[0]["body"]["chat_template_kwargs"],
                         {"enable_thinking": False})
        self.assertEqual(read_calls(self.calls)[0].model, f"{pin.hf_repo}@{pin.revision}")

    def test_ledger_offers_the_interim_harness_names(self):
        with FakeServer([(200, completion("x"))]) as srv:
            self.client(srv).chat(MESSAGES, READ, prompt_sha256=None)
        self.assertEqual(len(self.ledger.records), 1)
        record = dataclasses.replace(self.ledger.records[0], call_id=self.ledger.new_id())
        self.ledger.append(record)
        self.assertEqual(len(read_calls(self.calls)), 2)

    def test_judge_calls_are_evaluation_overhead(self):
        context = CallContext("judge", "evaluation", history_id="h1", read_id="q1@4", version=4)
        with FakeServer([(200, completion("CORRECT", 1))]) as srv:
            self.client(srv).chat(MESSAGES, context, prompt_sha256=None)
        self.assertEqual(read_calls(self.calls)[0].category, "evaluation")


if __name__ == "__main__":
    unittest.main()
