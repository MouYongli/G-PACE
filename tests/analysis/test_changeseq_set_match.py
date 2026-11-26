"""Normalised set match of the change sequences and the paired cluster bootstrap (E005)."""

from __future__ import annotations

import unittest

from grace.eval.analysis.metrics.changeseq import (
    candidate_pools,
    cluster_bootstrap,
    family_of,
    mentions,
    paired_bootstrap,
    set_match,
    tokens,
)


def gold(reference, template="V1", *, outdated=(), premise=False, history="h-rho1-L60-000"):
    return {"history_id": history, "task_id": "t", "annotation": "generator",
            "reference": list(reference),
            "labels": {"template": template, "expected_abstention": not reference,
                       "premise_outdated": premise, "question_type": "uniform",
                       "change_type": "none"},
            "metadata": {"outdated_text": list(outdated)}}


class NormalisationTest(unittest.TestCase):
    def test_tokens_and_mentions(self):
        self.assertEqual(tokens("EC 175, Five-room!"), ("ec", "175", "5", "room"))
        self.assertTrue(mentions(tokens("It leaves at 16:40."), "16:40"))
        self.assertFalse(mentions(tokens("platform 13"), "3"))      # whole tokens only
        self.assertFalse(mentions(tokens("EC175"), "EC 175"))      # the surface form counts
        self.assertTrue(mentions(tokens("three of them"), "3"))
        self.assertEqual(family_of("car-rental-rho10-L200-001"), "car-rental")


class SetMatchTest(unittest.TestCase):
    POOL = {"Dutch", "Greek", "Polish"}

    def test_exact_set(self):
        g = gold(["Dutch", "Greek"], outdated=["Polish"])
        self.assertEqual(set_match("answer", ["Greek", "Dutch"], g, self.POOL), 1.0)
        self.assertEqual(set_match("answer", "Dutch and Greek", g, self.POOL), 1.0)

    def test_missing_or_extra_value_is_wrong(self):
        g = gold(["Dutch", "Greek"], outdated=["Polish"])
        self.assertEqual(set_match("answer", "Dutch", g, self.POOL), 0.0)
        self.assertEqual(set_match("answer", "Dutch, Greek and Polish", g, self.POOL), 0.0)

    def test_unknown_invalid_and_abstention(self):
        empty = gold([])
        self.assertEqual(set_match("unknown", None, empty, self.POOL), 1.0)
        self.assertEqual(set_match("answer", "You have not told me any.", empty, self.POOL), 1.0)
        self.assertEqual(set_match("answer", "Greek", empty, self.POOL), 0.0)
        self.assertEqual(set_match("unknown", None, gold(["Greek"]), self.POOL), 0.0)
        self.assertEqual(set_match("invalid", None, gold(["Greek"]), self.POOL), 0.0)

    def test_presupposition_may_reject_the_outdated_premise(self):
        g = gold(["journalism"], "V2", outdated=["education"], premise=True)
        pool = {"journalism", "education"}
        self.assertEqual(set_match("answer", "No, journalism now, not education.", g, pool), 1.0)
        self.assertEqual(set_match("answer", "Yes, still education.", g, pool), 0.0)
        plain = gold(["journalism"], "V2", outdated=["education"])
        self.assertEqual(set_match("answer", "journalism, before that education", plain, pool),
                         0.0)

    def test_constraints_score_values_and_choices_both_parts(self):
        g4 = gold([["apartmentSize", "three-room"], ["district", "Altstadt"]], "V4")
        pool4 = {"three-room", "five-room", "Altstadt"}
        self.assertEqual(set_match("answer", "A 3-room flat in Altstadt", g4, pool4), 1.0)
        self.assertEqual(set_match("answer", "A five-room flat in Altstadt", g4, pool4), 0.0)
        g6 = gold([["Opel Astra", "16:40"]], "V6", outdated=[["Toyota Yaris", "15:10"]])
        pool6 = {"Opel Astra", "16:40", "Toyota Yaris", "15:10"}
        self.assertEqual(set_match("answer", "Opel Astra, pickup at 16:40", g6, pool6), 1.0)
        self.assertEqual(set_match("answer", "Opel Astra", g6, pool6), 0.0)

    def test_a_pool_value_inside_a_gold_value_is_not_forbidden(self):
        g = gold(["Central Station"], "V2")
        self.assertEqual(set_match("answer", "Central Station", g, {"Central Station",
                                                                    "Station"}), 1.0)

    def test_candidate_pools(self):
        rows = [gold(["Dutch"], outdated=["Polish"]), gold([["Opel Astra", "16:40"]], "V6"),
                gold([["apartmentSize", "three-room"]], "V4")]
        pools = candidate_pools(rows)
        self.assertEqual(pools[("h-rho1-L60-000", "V1")], {"Dutch", "Polish"})
        self.assertEqual(pools[("h-rho1-L60-000", "V6")], {"Opel Astra", "16:40"})
        self.assertEqual(pools[("h-rho1-L60-000", "V4")], {"three-room"})


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.clusters = {f"r{i}": f"c{i % 3}" for i in range(30)}
        self.a = {r: float(i % 2) for i, r in enumerate(self.clusters)}
        self.b = {r: 0.0 for r in self.clusters}

    def test_identical_arms_differ_by_zero(self):
        out = paired_bootstrap(self.a, dict(self.a), self.clusters, resamples=200, seed=1)
        self.assertEqual((out["difference"], out["ci95"]), (0.0, [0.0, 0.0]))
        self.assertEqual((out["a_only_correct"], out["b_only_correct"]), (0, 0))

    def test_difference_interval_and_determinism(self):
        out = paired_bootstrap(self.a, self.b, self.clusters, resamples=500, seed=7)
        again = paired_bootstrap(self.a, self.b, self.clusters, resamples=500, seed=7)
        self.assertEqual(out, again)
        self.assertAlmostEqual(out["difference"], 0.5)
        self.assertLessEqual(out["ci95"][0], out["difference"])
        self.assertGreaterEqual(out["ci95"][1], out["difference"])
        self.assertEqual(out["n_clusters"], 3)
        self.assertEqual(out["a_only_correct"], 15)
        self.assertEqual(set(out["leave_one_cluster_out"]), {"c0", "c1", "c2"})

    def test_unpaired_reads_are_refused(self):
        with self.assertRaises(ValueError):
            paired_bootstrap(self.a, {"r0": 1.0}, self.clusters)

    def test_cluster_bootstrap_mean(self):
        out = cluster_bootstrap(self.a, self.clusters, resamples=100, seed=0)
        self.assertAlmostEqual(out["mean"], 0.5)
        self.assertEqual(out["n_reads"], 30)


if __name__ == "__main__":
    unittest.main()
