"""Unit tests of the MultiWOZ offer rule and census (T006) on synthetic annotations."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from grace.eval.datasets.benchmarks import multiwoz_offers as mo
from tests.contracts import benchmark_sources


def dialogue(acts21, states24, states22=None, states21=None, acts22=None, did="SYN.json"):
    """Synthetic dialogue: raw 2.1 acts per turn and one state per user turn per version."""
    def wrap(states):
        return [{k: {v} if isinstance(v, str) else set(v) for k, v in s.items()} for s in states]
    return mo.DialogueInput(
        dialogue_id=did, acts={"2.1": acts21, "2.2": acts22 or [None] * len(acts21)},
        states={"2.4": wrap(states24), "2.2": wrap(states22 or states24),
                "2.1": wrap(states21 or states24)})


class ValueMatching(unittest.TestCase):
    def test_lenient_matches(self):
        for a, b in [("the ashley hotel", "ashley hotel"), ("guest house", "guesthouse"),
                     ("west", "west of town"), ("mediterranean", "italian or mediterranean"),
                     ("hotel", "hotels"), ("moderate", "moderately priced"),
                     ("ashely hotel", "ashley hotel"), ("13.54", "13:54"),
                     ("8:07 am", "08:07"), ("do nt care", "dontcare")]:
            with self.subTest(a=a, b=b):
                self.assertTrue(mo.values_match(a, b))

    def test_non_matches(self):
        for a, b in [("cheap", "expensive"), ("10:00", "08:07"), ("2", "4"),
                     ("hotel", "guesthouse"), ("dontcare", "centre"), ("north", "east")]:
            with self.subTest(a=a, b=b):
                self.assertFalse(mo.values_match(a, b))

    def test_canon_pm(self):
        self.assertEqual(mo.canon("7:30 pm"), "19:30")
        self.assertEqual(mo.canon("12:15 am"), "00:15")


class ActParsing(unittest.TestCase):
    def test_slot_names_21(self):
        acts = mo.parse_acts({"Train-Inform": [["Day", "Monday"], ["Leave", "9:00"]],
                              "Hotel-Inform": [["Day", "Sunday"], ["Price", "Cheap "]]}, "2.1")
        self.assertIn(mo.Act("train", "inform", "day", "monday"), acts)
        self.assertIn(mo.Act("train", "inform", "leaveat", "9:00"), acts)
        self.assertIn(mo.Act("hotel", "inform", "bookday", "sunday"), acts)
        self.assertIn(mo.Act("hotel", "inform", "pricerange", "cheap"), acts)

    def test_booking_resolution(self):
        acts = mo.parse_acts({"Booking-Inform": [["none", "none"]]}, "2.1")
        previous = mo.parse_acts({"Hotel-Inform": [["Stay", "2"]]}, "2.1")
        resolved = mo.resolve_booking(acts, previous, None)
        self.assertEqual(resolved[0].domain, "hotel")
        self.assertEqual(resolved[0].intent, "booking-inform")
        self.assertEqual(mo.resolve_booking(acts, [], None)[0].domain, "booking")
        self.assertEqual(mo.resolve_booking(acts, [], "train")[0].domain, "train")


class OfferRule(unittest.TestCase):
    def test_recommend_then_accept_explicit(self):
        d = dialogue(
            [{"Restaurant-Inform": [["Food", "thai"]]},
             {"Restaurant-Recommend": [["Name", "Bangkok City"], ["Area", "centre"]]},
             {"Restaurant-Inform": [["People", "2"], ["Day", "monday"]]},
             {"Booking-Book": [["Ref", "X1"]]}],
            [{"restaurant-food": "thai"},
             {"restaurant-food": "thai", "restaurant-name": "bangkok city",
              "restaurant-bookpeople": "2", "restaurant-bookday": "monday"}],
            states22=[{"restaurant-food": "thai"},
                      {"restaurant-food": "thai", "restaurant-bookpeople": "2",
                       "restaurant-bookday": "monday", "restaurant-area": "centre"}])
        [record] = mo.identify(d, "2.1")
        self.assertEqual(record["label"], "accept")
        self.assertEqual(record["domains"]["restaurant"]["how"], "explicit")
        self.assertEqual(record["offer_kinds"], {"restaurant": ["recommend"]})
        slots = {s["slot"]: s for s in record["slots"]}
        self.assertEqual(slots["restaurant-name"]["2.4"], "offered")
        self.assertEqual(slots["restaurant-name"]["2.2"], "unset")
        self.assertFalse(slots["restaurant-name"]["agree_22_24"])
        self.assertTrue(slots["restaurant-area"]["2.2_new"])
        self.assertTrue(record["disagree_22_24"])
        self.assertEqual(record["state_signal"]["2.4"], "adopt")

    def test_select_then_reject_and_pick(self):
        acts = [{"Hotel-Inform": [["Area", "north"]]},
                {"Hotel-Select": [["Price", "cheap"], ["Price", "moderate"]]},
                {"Hotel-Inform": [["Price", "expensive"]]},
                {"Hotel-Select": [["Name", "A and B Guest House"], ["Name", "Acorn House"]]},
                {"Hotel-Inform": [["Name", "the acorn house"]]},
                {"general-reqmore": [["none", "none"]]}]
        states = [{"hotel-area": "north"}, {"hotel-area": "north", "hotel-pricerange": "expensive"},
                  {"hotel-area": "north", "hotel-pricerange": "expensive",
                   "hotel-name": "acorn house"}]
        first, second = mo.identify(dialogue(acts, states), "2.1")
        self.assertEqual(first["label"], "reject")
        self.assertEqual(first["domains"]["hotel"]["conflicts"], ["pricerange=expensive"])
        self.assertEqual(first["state_signal"]["2.4"], "other")
        self.assertEqual(second["label"], "accept")

    def test_entity_named_by_user_is_not_an_offer(self):
        acts = [{"Attraction-Inform": [["Name", "Clare Hall"]]},
                {"Attraction-Inform": [["Name", "clare hall"], ["Area", "west"]]},
                {"Attraction-Request": [["Post", "?"]]},
                {"Attraction-Inform": [["Post", "cb39al"]]}]
        states = [{"attraction-name": "clare hall"}, {"attraction-name": "clare hall"}]
        self.assertEqual(mo.identify(dialogue(acts, states), "2.1"), [])

    def test_new_entity_inform_is_an_offer(self):
        acts = [{"Attraction-Inform": [["Type", "college"]]},
                {"Attraction-Inform": [["Name", "Churchill College"], ["Area", "west"]]},
                {"Attraction-Request": [["Phone", "?"]]},
                {"Attraction-Inform": [["Phone", "0122"]]}]
        states = [{"attraction-type": "college"}, {"attraction-type": "college"}]
        [record] = mo.identify(dialogue(acts, states), "2.1")
        self.assertEqual(record["offer_kinds"], {"attraction": ["inform-entity"]})
        self.assertEqual(record["label"], "accept")
        self.assertEqual(record["domains"]["attraction"]["how"], "implicit")

    def test_booking_offer_needs_details_or_reference(self):
        acts = [{"Hotel-Inform": [["Name", "Acorn House"]]},
                {"Booking-Inform": [["none", "none"]]},
                {"Hotel-Request": [["Addr", "?"]]},
                {"Booking-Inform": [["none", "none"]]},
                {"Hotel-Request": [["Ref", "?"]]},
                {"general-bye": [["none", "none"]]}]
        states = [{"hotel-name": "acorn house"}] * 3
        first, second = mo.identify(dialogue(acts, states), "2.1")
        self.assertEqual(first["offer_kinds"], {"hotel": ["booking-inform"]})
        self.assertEqual(first["label"], "none")
        self.assertEqual(second["label"], "accept")

    def test_dontcare_is_not_a_rejection(self):
        acts = [{"Restaurant-Inform": [["Price", "expensive"]]},
                {"Restaurant-Select": [["Area", "centre"], ["Area", "west"]]},
                {"Restaurant-Inform": [["Area", "dontcare"]]},
                {"general-reqmore": [["none", "none"]]}]
        states = [{"restaurant-pricerange": "expensive"},
                  {"restaurant-pricerange": "expensive", "restaurant-area": "dontcare"}]
        [record] = mo.identify(dialogue(acts, states), "2.1")
        self.assertEqual(record["label"], "none")


class Census(unittest.TestCase):
    def test_half_width_and_rule(self):
        self.assertAlmostEqual(mo.half_width(400), 4.49, places=2)
        self.assertIsNone(mo.half_width(0))
        need = mo.recommendation(10)["min_n_for_threshold"]
        self.assertEqual(need, 323)
        self.assertIn("remain the primary", mo.recommendation(need)["recommendation"])
        self.assertIn("support", mo.recommendation(need - 1)["recommendation"])

    def test_counts_and_convention(self):
        acts = [{"Restaurant-Inform": [["Food", "thai"]]},
                {"Restaurant-Recommend": [["Name", "Bangkok City"]]},
                {"Restaurant-Inform": [["People", "2"]]},
                {"general-reqmore": [["none", "none"]]}]
        d1 = dialogue(acts, [{}, {"restaurant-name": "bangkok city"}], states22=[{}, {}],
                      did="A.json")
        d2 = dialogue(acts, [{}, {}], states22=[{}, {"restaurant-name": "bangkok city"}],
                      did="B.json")
        records = [r for d in (d1, d2) for r in mo.identify(d, "2.1")]
        c = mo.census(records, n_dialogues=2, n_user_turns=4)
        self.assertEqual(c["offer_turns"], 2)
        self.assertEqual(c["accept_or_reject"], 2)
        self.assertEqual(c["by_domain"]["restaurant"]["accept"], 2)
        self.assertEqual(c["disagree_22_24"]["turns_disagree"], 2)
        self.assertEqual(c["convention_22_24"]["only_22_offered"], 1)
        self.assertEqual(c["convention_22_24"]["only_24_offered"], 1)
        self.assertEqual(c["interval"]["n"], 2)

    def test_sample_is_seeded_and_stratified(self):
        records = [{"task_id": f"D{i}:2", "label": lab} for i, lab in
                   enumerate(["accept"] * 5 + ["reject"] * 3 + ["none"] * 4)]
        a = mo.sample(records, {"accept": 2, "reject": 5}, seed=1)
        self.assertEqual(a, mo.sample(records, {"accept": 2, "reject": 5}, seed=1))
        self.assertEqual([r["label"] for r in a].count("reject"), 3)
        self.assertEqual(len(a), 5)


class Loading(unittest.TestCase):
    def test_load_synthetic_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = benchmark_sources.multiwoz(Path(tmp))
            dirs = {v: config.source_dir(Path(tmp), v) for v in config.manifests()}
            ids = mo.split_ids(dirs["2.4"], "MULTIWOZ2.4/valListFile.json")
            dialogues, presence = mo.load_dialogues(dirs, ids, "dev", keep_text=False)
        self.assertEqual(ids, ["SYN0001.json"])
        self.assertIsNone(dialogues[0].texts)
        self.assertEqual(len(dialogues[0].states["2.2"]), 2)
        self.assertEqual(presence["2.4 data.json dialog_act"]["user_turns_with_acts"], 0)
        self.assertEqual(presence["2.1 data.json dialog_act"]["user_turns_with_acts"], 2)
        self.assertEqual(presence["2.4 dialogue_acts.json"]["system_turns_with_acts"], 1)


class HeldOutFlag(unittest.TestCase):
    def test_held_out_needs_flag(self):
        from grace.cli.data import multiwoz_offers as cli
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["--split", "held-out"])


if __name__ == "__main__":
    unittest.main()
