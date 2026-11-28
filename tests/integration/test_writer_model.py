"""E007 main configuration: GRACE's writer on its own model (`writer_model` of the engine config).

The writer and writer-side extensions use the port's `writer_client`; the planner and the views
keep the run's client. Fake clients only; no model server.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from grace.config.paths import REPO_ROOT
from grace.context.engine import GraceEngine
from grace.context.pipeline.update.updater import WriterConfig
from grace.eval.runner.harness.drive import ClientSettings, load_engine_config
from tests.integration.writer_fixture import history_info, message

ENGINES = REPO_ROOT / "configs" / "engines"


class FakeClient:
    def __init__(self, name):
        self.name = name


class Port:
    def __init__(self, writer_client=None):
        self.client = FakeClient("run")
        self.writer_client = writer_client
        self.decoding = {"seed": 0}
        self.observed = []

    def count_tokens(self, text):
        return len(text.split())

    def observe(self, texts):
        self.observed.extend(texts)


def build(port, **params) -> GraceEngine:
    return GraceEngine.from_port(port, views=None, **params)


class WriterClientTest(unittest.TestCase):
    def setUp(self):
        self.info = history_info("h", [message("h", 1, "Ana", "Hi")])

    def test_writer_uses_the_writer_client_and_the_planner_the_run_client(self):
        engine = build(Port(FakeClient("writer")))
        writer = engine.c.extractor(self.info)
        self.assertEqual(writer.client.name, "writer")
        self.assertEqual(engine.c.planner.client.name, "run")

    def test_without_a_writer_client_the_writer_shares_the_run_client(self):
        engine = build(Port())
        self.assertEqual(engine.c.extractor(self.info).client.name, "run")

    def test_extensions_get_the_writer_client(self):
        engine = build(Port(FakeClient("writer")),
                       components={"extension": {"factory": "slot-table"}})
        memory = engine.c.extension(self.info)
        self.assertEqual(memory.writer.client.name, "writer")


class ConfigTest(unittest.TestCase):
    def test_main_configuration(self):
        config = load_engine_config(ENGINES / "grace.yaml")
        self.assertEqual(config["writer_model"], "configs/models/qwen3-32b.yaml")
        writer = WriterConfig.load(REPO_ROOT / config["params"]["writer"])
        self.assertEqual(writer.granularity.name, "session")
        self.assertEqual(writer.decoding["max_tokens"], 12288)
        seg8 = WriterConfig.load(REPO_ROOT / "configs" / "common" / "writer-segment8.yaml")
        self.assertEqual((seg8.granularity.name, seg8.decoding["max_tokens"]),
                         ("segment-8", 4096))
        self.assertEqual(load_engine_config(ENGINES / "grace-writer-8b.yaml")["writer_model"],
                         "configs/models/qwen3-8b.yaml")

    def test_variants_with_the_claim_writer_share_the_main_writer(self):
        main = yaml.safe_load((ENGINES / "grace.yaml").read_text(encoding="utf-8"))
        for path in sorted(ENGINES.glob("grace-*.yaml")):
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            ext = (config["params"].get("components") or {}).get("extension") or {}
            with self.subTest(config=path.name):
                self.assertIn(config["params"]["writer"], ("configs/common/writer.yaml",
                                                           "configs/common/writer-segment8.yaml"))
                if ext.get("factory") == "slot-table" or path.stem == "grace-writer-8b":
                    continue   # own extractor (slot writer) or the small-writer arm
                self.assertEqual(config.get("writer_model"), main["writer_model"])

    def test_writer_endpoint(self):
        config = load_engine_config(ENGINES / "grace.yaml")
        run_model = REPO_ROOT / "configs" / "models" / "qwen3-8b.yaml"
        with self.assertRaises(ValueError):
            ClientSettings("http://run/v1", run_model).writer_info(config)
        info = ClientSettings("http://run/v1", run_model,
                              writer_url="http://writer/v1").writer_info(config)
        self.assertEqual((info["base_url"], info["served_name"]),
                         ("http://writer/v1", "Qwen/Qwen3-32B"))
        small = load_engine_config(ENGINES / "grace-writer-8b.yaml")
        info = ClientSettings("http://run/v1", Path(run_model),
                              writer_url="http://writer/v1").writer_info(small)
        self.assertEqual(info["base_url"], "http://run/v1")   # the run's model: --base-url
        self.assertIsNone(ClientSettings("http://run/v1", run_model).writer_info({}))


if __name__ == "__main__":
    unittest.main()
