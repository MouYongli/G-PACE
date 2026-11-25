"""Cost ledgers and amortisation tooling (task T030; plan 8; contracts.md, "Cost ledger").

The acceptance check "ledger totals reconcile with per-call logs on a fixture run" is
`FixtureRunTest`: real harness runs on the synthetic fixtures (fake backend), whose calls.jsonl
is summed independently here and compared with the library's ledgers and per-read charges.
"""

import copy
import json
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from grace.cli.cost import report
from grace.eval.analysis.metrics.cost import amortisation as am
from grace.eval.analysis.metrics.cost.ledger import (
    Ledger,
    LedgerError,
    Read,
    allocate,
    ledgers,
    load_run,
    percentile,
    reconcile,
    summary,
    system_cost,
)
from grace.eval.runner.harness import drive
from grace.eval.runner.harness.models import FakeBackend
from grace.eval.runner.harness.rundir import CodeState
from grace.llm.records import CallRecord, read_calls
from tests.contracts.test_cost_ledger import ledgers as reference_ledgers
from tests.contracts.test_cost_ledger import per_read as reference_per_read

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "tests" / "fixtures" / "runs"
BENCHMARKS = ROOT / "tests" / "fixtures" / "benchmarks"
ENGINES = ROOT / "configs" / "engines"
CODE = CodeState("0123456789abcdef0123456789abcdef01234567", False)
RUN_ID = "E000-20261125T000000Z-0001"


def record(call_id, *, category="A", call_type=None, trigger="read", history="h", read=None,
           version=1, inp=100, out=10, cached=0, gpu=1.0, status="ok", run_id="R-1"):
    call_type = call_type or {"W": "extract", "U": "plan", "A": "answer", "embedding": "embed",
                              "evaluation": "judge"}[category]
    if call_type == "embed":
        out = 0
    return CallRecord(call_id=call_id, run_id=run_id, history_id=history,
                      read_id=None if trigger == "write" else read, version=version,
                      call_type=call_type, trigger=trigger, category=category, model="m",
                      attempt=1, status=status, input_tokens=inp, output_tokens=out,
                      cached_input_tokens=cached, gpu_seconds=gpu, latency_ms=10.0,
                      prompt_sha256=None)


def write_run(directory: Path, run_id: str, records, reads, contexts=None, *, stage="system",
              upstream=(), status="completed"):
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(json.dumps({
        "run_id": run_id, "stage": stage, "status": status, "upstream": list(upstream)}))
    (directory / "calls.jsonl").write_text("".join(r.to_json() + "\n" for r in records))
    (directory / "predictions.jsonl").write_text("".join(
        json.dumps({"read_id": r.read_id, "history_id": r.history_id, "version": r.version})
        + "\n" for r in reads))
    if contexts:
        (directory / "contexts.jsonl").write_text("".join(
            json.dumps({"read_id": rid, "tokens": t}) + "\n" for rid, t in contexts.items()))
    return directory


class FixtureLedgerTest(unittest.TestCase):
    """The hand-computed totals of tests/fixtures/runs (Cost ledger contract fixture)."""

    def setUp(self):
        self.records = read_calls(RUNS / "calls.jsonl")
        self.expected = json.loads((RUNS / "ledger-expected.json").read_text("utf-8"))

    def test_three_ledgers_match_the_hand_computed_totals(self):
        got = ledgers(self.records)
        for category, want in self.expected["categories"].items():
            with self.subTest(category=category):
                self.assertEqual(got[category].logical, want["logical"])
                self.assertEqual(got[category].computed, want["computed"])
                self.assertAlmostEqual(got[category].gpu_seconds, want["gpu_seconds"])
                self.assertEqual(got[category].gpu_null, want["gpu_null"])

    def test_per_read_charges_and_reconciliation(self):
        reads = [Read(rid, "conv-syn-1", item["version"])
                 for rid, item in self.expected["reads"].items()]
        allocation = allocate(self.records, reads)
        for cost in allocation.reads:
            want = self.expected["reads"][cost.read.read_id]
            self.assertEqual((cost.w_before.logical, cost.u.logical, cost.a.logical),
                             (want["W_before"], want["U"], want["A"]))
        self.assertEqual(allocation.unassigned_w, Ledger())
        reconcile(self.records, allocation)

    def test_failed_attempts_count_and_judge_is_not_system_cost(self):
        by_category = ledgers(self.records)
        self.assertEqual(by_category["W"].failed_calls, 1)
        self.assertEqual(by_category["A"].failed_calls, 1)
        ok_only = ledgers([r for r in self.records if r.status == "ok"])
        self.assertGreater(by_category["A"].logical, ok_only["A"].logical)
        system = system_cost(by_category)
        self.assertEqual(system.logical, 650 + 160 + 972)
        everything = sum((by_category[c] for c in by_category), Ledger())
        self.assertEqual(everything.logical - system.logical, 40 + 203)


class AllocationTest(unittest.TestCase):
    def test_interleaved_reads_get_the_writes_since_the_previous_read(self):
        records = [record("w1", category="W", trigger="write", version=1, inp=10, out=0),
                   record("w2", category="W", trigger="write", version=2, inp=20, out=0),
                   record("w3", category="W", trigger="write", version=3, inp=30, out=0),
                   record("w4", category="W", trigger="write", version=4, inp=40, out=0),
                   record("a1", read="r@2", version=2), record("a2", read="r@3", version=3),
                   record("lazy", category="W", call_type="render", read="r@3", version=3,
                          inp=5, out=0)]
        reads = [Read("r@2", "h", 2), Read("r@3", "h", 3)]
        allocation = allocate(records, reads)
        self.assertEqual([c.w_before.logical for c in allocation.reads], [30, 35])
        self.assertEqual(allocation.unassigned_w.logical, 40)
        self.assertEqual(allocation.unassigned_w_ids, ["R-1/w4"])
        reconcile(records, allocation)

    def test_reads_at_one_version_charge_the_ingestion_once(self):
        records = [record("w1", category="W", trigger="write", version=1, inp=50, out=0),
                   record("w2", category="W", trigger="write", version=2, inp=50, out=0),
                   record("a1", read="q1", version=2), record("a2", read="q2", version=2)]
        allocation = allocate(records, [Read("q1", "h", 2), Read("q2", "h", 2)])
        self.assertEqual([c.w_before.logical for c in allocation.reads], [100, 0])

    def test_histories_are_separate(self):
        records = [record("w1", category="W", trigger="write", history="h1", version=1),
                   record("w2", category="W", trigger="write", history="h2", version=1,
                          inp=7, out=0),
                   record("a1", history="h1", read="x", version=1),
                   record("a2", history="h2", read="y", version=1)]
        allocation = allocate(records, [Read("x", "h1", 1), Read("y", "h2", 1)])
        self.assertEqual([c.w_before.logical for c in allocation.reads], [110, 7])

    def test_unknown_read_and_duplicate_read_are_refused(self):
        with self.assertRaises(LedgerError):
            allocate([record("a1", read="nope")], [Read("q", "h", 1)])
        with self.assertRaises(LedgerError):
            allocate([], [Read("q", "h", 1), Read("q", "h", 1)])

    def test_reconcile_detects_a_lost_record(self):
        records = [record("a1", read="q"), record("a2", read="q", inp=5)]
        allocation = allocate(records, [Read("q", "h", 1)])
        with self.assertRaises(LedgerError):
            reconcile(records + [record("a3", read="q")], allocation)

    def test_matches_the_contract_reference_on_random_records(self):
        import random

        rng = random.Random(7)
        for trial in range(30):
            records, reads, version = [], [], 0
            for step in range(rng.randint(1, 8)):
                version += rng.randint(0, 2)
                for _ in range(rng.randint(0, 3)):
                    records.append(record(f"w{trial}-{len(records)}", category="W",
                                          trigger="write", version=max(version, 1),
                                          inp=rng.randint(1, 50), out=rng.randint(0, 5),
                                          status=rng.choice(["ok", "failed"])))
                rid = f"q{step}@{max(version, 1)}"
                reads.append(Read(rid, "h", max(version, 1)))
                for cat in ("U", "A"):
                    for _ in range(rng.randint(0, 2)):
                        inp = rng.randint(1, 50)
                        records.append(record(f"{cat}{trial}-{len(records)}", category=cat,
                                              read=rid, version=max(version, 1), inp=inp,
                                              cached=rng.randint(0, inp)))
            rows = [json.loads(r.to_json()) for r in records]
            reference = reference_per_read(rows, {r.read_id: r.version for r in reads})
            allocation = allocate(records, reads)
            reconcile(records, allocation)
            for cost in allocation.reads:
                want = reference[cost.read.read_id]
                self.assertEqual((cost.w_before.logical, cost.u.logical, cost.a.logical),
                                 (want["W_before"], want["U"], want["A"]))
            ref = reference_ledgers(rows)
            for category, ledger in ledgers(records).items():
                if ledger.calls:
                    self.assertEqual(ledger.computed, ref[category]["computed"])


class FixtureRunTest(unittest.TestCase):
    """Acceptance: ledger totals reconcile with the per-call log of real fixture runs."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def engine(self, name):
        if name != "summary-rewrite":
            return ENGINES / f"{name}.yaml"
        # the fixture history has 5 messages: a recent window of 1 makes the summary write
        path = self.tmp / "summary-rewrite.yaml"
        path.write_text((ENGINES / "summary-rewrite.yaml").read_text("utf-8")
                        .replace("recent_k: 8", "recent_k: 1"), encoding="utf-8")
        return path

    def run_engine(self, name, schedule=None, caching=None):
        result = drive.run_system(
            engine_config=self.engine(name), records=BENCHMARKS / "locomo", budget=None,
            experiment="T030", run_root=self.tmp, schedule=schedule, code=CODE, command="test",
            backend_factory=lambda c: FakeBackend(
                prefix_caching=c if caching is None else caching))
        self.assertEqual(result.status, "completed", result.failure)
        return result.run_dir

    def independent_totals(self, run_dir):
        rows = [json.loads(line) for line in
                (run_dir / "calls.jsonl").read_text("utf-8").splitlines()]
        totals = {}
        for row in rows:
            t = totals.setdefault(row["category"], [0, 0, 0])
            t[0] += 1
            t[1] += row["input_tokens"] + row["output_tokens"]
            t[2] += row["input_tokens"] - row["cached_input_tokens"] + row["output_tokens"]
        return totals

    def test_totals_reconcile_for_every_engine_and_schedule(self):
        for name in ("summary-rewrite", "full-history-cached", "bm25"):
            for schedule in (None, "streaming"):
                with self.subTest(engine=name, schedule=schedule):
                    run_dir = self.run_engine(name, schedule)
                    report_ = summary(load_run(run_dir))
                    for category, (calls, logical, computed) in \
                            self.independent_totals(run_dir).items():
                        got = report_["ledgers"][category]
                        self.assertEqual((got["calls"], got["logical"], got["computed"]),
                                         (calls, logical, computed))
                    per_read = sum(r["W_before"]["logical"] + r["U"]["logical"]
                                   + r["A"]["logical"] for r in report_["reads"])
                    self.assertEqual(per_read + report_["unassigned_w"]["logical"],
                                     report_["system"]["logical"])
                    self.assertEqual(report_["n_reads"], 3)

    def test_summary_rewrite_charges_writes_before_streaming_reads(self):
        run = load_run(self.run_engine("summary-rewrite", "streaming"))
        allocation = run.allocation()
        w = ledgers(run.records)["W"]
        self.assertGreater(w.calls, 0)
        charged = sum(c.w_before.logical for c in allocation.reads)
        self.assertEqual(charged + allocation.unassigned_w.logical, w.logical)
        # reads at version 3 and 5: the first is charged the writes of versions 1..3 only
        first = min(allocation.reads, key=lambda c: c.read.version)
        self.assertGreater(first.w_before.logical, 0)
        self.assertLess(first.w_before.logical, w.logical)

    def test_cli_ledger_command(self):
        run_dir = self.run_engine("summary-rewrite", "streaming")
        out = self.tmp / "ledger.json"
        self.assertEqual(report.main(["ledger", str(run_dir), "--json", str(out)]), 0)
        self.assertIn("reconciliation", json.loads(out.read_text("utf-8")))

    def test_cli_ledger_reports_a_mismatch(self):
        run_dir = self.run_engine("bm25")
        calls = run_dir / "calls.jsonl"
        rows = [json.loads(line) for line in calls.read_text("utf-8").splitlines()]
        stray = copy.deepcopy(rows[-1])
        stray["call_id"], stray["read_id"] = "c9999999", "not-a-read"
        calls.write_text("".join(json.dumps(r) + "\n" for r in [*rows, stray]))
        self.assertEqual(report.main(["ledger", str(run_dir)]), 1)


class HandBuiltRuns:
    """Full history with prefix caching against a system, on hand-built runs."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        reads = [Read(f"q{i}", "h", 10) for i in range(4)]
        self.reads = reads
        # Full history: H = 1000 tokens; question part 20, output 5; first read cold.
        full = [record(f"a{i}", read=r.read_id, version=10, inp=1020, out=5,
                       cached=0 if i == 0 else 1000, gpu=1.0 if i == 0 else 0.2)
                for i, r in enumerate(reads)]
        self.full = load_run(write_run(self.tmp / "full", "R-1", full, reads,
                                       {r.read_id: 1000 for r in reads}))
        uncached = [record(f"a{i}", read=r.read_id, version=10, inp=1020, out=5, gpu=1.0,
                           run_id="R-3") for i, r in enumerate(reads)]
        self.uncached = load_run(write_run(self.tmp / "uncached", "R-3", uncached, reads,
                                           {r.read_id: 1000 for r in reads}))
        # System: W = 2000 at write time; 100 + 10 per read.
        system = [record("w1", category="W", trigger="write", version=10, inp=2000, out=0,
                         run_id="R-2")]
        system += [record(f"s{i}", read=r.read_id, version=10, inp=100, out=10, run_id="R-2")
                   for i, r in enumerate(reads)]
        self.system = load_run(write_run(self.tmp / "sys", "R-2", system, reads))


class AmortisationTest(HandBuiltRuns, unittest.TestCase):

    def test_measured_full_history_row_and_formula(self):
        row = am.full_history_row(self.full)
        self.assertEqual(row["logical"], 4 * 1025)
        self.assertEqual(row["computed"], 1025 + 3 * 25)
        self.assertAlmostEqual(row["gpu_seconds"], 1.6)
        self.assertEqual(row["token_cache_ratio"], 0.0)
        # H + c(M-1)H + sum(L): with c = 0 and L = 25, 1000 + 4 * 25
        self.assertEqual(row["formula_cached_at_measured_c"], 1100)
        self.assertEqual(am.formula_full_history(self.full, 1.0), 4 * 1025)
        self.assertEqual(am.formula_full_history(self.full, 0.5), 1000 + 0.5 * 3000 + 100)

    def test_partial_cache_hit_gives_a_token_ratio(self):
        reads = [Read("x", "h", 1), Read("y", "h", 1)]
        recs = [record("a", read="x", inp=520, cached=0), record("b", read="y", inp=520,
                                                                cached=400)]
        run = load_run(write_run(self.tmp / "partial", "R-1", recs, reads,
                                 {"x": 500, "y": 500}))
        self.assertAlmostEqual(am.token_cache_ratio(run)["value"], 0.2)

    def test_gpu_cache_ratio_pairs_warm_reads(self):
        gpu = am.gpu_cache_ratio(self.full, self.uncached)
        self.assertEqual(gpu["pairs"], 3)
        self.assertAlmostEqual(gpu["value"], 0.2)

    def test_payback_over_c(self):
        points = {p.c: p for p in am.payback_curve(self.system, self.full, [0.0, 0.5, 1.0])}
        # c = 1: baseline 1025 per read, system 110: Delta 915, M* = ceil(2000 / 915) = 3
        self.assertEqual(points[1.0].delta, 915)
        self.assertEqual(points[1.0].m_star, 3)
        # c = 0: baseline 25 per warm read, system 110: no payback point
        self.assertIsNone(points[0.0].m_star)
        self.assertEqual(points[0.5].delta, 525 - 110)
        self.assertEqual(points[0.5].m_star, math.ceil(2000 / 415))

    def test_payback_read_count_edge_cases(self):
        self.assertIsNone(am.payback_read_count(100, 0))
        self.assertIsNone(am.payback_read_count(100, -3))
        self.assertEqual(am.payback_read_count(0, 5), 0)
        self.assertEqual(am.payback_read_count(10, 5), 2)

    def test_cumulative_curves_and_crossing(self):
        system = am.cumulative(self.system, "sys", ledger="logical")[0]
        full = am.cumulative(self.full, "full", ledger="logical")[0]
        self.assertEqual(system.points, [2110, 2220, 2330, 2440])
        self.assertEqual(full.points, [1025, 2050, 3075, 4100])
        self.assertEqual(am.crossing(system, full), 3)
        cached = am.cumulative(self.full, "full", ledger="computed")[0]
        self.assertIsNone(am.crossing(system, cached))
        shuffled = am.cumulative(self.system, "sys", ledger="logical", seed=1)[0]
        self.assertEqual(shuffled.points[-1], system.points[-1])
        self.assertEqual(shuffled.points[0], 2110)

    def test_cost_per_success(self):
        result = am.cost_per_success(self.system, {"q0": True, "q1": False, "q2": True})
        self.assertEqual(result["n_success"], 2)
        self.assertEqual(result["n_unscored"], 1)
        self.assertEqual(result["success_rate"], 0.5)
        self.assertEqual(result["cost_per_success"]["logical"], 2440 / 2)
        none = am.cost_per_success(self.system, {})
        self.assertIsNone(none["cost_per_success"]["logical"])

    def test_success_from_judgements(self):
        rows = [{"read_id": "q0", "judge": "blind", "verdict": "correct"},
                {"read_id": "q1", "judge": "blind", "verdict": "invalid"},
                {"read_id": "q0", "judge": "official", "verdict": "incorrect"}]
        self.assertEqual(am.success_from_judgements(rows, "blind"), {"q0": True, "q1": False})
        with self.assertRaises(LedgerError):
            am.success_from_judgements(rows)

    def test_read_stage_carries_its_ingestion(self):
        ingest = [record("c1", category="W", trigger="write", version=10, inp=300, out=0,
                         run_id="I-1"),
                  record("c2", category="W", trigger="write", version=11, inp=7, out=0,
                         run_id="I-1")]
        ingest_dir = write_run(self.tmp / "ingest", "I-1", ingest, [], stage="ingest")
        reads = [Read("q0", "h", 10)]
        read_dir = write_run(self.tmp / "read", "R-9",
                             [record("c1", read="q0", version=10, run_id="R-9")], reads,
                             stage="read", upstream=[{"run_id": "I-1", "stage": "ingest",
                                                      "path": str(ingest_dir)}])
        run = load_run(read_dir)
        allocation = run.allocation()  # call IDs repeat across the two runs
        self.assertEqual(allocation.reads[0].w_before.logical, 300)
        self.assertEqual(allocation.unassigned_w_ids, ["I-1/c2"])
        reconcile(run.records, allocation)
        self.assertEqual(am.mean_cost_per_read(run)["logical"], 417)

    def test_percentile(self):
        self.assertIsNone(percentile([], 50))
        self.assertEqual(percentile([1, 2, 3, 4], 50), 2.5)
        self.assertAlmostEqual(percentile(list(range(1, 101)), 95), 95.05)


class ReportCliTest(HandBuiltRuns, unittest.TestCase):
    """The curve commands write only into a new directory under the runs root."""

    def setUp(self):
        super().setUp()
        self.root = self.tmp / "runs-root"
        self.root.mkdir()
        previous = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = str(self.tmp)
        self.addCleanup(lambda: os.environ.__setitem__("PROJECT_ROOT", previous)
                        if previous is not None else os.environ.pop("PROJECT_ROOT"))
        self.runs_root = report.shared_dir("runs_root")
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def test_amortise_payback_and_success(self):
        out = self.runs_root / "T030" / "curves"
        self.assertEqual(report.main([
            "amortise", "--out", str(out / "a"), "--run", f"sys={self.tmp / 'sys'}",
            "--run", f"full={self.tmp / 'full'}", "--ledger", "logical",
            "--baseline", "full"]), 0)
        self.assertEqual(json.loads((out / "a" / "crossings.json").read_text())[0]
                         ["crossing_reads"], 3)
        self.assertTrue((out / "a" / "cumulative.png").stat().st_size > 0)
        inputs = json.loads((out / "a" / "inputs.json").read_text())
        self.assertEqual({i["run_id"] for i in inputs["inputs"]}, {"R-1", "R-2"})
        self.assertEqual(report.main([
            "payback", "--out", str(out / "p"), "--system", f"sys={self.tmp / 'sys'}",
            "--full-history", str(self.tmp / "full"), "--uncached",
            str(self.tmp / "uncached"), "--steps", "4"]), 0)
        row = json.loads((out / "p" / "full-history-row.json").read_text())
        self.assertEqual(row["cached"]["computed"], 1100)
        self.assertAlmostEqual(row["gpu_cache_ratio"]["value"], 0.2)
        self.assertTrue((out / "p" / "payback.png").exists())
        judge = self.tmp / "judge"
        judge.mkdir()
        (judge / "judgements.jsonl").write_text(
            json.dumps({"read_id": "q0", "judge": "blind", "verdict": "correct"}) + "\n")
        self.assertEqual(report.main([
            "success", "--out", str(out / "s"), "--run",
            f"sys={self.tmp / 'sys'}:{judge}"]), 0)
        rows = json.loads((out / "s" / "cost-per-success.json").read_text())
        self.assertEqual(rows[0]["n_success"], 1)

    def test_quality_command(self):
        score = self.tmp / "score"
        score.mkdir()
        (score / "run.json").write_text(json.dumps({"run_id": "S-1", "upstream": [
            {"run_id": "R-2", "stage": "system", "path": str(self.tmp / "sys")}]}))
        (score / "metrics.json").write_text(json.dumps({"metrics": [
            {"metric": "f1", "annotation": "a", "stratum": None, "value": 0.5,
             "n_scored": 4}]}))
        out = self.runs_root / "T030" / "q"
        self.assertEqual(report.main(["quality", "--out", str(out), "--score", f"sys={score}",
                                      "--metric", "f1", "--ledger", "logical"]), 0)
        self.assertIn("sys,f1,0.5,4,610.0", (out / "quality.csv").read_text())

    def test_out_must_be_new_and_under_the_runs_root(self):
        with self.assertRaises(SystemExit):
            report.main(["amortise", "--out", str(self.tmp / "elsewhere"), "--run",
                         f"sys={self.tmp / 'sys'}"])
        with self.assertRaises(FileExistsError):
            report.main(["amortise", "--out", str(self.runs_root), "--run",
                         f"sys={self.tmp / 'sys'}"])

    def test_unfinished_runs_are_refused(self):
        write_run(self.tmp / "running", "R-7", [], [], status="running")
        with self.assertRaises(SystemExit):
            report.main(["amortise", "--out", str(self.runs_root / "x"), "--run",
                         f"r={self.tmp / 'running'}"])


if __name__ == "__main__":
    unittest.main()
