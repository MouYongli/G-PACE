"""E011 (ablation B): single-time extractor, the writer's no-guard config, the E011 driver's pure
helpers (sharding, population sampling, the guard-share statistic, change-seq stale values)."""

from __future__ import annotations

import unittest

import yaml

from grace.cli import ablation_b as ab
from grace.config.paths import REPO_ROOT
from grace.context.pipeline.update.extract import Extraction, Extractor
from grace.context.pipeline.update.patch import ClaimPatch, PatchClaim, PatchStance, StanceFields
from grace.context.pipeline.update.single_time import SingleTimeExtractor, strip_valid_time
from grace.eval.analysis.metrics import changeseq as csm

CONFIG = REPO_ROOT / "configs" / "experiments" / "E011-ablation-b-attribution-guard.yaml"


def timed_patch() -> ClaimPatch:
    return ClaimPatch(
        claims=(PatchClaim(1, "user", "livesIn", "Hamburg", valid_from="2015-01-01",
                           valid_until="2019-01-01", time_expression="from 2015 to 2019"),),
        stances=(PatchStance(2, "k1", StanceFields(polarity="negative"), ends="change",
                             valid_until="2020-01-01"),))


class Fixed(Extractor):
    def __init__(self, result: Extraction):
        self.result = result

    def extract(self, request):
        return self.result


class SingleTimeTest(unittest.TestCase):
    def test_valid_times_are_dropped_and_nothing_else(self):
        patch = strip_valid_time(timed_patch())
        claim, stance = patch.claims[0], patch.stances[0]
        self.assertEqual((claim.valid_from, claim.valid_until, claim.time_expression),
                         (None, None, None))
        self.assertEqual((claim.subject, claim.predicate, claim.object),
                         ("user", "livesIn", "Hamburg"))
        self.assertIsNone(stance.valid_until)
        self.assertEqual((stance.ends, stance.stance.polarity), ("change", "negative"))

    def test_wrapper_keeps_status_and_call_ids(self):
        ok = Extraction("ok", timed_patch(), call_ids=("c1",), statuses=("ok",))
        out = SingleTimeExtractor(Fixed(ok)).extract(None)
        self.assertEqual((out.status, out.call_ids), ("ok", ("c1",)))
        self.assertIsNone(out.patch.claims[0].valid_from)
        failed = Extraction("failed", None, error="x", call_ids=("c2",))
        self.assertIs(SingleTimeExtractor(Fixed(failed)).extract(None), failed)


class WriterConfigTest(unittest.TestCase):
    def test_noguard_writer_differs_from_the_main_writer_only_in_the_guard(self):
        main = yaml.safe_load((REPO_ROOT / "configs/common/writer.yaml").read_text())
        noguard = yaml.safe_load((REPO_ROOT / "configs/common/writer-noguard.yaml").read_text())
        self.assertTrue(main.pop("guard"))
        self.assertFalse(noguard.pop("guard"))
        self.assertEqual(main, noguard)


class DriverTest(unittest.TestCase):
    def test_config_arms_name_existing_engine_configs(self):
        config = ab.load_experiment(CONFIG)
        for name, arm in config["arms"].items():
            with self.subTest(arm=name):
                self.assertTrue((REPO_ROOT / arm["engine"]).is_file())
        self.assertEqual(sum("representation" in a for a in config["arms"].values()), 8)

    def test_shards_partition_the_histories(self):
        items = [f"h{i}" for i in range(10)]
        parts = [ab.shard(items, f"{i}/3") for i in range(3)]
        self.assertEqual(sorted(sum(parts, [])), sorted(items))
        self.assertEqual(ab.shard(items, None), items)
        with self.assertRaises(ValueError):
            ab.shard(items, "3/3")

    def test_population_is_a_seeded_subset_of_dialogues_with_paired_items(self):
        def gold(h, t, paired):
            return {"history_id": h, "task_id": f"{h}:{t}",
                    "reference": {"retention": [], "paired": [{}] if paired else []}}
        derived = {g["task_id"]: g for g in (
            gold("A", 2, True), gold("A", 4, False), gold("B", 2, False), gold("C", 2, True),
            gold("D", 6, True))}
        spec = {"sample": 2, "sample_seed": 28}
        histories, tasks = ab.mw_population(spec, derived=derived)
        self.assertEqual(len(histories), 2)
        self.assertNotIn("B", histories)
        self.assertEqual(tasks, sorted(t for t, g in derived.items()
                                       if g["history_id"] in histories))
        self.assertEqual(ab.mw_population(spec, derived=derived), (histories, tasks))
        with self.assertRaises(ValueError):
            ab.mw_population({"sample": 4, "sample_seed": 1}, derived=derived)

    def test_guard_share(self):
        keys = [f"k{i}" for i in range(8)]
        clusters = {k: f"c{i // 2}" for i, k in enumerate(keys)}
        guard_on = dict.fromkeys(keys, 1.0)
        guard_off = {k: float(i % 2) for i, k in enumerate(keys)}   # guard gain 0.5
        tagged = {k: 1.0 if i % 4 != 0 else 0.0 for i, k in enumerate(keys)}
        rrf = guard_off                                              # tag gain 0.25
        out = ab.guard_share(tagged, rrf, guard_on, guard_off, clusters, resamples=200)
        self.assertAlmostEqual(out["guard_gain"], 0.5)
        self.assertAlmostEqual(out["tag_gain"], 0.25)
        self.assertAlmostEqual(out["share"], 0.5)
        self.assertEqual(out["n"], 8)

    def test_stale_value_use_on_changeseq(self):
        gold = [{"task_id": "t1", "annotation": "generator",
                 "labels": {"template": "V2", "premise_outdated": False,
                            "question_type": "changed", "change_type": "C5",
                            "pair_kind": None},
                 "metadata": {"outdated_text": ["Leipzig"]}}]
        scored = [csm.Scored("r1", "t1", "s1", "fam", "changed", "V2", "C5", "answer", 0.0)]
        rows = ab.cs_values(scored, gold, [{"read_id": "r1", "output": "answer",
                                            "prediction": "You live in Leipzig."}],
                            ["changed"], ["change_type"])
        metrics = {r["metric"]: r["value"] for r in rows}
        self.assertEqual(metrics["stale_value_use"], 1.0)
        self.assertEqual(metrics["set-match|change_type=C5"], 0.0)


if __name__ == "__main__":
    unittest.main()
