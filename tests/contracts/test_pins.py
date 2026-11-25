"""Pins of T004: prompts, schemas, judges, scorers, budgets and model tokenizer pins.

Every prompt under resources/prompts/ is registered in configs/common/prompts.yaml with the hash
that call records carry; every judge config names registered prompts with the same hash; every
scorer's code path resolves. A changed prompt fails here until its pin is updated deliberately.
"""

import hashlib
import importlib
import unittest
from pathlib import Path

import yaml

from grace.llm.prompts import PROMPTS_DIR, load_prompt, load_registry
from grace.llm.records import CALL_TYPES
from grace.llm.structured import SCHEMAS_DIR, load_schema
from grace.llm.tokens import TokenizerPin

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"
REGISTRY = CONFIGS / "common" / "prompts.yaml"
POLICIES = {"count_as_wrong", "exclude_and_report"}


def yaml_file(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class PromptPinTest(unittest.TestCase):
    def test_every_prompt_is_registered_with_its_hash(self):
        registry = load_registry(REGISTRY)
        on_disk = {p.name for p in PROMPTS_DIR.iterdir() if p.is_dir()}
        self.assertEqual(on_disk, set(registry))
        for name, entry in registry.items():
            with self.subTest(prompt=name):
                prompt = load_prompt(name)
                self.assertEqual(prompt.sha256, entry["sha256"])
                self.assertIn(entry["call_type"], CALL_TYPES)
                if entry["schema"] is None:
                    self.assertIsNone(entry["schema_sha256"])
                else:
                    path = SCHEMAS_DIR.parent / f"{entry['schema']}.json"
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                     entry["schema_sha256"])
                    load_schema(Path(entry["schema"]).name)

    def test_judge_configs_pin_registered_prompts(self):
        registry = load_registry(REGISTRY)
        configs = sorted((CONFIGS / "judges").glob("*.yaml"))
        self.assertEqual({p.stem for p in configs}, {"blind", "longmemeval-official"})
        for path in configs:
            config = yaml_file(path)
            with self.subTest(judge=path.stem):
                self.assertEqual(config["judge"], path.stem)
                prompts = config.get("prompts") or {"-": {"prompt": config["prompt"],
                                                          "sha256": config["prompt_sha256"]}}
                for item in prompts.values():
                    self.assertEqual(registry[item["prompt"]]["call_type"], "judge")
                    self.assertEqual(registry[item["prompt"]]["sha256"], item["sha256"])
                self.assertEqual(config["decoding"]["temperature"], 0.0)
                self.assertEqual(config["judged_outputs"], ["answer"])
                # D006: every judge names its model; Azure keys come only from the environment
                for model in (config["model"], config.get("comparison_model")):
                    if model is None:
                        continue
                    self.assertIn(model["provider"], {"vllm", "azure-openai"})
                    if model["provider"] == "vllm":
                        self.assertEqual(len(model["revision"]), 40)
                    else:
                        self.assertEqual(model["auth_header"], "api-key")
                        self.assertTrue(model["api_key_env"].isupper())
                expected = {"blind": "vllm", "longmemeval-official": "azure-openai"}
                self.assertEqual(config["model"]["provider"], expected[path.stem])


class ScorerRegistryTest(unittest.TestCase):
    def test_scorers_resolve_and_are_complete(self):
        registry = yaml_file(CONFIGS / "common" / "scorers.yaml")["benchmarks"]
        benchmarks = {p.stem for p in (CONFIGS / "benchmarks").glob("*.yaml")}
        self.assertEqual(set(registry), benchmarks)
        judges = {p.stem for p in (CONFIGS / "judges").glob("*.yaml")}
        for slug, entry in registry.items():
            for metric in entry["metrics"]:
                with self.subTest(benchmark=slug, metric=metric["name"]):
                    module, _, name = metric["code"].partition(":")
                    self.assertTrue(callable(getattr(importlib.import_module(module), name)))
                    self.assertIn(metric["direction"], {"higher", "lower"})
                    self.assertIn(metric["invalid_policy"], POLICIES)
                    self.assertTrue(metric.get("annotation") or metric.get("annotations"))
                    if "judge" in metric:
                        self.assertIn(metric["judge"], judges)


class BudgetAndModelPinTest(unittest.TestCase):
    def test_budget_levels(self):
        budgets = yaml_file(CONFIGS / "common" / "budgets.yaml")
        self.assertEqual(budgets["answer"]["memory_levels"], [256, 512, 1024, "full"])
        self.assertEqual(budgets["answer"]["further_retrieval_per_read"], 1)
        self.assertEqual(budgets["pipeline"]["repairs_per_read"], 1)

    def test_model_pins_match_d006(self):
        roles = {"qwen3-8b": "primary", "qwen3.5-9b": "contemporary",
                 "qwen3.5-27b": "long-context", "gemma-4-31b-it": "long-context",
                 "qwen3-32b": "writer-scale", "mistral-small-3.2-24b": "renderer"}
        paths = sorted((CONFIGS / "models").glob("*.yaml"))
        self.assertEqual({p.stem for p in paths}, set(roles))
        for path in paths:
            with self.subTest(model=path.stem):
                config = yaml_file(path)
                self.assertEqual((config["status"], config["role"]), ("selected", roles[path.stem]))
                pin = TokenizerPin.from_config(config)
                self.assertFalse(pin.thinking)
                if roles[path.stem] == "renderer":
                    # The change-sequence renderer (T015) samples with a seed per attempt at the
                    # model card's temperature; it is never an evaluated model.
                    self.assertEqual(config["decoding"]["temperature"], 0.15)
                    self.assertEqual(config["tokenizer"]["backend"], "mistral-common")
                    continue
                self.assertEqual(pin.template_kwargs.get("enable_thinking"), False)
                self.assertEqual(config["decoding"]["temperature"], 0.0)

if __name__ == "__main__":
    unittest.main()
