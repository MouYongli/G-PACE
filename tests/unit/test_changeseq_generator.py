"""Change-sequence generator (task T015): families and split, determinism, the checks every
generated sequence must pass, the well-formedness and invariant checkers on broken inputs, read
schedules and the renderer's output checks.

Only development families are generated here. Held-out families are parsed for the split and
disjointness tests and never generated.
"""

import ast
import json
import unittest
from collections import Counter
from pathlib import Path

from grace.eval.datasets.changeseq import regraph
from grace.eval.datasets.changeseq.build import generate_sequence
from grace.eval.datasets.changeseq.events import (
    LogRecord,
    Macro,
    NewClaim,
    Stance,
    Supersede,
    check_log,
)
from grace.eval.datasets.changeseq.generate import plan_sequence
from grace.eval.datasets.changeseq.invalidation import GoldStaleness, check_invariants
from grace.eval.datasets.changeseq.render import RenderRequest, check_output, surfaces
from grace.eval.datasets.changeseq.schedule import read_points
from grace.eval.datasets.changeseq.template_families import (
    CHANGE_TYPES,
    CellConfig,
    FamilyError,
    ScheduleSpec,
    compute_split,
    family_ids,
    grammar,
    load_family,
    load_split,
)

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "grace" / "eval" / "datasets" / "changeseq"
DEV = ("train-travel", "flight-travel", "car-rental", "hotel-stay", "apartment-search")
SCHEDULES = (ScheduleSpec("A", m=8, d=1), ScheduleSpec("U", m=5), ScheduleSpec("P", interval=6))


def cell(family="train-travel", length=80, density=30.0, **kw):
    return CellConfig(family=family, length=length, density=density, schedules=SCHEDULES, **kw)


class FamilyAndSplitTest(unittest.TestCase):
    def test_every_family_parses_and_is_in_exactly_one_split(self):
        split = load_split()
        ids = family_ids()
        self.assertEqual(len(ids), 20)
        self.assertEqual(sorted(split.development + split.held_out), ids)
        self.assertEqual(sorted(split.development), sorted(DEV))
        self.assertEqual(len(split.held_out), 15)
        for family_id in ids:
            self.assertEqual(load_family(family_id).family_id, family_id)

    def test_split_is_the_seeded_permutation_of_whole_groups(self):
        split = load_split()
        dev, held = compute_split({g: list(f) for g, f in split.groups.items()}, split.seed, 5)
        self.assertEqual(dev, ["lodging", "travel"])
        self.assertFalse(set(dev) & set(held))
        for group, families in split.groups.items():
            self.assertEqual(len({split.split_of(f) for f in families}), 1, group)
        for family_id in family_ids():
            self.assertIn(load_family(family_id).group, split.groups)
            self.assertIn(family_id, split.groups[load_family(family_id).group])

    def test_development_and_held_out_share_no_domain_content(self):
        split = load_split()

        def content(families):
            out = {}
            for f in families:
                for kind, values in load_family(f).domain_content().items():
                    out.setdefault(kind, set()).update(values)
            return out

        dev, held = content(split.development), content(split.held_out)
        for kind in dev:
            with self.subTest(kind=kind):
                self.assertEqual(dev[kind] & held[kind], set())

    def test_bad_family_and_cell_configs_fail_loudly(self):
        raw = {"id": "x", "group": "g", "title": "t", "companions": ["A", "B"]}
        from grace.eval.datasets.changeseq.template_families import parse_family
        with self.assertRaises(FamilyError):
            parse_family(raw)
        with self.assertRaises(FamilyError):
            CellConfig(family="train-travel", mix={"C1": 1.0})
        with self.assertRaises(FamilyError):
            ScheduleSpec.parse("X3")

    def test_budget_counts_use_largest_remainder(self):
        counts = CellConfig(family="train-travel", length=200, density=10).counts()
        self.assertEqual(sum(counts[t] for t in ("C1", "C2", "C3", "C4", "C5")), 18)
        self.assertEqual(sorted(counts[t] for t in ("C1", "C2", "C3", "C4", "C5")),
                         [3, 3, 4, 4, 4])
        self.assertEqual((counts["C6"], counts["C7"]), (18, 18))
        self.assertEqual(grammar().setup_length(200), 20)
        self.assertEqual(grammar().setup_length(50), 10)


class GeneratedSequenceTest(unittest.TestCase):
    """generate_sequence raises GenerationError on any failed check, so building is the test."""

    @classmethod
    def setUpClass(cls):
        cls.bundles = [generate_sequence(f, cell(f, length=n, density=rho), seed,
                                         f"{f}-{rho}-{seed}")
                       for f, n, rho, seed in (("train-travel", 200, 30, 1),
                                               ("hotel-stay", 200, 10, 2),
                                               ("apartment-search", 80, 10, 3),
                                               ("car-rental", 80, 3, 4),
                                               ("flight-travel", 80, 30, 5))]

    def test_all_checks_pass(self):
        for b in self.bundles:
            self.assertEqual(set(b.checks), {"well_formedness", "focus_types", "invariants",
                                             "gold_graph", "graph_reevaluation",
                                             "render_checks"})

    def test_every_change_type_occurs(self):
        kinds, subs, v6 = Counter(), Counter(), Counter()
        for b in self.bundles:
            kinds.update(x["change_type"] for x in b.gold.labels)
            subs.update(s for x in b.gold.labels for s in x["sub_kinds"])
            v6.update(x["change_type"] for x in b.gold.labels
                      if x["binding_id"].startswith("V6:"))
        self.assertEqual(set(CHANGE_TYPES) | {"untouched"}, set(kinds))
        self.assertEqual(set(subs), {"a", "b", "c"})
        # The current-choice view gets its first choice (C2) and rejections (C3) from
        # acceptances and rejections of any focus; offers are C7 for it.
        for kind in ("C2", "C3", "C7"):
            self.assertGreater(v6[kind], 0, kind)
    def test_many_plans_are_well_formed_and_cover_every_macro(self):
        """Planning is cheap: 60 plans over three densities and all development families.
        Regression: a date correction once reused the (value, start) of an earlier claim (G1)."""
        macros = Counter()
        for i, family_id in enumerate(DEV * 12):
            family = load_family(family_id)
            plan = plan_sequence(family, CellConfig(family=family_id, density=(3, 10, 30)[i % 3]),
                                 1000 + i, "s")
            world = plan.world
            exclusive = {p for p in family.predicate_names() if family.is_exclusive(p)}
            self.assertEqual(check_log(plan.log, world.authority, exclusive,
                                       world.catalogue_predicate, world.choice_predicate), [])
            macros.update(r.macro.name for r in plan.log if r.macro)
        # `m-accept-first` (an acceptance planned as C2 for the current-choice view) is rare:
        # most first acceptances are planned as C3 for the pending view, which needs the same
        # pending offers. Both realise C2 on the current-choice view.
        self.assertEqual(set(grammar().macros) - set(macros) - {"m-accept-first"}, set())

    def test_both_outcomes_of_designed_over_marking_cases_occur(self):
        outcomes = Counter()
        for b in self.bundles:
            for x in b.gold.labels:
                o = "answer" if x["answer_stale"] else "citation" if x["citation_stale"] \
                    else "neither"
                outcomes[(x["change_type"], o)] += 1
        for pair in (("C3", "answer"), ("C3", "neither"), ("C5", "answer"),
                     ("C5", "citation"), ("C6", "citation")):
            self.assertGreater(outcomes[pair], 0, pair)

    def test_gold_graph_holds_every_version(self):
        for b in self.bundles:
            self.assertEqual(b.store.versions(), tuple(range(1, len(b.plan.log) + 1)))

    def test_questions_are_consistent_with_the_labels(self):
        for b in self.bundles:
            types = {(x["version"], x["binding_id"]): x["change_type"] for x in b.gold.labels}
            versions = {r.message_id: r.version for r in b.plan.log}
            for sched in b.schedules:
                prev = b.plan.setup_length
                by_read = {}
                for q in sched.questions:
                    by_read.setdefault(q["read_version"], []).append(q)
                for r in sched.points:
                    qs = by_read[r]
                    self.assertGreater(r, b.plan.setup_length)
                    self.assertIn(len(qs), (2, 3, 4))
                    for q in qs:
                        expected = sorted({types[(t, q["binding_id"])]
                                           for t in range(prev + 1, r + 1)} - {"untouched"})
                        self.assertEqual(q["change_types"], expected)
                        self.assertTrue(all(versions[m] <= r for m in q["evidence"]))
                        self.assertEqual(q["expected_abstention"], not q["answer"])
                        if q["type"] not in ("known_then", "seen_from_now"):
                            self.assertEqual(q["answer"], b.gold.value(q["binding_id"],
                                                                       r)["ans"])
                    pair = [q for q in qs if q["pair_id"]]
                    self.assertIn(len(pair), (0, 2))
                    prev = r

    def test_pairs_are_differing_or_control_as_labelled(self):
        kinds = Counter()
        for b in self.bundles:
            for sched in b.schedules:
                pairs = {}
                for q in sched.questions:
                    if q["pair_id"]:
                        pairs.setdefault(q["pair_id"], {})[q["pair_role"]] = q
                for p in pairs.values():
                    then, now = p["known-then"], p["seen-from-now"]
                    self.assertLess(then["kappa"], now["kappa"])
                    self.assertEqual(then["tau"], now["tau"])
                    differ = then["answer"] != now["answer"]
                    self.assertEqual(then["pair_kind"], "differing" if differ else "control")
                    kinds[then["pair_kind"]] += 1
        self.assertGreater(kinds["control"], 0)
        self.assertGreater(kinds["differing"], 0)


class DeterminismTest(unittest.TestCase):
    def test_same_seed_same_log_labels_and_text(self):
        a = generate_sequence("train-travel", cell(length=60), 7, "s")
        b = generate_sequence("train-travel", cell(length=60), 7, "s")
        self.assertEqual([r.to_json() for r in a.plan.log], [r.to_json() for r in b.plan.log])
        self.assertEqual(a.gold.labels, b.gold.labels)
        self.assertEqual([m.text for m in a.rendered.messages],
                         [m.text for m in b.rendered.messages])
        self.assertEqual([s.questions for s in a.schedules], [s.questions for s in b.schedules])
        c = plan_sequence(load_family("train-travel"), cell(length=60), 8, "s")
        self.assertNotEqual([r.to_json() for r in a.plan.log], [r.to_json() for r in c.log])

    def test_log_round_trips(self):
        plan = plan_sequence(load_family("hotel-stay"), cell("hotel-stay", length=60), 3, "s")
        for r in plan.log:
            self.assertEqual(LogRecord.from_record(json.loads(r.to_json())), r)


class ScheduleTest(unittest.TestCase):
    def test_schedule_types(self):
        plan = plan_sequence(load_family("car-rental"), CellConfig(family="car-rental"), 11, "s")
        L0 = plan.setup_length
        self.assertEqual(read_points(ScheduleSpec("U", m=10), plan),
                         [L0 + round(j * 180 / 10) for j in range(1, 11)])
        anchored = read_points(ScheduleSpec("A", m=20, d=1), plan)
        self.assertEqual(len(anchored), 20)
        focus = {r.version + 1 for r in plan.log
                 if r.macro and r.macro.intended_type in ("C1", "C2", "C3", "C4", "C5")}
        self.assertGreaterEqual(len(set(anchored) & focus), 5)
        poisson = read_points(ScheduleSpec("P", interval=10), plan)
        self.assertTrue(all(L0 < r <= 200 for r in poisson))
        self.assertEqual(poisson, sorted(set(poisson)))
        self.assertGreater(len(poisson), 5)


def _rec(t, speaker, *events, name="m-x"):
    return LogRecord(t, f"m{t}", "ep-0", speaker, "2026-01-01", tuple(events),
                     Macro(f"x{t}", name, "C2", "V2:user:livesIn") if events else None,
                     {} if events else {"skeleton": "filler"})


AUTH = {"livesIn": "user", "plays": "user", "sel": "assistant", "arr": "assistant",
        "q": "user"}
EXCL = {"livesIn", "arr", "q"}


def violations(*records):
    return check_log(list(records), AUTH, EXCL, "arr", "sel")


class WellFormednessTest(unittest.TestCase):
    def test_g1_repeated_proposition(self):
        v = violations(_rec(1, "user", NewClaim("c1", "u", "plays", "harp", "string"),
                            Stance("a1", "c1", "inform")),
                       _rec(2, "user", NewClaim("c2", "u", "plays", "harp", "string"),
                            Stance("a2", "c2", "inform")))
        self.assertTrue(any("G1" in x for x in v), v)

    def test_g2_supersession_needs_a_licence(self):
        base = _rec(1, "user", NewClaim("c1", "u", "plays", "harp", "string"),
                    Stance("a1", "c1", "inform"))
        # A replacing claim on a multi-valued predicate does not license supersession (G2(i)).
        v = violations(base, _rec(2, "user", NewClaim("c2", "u", "plays", "oboe", "string"),
                                  Stance("a2", "c2", "inform"),
                                  Supersede("s1", "c1", "change", "a2", "c2")))
        self.assertTrue(any("G2(i)" in x for x in v), v)
        # Another speaker's denial does not license a removal (same speaker and function).
        v = violations(base, _rec(2, "assistant", Stance("a2", "c1", "inform",
                                                          polarity="negative"),
                                  Supersede("s1", "c1", "change", "a2")))
        self.assertTrue(any("G2 no earlier attribution" in x for x in v), v)

    def test_g3_double_supersession(self):
        v = violations(
            _rec(1, "user", NewClaim("c1", "u", "plays", "harp", "string"),
                 Stance("a1", "c1", "inform")),
            _rec(2, "user", Stance("a2", "c1", "inform", polarity="negative"),
                 Supersede("s1", "c1", "change", "a2")),
            _rec(3, "user", Stance("a3", "c1", "inform", polarity="negative"),
                 Supersede("s2", "c1", "correction", "a3")))
        self.assertTrue(any("G3" in x for x in v), v)

    def test_g4_g5_g6_g8(self):
        offer = _rec(1, "assistant", NewClaim("c1", "k", "sel", "X", "entity"),
                     Stance("a1", "c1", "offer"))
        self.assertTrue(any("G5" in x for x in violations(offer)))
        v = violations(_rec(1, "assistant", NewClaim("c1", "u", "livesIn", "Oslo", "string"),
                            Stance("a1", "c1", "inform")))
        self.assertTrue(any("G4" in x for x in v), v)
        good_offer = lambda t, c, item: _rec(  # noqa: E731
            t, "assistant", NewClaim(c, "k", "sel", item, "entity"), Stance(f"a{c}", c, "offer"),
            NewClaim(f"d{c}", item, "arr", "10:00:00", "time"), Stance(f"ad{c}", f"d{c}",
                                                                      "inform"))
        v = violations(good_offer(1, "c1", "X"), _rec(2, "user", Stance("r", "c1", "reject")),
                       _rec(3, "user", Stance("acc", "c1", "accept")))
        self.assertTrue(any("G6" in x for x in v), v)
        v = violations(good_offer(1, "c1", "X"), good_offer(2, "c2", "Y"),
                       _rec(3, "user", Stance("x1", "c1", "accept")),
                       _rec(4, "user", Stance("x2", "c2", "accept")),
                       _rec(5, "user", Stance("x3", "c2", "reject")))
        self.assertTrue(any("G8" in x for x in v), v)

    def test_g7_filler_with_events(self):
        r = LogRecord(1, "m1", "ep", "user", "2026-01-01",
                      (NewClaim("c1", "u", "plays", "harp", "string"), Stance("a1", "c1",
                                                                              "inform")),
                      Macro("x", "m-add", "C2", "V1:u:plays"), {"skeleton": "filler"})
        self.assertTrue(any("G7" in x for x in violations(r)))


class CheckerNegativeTest(unittest.TestCase):
    def test_invariant_checker_flags_a_wrong_outcome(self):
        g = GoldStaleness([], labels=[{"version": 1, "binding_id": "b", "answer_stale": True,
                                       "citation_stale": False, "change_type": "C6",
                                       "sub_kinds": []},
                                      {"version": 2, "binding_id": "b", "answer_stale": False,
                                       "citation_stale": True, "change_type": "C7",
                                       "sub_kinds": ["a"]}])
        self.assertEqual(len(check_invariants(g)), 2)

    def test_graph_reevaluation_detects_a_corrupted_reference(self):
        b = generate_sequence("train-travel", cell(length=60), 5, "s")
        values = {k: [dict(v) for v in vs] for k, vs in b.gold.values.items()}
        key = next(k for k in values if k.startswith("V2:user"))
        values[key][-1]["ev"] = values[key][-1]["ev"] + ["m9999"]
        found = regraph.disagreements(b.store, b.plan.bindings(), b.plan.world, values)
        self.assertEqual(len(found), 1)

    def test_render_checks(self):
        family = load_family("train-travel")
        req = RenderRequest("s", 1, "m1", "user", "2026-01-01", (), "first", {"stmt": "x"},
                            None, ("Munich",), (), ("Cologne",), (), 0)
        self.assertEqual(check_output("I live in Munich.", req), [])
        self.assertEqual(len(check_output("I live in Cologne.", req)), 2)
        self.assertTrue(check_output("That claim about Munich", req))
        self.assertIn("Munich", surfaces(family))
        self.assertIn("ICE 947", surfaces(family))
        self.assertIn("17:25", surfaces(family))


class ImportIndependenceTest(unittest.TestCase):
    """The reference functions use no query compiler, IR or SPARQL engine (design 6.4)."""

    def test_reference_modules_import_no_query_machinery(self):
        for name in ("invalidation.py", "regraph.py", "events.py", "generate.py",
                     "schedule.py"):
            tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported.add(node.module or "")
            for module in imported:
                with self.subTest(file=name, module=module):
                    self.assertNotIn("pipeline", module)
                    self.assertNotIn("pyoxigraph", module)
                    self.assertNotIn("rdflib", module)
            source = (PACKAGE / name).read_text(encoding="utf-8")
            self.assertNotIn(".query(", source)


if __name__ == "__main__":
    unittest.main()
