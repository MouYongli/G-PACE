"""llm/tokens.py: pins are enforced; real counting is checked only if the HF cache holds a model."""

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from grace.llm.tokens import (
    DSV4ChatCounter,
    HFTokenCounter,
    TokenizerPin,
    TokenizerPinError,
    counter_for_model_config,
    locate_snapshot,
    read_chat_template,
    verify_snapshot,
)

MODELS = Path(__file__).resolve().parents[2] / "configs" / "models"


def pin_for(files: dict[str, bytes]) -> TokenizerPin:
    return TokenizerPin(model="m", hf_repo="org/m", revision="0" * 40,
                        files={k: hashlib.sha256(v).hexdigest() for k, v in files.items()},
                        chat_template="chat_template.jinja")


class PinTest(unittest.TestCase):
    def test_model_configs_parse(self):
        configs = sorted(MODELS.glob("*.yaml"))
        self.assertTrue(configs)
        for path in configs:
            with self.subTest(config=path.name):
                pin = TokenizerPin.from_file(path)
                self.assertEqual(pin.model, path.stem)
                self.assertEqual(len(pin.template_sha256), 64)

    def test_incomplete_pins_fail(self):
        config = yaml.safe_load((MODELS / "qwen3.5-9b.yaml").read_text("utf-8"))
        broken = [
            {**config, "revision": "main"},
            {**config, "tokenizer": {**config["tokenizer"], "chat_template": "other.jinja"}},
            {**config, "tokenizer": {**config["tokenizer"], "files": {"chat_template.jinja": "x"}}},
            {k: v for k, v in config.items() if k != "tokenizer"},
            {k: v for k, v in config.items() if k != "thinking"},  # thinking must be explicit
            {**config, "thinking": True},  # disagrees with enable_thinking: false
            {**config, "thinking": "no"},
        ]
        for item in broken:
            with self.assertRaises(TokenizerPinError):
                TokenizerPin.from_config(item)

    def test_snapshot_mismatch_and_missing_file_fail(self):
        files = {"chat_template.jinja": b"{{ messages }}", "tokenizer.json": b"{}"}
        pin = pin_for(files)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, data in files.items():
                (root / name).write_bytes(data)
            verify_snapshot(pin, root)
            (root / "tokenizer.json").write_bytes(b"{ }")
            with self.assertRaisesRegex(TokenizerPinError, "tokenizer.json: sha256"):
                verify_snapshot(pin, root)
            (root / "chat_template.jinja").unlink()
            with self.assertRaisesRegex(TokenizerPinError, "chat_template.jinja: missing"):
                verify_snapshot(pin, root)

    def test_uncached_revision_is_reported_not_downloaded(self):
        pin = pin_for({"chat_template.jinja": b""})
        with self.assertRaises(TokenizerPinError):
            locate_snapshot(TokenizerPin(**{**pin.__dict__, "hf_repo": "grace-test/absent"}))


class ChatTemplateFileTest(unittest.TestCase):
    def test_jinja_file_and_embedded_json_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            jinja = Path(tmp) / "chat_template.jinja"
            jinja.write_text("{{ messages }}", encoding="utf-8")
            self.assertEqual(read_chat_template(jinja), "{{ messages }}")
            config = Path(tmp) / "tokenizer_config.json"
            config.write_text(json.dumps({"chat_template": "{% for m in messages %}{% endfor %}"}),
                              encoding="utf-8")
            self.assertEqual(read_chat_template(config), "{% for m in messages %}{% endfor %}")
            config.write_text(json.dumps({"model_max_length": 8}), encoding="utf-8")
            with self.assertRaises(TokenizerPinError):
                read_chat_template(config)


class CachedModelTest(unittest.TestCase):
    """Runs against every pinned model found in the local cache; skips when none is."""

    def test_pinned_counters_count_the_chat_template(self):
        found = 0
        for path in sorted(MODELS.glob("*.yaml")):
            if yaml.safe_load(path.read_text("utf-8"))["tokenizer"].get("backend") is not None:
                continue  # not a transformers chat template (the renderer's Tekken pin; T015)
            pin = TokenizerPin.from_file(path)
            try:
                snapshot = locate_snapshot(pin)
            except TokenizerPinError:
                continue
            found += 1
            with self.subTest(model=pin.model):
                counter = HFTokenCounter(pin, snapshot)
                messages = [{"role": "system", "content": "Answer briefly."},
                            {"role": "user", "content": "How long is my commute now?"}]
                rendered = counter.render(messages)
                self.assertIn("How long is my commute now?", rendered)
                total = counter.count_messages(messages)
                self.assertGreater(total, counter.count_text("Answer briefly.") +
                                   counter.count_text("How long is my commute now?"))
                self.assertEqual(counter.count_text(""), 0)
                # a tampered template file is refused
                with tempfile.TemporaryDirectory() as tmp:
                    copy = Path(tmp) / "snap"
                    shutil.copytree(snapshot, copy, symlinks=False,
                                    ignore=shutil.ignore_patterns("*.safetensors"))
                    (copy / pin.chat_template).write_text("{{ 'x' }}", encoding="utf-8")
                    with self.assertRaises(TokenizerPinError):
                        HFTokenCounter(pin, copy)
        if not found:
            self.skipTest("no pinned model in the local Hugging Face cache")


class DSV4ChatCounterTest(unittest.TestCase):
    """Chat-mode rendering of the DeepSeek-V4 judge. The expected strings are the output of the
    snapshot's own `encoding_dsv4.encode_messages(messages, thinking_mode="chat")`."""

    def test_render_matches_the_model_encoder(self):
        bos, user, asst, eos = ("<｜begin▁of▁sentence｜>", "<｜User｜>", "<｜Assistant｜>",
                                "<｜end▁of▁sentence｜>")
        cases = [
            ([{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}],
             f"{bos}S{user}Q{asst}</think>"),
            ([{"role": "user", "content": "hi"}], f"{bos}{user}hi{asst}</think>"),
            ([{"role": "system", "content": "s"}, {"role": "user", "content": "u1"},
              {"role": "assistant", "content": "a1"}, {"role": "user", "content": "u2"}],
             f"{bos}s{user}u1{asst}</think>a1{eos}{user}u2{asst}</think>"),
        ]
        for messages, expected in cases:
            self.assertEqual(DSV4ChatCounter.render(messages), expected)

    def test_unsupported_messages_are_refused(self):
        with self.assertRaises(ValueError):
            DSV4ChatCounter.render([{"role": "tool", "content": "x"}])
        with self.assertRaises(ValueError):
            DSV4ChatCounter.render([{"role": "user", "content": "x", "tools": []}])

    def test_judge_pin_selects_the_counter_or_reports_the_missing_snapshot(self):
        path = MODELS / "deepseek-v4-flash-0731.yaml"
        pin = TokenizerPin.from_file(path)
        self.assertFalse(pin.thinking)
        self.assertEqual(pin.template_kwargs, {"enable_thinking": False})
        try:
            counter = counter_for_model_config(path)
        except TokenizerPinError:
            self.skipTest("DeepSeek-V4-Flash-0731 is not in the local Hugging Face cache")
        self.assertIsInstance(counter, DSV4ChatCounter)
        messages = [{"role": "system", "content": "Grade."},
                    {"role": "user", "content": "Question: q"}]
        self.assertEqual(counter.count_messages(messages),
                         counter.count_text(DSV4ChatCounter.render(messages)))
        self.assertEqual(counter.count_text(""), 0)


if __name__ == "__main__":
    unittest.main()
