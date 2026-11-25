"""llm/tokens.py: pins are enforced; real counting is checked only if the HF cache holds a model."""

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from grace.llm.tokens import (
    HFTokenCounter,
    TokenizerPin,
    TokenizerPinError,
    locate_snapshot,
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


class CachedModelTest(unittest.TestCase):
    """Runs against every pinned model found in the local cache; skips when none is."""

    def test_pinned_counters_count_the_chat_template(self):
        found = 0
        for path in sorted(MODELS.glob("*.yaml")):
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


if __name__ == "__main__":
    unittest.main()
