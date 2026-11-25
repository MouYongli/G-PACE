"""Blind judge and the official LongMemEval judge, run through llm/ against a fake server."""

import json
import tempfile
import unittest
from pathlib import Path

from grace.eval.analysis.judging.judge import (
    blind_inputs,
    blind_judge,
    parse_label,
    read_judgements,
    write_judgements,
)
from grace.eval.analysis.judging.official import (
    TEMPLATES,
    longmemeval_judge,
    parse_yes,
    template_for,
)
from grace.llm.client import ChatClient, Endpoint
from grace.llm.prompts import load_pinned
from grace.llm.records import CallLedger, read_calls
from tests.llm.fakes import FakeServer, WordCounter, completion

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "configs" / "common" / "prompts.yaml"
FIXTURES = ROOT / "tests" / "fixtures" / "benchmarks"
SECRETS = ("GRACE-variant-B", "E001-20261125T000000Z-dead", "D1:1", "sess_b:0", "raw secret")


def first(slug, name):
    return json.loads((FIXTURES / slug / name).read_text("utf-8").splitlines()[0])


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = CallLedger(Path(self.tmp.name) / "calls.jsonl", "J-run")
        self.task = first("longmemeval-s", "read_tasks.jsonl")
        self.gold = first("longmemeval-s", "gold.jsonl")
        self.prediction = dict(first("longmemeval-s", "predictions.jsonl"),
                               raw_output="raw secret", context_ids=["sess_b:0"],
                               metadata={"engine": "GRACE-variant-B",
                                         "run_id": "E001-20261125T000000Z-dead"})

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, server):
        endpoint = Endpoint(server.base_url, "judge-model", "judge@" + "1" * 40, timeout_s=5.0)
        return ChatClient(endpoint, self.ledger, WordCounter(), sleep=lambda s: None)

    def test_judge_sees_only_question_reference_and_response(self):
        inputs = blind_inputs(self.task, self.gold, self.prediction)
        self.assertEqual(set(inputs), {"question", "reference", "response"})
        prompt = load_pinned("judge", REGISTRY)
        with FakeServer([(200, completion("CORRECT", 1))]) as srv:
            judgement = blind_judge("blind", self.client(srv), prompt,
                                    {"temperature": 0.0, "max_tokens": 10}).judge(
                self.task, self.gold, self.prediction)
        sent = json.dumps(srv.requests[0]["body"])
        for secret in SECRETS:
            self.assertNotIn(secret, sent)
        self.assertIn(self.task["question"], sent)
        self.assertEqual(judgement.verdict, "correct")
        self.assertEqual((judgement.read_id, judgement.annotation, judgement.judge),
                         (self.task["read_id"], "cleaned", "blind"))
        [record] = read_calls(self.ledger.path)
        self.assertEqual((record.call_type, record.category, record.call_id),
                         ("judge", "evaluation", judgement.call_id))
        self.assertEqual(record.prompt_sha256, prompt.sha256)

    def test_unparsable_verdict_is_invalid(self):
        prompt = load_pinned("judge", REGISTRY)
        with FakeServer([(200, completion("Probably correct", 2))]) as srv:
            judgement = blind_judge("blind", self.client(srv), prompt, {}).judge(
                self.task, self.gold, self.prediction)
        self.assertEqual(judgement.verdict, "invalid")
        self.assertEqual(read_calls(self.ledger.path)[0].status, "invalid_output")

    def test_parse_rules(self):
        cases = {"CORRECT": "correct", " incorrect.\n": "incorrect", "Correct": "correct",
                 "CORRECT, because": "invalid", "": "invalid", None: "invalid"}
        for text, verdict in cases.items():
            self.assertEqual(parse_label(text), verdict)
        self.assertEqual(parse_yes("Yes."), "correct")
        self.assertEqual(parse_yes("no"), "incorrect")
        self.assertEqual(parse_yes(" "), "invalid")

    def test_only_answers_are_judged(self):
        for output in ("unknown", "invalid"):
            with self.assertRaises(ValueError):
                blind_inputs(self.task, self.gold, dict(self.prediction, output=output,
                                                        prediction=None))
        state_task = first("multiwoz", "read_tasks.jsonl")
        with self.assertRaises(ValueError):
            blind_inputs(state_task, first("multiwoz", "gold.jsonl"),
                         first("multiwoz", "predictions.jsonl"))

    def test_longmemeval_template_choice(self):
        self.assertEqual(template_for({"question_type": "knowledge-update",
                                       "abstention": False}, "q1"), "knowledge-update")
        self.assertEqual(template_for({"question_type": "multi-session"}, "q1"), "default")
        self.assertEqual(template_for({"question_type": "temporal-reasoning"}, "q1_abs"),
                         "abstention")
        self.assertEqual(template_for({"question_type": "multi-session",
                                       "abstention": True}, "q1"), "abstention")
        with self.assertRaises(ValueError):
            template_for({"question_type": "other"}, "q1")

    def test_longmemeval_judge_uses_the_typed_template(self):
        prompts = {t: load_pinned(f"judge-longmemeval-{t}", REGISTRY) for t in TEMPLATES}
        with FakeServer([(200, completion("yes", 1))]) as srv:
            judge = longmemeval_judge("longmemeval-official", self.client(srv), prompts, {})
            judgement = judge.judge(self.task, self.gold, self.prediction)
        [message] = srv.requests[0]["body"]["messages"]  # upstream sends one user message
        self.assertIn("updated answer", message["content"])  # knowledge-update template
        self.assertTrue(message["content"].endswith("Answer yes or no only."))
        self.assertEqual(judgement.verdict, "correct")
        self.assertEqual(read_calls(self.ledger.path)[0].prompt_sha256,
                         prompts["knowledge-update"].sha256)

    def test_judgements_file_round_trip(self):
        prompt = load_pinned("judge", REGISTRY)
        with FakeServer([(200, completion("INCORRECT", 1))]) as srv:
            judgement = blind_judge("blind", self.client(srv), prompt, {}).judge(
                self.task, self.gold, self.prediction)
        path = Path(self.tmp.name) / "judgements.jsonl"
        write_judgements(path, [judgement])
        self.assertEqual(read_judgements(path, "blind"), {judgement.read_id: judgement})
        with self.assertRaises(FileExistsError):
            write_judgements(path, [judgement])
        with self.assertRaises(ValueError):
            write_judgements(Path(self.tmp.name) / "dup.jsonl", [judgement, judgement])


if __name__ == "__main__":
    unittest.main()
