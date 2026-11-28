"""E001 judge stage (`grace.cli.pilot judge`, `grace.cli.run.judge`) on the synthetic fixtures.

A fake-backend system run on the LoCoMo fixture is judged through `grace.llm` with a scripted
transport standing in for the remote judge: no network, no key, no benchmark data.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from grace.cli import pilot as cli
from grace.cli.run import judge as stage
from grace.eval.runner.harness import drive
from grace.eval.runner.harness.models import FakeBackend
from tests.contracts.test_experiment_run import check_run
from tests.integration.test_pilot import CODE, CONFIG, FIXTURES, ROOT, WordCounter, fixture_records
from tests.llm.fakes import completion

JUDGE_CONFIG = ROOT / "configs" / "judges" / "blind.yaml"
PRICES = {"input": 0.484, "cached_input": 0.121, "output": 1.936}
ENV = {"AZURE_OPENAI_ENDPOINT": "http://judge.invalid/openai/v1",
       "AZURE_OPENAI_DEPLOYMENT": "judge-deployment", "AZURE_OPENAI_API_KEY": "not-a-key"}


def http_error(code, body):
    return urllib.error.HTTPError("http://judge.invalid", code, "error", {},
                                  io.BytesIO(json.dumps(body).encode()))


class ScriptedPost:
    """Replies to every request with `reply(payload)`; keeps payloads and headers."""

    def __init__(self, reply):
        self.reply, self.requests = reply, []

    def __call__(self, url, payload, headers, timeout):
        self.requests.append({"url": url, "payload": payload, "headers": headers})
        result = self.reply(payload)
        if isinstance(result, Exception):
            raise result
        return result


class JudgeStageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.exp = cli.load_experiment(CONFIG)
        self.probe, _ = cli.run_probe(CONFIG, self.tmp / "probe", counter=WordCounter(),
                                      loader=fixture_records, code=CODE, command="test")
        result = drive.run_system(
            engine_config=ROOT / "configs" / "engines" / "full-history-cached.yaml",
            records=FIXTURES / "locomo", budget=None, experiment="E001",
            run_root=self.tmp / "system", code=CODE, command="test",
            backend_factory=lambda c: FakeBackend(prefix_caching=c))
        self.system = result.run_dir
        self.predictions = stage.read_jsonl(self.system / "predictions.jsonl")
        self.answers = [p for p in self.predictions if p["output"] == "answer"]
        self.assertTrue(self.answers, "the fake run must produce answers to judge")

    def judge(self, post, max_usd=2.0, limit=None):
        with mock.patch.dict(os.environ, ENV):
            return self._judge(post, max_usd, limit)

    def _judge(self, post, max_usd, limit):
        return cli.run_judging(
            self.exp, CONFIG, [self.system], self.tmp / "judge", judge_config_path=JUDGE_CONFIG,
            judge_model="comparison_model", prices=PRICES, max_usd=max_usd, workers=2,
            limit=limit, loader=fixture_records, counter=WordCounter(), environ=ENV,
            post=post, code=CODE, command="test")

    def test_judges_every_answer_and_records_server_usage(self):
        post = ScriptedPost(lambda p: dict(completion("CORRECT", 1, prompt_tokens=200, cached=0),
                                           model="gpt-4.1-mini-2025-04-14",
                                           choices=[{"message": {"content": "CORRECT"},
                                                     "finish_reason": "stop"}]))
        (result,) = self.judge(post)
        self.assertEqual(result.status, "completed", result.failure)
        run = check_run(result.run_dir)
        self.assertEqual(run["stage"], "judge")
        self.assertEqual(run["upstream"][0]["run_id"], self.system.name)
        self.assertEqual(run["n_records"], len(self.answers))
        judgements = stage.read_jsonl(result.run_dir / "judgements.jsonl")
        self.assertEqual([j["read_id"] for j in judgements], [p["read_id"] for p in self.answers])
        self.assertEqual({j["verdict"] for j in judgements}, {"correct"})
        self.assertEqual({j["judge"] for j in judgements}, {"blind"})
        # Remote endpoint: api-key header, deployment as model, frozen decoding.
        request = post.requests[0]
        self.assertEqual(request["headers"], {"api-key": "not-a-key"})
        self.assertEqual(request["url"], "http://judge.invalid/openai/v1/chat/completions")
        self.assertEqual(request["payload"]["model"], "judge-deployment")
        self.assertEqual({k: request["payload"][k] for k in ("temperature", "max_tokens", "seed")},
                         {"temperature": 0.0, "max_tokens": 10, "seed": 0})
        calls = stage.read_jsonl(result.run_dir / "calls.jsonl")
        self.assertEqual({(c["call_type"], c["trigger"], c["model"]) for c in calls},
                         {("judge", "evaluation", "gpt-4.1-mini@2025-04-14")})
        usage = stage.read_jsonl(result.run_dir / stage.USAGE_FILE)
        self.assertEqual({u["prompt_tokens"] for u in usage}, {200})
        self.assertEqual({u["server_model"] for u in usage}, {"gpt-4.1-mini-2025-04-14"})
        # Nothing from the environment beyond variable names reaches the run directory.
        for path in result.run_dir.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for value in ENV.values():
                    self.assertNotIn(value, text, path.name)
        # Summary over the judge run.
        summary = cli.judge_summary(self.exp, [result.run_dir], self.probe, PRICES)
        (row,) = summary["runs"]
        self.assertEqual(row["judged_correct"], len(self.answers))
        self.assertEqual(row["usage"]["prompt_tokens"], 200 * len(self.answers))
        self.assertAlmostEqual(summary["usage_total"]["usd"],
                               len(self.answers) * (200 * 0.484 + 1.936) / 1e6, places=6)

    def test_content_filter_counts_as_judge_invalid(self):
        post = ScriptedPost(lambda p: http_error(400, {"error": {
            "code": "content_filter", "innererror": {"code": "ResponsibleAIPolicyViolation"}}}))
        (result,) = self.judge(post, limit=1)
        self.assertEqual(result.status, "completed", result.failure)
        (judgement,) = stage.read_jsonl(result.run_dir / "judgements.jsonl")
        self.assertEqual(judgement["verdict"], "invalid")
        self.assertIsNone(judgement["raw_output"])
        (usage,) = stage.read_jsonl(result.run_dir / stage.USAGE_FILE)
        self.assertEqual((usage["http_status"], usage["error_code"]), (400, "content_filter"))

    def test_authentication_error_fails_the_run(self):
        post = ScriptedPost(lambda p: http_error(401, {"error": {"code": "401"}}))
        (result,) = self.judge(post)
        self.assertEqual(result.status, "failed")
        self.assertIn("authentication", result.failure)

    def test_spend_projection_stops_the_run(self):
        post = ScriptedPost(lambda p: completion("CORRECT", 1, prompt_tokens=10_000_000))
        (result,) = self.judge(post, max_usd=0.01)
        self.assertEqual(result.status, "failed")
        self.assertIn("spend", result.failure)

    def test_run_without_answers_is_skipped_without_loading_gold(self):
        empty = self.tmp / "no-answers"
        shutil.copytree(self.system, empty)
        rows = [dict(p, output="unknown", prediction=None) for p in self.predictions]
        (empty / "predictions.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

        def refuse(slug, spec):
            raise AssertionError("gold loaded for a run with nothing to judge")
        with mock.patch.dict(os.environ, ENV):
            results = cli.run_judging(
                self.exp, CONFIG, [empty], self.tmp / "judge", judge_config_path=JUDGE_CONFIG,
                judge_model="comparison_model", prices=PRICES, max_usd=1.0, workers=1,
                loader=refuse, counter=WordCounter(), environ=ENV,
                post=ScriptedPost(lambda p: AssertionError("no call expected")), code=CODE,
                command="test")
        self.assertEqual(results, [])

    def test_missing_environment_variable_is_refused(self):
        with self.assertRaises(RuntimeError) as ctx:
            stage.remote_endpoint({"provider": "azure-openai", "base_url_env": "A",
                                   "deployment_env": "B", "api_key_env": "C", "model": "m",
                                   "version": "v", "auth_header": "api-key"}, {"A": "x"})
        self.assertIn("B", str(ctx.exception))
        self.assertNotIn("x", str(ctx.exception))

    def local_judge(self, offset):
        """A local judge run whose server reports the local count plus `offset` tokens."""
        from grace.eval.analysis.judging.judge import blind_judge
        from grace.llm.client import ChatClient, Endpoint
        from grace.llm.prompts import load_pinned

        counter = WordCounter()
        post = ScriptedPost(lambda p: completion(
            "INCORRECT", 1, prompt_tokens=counter.count_messages(p["messages"]) + offset))
        usage = stage.UsageTransport(post)
        tasks, gold, data = cli.judge_inputs("locomo", self.exp["benchmarks"]["locomo"],
                                             fixture_records)
        prompt = load_pinned("judge", cli.PROMPT_REGISTRY)
        endpoint = Endpoint(base_url="http://127.0.0.1:1/v1", served_model="judge",
                            model_label="org/judge@" + "0" * 40,
                            chat_template_kwargs={"enable_thinking": False})
        result = stage.run_judge(
            self.system, run_root=self.tmp / "local", experiment="E001", judge_name="blind",
            make_judge=lambda client: blind_judge("blind", client, prompt, {"temperature": 0}),
            make_client=lambda ledger: ChatClient(endpoint, ledger, counter, transport=usage),
            usage=usage, tasks=tasks, gold=gold, data=data, resolved={}, config_path="x",
            workers=2, code=CODE, command="test", device="test", check_input_tokens=True)
        return result, post

    def test_local_judge_checks_input_tokens_against_the_server(self):
        result, post = self.local_judge(0)
        self.assertEqual(result.status, "completed", result.failure)
        self.assertEqual(post.requests[0]["payload"]["chat_template_kwargs"],
                         {"enable_thinking": False})
        log = (result.run_dir / "run.log").read_text(encoding="utf-8")
        self.assertIn(f"input-token check: {len(self.answers)} of {len(self.answers)}", log)
        result, _ = self.local_judge(1)
        self.assertEqual(result.status, "failed")
        self.assertIn("input-token check", result.failure)


class UsageTransportTest(unittest.TestCase):
    def test_rate_limit_waits_before_the_retry(self):
        waits = []

        def post(*args):
            raise urllib.error.HTTPError("u", 429, "busy", {"Retry-After": "7"},
                                         io.BytesIO(b"{}"))
        transport = stage.UsageTransport(post, sleep=waits.append)
        with self.assertRaises(OSError):
            transport("u", {}, {}, 1.0)
        self.assertEqual(waits, [7.0])
        self.assertEqual(transport.take()["http_status"], 429)
        self.assertIsNone(transport.take())

    def test_spend_guard(self):
        guard = stage.SpendGuard(1.0, planned_calls=100, prices=PRICES)
        for _ in range(10):
            guard.add({"prompt_tokens": 1000, "completion_tokens": 1})
        self.assertAlmostEqual(guard.spent, 10 * (1000 * 0.484 + 1.936) / 1e6)
        with self.assertRaises(stage.JudgeAbort):
            guard.add({"prompt_tokens": 3_000_000, "cached_tokens": 0})
        self.assertAlmostEqual(stage.usd({"prompt_tokens": 1_000_000, "cached_tokens": 500_000,
                                          "completion_tokens": 0}, PRICES), 0.3025)


if __name__ == "__main__":
    unittest.main()
