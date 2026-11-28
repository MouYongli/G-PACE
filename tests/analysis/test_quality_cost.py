"""E014 pricing with cache accountings, break-even and cumulative cost (quality_cost module)."""

import unittest
from pathlib import Path

from grace.eval.analysis.metrics.cost import quality_cost as qc
from grace.eval.analysis.metrics.cost.ledger import Read, RunCost
from grace.llm.records import CallRecord

CATEGORY = {"extract": ("W", "write"), "plan": ("U", "read"), "answer": ("A", "read")}


def rec(call_id, call_type, *, run="R-1", history="h", read=None, inp=1000, out=10, cached=0,
        model="Qwen/Qwen3-8B@abc", sha=None, version=1):
    category, trigger = CATEGORY[call_type]
    return CallRecord(call_id=call_id, run_id=run, history_id=history,
                      read_id=None if trigger == "write" else read, version=version,
                      call_type=call_type, trigger=trigger, category=category, model=model,
                      attempt=1, status="ok", input_tokens=inp, output_tokens=out,
                      cached_input_tokens=cached, gpu_seconds=None, latency_ms=1.0,
                      prompt_sha256=sha)


def run_cost(run_id, records, reads):
    return RunCost(Path("/nonexistent"), {"run_id": run_id}, records,
                   [Read(r, "h", 1) for r in reads], {})


class PricerTest(unittest.TestCase):
    def setUp(self):
        self.records = [
            rec("1", "extract", run="ING", model="Qwen/Qwen3-32B@x", inp=1000, cached=600, out=100),
            rec("2", "plan", read="q1", inp=2000, sha="P"),
            rec("3", "answer", read="q1", inp=500, sha="A"),
        ]
        self.unreported = qc.unreported_runs(self.records)

    def test_unreported_is_per_run_and_model(self):
        self.assertEqual(self.unreported, {("R-1", "Qwen/Qwen3-8B")})

    def test_reported_and_imputed(self):
        reported = qc.Pricer("reported", {}, self.unreported, {"P": 1600, "A": 400})
        imputed = qc.Pricer("imputed", {}, self.unreported, {"P": 1600, "A": 400})
        # c = 0: extract 1000 - 600 + 100; plan 2000 + 10; answer 500 + 10
        self.assertEqual(reported.price(self.records, 0.0), 500 + 2010 + 510)
        self.assertEqual(imputed.price(self.records, 0.0), 500 + 410 + 110)
        # c = 1 is the logical ledger under every accounting
        self.assertEqual(imputed.price(self.records, 1.0), reported.price(self.records, 1.0))

    def test_probe_overrides_static_and_caps_at_input(self):
        probe = qc.Pricer("probe", {}, self.unreported, {"P": 1600, "A": 400},
                          {"plan": 1900.0, "answer": 9999.0})
        self.assertEqual(probe.cached(self.records[1]), 1900)
        self.assertEqual(probe.cached(self.records[2]), 500)
        self.assertEqual(probe.cached(self.records[0]), 600)  # reporting run unchanged

    def test_compute_weight(self):
        p = qc.Pricer("reported", {"Qwen/Qwen3-32B": 4.0}, self.unreported)
        self.assertEqual(p.price(self.records[:1], 0.0), 4 * 500)


class BreakEvenTest(unittest.TestCase):
    def test_m_star_and_c_star(self):
        # system: W 1000 logical (all uncached), reads of 100; baseline warm reads 1100 input,
        # 1000 of it cached, so its warm read costs 100 + 1000 c.
        sys_records = [rec("w", "extract", run="S", inp=1000, out=0)]
        sys_records += [rec(f"a{i}", "answer", run="S", read=f"q{i}", inp=100, out=0)
                        for i in range(4)]
        base_records = [rec(f"b{i}", "answer", run="B", read=f"q{i}", inp=1100, out=0,
                            cached=0 if i == 0 else 1000) for i in range(4)]
        system = qc.System("s", [run_cost("S", sys_records, [f"q{i}" for i in range(4)])])
        base = qc.System("b", [run_cost("B", base_records, [f"q{i}" for i in range(4)])])
        p = qc.Pricer("reported")
        points = qc.break_even(system, base, p, p, [0.0, 0.5, 1.0])
        by_c = {b.c: b for b in points}
        self.assertIsNone(by_c[0.0].m_star)          # delta 0: no payback
        self.assertEqual(by_c[0.5].m_star, 2)        # delta 500, W 1000
        self.assertEqual(by_c[1.0].m_star, 1)
        self.assertEqual(qc.c_star(points), {"h": 0.5})

    def test_cumulative_and_crossing(self):
        records = [rec("w", "extract", run="S", inp=300, out=0),
                   rec("a", "answer", run="S", read="q1", inp=100, out=0),
                   rec("b", "answer", run="S", read="q2", inp=100, out=0)]
        system = qc.System("s", [run_cost("S", records, ["q1", "q2"])])
        curve = qc.cumulative(system, qc.Pricer("reported"), 1.0, upfront_writes=True)["h"]
        self.assertEqual(curve, [400.0, 500.0])
        self.assertEqual(qc.crossing(curve, [300.0, 600.0]), 2)
        self.assertIsNone(qc.crossing(curve, [300.0, 400.0]))

    def test_quality_helpers(self):
        summary = qc.f1_summary([{"f1": 1.0, "output": "answer"}, {"f1": 0.2, "output": "unknown"}],
                                0.5)
        self.assertEqual((summary["f1"], summary["n_success"], summary["n_unknown"]), (0.6, 1, 1))
        pts = [{"f1": 0.3, "tokens": 10}, {"f1": 0.35, "tokens": 30}, {"f1": 0.36, "tokens": 20}]
        self.assertEqual(qc.cheapest_at_quality(pts, 0.34)["tokens"], 20)
        self.assertIsNone(qc.cheapest_at_quality(pts, 0.4))


if __name__ == "__main__":
    unittest.main()
