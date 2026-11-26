"""Pure logic of the views package (T018): display forms, the rendering check, row IDs and units,
sentence binding invariants, family loading and the view config."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grace.context.memory.graph.entries import Entity, Value
from grace.context.pipeline.query.ir import Predicate
from grace.context.pipeline.query.result import Witness
from grace.context.views.dependencies import dependency_patterns
from grace.context.views.render import (
    LLMRenderer,
    RenderSpec,
    check_sentence,
    display,
    humanise,
    row_lines,
    template_sentence,
)
from grace.context.views.template_families import (
    FAMILIES,
    ViewConfig,
    load_families,
    load_family,
    load_view_config,
)
from grace.context.views.view import Binding, Row, Sentence, ViewError, row_id, units


class DisplayTest(unittest.TestCase):
    def test_display_forms(self):
        self.assertEqual(humanise("playsInstrument"), "plays instrument")
        self.assertEqual(humanise("arriveBy"), "arrive by")
        self.assertEqual(display(Value("20:45:00", "time")), "20:45")
        self.assertEqual(display(Value("20:45:30", "time")), "20:45:30")
        self.assertEqual(display(Entity("TR7143")), "TR7143")
        self.assertEqual(display(Predicate("scheduledArrival")), "scheduled arrival")
        self.assertEqual(display(Value("2023-05-25", "date")), "2023-05-25")


class CheckTest(unittest.TestCase):
    def test_passes_with_all_values_and_nothing_else(self):
        self.assertIsNone(check_sentence("Melanie plays the Violin.", ["violin"],
                                         ["melanie"], ["clarinet"]))
        self.assertIsNone(check_sentence("She must arrive by 20:45.", ["arrive by", "20:45"]))

    def test_missing_value(self):
        self.assertIn("missing", check_sentence("Melanie plays the viola.", ["violin"]))

    def test_value_of_another_row(self):
        reason = check_sentence("Violin and clarinet.", ["violin"], [], ["clarinet"])
        self.assertIn("another row", reason)

    def test_other_value_inside_an_own_value_is_allowed(self):
        self.assertIsNone(check_sentence("TR71430 arrives.", ["TR71430"], [], ["TR7143"]))

    def test_number_from_outside(self):
        self.assertIn("number", check_sentence("2 of 3 instruments.", ["2"]))
        self.assertIsNone(check_sentence("Request 1 needs 20:45.", ["20:45"], ["request1"]))

    def test_empty(self):
        self.assertEqual(check_sentence("...", ["x"]), "empty sentence")


class BindingConstantTest(unittest.TestCase):
    """The rendering check requires the binding's subject (E005, user decision 2026-11-26)."""

    CONSTRAINTS = RenderSpec("constraints requested for train booking A", ("constraint", "value"),
                             subject="train booking A",
                             sentence="Requested for {subject}: {constraint} {value}.")

    def rows(self):
        r1 = Row("r1", (Predicate("arriveBy"), Value("12:00:00", "time")))
        r2 = Row("r2", (Predicate("departFrom"), Entity("Bonn")))
        return {"r1": r1, "r2": r2}

    def check(self, spec, text, unit=("r1",)):
        rows = self.rows()
        return LLMRenderer._check(spec, rows, [("r1",), ("r2",)], [unit], text)

    def test_sentence_without_its_task_fails(self):
        reason = self.check(self.CONSTRAINTS, "The constraint is arrive by 12:00.")
        self.assertEqual(reason, "binding constant 'train booking A' is missing")

    def test_sentence_naming_its_task_passes(self):
        for text in ("Requested for train booking A: arrive by 12:00.",
                     "Train booking A must arrive by 12:00.",
                     "For train-booking A, the user wants to arrive by 12:00."):
            self.assertIsNone(self.check(self.CONSTRAINTS, text), text)

    def test_template_sentence_passes_its_own_check(self):
        rows = self.rows()
        text = template_sentence(self.CONSTRAINTS, rows, ("r1",))
        self.assertEqual(text, "Requested for train booking A: arrive by 12:00.")
        self.assertIsNone(self.check(self.CONSTRAINTS, text))

    def test_another_task_does_not_stand_in(self):
        self.assertIn("binding constant",
                      self.check(self.CONSTRAINTS, "Train booking B must arrive by 12:00."))

    def test_row_values_are_still_required(self):
        self.assertIn("missing", self.check(self.CONSTRAINTS, "Train booking A: arrive by."))

    def test_predicate_and_title_are_not_required(self):
        spec = RenderSpec("speaks language of Jonas", ("value",), subject="Jonas",
                          predicate="speaksLanguage", sentence="{subject} {predicate} {value}.")
        rows = {"r1": Row("r1", (Entity("Polish"),))}
        self.assertEqual(spec.required_constants(), ("Jonas",))
        self.assertIsNone(LLMRenderer._check(spec, rows, [("r1",)], [("r1",)],
                                             "Jonas speaks Polish."))
        self.assertIn("binding constant", LLMRenderer._check(spec, rows, [("r1",)], [("r1",)],
                                                             "The language is Polish."))

    def test_view_without_binding_requires_only_its_rows(self):
        spec = RenderSpec("t", ("value",))
        self.assertEqual(spec.required_constants(), ())
        rows = {"r1": Row("r1", (Entity("Polish"),))}
        self.assertIsNone(LLMRenderer._check(spec, rows, [("r1",)], [("r1",)], "Polish."))

    def test_check_sentence_binding_argument(self):
        self.assertIsNone(check_sentence("Request 1 needs 20:45.", ["20:45"], [], [],
                                         ["request 1"]))
        self.assertEqual(check_sentence("It needs 20:45.", ["20:45"], [], [], ["request 1"]),
                         "binding constant 'request 1' is missing")
        # Numbers of a binding constant are permitted like those of an allowed value.
        self.assertIsNone(check_sentence("Request 1: 20:45.", ["20:45"], binding=["request 1"]))


class RowsTest(unittest.TestCase):
    def test_row_ids_are_stable_and_kind_specific(self):
        values = (Entity("violin"),)
        self.assertEqual(row_id(values), row_id((Entity("violin"),)))
        self.assertNotEqual(row_id(values), row_id((Value("violin"),)))
        self.assertTrue(row_id((), aggregate=True).startswith("a"))

    def test_units_put_members_under_their_aggregate(self):
        m1 = Row("r1", (Entity("violin"),), (Witness.of(["c1"]),), ("m2",))
        m2 = Row("r2", (Entity("clarinet"),), (Witness.of(["c2"]),), ("m7",))
        agg = Row("a1", (Value("2", "integer"),), (), (), aggregate=True, members=("r1", "r2"))
        self.assertEqual(units((m1, m2, agg)), [("a1", "r1", "r2")])
        self.assertEqual(units((m1, m2)), [("r1",), ("r2",)])
        spec = RenderSpec("t", ("value",), is_count=True, subject="melanie",
                          predicate="playsInstrument",
                          sentence="{subject} {predicate}: {count}.")
        rows = {r.row_id: r for r in (m1, m2, agg)}
        self.assertEqual(template_sentence(spec, rows, ("a1", "r1", "r2")),
                         "melanie plays instrument: 2.")
        self.assertEqual(row_lines(spec, rows, [("a1", "r1", "r2")]),
                         "[a1] count = 2\n  member [r1] value = violin\n"
                         "  member [r2] value = clarinet")

    def test_sentence_needs_rows_and_a_known_source(self):
        with self.assertRaises(ViewError):
            Sentence("x", ())
        with self.assertRaises(ViewError):
            Sentence("x", ("r1",), source="guess")


class FamiliesTest(unittest.TestCase):
    def test_six_families_load_and_bind(self):
        families = load_families()
        self.assertEqual(tuple(families), FAMILIES)
        self.assertEqual([f.reference for f in families.values()],
                         ["V1", "V2", "V3", "V4", "V5", "V6"])
        config = ViewConfig()
        pending = families["pending"].bind(Binding("pending", "task 1"), config)
        self.assertIsNotNone(pending.negation)
        self.assertEqual(pending.where[0].subject, Entity("task 1"))
        count = families["count"].bind(Binding("count", "x", "p"), config)
        self.assertIsNotNone(count.count)
        with self.assertRaises(ViewError):
            families["list"].bind(Binding("list", "x", "not a name"), config)
        with self.assertRaises(ViewError):
            families["list"].bind(Binding("list", "x"), config)
        listed = families["list"].bind(Binding("list", "x", "p"), config)
        self.assertIsNone(listed.where[0].attribution.speaker)
        strict = families["list"].bind(Binding("list", "x", "p"),
                                       ViewConfig(state_speaker="user"))
        self.assertEqual(strict.where[0].attribution.speaker, Entity("user"))
        self.assertIsNotNone(families["current"].bind(Binding("current", "x", "p"),
                                                      config).latest)
        deps = dependency_patterns(families["choice"].bind(Binding("choice", "k"), config))
        self.assertEqual([d.role for d in deps], ["positive", "positive", "negated"])

    def test_malformed_family_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.yaml"
            path.write_text("family: other\nreference: V1\nbinding: task\ntitle: t\n"
                            "query: x\nsentence: s\n", encoding="utf-8")
            with self.assertRaises(ViewError):
                load_family("list", Path(tmp))
            bad = Path(tmp) / "views.yaml"
            bad.write_text("families: [list]\n", encoding="utf-8")
            with self.assertRaises(ViewError):
                load_view_config(bad)
        with self.assertRaises(ViewError):
            ViewConfig(families=("list", "unknown"))
        with self.assertRaises(ViewError):
            ViewConfig(instantiation_threshold=0)
        self.assertEqual(ViewConfig(thresholds={"count": 3}).threshold("count"), 3)


if __name__ == "__main__":
    unittest.main()
