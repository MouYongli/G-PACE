"""E001 pilot driver (`grace.cli.pilot`) end to end on the synthetic fixtures.

The probe runs on fixture records through an injected loader and a whitespace token counter; a
fake-backend system run is then summarised. No model, no benchmark data, no GPU.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from grace.cli import pilot as cli
from grace.context import api
from grace.eval.datasets.benchmarks.base import Records
from grace.eval.datasets.benchmarks.records import Gold
from grace.eval.engines.baselines.base import message_time
from grace.eval.engines.baselines.raw import RawText
from grace.eval.runner.harness import drive
from grace.eval.runner.harness.answer import messages_for
from grace.eval.runner.harness.models import FakeBackend, RecordingModel
from grace.eval.runner.harness.rundir import CodeState
from grace.llm.records import CallLedger
from tests.contracts.records import read_jsonl
from tests.contracts.test_experiment_run import check_run

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "benchmarks"
CONFIG = ROOT / "configs" / "experiments" / "E001-pilot-measurements.yaml"
CODE = CodeState("0123456789abcdef0123456789abcdef01234567", False)


class WordCounter:
    name = "words"

    def count_text(self, text):
        return len(text.split())

    def count_messages(self, messages):
        return sum(len(m["content"].split()) + 4 for m in messages)


def fixture_records(slug, spec):
    directory = FIXTURES / slug
    records = Records(slug, "fixture")
    records.histories = [api.HistoryInfo.from_record(r)
                         for r in read_jsonl(directory / "histories.jsonl")]
    records.messages = [api.Message.from_record(r)
                        for r in read_jsonl(directory / "messages.jsonl")]
    records.schedules["read_tasks.jsonl"] = [api.ReadTask.from_record(r) for r in
                                             read_jsonl(directory / "read_tasks.jsonl")]
    records.gold = [Gold.from_record(r) for r in read_jsonl(directory / "gold.jsonl")]
    if slug == "halumem-medium":
        records.scoring["memory_points.jsonl"] = [
            {"history_id": "user-001", "memory_content": "synthetic memory point for s1:0",
             "is_update": "True"}]
    if slug == "change-seq":
        records.scoring["stale_labels.jsonl"] = [
            {"history_id": "seq-0001", "binding_id": "V1:k", "version": 2,
             "answer_stale": True, "citation_stale": False}]
    return records


class PilotProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_probe_run_writes_records_lengths_and_tables(self):
        run_dir, status = cli.run_probe(CONFIG, self.tmp, counter=WordCounter(),
                                        loader=fixture_records, code=CODE, command="test")
        self.assertEqual(status, "completed")
        run = check_run(run_dir)
        self.assertEqual(run["stage"], "probe")
        exp = cli.load_experiment(CONFIG)
        total_reads = 0
        for slug in exp["benchmarks"]:
            self.assertTrue((run_dir / "records" / slug / "gold.jsonl").exists())
            reads = read_jsonl(run_dir / "lengths" / f"{slug}.reads.jsonl")
            fixture = read_jsonl(FIXTURES / slug / "read_tasks.jsonl")
            self.assertEqual(len(reads), len(fixture))
            for row in reads:  # the prompt holds the whole visible history plus fixed parts
                self.assertGreater(row["prompt_tokens"], row["context_tokens"])
            total_reads += len(reads)
        self.assertEqual(run["n_records"], total_reads)
        tables = json.loads((run_dir / "pilot-probe.json").read_text(encoding="utf-8"))
        self.assertEqual(set(tables["benchmarks"]), set(exp["benchmarks"]))
        self.assertFalse(tables["benchmarks"]["locomo"]["update_density"]["available"])
        self.assertTrue(tables["benchmarks"]["multiwoz"]["update_density"]["available"])
        reserve = tables["prompt_reserve"]
        self.assertEqual(reserve["prompt_reserve_tokens"] % 128, 0)
        self.assertGreaterEqual(reserve["prompt_reserve_tokens"],
                                reserve["fixed_prompt_tokens_max"] + 256)

    def test_probe_counts_the_prompt_the_harness_sends(self):
        """The probe's prompt count equals the count of the full-history answer call."""
        run_dir, _ = cli.run_probe(CONFIG, self.tmp, counter=WordCounter(),
                                   loader=fixture_records, code=CODE, command="test")
        probe = {r["read_id"]: r for r in
                 read_jsonl(run_dir / "lengths" / "locomo.reads.jsonl")}
        counter = WordCounter()
        sent = {}

        backend = FakeBackend(prefix_caching=False)
        ledger = CallLedger(self.tmp / "calls.jsonl", "x")
        model = RecordingModel(backend, ledger)
        items = drive.load_fixture(FIXTURES / "locomo")
        for item in items.histories:
            engine = RawText(model)
            engine.open(item.history)
            for message in item.messages:
                engine.write(message)
            for task in item.reads:
                context = engine.read(task, None).context
                last = next(m for m in item.messages if m.version == task.version)
                prompt = messages_for(context.text, task, message_time(last, item.history))
                sent[task.read_id] = counter.count_messages(prompt)
        # Reads at the last version see the whole history, as in the probe.
        for read_id, tokens in sent.items():
            if probe[read_id]["version"] == max(r["version"] for r in probe.values()):
                self.assertEqual(probe[read_id]["prompt_tokens"], tokens)


class PilotCellsTest(unittest.TestCase):
    def setUp(self):
        self.exp = cli.load_experiment(CONFIG)

    def test_samples_are_nested_and_shards_partition(self):
        ids = [f"h{i}" for i in range(30)]
        small = cli.sample(ids, 3, "grace-E001")
        self.assertEqual(cli.sample(ids, 10, "grace-E001")[:3], small)
        self.assertEqual(sorted(cli.sample(ids, "all", "grace-E001")), sorted(ids))
        runs = cli.cell_runs(self.exp, "full-cached", lambda slug: ids)
        multiwoz = [r for r in runs if r["benchmark"] == "multiwoz"]
        self.assertEqual(len(multiwoz), 8)
        self.assertEqual(sorted(h for r in multiwoz for h in r["histories"]), sorted(ids))

    def test_cells_name_existing_engines_and_conditions(self):
        for name, cell in self.exp["cells"].items():
            self.assertIn(cell["condition"], self.exp["serving"]["conditions"], name)
            for engine in cell["engines"]:
                drive.load_engine_config(ROOT / engine)
            record = cli.serving_record(self.exp, name)
            self.assertEqual(record["prefix_caching"], cell["condition"] == "apc-on")

    def test_raw_engines_keep_the_prompt_inside_the_window(self):
        """Decision of E001: full-history and last-k reserve room for the fixed prompt parts."""
        for name in ("full-history", "full-history-cached", "last-k"):
            config = yaml.safe_load((ROOT / "configs" / "engines" / f"{name}.yaml").read_text())
            params = config["params"]
            self.assertGreater(params["prompt_reserve_tokens"], 256, name)
            self.assertLess(params["prompt_reserve_tokens"], params["window_tokens"], name)


class PilotSummaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_summary_over_a_fake_run(self):
        probe_dir, _ = cli.run_probe(CONFIG, self.tmp, counter=WordCounter(),
                                     loader=fixture_records, code=CODE, command="test")
        result = drive.run_system(
            engine_config=ROOT / "configs" / "engines" / "full-history-cached.yaml",
            records=FIXTURES / "locomo", budget=None, experiment="E001", run_root=self.tmp,
            code=CODE, command="test",
            backend_factory=lambda c: FakeBackend(prefix_caching=c))
        self.assertEqual(result.status, "completed")
        exp = cli.load_experiment(CONFIG)
        summary = cli.summarise(exp, [result.run_dir], probe_dir, WordCounter())
        (table,) = summary["runs"]
        self.assertEqual(table["n_records"], result.n_reads)
        answer = table["answer_calls"]
        self.assertGreater(answer["input_tokens"], 0)
        self.assertLessEqual(answer["cached_input_tokens"], answer["input_tokens"])
        self.assertIn("locomo", summary["judging_estimate"]["by_benchmark"])


class RawReserveTest(unittest.TestCase):
    def test_reserve_shrinks_the_full_history_context(self):
        items = drive.load_fixture(FIXTURES / "locomo")
        item = items.histories[0]
        backend = FakeBackend(prefix_caching=False)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        model = RecordingModel(backend, CallLedger(tmp / "calls.jsonl", "x"))
        engine = RawText(model, window_tokens=40, prompt_reserve_tokens=15)
        engine.open(item.history)
        for message in item.messages:
            engine.write(message)
        context = engine.read(item.reads[-1], None).context
        self.assertLessEqual(context.tokens, 25)
        self.assertIn("earlier messages omitted", context.text)
        self.assertIsNone(context.budget_tokens)
        with self.assertRaises(ValueError):
            RawText(model, window_tokens=40, prompt_reserve_tokens=40)


if __name__ == "__main__":
    unittest.main()
