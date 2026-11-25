"""E001 pilot statistics (`grace.eval.analysis.metrics.pilot`) on hand-computed cases."""

import unittest

from grace.eval.analysis.metrics import pilot


def read(history, version, prompt, context, task=None, rid=None):
    return {"history_id": history, "version": version, "prompt_tokens": prompt,
            "context_tokens": context, "task_id": task or f"{history}:{version}",
            "read_id": rid or f"{history}:{version}@{version}"}


class DistributionTest(unittest.TestCase):
    def test_percentiles_interpolate_like_numpy(self):
        d = pilot.distribution([4, 1, 3, 2])
        self.assertEqual((d["n"], d["sum"], d["min"], d["max"]), (4, 10, 1, 4))
        self.assertEqual(d["p50"], 2.5)
        self.assertAlmostEqual(d["p25"], 1.75)
        self.assertAlmostEqual(d["p90"], 3.7)

    def test_empty(self):
        self.assertEqual(pilot.distribution([])["n"], 0)
        self.assertIsNone(pilot.distribution([])["p50"])


class FullHistoryCostTest(unittest.TestCase):
    def test_incremental_accounting_of_plan_8_2(self):
        # Prompt = context + 10 fixed tokens. Reads at contexts 100, 100 (same version), 150.
        reads = [read("h", 5, 110, 100, rid="a"), read("h", 5, 110, 100, rid="b"),
                 read("h", 8, 160, 150, rid="c")]
        # First pays 110; second pays its fixed 10; third pays 50 new + 10 fixed.
        self.assertEqual(pilot.incremental_input(reads), 110 + 10 + 60)

    def test_length_tables(self):
        histories = [{"history_id": "h", "n_messages": 8, "history_tokens": 150,
                      "mean_message_tokens": 18.0},
                     {"history_id": "g", "n_messages": 2, "history_tokens": 40,
                      "mean_message_tokens": 20.0}]
        reads = [read("h", 5, 110, 100), read("h", 8, 160, 150), read("g", 2, 50, 40)]
        t = pilot.length_tables(histories, reads, window_tokens=120, output_reserve_tokens=20)
        cost = t["full_history_cost"]
        self.assertEqual(cost["logical_input_tokens"], 320)
        self.assertEqual(cost["incremental_input_tokens"], 110 + 60 + 50)
        self.assertAlmostEqual(cost["prefix_reuse_bound"], 100 / 320, places=6)
        # 110 + 20 > 120 and 160 + 20 > 120; 50 + 20 fits.
        self.assertEqual(t["window"]["reads_over_window"], 2)
        self.assertEqual(t["window"]["histories_over_window"], 1)
        self.assertEqual(t["fixed_prompt_tokens"]["max"], 10)

    def test_prompt_reserve_rule(self):
        self.assertEqual(pilot.prompt_reserve(600, 256, 64, 128), 1024)
        self.assertEqual(pilot.prompt_reserve(577, 256, 64, 128), 1024)
        self.assertEqual(pilot.prompt_reserve(705, 256, 64, 128), 1152)


class UpdateDensityTest(unittest.TestCase):
    def test_multiwoz_revisions(self):
        reads = [read("d", 1, 0, 0, "d:0"), read("d", 3, 0, 0, "d:2"),
                 read("d", 5, 0, 0, "d:4"), read("d", 7, 0, 0, "d:6")]
        states = {"d:0": {"a": "1"}, "d:2": {"a": "1", "b": "x"},  # addition
                  "d:4": {"a": "2", "b": "x"},                     # revision
                  "d:6": {"a": "2", "b": "x"}}                     # no change
        gold = [{"task_id": t, "annotation": "2.4", "reference": s} for t, s in states.items()]
        gold.append({"task_id": "d:4", "annotation": "2.1", "reference": {}})
        d = pilot.multiwoz_density(reads, gold, n_messages=8)
        self.assertEqual(d["rereads"], 3)
        self.assertEqual(d["rereads_after_answer_change"], 2)
        self.assertEqual(d["rereads_after_revision"], 1)
        self.assertEqual(d["slot_additions"], 2)
        self.assertEqual(d["revisions_per_1000_messages"], 125.0)

    def test_multiwoz_removal_counts_as_revision(self):
        reads = [read("d", 1, 0, 0, "d:0"), read("d", 3, 0, 0, "d:2")]
        gold = [{"task_id": "d:0", "annotation": "2.4", "reference": {"a": "1"}},
                {"task_id": "d:2", "annotation": "2.4", "reference": {}}]
        d = pilot.multiwoz_density(reads, gold, n_messages=4)
        self.assertEqual((d["slot_removals"], d["rereads_after_revision"]), (1, 1))

    def test_halumem_reads_citing_updates(self):
        points = [{"history_id": "u", "memory_content": "lives in Rome", "is_update": "True"},
                  {"history_id": "u", "memory_content": "likes tea", "is_update": "False"},
                  {"history_id": "v", "memory_content": "likes tea", "is_update": True}]
        gold = [{"task_id": "q1", "labels": {"question_type": "Dynamic Update"},
                 "metadata": {"evidence_memory_points": [{"memory_content": "lives in Rome"}]}},
                {"task_id": "q2", "labels": {"question_type": "Basic Fact Recall"},
                 "metadata": {"evidence_memory_points": [{"memory_content": "likes tea"}]}}]
        reads = [read("u", 3, 0, 0, "q1"), read("u", 4, 0, 0, "q2")]
        d = pilot.halumem_density(reads, gold, points, n_messages=500)
        self.assertEqual(d["update_points"], 2)
        self.assertEqual(d["updates_per_1000_messages"], 4.0)
        self.assertEqual(d["reads_citing_update"], 1)  # "likes tea" is an update only for v

    def test_stratum(self):
        gold = [{"task_id": "a", "labels": {"question_type": "knowledge-update"}},
                {"task_id": "b", "labels": {"question_type": "multi-session"}}]
        reads = [read("a", 9, 0, 0, "a"), read("b", 9, 0, 0, "b")]
        d = pilot.stratum_density(reads, gold, 1000, "question_type", "knowledge-update", "x")
        self.assertEqual((d["reads_in_stratum"], d["share_reads_in_stratum"]), (1, 0.5))

    def test_changeseq_reads_after_stale_update(self):
        labels = [{"history_id": "s", "binding_id": "V1:k", "version": 3, "answer_stale": True,
                   "citation_stale": False},
                  {"history_id": "s", "binding_id": "V2:k", "version": 6, "answer_stale": False,
                   "citation_stale": True}]
        gold = [{"task_id": t, "metadata": {"binding_id": b}}
                for t, b in (("t1", "V1:k"), ("t2", "V1:k"), ("t3", "V2:k"))]
        reads = [read("s", 2, 0, 0, "t1", "r1"), read("s", 5, 0, 0, "t2", "r2"),
                 read("s", 8, 0, 0, "t3", "r3")]
        d = pilot.changeseq_density(reads, gold, labels, n_messages=10)
        # r2 reads V1 after its stale update at 3; r3's binding was only citation-stale.
        self.assertEqual(d["reads_after_answer_stale_update"], 1)
        self.assertEqual(d["answer_stale_messages"], 1)
        self.assertEqual(d["citation_stale_messages"], 1)


def call(new, cached, out, latency, status="ok", category="A", call_type="answer"):
    return {"input_tokens": new + cached, "cached_input_tokens": cached, "output_tokens": out,
            "latency_ms": latency, "status": status, "category": category,
            "call_type": call_type}


class CacheTest(unittest.TestCase):
    def test_call_sums(self):
        s = pilot.call_sums([call(100, 900, 10, 50.0), call(0, 0, 0, 5.0, status="failed")])
        self.assertEqual(s["computed_tokens"], 110)
        self.assertEqual(s["logical_tokens"], 1010)
        self.assertEqual(s["cache_hit_ratio"], 0.9)
        self.assertEqual(s["failed"], 1)

    def test_compute_ratio_recovers_the_coefficients(self):
        # latency = 20 + 0.5 ms per 1k new input + 0.05 per 1k cached + 15 per 1k output.
        calls = []
        for new, cached, out in [(30000, 0, 20), (1000, 29000, 30), (500, 10000, 10),
                                 (20000, 5000, 50), (8000, 0, 5), (200, 31000, 40),
                                 (16000, 16000, 25), (4000, 2000, 60), (100, 100, 1)]:
            latency = 20 + 0.5 * new / 1000 + 0.05 * cached / 1000 + 15 * out / 1000
            calls.append(call(new, cached, out, latency))
        calls.append(call(10, 10, 1, 1e6, status="failed"))  # failed attempts are left out
        fit = pilot.compute_ratio(calls)
        self.assertAlmostEqual(fit["c"], 0.1, places=3)
        self.assertAlmostEqual(fit["intercept_ms"], 20, places=2)
        self.assertAlmostEqual(fit["r2"], 1.0, places=4)

    def test_compute_ratio_needs_separable_calls(self):
        calls = [call(1000 * i, 0, 10, 10.0 + i) for i in range(1, 10)]
        self.assertIsNone(pilot.compute_ratio(calls)["c"])  # no cached input: singular

    def test_judge_estimate(self):
        est = pilot.judge_estimate([{"output": "answer"}, {"output": "unknown"}], [400],
                                   {"input": 0.5, "output": 2.0}, output_tokens=10)
        self.assertEqual(est["judgeable_predictions"], 1)
        self.assertAlmostEqual(est["secondary_usd_estimate"], (400 * 0.5 + 10 * 2.0) / 1e6, 6)


if __name__ == "__main__":
    unittest.main()
