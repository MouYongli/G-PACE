"""T013 write-budget driver (`grace.cli.write_budget`) on synthetic inputs.

Unit maths (units, writer cost, pricing, break-even, the latency fit) on hand-computed cases; the
`estimate` stage on the LoCoMo fixture with synthetic upstream call records; `measure-c` against a
fake OpenAI-compatible transport that simulates a prefix cache and a known compute ratio. No model,
no benchmark data, no GPU.
"""

import json
import os
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from grace.cli import write_budget as wb
from grace.context import api
from grace.eval.datasets.benchmarks.base import Records
from grace.eval.runner.harness.rundir import CodeState
from grace.llm.records import CallRecord
from tests.contracts.records import read_jsonl
from tests.contracts.test_experiment_run import check_run

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "experiments" / "T013-write-budget.yaml"
FIXTURE = ROOT / "tests" / "fixtures" / "benchmarks" / "locomo"
CODE = CodeState("0123456789abcdef0123456789abcdef01234567", False)


class WordCounter:
    name = "words"

    def count_text(self, text):
        return len(text.split())

    def count_messages(self, messages):
        return sum(len(m["content"].split()) + 4 for m in messages)


def message(version, segment):
    return api.Message("locomo", "fixture", "h", version, f"m{version}", segment, "A", "peer",
                       "text", None, None)


def record(run_id, n, history, read_id, inp, cached, out, category="A", status="ok"):
    call_type = {"A": "answer", "W": "extract"}[category]
    trigger = "read" if category == "A" else "write"
    return CallRecord(f"c{n:07d}", run_id, history, read_id if category == "A" else None, 1,
                      call_type, trigger, category, "m@x", 1, status, inp, out, cached, None,
                      1.0, None)


class UnitsAndCostTest(unittest.TestCase):
    def setUp(self):
        segments = ["s1"] * 5 + ["s2"] * 3
        self.messages = [message(i + 1, s) for i, s in enumerate(segments)]

    def test_units(self):
        self.assertEqual(len(wb.units_of(self.messages, {"unit": "message"})), 8)
        self.assertEqual(wb.units_of(self.messages, {"unit": "session"}),
                         [[0, 1, 2, 3, 4], [5, 6, 7]])
        # segments never cross a session boundary
        self.assertEqual(wb.units_of(self.messages, {"unit": "segment", "size": 2}),
                         [[0, 1], [2, 3], [4], [5, 6], [7]])
        with self.assertRaises(ValueError):
            wb.units_of(self.messages, {"unit": "segment", "size": 0})
        with self.assertRaises(ValueError):
            wb.units_of(self.messages, {"unit": "turn"})

    def test_writer_cost_by_hand(self):
        tokens = [10] * 8
        params = wb.WriterParams(prefix_tokens=100, candidate_base_tokens=5,
                                 candidate_tokens_per_message=1, context_messages=2,
                                 output_tokens_per_message=3, output_tokens_per_call=2)
        cost = wb.writer_cost(tokens, [[0, 1, 2, 3, 4], [5, 6, 7]], params)
        # call 1: 5 + 5 + 0 context + 50; call 2: 5 + 3 + 20 context + 30
        self.assertEqual(cost.varying, 60 + 58)
        self.assertEqual(cost.output, (2 + 15) + (2 + 9))
        self.assertEqual(cost.calls, 2)
        self.assertEqual(cost.logical, 200 + 118 + 28)
        self.assertEqual(cost.computed, 100 + 118 + 28)  # the first prefix is never cached
        self.assertAlmostEqual(cost.price(0.5), 150 + 118 + 28)
        with self.assertRaises(ValueError):
            cost.price(1.5)
        self.assertEqual(wb.WriteCost(0, 100, 0, 0).price(0.3), 0.0)

    def test_finer_units_cost_more(self):
        tokens = [10] * 8
        params = wb.WriterParams.from_dict(yaml.safe_load(CONFIG.read_text())["writer"]
                                           ["scenarios"]["central"])
        per_message = wb.writer_cost(tokens, wb.units_of(self.messages, {"unit": "message"}),
                                     params)
        per_session = wb.writer_cost(tokens, wb.units_of(self.messages, {"unit": "session"}),
                                     params)
        for c in (0.0, 0.1, 1.0):
            self.assertGreater(per_message.price(c), per_session.price(c))


class BreakEvenTest(unittest.TestCase):
    def side(self):
        # full history: first read 1,000 input; warm reads 1,010 input of which 1,000 cached
        full = [record("F", 1, "h", "r1", 1000, 0, 10),
                record("F", 2, "h", "r2", 1010, 1000, 10),
                record("F", 3, "h", "r3", 1010, 1000, 10)]
        answers = [record("A", i, "h", f"r{i}", 300, 100, 10) for i in (1, 2, 3)]
        return wb.read_sides(full, answers)["h"]

    def test_read_side(self):
        side = self.side()
        self.assertEqual(side.reads, 3)
        self.assertEqual(side.full_per_read(0.0), 20)
        self.assertEqual(side.full_per_read(1.0), 1020)
        self.assertEqual(side.full_total(0.5), 1010 + 2 * 520)
        self.assertEqual(side.answer_per_read(0.0), 210)

    def test_point_and_smallest_c(self):
        side = self.side()
        planner = wb.PlannerParams(1, 0, 10, 10)
        self.assertEqual(planner.per_read(0.5, 100), 70)
        fn = lambda c: wb.point(c, lambda c: 1000.0, side,  # noqa: E731
                                lambda c: planner.per_read(c, 100))
        # c = 0: f = 20, a = 210 + 20 -> no payback point
        self.assertIsNone(fn(0.0).m_star)
        # c = 1: f = 1020, a = 310 + 120 = 430, delta 590 -> ceil(1000 / 590) = 2
        p = fn(1.0)
        self.assertAlmostEqual(p.delta, 590)
        self.assertEqual(p.m_star, 2)
        c = wb.smallest_c(fn, 3, 1000)
        self.assertIsNotNone(c)
        self.assertLessEqual(fn(c).m_star, 3)
        self.assertTrue(fn(c - 0.001).m_star is None or fn(c - 0.001).m_star > 3)

    def test_needs_two_reads(self):
        with self.assertRaises(ValueError):
            wb.read_sides([record("F", 1, "h", "r1", 10, 0, 1)],
                          [record("A", 1, "h", "r1", 10, 0, 1)])


class RegimeRatioTest(unittest.TestCase):
    def test_by_hand(self):
        rows = [{"kind": "measure", "target_cached": 0, "target_new": 128, "latency_s": 0.01},
                {"kind": "measure", "target_cached": 0, "target_new": 128, "latency_s": 0.03},
                {"kind": "measure", "target_cached": 1000, "target_new": 128, "latency_s": 0.04},
                {"kind": "prime", "target_cached": 0, "target_new": 1000, "latency_s": 0.22}]
        # (0.04 - 0.02) / (0.22 - 0.02)
        self.assertAlmostEqual(wb.regime_ratio(rows, 1000, 128), 0.1)
        with self.assertRaises(ValueError):
            wb.regime_ratio(rows, 2000, 128)


class FitTest(unittest.TestCase):
    def test_recovers_known_ratio(self):
        rng = random.Random(0)
        rows = []
        for _ in range(200):
            new, cached = rng.randrange(100, 5000), rng.choice([0, 2000, 8000, 16000])
            rows.append({"new": new, "cached": cached,
                         "latency_s": 0.02 + 1e-5 * new + 1e-6 * cached + rng.gauss(0, 1e-4)})
        result = wb.fit(rows)
        self.assertAlmostEqual(result["c"], 0.1, places=2)
        self.assertGreater(result["r2"], 0.99)
        low, high = wb.bootstrap_c(rows, 50, 0)
        self.assertLessEqual(low, 0.1 + 0.01)
        self.assertGreaterEqual(high, 0.1 - 0.01)


def fixture_loader(slug, split):
    records = Records(slug, "fixture")
    records.histories = [api.HistoryInfo.from_record(r)
                         for r in read_jsonl(FIXTURE / "histories.jsonl")]
    records.messages = [api.Message.from_record(r) for r in read_jsonl(FIXTURE / "messages.jsonl")]
    records.schedules["read_tasks.jsonl"] = [api.ReadTask.from_record(r)
                                             for r in read_jsonl(FIXTURE / "read_tasks.jsonl")]
    return records


def write_run(path: Path, records, status="completed"):
    path.mkdir(parents=True)
    run_id = path.name
    (path / "run.json").write_text(json.dumps({"run_id": run_id, "stage": "system",
                                               "status": status}))
    with (path / "calls.jsonl").open("w") as handle:
        for r in records:
            handle.write(r.to_json() + "\n")


class EstimateStageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        runs = self.tmp / "project" / "runs"
        history = "conv-syn-1"
        full, answers, writes = [], [], []
        for i in range(1, 4):
            full.append(record("E001-20261125T000000Z-0001", i, history, f"q{i}", 1000,
                               0 if i == 1 else 980, 10))
            answers.append(record("E001-20261125T000000Z-0002", i, history, f"q{i}", 300, 50, 10))
            writes.append(record("E001-20261125T000000Z-0003", i, history, None, 200, 100, 30,
                                 category="W"))
        write_run(runs / "E001" / "E001-20261125T000000Z-0001", full)
        write_run(runs / "E001" / "E001-20261125T000000Z-0002", answers)
        write_run(runs / "E001" / "E001-20261125T000000Z-0003", writes)
        config = yaml.safe_load(CONFIG.read_text())
        config["read"]["full_history_run"] = "E001/E001-20261125T000000Z-0001"
        config["read"]["answer_run"] = "E001/E001-20261125T000000Z-0002"
        config["reference_writers"] = {"slot-table": ["E001/E001-20261125T000000Z-0003"]}
        config["c_grid_steps"] = 10
        probe = runs / "T013" / "T013-20261126T000000Z-0004"
        write_run(probe, [])
        (probe / "compute-ratio.json").write_text(json.dumps({"c": 0.2, "c_ci95": [0.1, 0.3]}))
        (probe / "trials.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
            {"kind": "measure", "target_cached": 0, "target_new": 8, "latency_s": 0.01},
            {"kind": "measure", "target_cached": 64, "target_new": 8, "latency_s": 0.02},
            {"kind": "prime", "target_cached": 0, "target_new": 64, "latency_s": 0.11}]))
        config["cache_ratios"] = [
            {"label": "quoted", "value": 0.08},
            {"label": "pooled", "run": "T013/T013-20261126T000000Z-0004"},
            {"label": "regime", "run": "T013/T013-20261126T000000Z-0004",
             "regime": {"cached": 64, "new": 8}}]
        self.config = self.tmp / "config.yaml"
        self.config.write_text(yaml.safe_dump(config))
        self.env = mock.patch.dict(os.environ, {"PROJECT_ROOT": str(self.tmp / "project")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_estimate_run(self):
        run_dir, status = wb.run_estimate(self.config, self.tmp / "out", counter=WordCounter(),
                                          loader=fixture_loader, code=CODE, command="test",
                                          draw=False)
        self.assertEqual(status, "completed")
        run = check_run(run_dir)
        self.assertEqual(run["stage"], "probe")
        self.assertEqual(run["upstream"], [])
        result = json.loads((run_dir / "write-budget.json").read_text())
        self.assertEqual([h["history_id"] for h in result["histories"]], ["conv-syn-1"])
        self.assertEqual(result["histories"][0]["messages"], 5)
        self.assertEqual(result["histories"][0]["sessions"], 2)
        self.assertEqual(result["histories"][0]["reads"], 3)
        names = {(r["granularity"], r["scenario"]) for r in result["results"]}
        self.assertIn(("session", "central"), names)
        self.assertIn(("measured:slot-table", "measured"), names)
        self.assertEqual(len(names), 5 * 3 + 1)
        for row in result["results"]:
            self.assertEqual(len(row["curve"]), 11)
            self.assertEqual([m["label"] for m in row["at_marks"]],
                             [m["label"] for m in result["marks"]])
        self.assertEqual([round(m["c"], 6) for m in result["marks"]], [0.08, 0.2, 0.1])
        self.assertEqual(result["marks"][2]["run"]["run_id"], "T013-20261126T000000Z-0004")
        self.assertEqual(result["inputs"]["answer_run"]["run_id"], "E001-20261125T000000Z-0002")
        self.assertTrue((run_dir / "curves.csv").is_file())
        self.assertTrue((run_dir / "units.csv").is_file())

    def test_reference_weight_scales_the_writer_cost(self):
        config = yaml.safe_load(self.config.read_text())
        config["reference_writers"]["slot-table-x4"] = config["reference_writers"]["slot-table"]
        config["reference_weights"] = {"slot-table-x4": 4.0}
        self.config.write_text(yaml.safe_dump(config))
        run_dir, _ = wb.run_estimate(self.config, self.tmp / "out", counter=WordCounter(),
                                     loader=fixture_loader, code=CODE, command="test", draw=False)
        rows = {r["granularity"]: r for r in json.loads(
            (run_dir / "write-budget.json").read_text())["results"]}
        one, four = rows["measured:slot-table"], rows["measured:slot-table-x4"]
        self.assertEqual(four["W"]["logical"], 4 * one["W"]["logical"])
        self.assertEqual((one["W"]["weight"], four["W"]["weight"]), (1.0, 4.0))
        self.assertEqual(four["curve"][5]["w"], round(4 * one["curve"][5]["w"], 3))

    def test_refuses_incomplete_input_run(self):
        run = self.tmp / "project" / "runs" / "E001" / "E001-20261125T000000Z-0002" / "run.json"
        run.write_text(json.dumps({"run_id": "E001-20261125T000000Z-0002", "stage": "system",
                                   "status": "failed"}))
        with self.assertRaises(ValueError):
            wb.run_estimate(self.config, self.tmp / "out", counter=WordCounter(),
                            loader=fixture_loader, code=CODE, command="test", draw=False)


class FakeServer:
    """A prefix cache over system messages and a latency model with compute ratio 0.05."""

    def __init__(self, clock_box):
        self.seen = set()
        self.clock = clock_box

    def __call__(self, url, payload, headers, timeout):
        system, user = (m["content"] for m in payload["messages"])
        sys_tokens, user_tokens = len(system.split()) + 4, len(user.split()) + 4
        cached = sys_tokens if system in self.seen else 0
        self.seen.add(system)
        new = sys_tokens + user_tokens - cached
        self.clock[0] += 0.01 + 1e-4 * new + 5e-6 * cached
        return {"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": sys_tokens + user_tokens, "completion_tokens": 1,
                          "prompt_tokens_details": {"cached_tokens": cached}}}


class MeasureCTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        config = yaml.safe_load(CONFIG.read_text())
        config["compute_ratio"].update(cached_tokens=[0, 200, 800], new_tokens=[50, 300],
                                       repeats=2, warmup_calls=1, bootstrap=20)
        self.config = self.tmp / "config.yaml"
        self.config.write_text(yaml.safe_dump(config))

    def run_probe(self, checker):
        box = [0.0]
        options = {"transport": FakeServer(box), "clock": lambda: box[0]}
        return wb.run_measure_c(self.config, self.tmp / "out", base_url="http://fake/v1", gpu=9,
                                server_pid=1, counter=WordCounter(), client_options=options,
                                checker=checker, code=CODE, command="test")

    def test_recovers_ratio(self):
        def checker(when):
            return {"when": when, "exclusive": True, "utilization_pct": 0}
        run_dir, status = self.run_probe(checker)
        self.assertEqual(status, "completed")
        check_run(run_dir)
        result = json.loads((run_dir / "compute-ratio.json").read_text())
        self.assertAlmostEqual(result["c"], 0.05, places=3)
        self.assertTrue(result["gpu_exclusive"])
        calls = (run_dir / "calls.jsonl").read_text().splitlines()
        # 1 warm-up + 2 x 2 cold trials + 2 x 2 x 2 x 2 primed trials
        self.assertEqual(len(calls), 1 + 4 + 16)
        self.assertEqual(result["calls"], 21)

    def test_fails_when_gpu_is_shared(self):
        def checker(when):
            return {"when": when, "exclusive": when != "after", "utilization_pct": 0}
        with self.assertRaises(RuntimeError):
            self.run_probe(checker)
        run_dir = next((self.tmp / "out" / "T013").iterdir())
        run = json.loads((run_dir / "run.json").read_text())
        self.assertEqual(run["status"], "failed")
        self.assertIn("not exclusive", run["failure"])
        self.assertFalse((run_dir / "compute-ratio.json").exists())


if __name__ == "__main__":
    unittest.main()
