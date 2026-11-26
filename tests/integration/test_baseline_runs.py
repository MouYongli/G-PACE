"""Every baseline runs end to end on every fixture benchmark through the harness (T003).

Each run is checked with the reference checks of the contract tests: run.json (Experiment run),
predictions aligned against the read tasks and gold (Prediction), calls.jsonl (Cost ledger), and
the record fields of contexts.jsonl and the traces. Runs use the deterministic fake backend.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from grace.eval.engines.baselines import graphiti
from grace.eval.runner.harness import drive
from grace.eval.runner.harness.answer import is_answer_call, is_final_call
from grace.eval.runner.harness.models import FakeBackend, fake_responder
from grace.eval.runner.harness.rundir import CodeState
from tests.contracts.records import check_fields, load_benchmark, read_jsonl
from tests.contracts.test_cost_ledger import check_calls
from tests.contracts.test_experiment_run import ARTEFACTS, check_run

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "tests" / "fixtures" / "benchmarks"
ALL_ENGINES = sorted((ROOT / "configs" / "engines").glob("*.yaml"))
# Graphiti's config needs the envs/graphiti environment; there every config runs.
ENGINES = [config for config in ALL_ENGINES if graphiti.runnable(config)]
CODE = CodeState("0123456789abcdef0123456789abcdef01234567", False)


def retrieving(messages):
    if is_answer_call(messages) and not is_final_call(messages):
        return json.dumps({"output": "retrieve", "query": "instruments cat"})
    return fake_responder(messages)


class BaselineRunsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_one(self, config, benchmark, budget, schedule=None, responder=fake_responder):
        return drive.run_system(
            engine_config=config, records=BENCHMARKS / benchmark, budget=budget,
            experiment="T003", run_root=self.tmp, schedule=schedule, code=CODE,
            command="test", backend_factory=lambda c: FakeBackend(responder, prefix_caching=c))

    def check(self, result, benchmark, budget, schedule_file="read_tasks.jsonl"):
        self.assertEqual(result.status, "completed", result.failure)
        run = check_run(result.run_dir)
        self.assertEqual(run["stage"], "system")
        fixture = load_benchmark(BENCHMARKS / benchmark)
        reads = fixture["schedules"][schedule_file]
        predictions = read_jsonl(result.run_dir / "predictions.jsonl")
        aligned = drive_align(reads, fixture, predictions)
        self.assertEqual(len(aligned), len(reads))
        self.assertEqual(run["n_records"], len(reads))
        calls = read_jsonl(result.run_dir / "calls.jsonl")
        check_calls(calls)
        call_ids = {c["call_id"] for c in calls}
        self.assertTrue(all(c["run_id"] == result.run_id for c in calls))
        for name, spec in ARTEFACTS.items():
            if name.endswith(".jsonl") and name != "judgements.jsonl":
                check_fields(read_jsonl(result.run_dir / name), spec, name)
        contexts = {c["read_id"]: c for c in read_jsonl(result.run_dir / "contexts.jsonl")}
        traces = {t["read_id"]: t for t in read_jsonl(result.run_dir / "traces/read.jsonl")}
        self.assertEqual(set(contexts), set(reads))
        for p in predictions:
            context, trace = contexts[p["read_id"]], traces[p["read_id"]]
            self.assertEqual(trace["included_ids"], p["context_ids"])
            self.assertEqual(trace["further_retrieval"], p["further_retrieval"])
            self.assertEqual(context["budget_tokens"], budget)
            if budget is not None:
                self.assertLessEqual(context["tokens"], budget)
            self.assertTrue(set(trace["call_ids"]) <= call_ids)
            answers = [c for c in calls if c["read_id"] == p["read_id"]
                       and c["call_type"] == "answer"]
            self.assertTrue(answers)
        writes = read_jsonl(result.run_dir / "traces/write.jsonl")
        n_messages = sum(h["n_messages"] for h in fixture["histories"].values())
        self.assertEqual(len(writes), n_messages)
        for w in writes:
            self.assertTrue(set(w["call_ids"]) <= call_ids)

    def test_every_baseline_on_every_fixture(self):
        self.assertEqual(len(ALL_ENGINES), 12)  # graphiti-native.yaml (T034) is the 12th
        for config in ENGINES:
            for benchmark in sorted(p.name for p in BENCHMARKS.iterdir()):
                for budget in (None, 24):
                    with self.subTest(engine=config.stem, benchmark=benchmark, budget=budget):
                        self.check(self.run_one(config, benchmark, budget), benchmark, budget)

    def test_streaming_schedule_and_further_retrieval(self):
        for config in ENGINES:
            with self.subTest(engine=config.stem):
                result = self.run_one(config, "locomo", 256, "streaming", retrieving)
                self.check(result, "locomo", 256, "read_tasks.streaming.jsonl")
                predictions = read_jsonl(result.run_dir / "predictions.jsonl")
                self.assertTrue(all(p["further_retrieval"] for p in predictions))
                early = next(p for p in predictions if p["version"] == 3)
                self.assertTrue(set(early["context_ids"]) <= {"D1:1", "D1:2", "D1:3"})

    def test_dirty_code_is_not_a_completed_run(self):
        result = drive.run_system(
            engine_config=ENGINES[0], records=BENCHMARKS / "locomo", budget=None,
            experiment="T003", run_root=self.tmp, code=CodeState(CODE.sha, True),
            command="test")
        self.assertEqual(result.status, "failed")
        self.assertIn("code_dirty", result.failure)
        check_run(result.run_dir)

    def test_held_out_splits_are_refused(self):
        records = self.tmp / "records"
        shutil.copytree(BENCHMARKS / "locomo", records)
        for name in ("histories.jsonl", "messages.jsonl", "read_tasks.jsonl"):
            path = records / name
            path.write_text(path.read_text().replace('"split": "fixture"', '"split": "test"'))
        with self.assertRaises(ValueError):
            drive.run_system(engine_config=ENGINES[0], records=records, budget=None,
                             experiment="T003", run_root=self.tmp, code=CODE, command="test")


def drive_align(reads, fixture, predictions):
    from tests.contracts.records import align_predictions
    return align_predictions(reads, fixture["messages"], fixture["gold"], predictions)


if __name__ == "__main__":
    unittest.main()
