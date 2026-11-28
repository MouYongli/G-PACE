"""Gold sentinel (structure.md, "Dependency rules"; T003 acceptance).

A sentinel string is planted in every gold record of every fixture benchmark. Each baseline config
then runs through the harness, and the test asserts that the sentinel appears in no input any
baseline or model receives: no argument of any ContextEngine call, no prompt or embedding text,
and no file of the run. A positive control plants the sentinel in a visible message and checks that
the same capture finds it, so the negative result is not an artefact of the capture.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from grace.context import api
from grace.eval.engines.baselines import graphiti
from grace.eval.runner.harness import drive
from grace.eval.runner.harness.answer import is_answer_call, is_final_call
from grace.eval.runner.harness.models import FakeBackend, fake_responder
from grace.eval.runner.harness.rundir import CodeState

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "tests" / "fixtures" / "benchmarks"
ALL_ENGINES = sorted((ROOT / "configs" / "engines").glob("*.yaml"))
# Graphiti's config needs the envs/graphiti environment; there every config runs.
ENGINES = [config for config in ALL_ENGINES if graphiti.runnable(config)]
SENTINEL = "GOLDSENTINEL7f3a"
CODE = CodeState("0" * 40, False)


def plant_in_gold(row: dict) -> dict:
    row = dict(row, reference=f"{SENTINEL} {json.dumps(row['reference'])}",
               labels={**row["labels"], "sentinel": SENTINEL})
    row["metadata"] = {**row.get("metadata", {}), "note": SENTINEL}
    return row


def retrieving_responder(messages):
    """Ask for further retrieval whenever it is allowed, so that path is covered too."""
    if is_answer_call(messages) and not is_final_call(messages):
        return json.dumps({"output": "retrieve", "query": "more about the question"})
    return fake_responder(messages)


class Capturing(api.ContextEngine):
    """Wraps an engine and keeps the repr of every argument it receives."""

    def __init__(self, inner: api.ContextEngine, seen: list[str]):
        self.inner, self.seen = inner, seen

    def open(self, history):
        self.seen.append(repr(history))
        return self.inner.open(history)

    @property
    def version(self):
        return self.inner.version

    def write(self, message):
        self.seen.append(repr(message))
        return self.inner.write(message)

    def read(self, task, budget_tokens):
        self.seen.append(repr((task, budget_tokens)))
        return self.inner.read(task, budget_tokens)

    def further_retrieval(self, task, request, budget_tokens):
        self.seen.append(repr((task, request, budget_tokens)))
        return self.inner.further_retrieval(task, request, budget_tokens)

    def end_read(self, task):
        self.seen.append(repr(task))
        return self.inner.end_read(task)

    def finish(self):
        return self.inner.finish()

    def save(self, directory):
        return self.inner.save(directory)

    def restore(self, directory):
        return self.inner.restore(directory)


def run_all(records: Path, run_root: Path, responder) -> list[str]:
    """Run every engine config on `records`; return every captured input and every run file."""
    seen: list[str] = []
    for config in ENGINES:
        result = drive.run_system(
            engine_config=config, records=records, budget=None, experiment="T003",
            run_root=run_root, code=CODE, command="test",
            backend_factory=lambda caching: FakeBackend(responder, prefix_caching=caching),
            on_model=lambda model: seen.append(model.observed) or None,
            engine_wrapper=lambda engine: Capturing(engine, seen))
        if result.status != "completed":
            raise AssertionError(f"{config.name}: {result.failure}")
        for path in result.run_dir.rglob("*"):
            if path.is_file() and path.name != "run.json":
                seen.append(path.read_text(encoding="utf-8"))
    # model.observed lists fill during the run; flatten them now.
    return [s for item in seen for s in (item if isinstance(item, list) else [item])]


class GoldSentinelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def copy(self, benchmark: str, plant_messages: bool = False) -> Path:
        target = self.tmp / "records" / benchmark
        shutil.copytree(BENCHMARKS / benchmark, target)
        gold = target / "gold.jsonl"
        rows = [plant_in_gold(json.loads(line)) for line in gold.read_text().splitlines()]
        gold.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        if plant_messages:
            messages = target / "messages.jsonl"
            rows = [json.loads(line) for line in messages.read_text().splitlines()]
            rows[0]["text"] += f" {SENTINEL}"
            messages.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return target

    def test_gold_never_reaches_a_baseline(self):
        self.assertGreater(len(ENGINES), 0)
        for benchmark in sorted(p.name for p in BENCHMARKS.iterdir()):
            with self.subTest(benchmark=benchmark):
                records = self.copy(benchmark)
                self.assertIn(SENTINEL, (records / "gold.jsonl").read_text())
                seen = run_all(records, self.tmp / "runs" / benchmark, retrieving_responder)
                self.assertTrue(seen)
                leaks = [s[:200] for s in seen if SENTINEL in s]
                self.assertEqual(leaks, [], f"gold sentinel reached a baseline in {benchmark}")

    def test_capture_finds_a_planted_visible_sentinel(self):
        records = self.copy("locomo", plant_messages=True)
        seen = run_all(records, self.tmp / "runs" / "control", retrieving_responder)
        self.assertTrue(any(SENTINEL in s for s in seen))


if __name__ == "__main__":
    unittest.main()
