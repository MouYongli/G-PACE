"""Model renderer of the change sequences (task T015, design section 7; D006): prompt input, seeds
per attempt, call records through grace.llm, retries and template fallback, mention checks,
per-family fallback statistics, the Tekken token counter and the cross-check's node label.

No model is called: a fake transport stands in for the server.
"""

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from grace.cli.data.changeseq_crosscheck import node_of
from grace.eval.datasets.changeseq.build import (
    DatasetConfig,
    build_dataset,
    generate_sequence,
)
from grace.eval.datasets.changeseq.model_renderer import (
    DEFAULT_MODEL_CONFIG,
    PROMPT_REGISTRY,
    ModelRenderer,
    TekkenCounter,
    clean,
    prompt_values,
)
from grace.eval.datasets.changeseq.render import (
    RenderRequest,
    check_output,
    template_sentence,
)
from grace.eval.datasets.changeseq.template_families import CellConfig, FamilyError, ScheduleSpec
from grace.llm.client import ChatClient, Endpoint
from grace.llm.prompts import load_pinned
from grace.llm.records import CallLedger, read_calls
from grace.llm.tokens import TokenizerPin, TokenizerPinError, locate_snapshot

SCHEDULES = (ScheduleSpec("U", m=5),)


class WordCounter:
    name = "words"

    def count_text(self, text):
        return len(text.split())

    def count_messages(self, messages):
        return sum(len(m["content"].split()) for m in messages)


class FakeModel:
    """Transport that answers with `reply(user_message, payload)`."""

    def __init__(self, reply):
        self.reply, self.payloads = reply, []

    def __call__(self, url, payload, headers, timeout):
        self.payloads.append(payload)
        text = self.reply(payload["messages"][-1]["content"], payload)
        return {"choices": [{"message": {"content": text}}],
                "usage": {"completion_tokens": 5, "prompt_tokens": 7}}


def required_of(user: str) -> list[str]:
    line = next(x for x in user.splitlines() if x.startswith("Must mention: "))
    value = line.removeprefix("Must mention: ")
    return [] if value == "nothing" else value.split("; ")


def meaning_of(user: str) -> str:
    return next(x for x in user.splitlines() if x.startswith("Meaning: ")).removeprefix(
        "Meaning: ")


def good_reply(user, payload):
    """A paraphrase that mentions every required value (fillers: a fixed line)."""
    req = required_of(user)
    return ("Okay, noted: " + ", ".join(req) + ".") if req else "\"Sounds good.\""


def renderer(tmp: Path, reply) -> tuple[ModelRenderer, FakeModel, CallLedger]:
    config = yaml.safe_load(DEFAULT_MODEL_CONFIG.read_text(encoding="utf-8"))
    fake = FakeModel(reply)
    ledger = CallLedger(tmp / "calls.jsonl", "R1")
    pin = TokenizerPin.from_config(config)
    client = ChatClient(Endpoint.for_model(pin, "http://fake/v1", config["served_name"]),
                        ledger, WordCounter(), transport=fake, sleep=lambda s: None)
    prompt = load_pinned("render-changeseq", PROMPT_REGISTRY)
    return ModelRenderer(client, prompt, config, "configs/models/mistral-small-3.2-24b.yaml"), \
        fake, ledger


def cell(length=60):
    return CellConfig(family="train-travel", length=length, density=30.0, schedules=SCHEDULES)


class ModelRendererTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepted_messages_calls_and_seeds(self):
        r, fake, ledger = renderer(self.dir, good_reply)
        b = generate_sequence("train-travel", cell(), 7, "s", renderer=r)
        self.assertEqual(b.rendered.fallback_rate, 0.0)
        self.assertEqual(len(fake.payloads), len(b.plan.log))       # one attempt each
        calls = read_calls(ledger.path)
        self.assertEqual({(c.call_type, c.trigger, c.category) for c in calls},
                         {("render", "write", "W")})
        self.assertEqual({c.history_id for c in calls}, {"s"})
        self.assertEqual([c.version for c in calls], [m.record.version for m in
                                                     b.rendered.messages])
        self.assertEqual({c.prompt_sha256 for c in calls}, {r.prompt.sha256})
        self.assertEqual({c.model for c in calls}, {r.name})
        seeds = [p["seed"] for p in fake.payloads]
        self.assertEqual(len(set(seeds)), len(seeds))
        self.assertEqual({p["temperature"] for p in fake.payloads}, {0.15})
        texts = [m.text for m in b.rendered.messages]
        self.assertIn("Sounds good.", texts)                       # quotes removed
        self.assertTrue(any(t.startswith("Okay, noted: ") for t in texts))
        self.assertEqual(b.renderer["kind"], "model")
        self.assertEqual(b.renderer["revision"], "95a6d26c4bfb886c58daf9d3f7332c857cb27b43")
        self.assertEqual(b.renderer["prompt_sha256"], r.prompt.sha256)
        self.assertEqual(r.token_check()["calls"], len(calls))

    def test_prompt_sees_only_earlier_messages_and_the_section_7_inputs(self):
        r, fake, _ = renderer(self.dir, good_reply)
        b = generate_sequence("train-travel", cell(), 7, "s", renderer=r)
        lines = [f"{m.record.speaker}: {m.text}" for m in b.rendered.messages]
        for i, payload in enumerate(fake.payloads):
            user = payload["messages"][-1]["content"]
            previous = user.split("Earlier messages (oldest first):\n", 1)[1].split(
                "\n\nMeaning: ", 1)[0]
            want = "\n".join(lines[max(0, i - 6):i]) or "(none, this is the first message)"
            self.assertEqual(previous, want)
            for field in ("Speaker: ", "Date: ", "Meaning: ", "Facts: ",
                          "Discourse requirement: ", "Must not mention: "):
                self.assertIn(field, user)
        corrections = [p["messages"][-1]["content"] for p, m in zip(
            fake.payloads, b.rendered.messages, strict=True) if m.record.cue.get("discourse")
            == "correction"]
        self.assertTrue(corrections)
        for user in corrections:
            self.assertIn("must signal that an earlier statement was wrong", user)

    def test_failed_attempts_retry_with_new_seeds_then_fall_back(self):
        def reply(user, payload):
            if required_of(user):
                return "This event changed nothing."          # meta-language, no values
            return "Sure."
        r, fake, ledger = renderer(self.dir, reply)
        b = generate_sequence("train-travel", cell(), 7, "s", renderer=r)
        rows = [(m, x) for m, x in zip(b.rendered.messages, b.rendered.log, strict=True)
                if m.record.cue.get("required")]
        self.assertTrue(rows)
        for m, x in rows:
            self.assertTrue(x["fallback"])
            self.assertEqual(len(x["attempts"]), 3)
            self.assertEqual(x["final_failures"], [])
            self.assertIn("text", x["attempts"][0])            # rejected text is logged
            self.assertNotIn("event", m.text.casefold())
        by_version = {}
        for p in fake.payloads:
            by_version.setdefault(p["messages"][-1]["content"], []).append(p["seed"])
        retried = [s for s in by_version.values() if len(s) == 3]
        self.assertTrue(retried)
        for seeds in retried:
            self.assertEqual(seeds, [seeds[0], seeds[0] + 1, seeds[0] + 2])
        self.assertEqual(len(read_calls(ledger.path)), len(fake.payloads))

    def test_dataset_records_renderer_and_fallback_rate_per_family(self):
        def reply(user, payload):
            return "Hmm." if required_of(user) else "Sure."
        r, _, _ = renderer(self.dir, reply)
        config = DatasetConfig.from_dict({
            "dataset": "d", "seed": 1,
            "renderer": {"kind": "model", "workers": 2},
            "cells": [{"families": ["train-travel", "car-rental"], "density": [30],
                       "length": 40, "schedules": ["U5"], "primary_schedule": "U5",
                       "sequences_per_family": 1}]})
        self.assertEqual(config.renderer_kind, "model")
        dataset = build_dataset(config, self.dir / "ds", "0" * 40, renderer=r, workers=2)
        self.assertEqual(sorted(dataset["render"]), ["car-rental", "train-travel"])
        for stats in dataset["render"].values():
            self.assertGreater(stats["fallback_rate"], 0.10)
            self.assertTrue(stats["over_limit"])
            self.assertEqual(stats["attempts"], stats["messages"] + 2 * stats["fallbacks"])
        self.assertEqual(dataset["renderer"]["model"], "mistral-small-3.2-24b")
        self.assertEqual(dataset["generator"]["version"], "changeseq-generator-2")
        on_disk = json.loads((self.dir / "ds" / "dataset.json").read_text("utf-8"))
        self.assertEqual(on_disk["render"], dataset["render"])

    def test_dataset_config_renderer_forms(self):
        base = {"dataset": "d", "seed": 1, "cells": []}
        self.assertEqual(DatasetConfig.from_dict(base).renderer_kind, "template")
        for bad in ("mistral", {"kind": "other"}, {"kind": "model", "url": "x"}):
            with self.assertRaises(FamilyError):
                DatasetConfig.from_dict({**base, "renderer": bad})


class MentionCheckTest(unittest.TestCase):
    def req(self, required=(), forbidden=(), aliases=None):
        return RenderRequest("s", 1, "m1", "user", "2026-04-01", (), "first", {"stmt": "x"},
                             None, tuple(required), (), tuple(forbidden), (), 0,
                             aliases=aliases or {})

    def test_normalised_values_and_hours(self):
        r = self.req(required=("09:41", "ICE 947"), forbidden=("08:00",))
        self.assertEqual(check_output("ICE 947 arrives at 9:41.", r), [])
        self.assertEqual(check_output("ice 947 arrives at 09:41, not 18:00.", r), [])
        self.assertTrue(check_output("ICE 947 arrives at 8:00 and 09:41.", r))
        self.assertTrue(check_output("ICE 9470 arrives at 09:41.", r))

    def test_date_alias(self):
        r = self.req(required=("2 April 2026",), aliases={"2 April 2026": ("2 April",)})
        self.assertEqual(check_output("I lived there from 2 April.", r), [])
        self.assertTrue(check_output("I lived there from 12 April.", r))
        self.assertTrue(check_output("I lived there from 2 April.", self.req(
            required=("2 April 2026",))))

    def test_clean(self):
        self.assertEqual(clean(' "Assistant: Hello there." '), "Hello there.")
        self.assertEqual(clean("User: 'Fine.'"), "Fine.")
        self.assertEqual(clean(None), "")

    def test_template_sentence_is_the_meaning(self):
        r = self.req()
        values = prompt_values(RenderRequest(
            "s", 1, "m1", "user", "2026-04-01", (), "first", {"stmt": "I speak Greek"},
            "correction", ("Greek",), (), ("Dutch",), ("user: hi",), 5))
        self.assertEqual(values["meaning"], "I speak Greek.")
        self.assertEqual(values["date"], "1 April 2026")
        self.assertEqual(values["discourse"], "must signal that an earlier statement was wrong")
        self.assertEqual((values["required"], values["forbidden"]), ("Greek", "Dutch"))
        self.assertEqual(template_sentence(r), "X.")


class TekkenCounterTest(unittest.TestCase):
    """Runs only where the renderer snapshot is in the local Hugging Face cache."""

    def test_counts_match_mistral_common(self):
        pin = TokenizerPin.from_file(DEFAULT_MODEL_CONFIG)
        try:
            snapshot = locate_snapshot(pin)
        except TokenizerPinError:
            self.skipTest("renderer snapshot not in the local cache")
        counter = TekkenCounter(pin, snapshot)
        # Reference counts from mistral-common 1.13.1 (InstructTokenizerV11) on this snapshot.
        self.assertEqual(counter.count_messages(
            [{"role": "system", "content": "Sys line.\nTwo"},
             {"role": "user", "content": "Hello there, 3 cats."}]), 16)
        self.assertEqual(counter.count_messages(
            [{"role": "user", "content": "Hello there, 3 cats."}]), 10)
        self.assertEqual(counter.count_messages(
            [{"role": "system", "content": "S"}, {"role": "user", "content": "a"},
             {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]), 12)
        with self.assertRaises(ValueError):
            counter.count_messages([{"role": "user", "content": "a"},
                                    {"role": "system", "content": "b"}])


class CrosscheckNodeTest(unittest.TestCase):
    def test_node_from_run_directory(self):
        runs = Path("/r/runs")
        self.assertEqual(node_of(runs / "T017" / "artifacts" / "x", runs), "T017")
        self.assertEqual(node_of(runs / "E002" / "x", runs), "E002")
        self.assertIsNone(node_of(runs / "scratch" / "x", runs))


if __name__ == "__main__":
    unittest.main()
