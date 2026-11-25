"""One interface test suite run against every engine config in configs/engines/ (structure.md).

Checks the requirements of the ContextEngine interface: writes are in version order and per
history; a read is bound to the current version and sees no later message; a read does not change
the engine's state; save and restore reproduce the same working context.
"""

import json
import tempfile
import unittest
from pathlib import Path

from grace.context import api
from grace.eval.engines.baselines import graphiti
from grace.eval.runner.harness.drive import build_engine, load_engine_config
from grace.eval.runner.harness.inputs import load_fixture as load
from grace.eval.runner.harness.models import FakeBackend, RecordingModel
from grace.llm.records import CallLedger

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "tests" / "fixtures" / "benchmarks"
ENGINES = sorted((ROOT / "configs" / "engines").glob("*.yaml"))


def slot_responder(messages):
    """Fill one slot per message so the slot table holds rows."""
    system, user = messages[0]["content"], messages[-1]["content"]
    if "slot table" in system:
        word = user.rsplit(" ", 1)[-1].strip(".!?") or "x"
        return json.dumps({"entries": [{"slot": "person.activity", "value": word,
                                        "function": "inform"}]})
    if "running summary" in system:
        return "summary of " + " ".join(user.split()[:20])
    return '{"output": "unknown"}'


class EngineSuite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def engine(self, config):
        """The configured engine; summary windows shrunk so the five fixture messages summarise."""
        ledger = CallLedger(self.dir / f"calls-{config.stem}.jsonl",
                            "T003-20261125T000000Z-0000")
        model = RecordingModel(FakeBackend(slot_responder), ledger)
        settings = load_engine_config(config)
        if settings["engine"] == "summary":
            settings["params"].update(recent_k=1, block_size=2)
        return build_engine(settings, model)

    def test_suite(self):
        item = load(BENCHMARKS / "locomo", "streaming").histories[0]
        for config in ENGINES:
            with self.subTest(engine=config.stem):
                if load_engine_config(config)["engine"] == "graphiti" and \
                        graphiti.features()["graphiti-core"] is None:
                    continue  # needs the envs/graphiti environment; tests/integration covers it
                engine = self.engine(config)
                with self.assertRaises(RuntimeError):
                    engine.write(item.messages[0])  # not opened
                engine.open(item.history)
                self.assertEqual(engine.version, 0)
                with self.assertRaises(ValueError):
                    engine.write(item.messages[1])  # version 2 before version 1
                other = api.Message(**{**item.messages[0].__dict__, "history_id": "other"})
                with self.assertRaises(ValueError):
                    engine.write(other)
                early = next(t for t in item.reads if t.version == 3)
                for message in item.messages[:3]:
                    trace = engine.write(message).trace
                    self.assertEqual(trace.version, message.version)
                    self.assertEqual(trace.message_ids, (message.message_id,))
                first = engine.read(early, None)
                visible = {m.message_id for m in item.messages[:3]}
                ids = set(first.context.context_ids) | {
                    i for f in first.context.fragments for i in f.evidence_ids}
                self.assertTrue(ids <= visible, ids - visible)
                self.assertEqual(engine.read(early, None).context, first.context)
                engine.end_read(early)
                saved = self.dir / config.stem
                saved.mkdir()
                files = engine.save(saved)
                self.assertTrue(files and all(Path(f).is_file() for f in files))
                restored = self.engine(config)
                restored.restore(saved)
                self.assertEqual(restored.version, 3)
                self.assertEqual(restored.read(early, None).context, first.context)
                late = next(t for t in item.reads if t.version == 5)
                with self.assertRaises(ValueError):
                    engine.read(late, None)  # bound to version 5, engine at 3
                for message in item.messages[3:]:
                    engine.write(message)
                    restored.write(message)
                self.assertEqual(restored.read(late, 64).context, engine.read(late, 64).context)
                further = engine.further_retrieval(late, "clarinet", 64)
                self.assertTrue(further.trace.further_retrieval)
                self.assertLessEqual(further.context.tokens, 64)


if __name__ == "__main__":
    unittest.main()
