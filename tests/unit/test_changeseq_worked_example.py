"""The worked example of docs/research/change-sequences.md, section 6.5 (required T015 fixture).

The event log is written by hand from the table; the expected labels and the known-then /
seen-from-now pair are the table's values, not outputs of the code under test.
"""

import unittest

from grace.eval.datasets.changeseq import gold, regraph
from grace.eval.datasets.changeseq.events import (
    LogRecord,
    Macro,
    NewClaim,
    Stance,
    Supersede,
    check_log,
)
from grace.eval.datasets.changeseq.invalidation import (
    Binding,
    DerivedState,
    World,
    check_invariants,
    gold_staleness,
    hist,
    hist_determinate,
)

WORLD = World(authority={"livesIn": "user", "playsInstrument": "user", "arriveBy": "user",
                         "destination": "user", "scheduledArrival": "assistant"},
              constraint_predicates=frozenset({"arriveBy", "destination"}),
              choice_predicate="selectedService", catalogue_predicate="scheduledArrival")
BINDINGS = [Binding("V2", "user", "livesIn"), Binding("V1", "user", "playsInstrument"),
            Binding("V3", "user", "playsInstrument"), Binding("V4", "k1"), Binding("V5", "k1"),
            Binding("V6", "k1")]
DATES = {1: "2026-10-15", **{t: "2026-10-24" for t in range(2, 7)}, 7: "2026-11-03",
         8: "2026-11-03"}


def record(t, speaker, *events, name="m-x", episode=None):
    return LogRecord(t, f"m{t}", episode or f"ep-{DATES[t]}", speaker, DATES[t], tuple(events),
                     Macro(f"x{t}", name, "C2", "V2:user:livesIn"))


def worked_example() -> list[LogRecord]:
    return [
        record(1, "user", NewClaim("c1", "user", "livesIn", "Munich", "string"),
               Stance("a1", "c1", "inform")),
        record(2, "user", NewClaim("c2", "k1", "arriveBy", "18:00:00", "time"),
               Stance("a2", "c2", "request"),
               NewClaim("c3", "k1", "destination", "Berlin", "string"),
               Stance("a3", "c3", "request")),
        record(3, "assistant", NewClaim("c4", "k1", "selectedService", "ICE947", "entity"),
               Stance("a4", "c4", "offer"),
               NewClaim("c5", "ICE947", "scheduledArrival", "17:25:00", "time"),
               Stance("a5", "c5", "inform")),
        record(4, "user", Stance("a6", "c4", "accept")),
        record(5, "user", NewClaim("c6", "user", "playsInstrument", "violin", "string"),
               Stance("a7", "c6", "inform")),
        record(6, "assistant", Stance("a8", "c1", "inform", derived=True)),
        record(7, "user", NewClaim("c7", "user", "livesIn", "Cologne", "string",
                                   start="2026-11-01"),
               Stance("a9", "c7", "inform"),
               Supersede("s1", "c1", "change", "a9", "c7")),
        record(8, "user", NewClaim("c8", "user", "livesIn", "Cologne", "string",
                                   start="2026-10-20"),
               Stance("a10", "c8", "inform"),
               Supersede("s2", "c7", "correction", "a10", "c8")),
    ]


# (type, outcome) per version and binding, from the table of section 6.5; "-" is untouched.
EXPECTED = {
    1: {"V2:user:livesIn": ("C2", "answer")},
    2: {"V4:k1": ("C2", "answer")},
    3: {"V5:k1": ("C2", "answer"), "V6:k1": ("C7", "neither")},
    4: {"V5:k1": ("C3", "answer"), "V6:k1": ("C2", "answer")},
    5: {"V1:user:playsInstrument": ("C2", "answer"), "V3:user:playsInstrument": ("C4", "answer")},
    6: {"V2:user:livesIn": ("C6", "citation")},
    7: {"V2:user:livesIn": ("C1", "answer")},
    8: {"V2:user:livesIn": ("C5", "citation")},
}


class WorkedExampleTest(unittest.TestCase):
    def setUp(self):
        self.log = worked_example()
        self.gold = gold_staleness(self.log, WORLD, BINDINGS)

    def test_log_is_well_formed(self):
        self.assertEqual(check_log(self.log, WORLD.authority, {"livesIn", "arriveBy",
                                                               "destination",
                                                               "scheduledArrival"},
                                   "scheduledArrival", "selectedService"), [])

    def test_labels_match_the_table(self):
        for x in self.gold.labels:
            kind, out = EXPECTED[x["version"]].get(x["binding_id"], ("untouched", "neither"))
            got = ("answer" if x["answer_stale"] else
                   "citation" if x["citation_stale"] else "neither")
            with self.subTest(t=x["version"], binding=x["binding_id"]):
                self.assertEqual((x["change_type"], got), (kind, out))

    def test_c7_sub_kinds_at_the_offer(self):
        row = next(x for x in self.gold.labels if x["version"] == 3
                   and x["binding_id"] == "V6:k1")
        self.assertEqual(row["sub_kinds"], ["a", "c"])

    def test_invariants_hold(self):
        self.assertEqual(check_invariants(self.gold), [])

    def test_answers_and_witnesses(self):
        v6 = self.gold.value("V6:k1", 4)
        self.assertEqual(v6["ans"], [["ICE947", "17:25:00"]])
        self.assertEqual(v6["wit"], [[["ICE947", "17:25:00"], [sorted(["c4", "a6", "c5",
                                                                       "a5"])]]])
        self.assertEqual(v6["ev"], ["m3", "m4"])
        self.assertEqual(self.gold.value("V2:user:livesIn", 8)["wit"],
                         [["Cologne", [["a10", "c8"]]]])
        self.assertEqual(self.gold.value("V2:user:livesIn", 6)["ev"], ["m1", "m6"])
        self.assertEqual(self.gold.value("V3:user:playsInstrument", 4)["ans"], [0])

    def test_span_staleness_is_not_the_disjunction(self):
        self.assertEqual(self.gold.stale("V2:user:livesIn", 6, 8), "answer")
        self.assertEqual(self.gold.stale("V2:user:livesIn", 7, 8), "citation")
        self.assertIsNone(self.gold.stale("V4:k1", 2, 8))

    def test_known_then_and_seen_from_now_pair(self):
        S = DerivedState(self.log, WORLD)
        for reading in ("neg-inf", "message-date"):
            self.assertEqual(hist(S, "user", "livesIn", "2026-10-24", 4, reading)[0], "Munich")
            self.assertEqual(hist(S, "user", "livesIn", "2026-10-24", 8, reading)[0],
                             "Cologne")
        self.assertEqual(hist_determinate(S, "user", "livesIn", "2026-10-24", 4), "Munich")
        self.assertEqual(hist_determinate(S, "user", "livesIn", "2026-10-24", 8), "Cologne")
        # At k = 7 the move is dated 1 November, so 24 October is still Munich.
        self.assertEqual(hist_determinate(S, "user", "livesIn", "2026-10-24", 7), "Munich")

    def test_gold_graph_validates_and_agrees_with_the_log(self):
        store = gold.build_store(self.log, "worked-example", validate="commit")
        self.assertEqual(store.head, 8)
        self.assertEqual(gold.validate_graph(store)[0], True)
        self.assertEqual(regraph.disagreements(store, BINDINGS, WORLD, self.gold.values), [])


if __name__ == "__main__":
    unittest.main()
