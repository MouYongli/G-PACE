"""An engine's own chat model (T034, Graphiti's native-backbone row): `engine_llm` in an engine
config, `EngineLLMModel`, server-reported input tokens and the tokenizer.json counter.

Uses the fake OpenAI-compatible server of tests/llm/fakes.py: no GPU, no network beyond loopback,
no hosted API, no Hugging Face cache (the counter is built from a tokenizer made in the test).
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from grace.eval.engines.baselines.base import CallTag
from grace.eval.runner.harness import drive
from grace.eval.runner.harness.models import ClientModel, EngineLLMModel
from grace.llm.client import ChatClient, Endpoint
from grace.llm.embeddings import EmbeddingClient
from grace.llm.records import CallContext, CallLedger, read_calls
from grace.llm.tokens import TokenizerJsonCounter, TokenizerPinError, sha256_file
from tests.contracts.records import read_jsonl
from tests.contracts.test_cost_ledger import check_calls
from tests.llm.fakes import FakeServer, WordCounter, completion

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "configs" / "engines" / "graphiti-native.yaml"
PLAIN = ROOT / "configs" / "engines" / "graphiti.yaml"
RUN = "T034-20261126T000000Z-0000"
MESSAGES = [{"role": "system", "content": "fixed prefix"}, {"role": "user", "content": "a b c"}]
ENV = {"T_URL": "", "T_DEPLOYMENT": "dep-1", "T_KEY": "secret"}


def word_tokenizer(path: Path) -> Path:
    """A whitespace word-level tokenizer.json (stands in for o200k)."""
    import tokenizers
    from tokenizers import models, pre_tokenizers

    vocab = {"[UNK]": 0, **{w: i + 1 for i, w in enumerate("fixed prefix a b c".split())}}
    tok = tokenizers.Tokenizer(models.WordLevel(vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.save(str(path))
    return path


def spec(**overrides) -> dict:
    return {"label": "hosted/m@2025", "base_url_env": "T_URL", "deployment_env": "T_DEPLOYMENT",
            "api_key_env": "T_KEY", "auth_header": "api-key", "input_tokens": "server",
            "tokenizer": {"hf_repo": "x/y", "revision": "0" * 40, "file": "tokenizer.json",
                          "sha256": "0" * 64},
            "decoding": {"temperature": 0.0, "top_p": 1.0}, **overrides}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.calls = self.tmp / "calls.jsonl"
        self.ledger = CallLedger(self.calls, RUN)


class ServerInputTokensTest(Base):
    def client(self, server, source):
        endpoint = Endpoint(base_url=server.base_url, served_model="m", model_label="m@1",
                            timeout_s=5.0, input_tokens=source)
        return ChatClient(endpoint, self.ledger, WordCounter(), sleep=lambda s: None)

    def test_server_mode_records_prompt_tokens_and_local_mode_does_not(self):
        context = CallContext("external", "write", history_id="h", version=1)
        with FakeServer([(200, completion("x", 2, prompt_tokens=40, cached=8))] * 2) as srv:
            self.client(srv, "server").chat(MESSAGES, context, prompt_sha256=None)
            self.client(srv, "local").chat(MESSAGES, context, prompt_sha256=None)
        server, local = read_calls(self.calls)
        self.assertEqual((server.input_tokens, server.cached_input_tokens), (40, 8))
        self.assertEqual((local.input_tokens, local.cached_input_tokens), (13, 8))  # 4+2 + 4+3
        check_calls(read_jsonl(self.calls))

    def test_server_mode_falls_back_to_the_local_count(self):
        context = CallContext("external", "write", history_id="h", version=1)
        with FakeServer([(500, {}), (200, completion("x", 2))]) as srv:
            self.client(srv, "server").chat(MESSAGES, context, prompt_sha256=None)
        self.assertEqual([(r.status, r.input_tokens) for r in read_calls(self.calls)],
                         [("failed", 13), ("ok", 13)])

    def test_unknown_source_is_refused(self):
        with self.assertRaises(ValueError):
            Endpoint(base_url="http://x/v1", served_model="m", model_label="m", input_tokens="x")


class TokenizerJsonCounterTest(Base):
    def test_counts_contents_plus_the_chat_overhead(self):
        path = word_tokenizer(self.tmp / "tokenizer.json")
        counter = TokenizerJsonCounter("t", path, sha256_file(path))
        self.assertEqual(counter.count_text("fixed prefix"), 2)
        self.assertEqual(counter.count_messages(MESSAGES), (2 + 3) + (3 + 3) + 3)

    def test_a_changed_file_is_refused(self):
        path = word_tokenizer(self.tmp / "tokenizer.json")
        with self.assertRaises(TokenizerPinError):
            TokenizerJsonCounter("t", path, "0" * 64)


class EngineLLMConfigTest(Base):
    def write(self, config: dict) -> Path:
        path = self.tmp / "engine.yaml"
        path.write_text(yaml.safe_dump(config), encoding="utf-8")
        return path

    def test_native_config_differs_from_graphiti_only_by_its_llm(self):
        native, plain = drive.load_engine_config(NATIVE), drive.load_engine_config(PLAIN)
        llm = native.pop("engine_llm")
        native.pop("description"), plain.pop("description")
        self.assertEqual(native, plain)
        self.assertEqual((llm["label"], llm["input_tokens"], llm["auth_header"]),
                         ("gpt-4.1-mini@2025-04-14", "server", "api-key"))
        self.assertEqual(llm["base_url_env"], "AZURE_OPENAI_ENDPOINT")
        self.assertFalse(any("://" in str(v) for v in llm.values()))  # no URL in the repository

    def test_bad_engine_llm_is_refused(self):
        base = {"engine": "raw", "params": {}}
        for bad in ({k: v for k, v in spec().items() if k != "label"}, {**spec(), "url": "x"}):
            with self.assertRaises(ValueError):
                drive.load_engine_config(self.write({**base, "engine_llm": bad}))
        self.assertIn("engine_llm", drive.load_engine_config(self.write({**base,
                                                                         "engine_llm": spec()})))

    def test_missing_environment_variables_are_named_without_values(self):
        with mock.patch.dict(os.environ, {"T_DEPLOYMENT": "dep-1"}, clear=False):
            os.environ.pop("T_URL", None), os.environ.pop("T_KEY", None)
            with self.assertRaises(RuntimeError) as caught:
                drive.engine_llm_endpoint(spec())
        self.assertIn("T_URL", str(caught.exception))
        self.assertIn("T_KEY", str(caught.exception))
        self.assertNotIn("dep-1", str(caught.exception))


class EngineLLMModelTest(Base):
    def test_engine_chat_goes_to_its_llm_and_the_rest_stays_on_the_base_model(self):
        tokenizer = word_tokenizer(self.tmp / "tokenizer.json")
        engine_spec = spec(tokenizer={"sha256": sha256_file(tokenizer)}, backoff_s=0,
                           transport_attempts=2)
        hosted = [(429, {}), (200, completion('{"ok": true}', 4, prompt_tokens=50, cached=0))]
        with FakeServer(hosted) as llm_srv, FakeServer([]) as base_srv, \
                FakeServer([]) as emb_srv:
            emb_srv.replies.append((200, {"data": [{"index": 0, "embedding": [1.0, 0.0]}],
                                          "usage": {"prompt_tokens": 1}}))
            base = ClientModel(
                ChatClient(Endpoint(base_url=base_srv.base_url, served_model="q",
                                    model_label="org/q@" + "0" * 40, timeout_s=5.0),
                           self.ledger, WordCounter(), sleep=lambda s: None),
                WordCounter(), decoding={"temperature": 0.0},
                embedder=EmbeddingClient(Endpoint(base_url=emb_srv.base_url, served_model="e",
                                                  model_label="org/e@" + "0" * 40,
                                                  timeout_s=5.0),
                                         self.ledger, lambda t: len(t.split()),
                                         sleep=lambda s: None))
            env = {**ENV, "T_URL": llm_srv.base_url}
            settings = drive.ClientSettings(base_srv.base_url)
            with mock.patch.dict(os.environ, env), mock.patch.object(
                    TokenizerJsonCounter, "from_pin",
                    lambda pin: TokenizerJsonCounter("t", tokenizer, pin["sha256"])):
                make = settings.engine_factory({"engine_llm": engine_spec}, seed=7)
                port = make(self.ledger, base)
                tag = CallTag("external", "write", "h", 1)
                result = port.chat(MESSAGES, tag, max_tokens=4096,
                                   response_format={"type": "json_object"})
                vectors = port.embed(["a b"], CallTag("embed", "write", "h", 1))
        self.assertIsInstance(port, EngineLLMModel)
        self.assertTrue(result.ok)
        self.assertEqual(port.model, "hosted/m@2025")
        self.assertEqual(port.count_tokens("a b c"), 3)  # the base model's counter
        self.assertEqual(vectors.vectors, ((1.0, 0.0),))
        self.assertEqual(base_srv.requests, [])  # no chat call reached the answering model
        sent = llm_srv.requests[-1]
        self.assertEqual((sent["api_key"], sent["auth"]), ("secret", None))
        self.assertEqual(sent["body"]["model"], "dep-1")
        self.assertEqual((sent["body"]["seed"], sent["body"]["max_tokens"],
                          sent["body"]["response_format"]), (7, 4096, {"type": "json_object"}))
        self.assertNotIn("chat_template_kwargs", sent["body"])
        records = read_calls(self.calls)
        self.assertEqual([(r.model, r.status, r.input_tokens) for r in records[:2]],
                         [("hosted/m@2025", "failed", 14), ("hosted/m@2025", "ok", 50)])
        self.assertEqual(records[2].model, "org/e@" + "0" * 40)
        check_calls(read_jsonl(self.calls))

    def test_no_engine_llm_means_the_engine_shares_the_run_model(self):
        self.assertIsNone(drive.ClientSettings("http://x/v1").engine_factory({}, seed=0))


if __name__ == "__main__":
    unittest.main()
