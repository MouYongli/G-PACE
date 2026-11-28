"""The view hit rule: a plan's query hits a view when it equals the bound query modulo a
consistent renaming of variables (`views/hitrule.py`; user decision of 2026-11-28, after E010)."""

import re
import unittest

from grace.context.engine import Views
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import load_vocabulary
from grace.context.pipeline.query.compile import compile_query
from grace.context.pipeline.query.execute import execute as execute_query
from grace.context.pipeline.query.grammar import parse, to_text
from grace.context.pipeline.query.planner import Plan
from grace.context.views import hitrule
from grace.context.views.readtime import ReadTimeViews
from grace.context.views.serialise import SerialisedViews
from grace.context.views.store import ViewStore
from grace.context.views.template_families import ViewConfig
from tests.integration.views_fixture import HEAD, HISTORY, build_store, changesets

VOCABULARY = load_vocabulary()


def q(text):
    return parse(text)


def renamed(query, suffix="_planner"):
    """The query with every variable renamed (`?x` -> `?x_planner`)."""
    text = to_text(query)
    for name in sorted(set(re.findall(r"\?([A-Za-z]\w*)", text))):
        text = re.sub(rf"\?{name}\b", f"?{name}{suffix}", text)
    return parse(text)


def plan_of(query):
    return Plan("r", "llm", query=query, compiled=compile_query(query, "rdf11"))


def rows_of(plan, graph, version):
    """The rows of executing the plan's own query (with members for a count)."""
    result = execute_query(plan.compiled, graph, version)
    return result, ReadTimeViews._rows(plan, result, graph, version)


def row_set(rows):
    return {(r.row_id, r.values, tuple(sorted(r.evidence))) for r in rows}


class MatchTest(unittest.TestCase):
    CONSTRAINTS = ("SELECT ?constraint ?value WHERE "
                   "{ (users_apartment_viewing_A, ?constraint, ?value) [user, request] }")

    def test_variable_names_alone_do_not_matter(self):
        plan = q("SELECT ?q ?v WHERE { (users_apartment_viewing_A, ?q, ?v) [user, request] }")
        self.assertEqual(hitrule.match(plan, q(self.CONSTRAINTS)),
                         {"q": "constraint", "v": "value"})
        self.assertEqual(hitrule.canonical(plan), hitrule.canonical(q(self.CONSTRAINTS)))

    def test_equal_queries_map_every_variable_to_itself(self):
        bound = q(self.CONSTRAINTS)
        self.assertEqual(hitrule.match(bound, bound), {"constraint": "constraint",
                                                       "value": "value"})
        self.assertIs(hitrule.for_plan("view", bound, {"constraint": "constraint"}), "view")

    def test_speaker_and_function_are_compared(self):
        bound = q("SELECT ?value WHERE { (Caroline, visited, ?value) [_, inform] }")
        for text in ("SELECT ?t WHERE { (Caroline, visited, ?t) [Caroline, inform] }",
                     "SELECT ?t WHERE { (Caroline, visited, ?t) [_, request] }",
                     "SELECT ?t WHERE { (Caroline, visited, ?t) [_, inform, mode=_] }",
                     "SELECT ?t WHERE { (Caroline, visited, ?t) }"):
            with self.subTest(text=text):
                self.assertIsNone(hitrule.match(q(text), bound))

    def test_constants_and_positions_are_compared(self):
        bound = q("SELECT ?value WHERE { (Caroline, visited, ?value) [_, inform] }")
        for text in (
                # subject and object swapped (E010's commonest LoCoMo near miss)
                "SELECT ?t WHERE { (?t, visited, Caroline) [_, inform] }",
                "SELECT ?t WHERE { (LGBTQ_support_group, visited, ?t) [_, inform] }",
                "SELECT ?t WHERE { (Melanie, visited, ?t) [_, inform] }",
                "SELECT ?t WHERE { (Caroline, attended, ?t) [_, inform] }",
                "SELECT ?t WHERE { (Caroline, visited, ?t) [_, inform] } AT(known=3)",
                "SELECT ?t WHERE { (Caroline, visited, ?t) [_, inform] AS ?c } "
                "LATEST BY version OF ?c"):
            with self.subTest(text=text):
                self.assertIsNone(hitrule.match(q(text), bound))

    def test_the_renaming_must_be_a_bijection_and_keep_column_order(self):
        two = q("SELECT ?a ?b WHERE { (?a, likes, ?b) [_, inform] }")
        for text in ("SELECT ?b ?a WHERE { (?a, likes, ?b) [_, inform] }",
                     "SELECT ?x ?y WHERE { (?y, likes, ?x) [_, inform] }"):
            with self.subTest(text=text):
                self.assertIsNone(hitrule.match(q(text), two))
        self.assertIsNone(hitrule.match(q("SELECT ?a WHERE { (?a, likes, ?a) [_, inform] }"),
                                        q("SELECT ?a WHERE { (?a, likes, ?b) [_, inform] }")))
        self.assertEqual(hitrule.match(q("SELECT ?y ?x WHERE { (?y, likes, ?x) [_, inform] }"),
                                       two), {"y": "a", "x": "b"})

    def test_filters_negation_and_labels_are_renamed_consistently(self):
        bound = q("SELECT ?item WHERE { (r1, selectedService, ?item) [assistant, offer] "
                  "NOT EXISTS { (r1, selectedService, ?item) [user, _] } }")
        plan = q("SELECT ?t WHERE { (r1, selectedService, ?t) [assistant, offer] "
                 "NOT EXISTS { (r1, selectedService, ?t) [user, _] } }")
        self.assertEqual(hitrule.match(plan, bound), {"t": "item"})
        loose = q("SELECT ?t WHERE { (r1, selectedService, ?t) [assistant, offer] "
                  "NOT EXISTS { (r1, selectedService, ?t) [assistant, _] } }")
        self.assertIsNone(hitrule.match(loose, bound))
        current = q('SELECT ?value WHERE { (lina, livesIn, ?value) [_, inform] AS ?c '
                    'FILTER(end(?c) > "9999-12-31"^^date) } LATEST BY version OF ?c')
        self.assertEqual(hitrule.match(renamed(current), current),
                         {"value_planner": "value", "c_planner": "c"})

    def test_string_literals_are_constants(self):
        a = q('SELECT ?x WHERE { (?x, says, "what ?x") [_, inform] }')
        b = q('SELECT ?y WHERE { (?y, says, "what ?y") [_, inform] }')
        self.assertIsNone(hitrule.match(a, b))


class FixtureViewsTest(unittest.TestCase):
    """Every view source hits on the bound query with other variable names, in the plan's names,
    and a hit holds the rows of executing the plan's own query."""

    def setUp(self):
        self.graph = build_store()
        self.reference = ViewStore(HISTORY, config=ViewConfig(), vocabulary=VOCABULARY)
        self.reference.materialise(self.graph, HEAD)
        self.assertTrue(self.reference.views())

    def check_hit(self, hit, view, plan):
        self.assertIsNotNone(hit)
        self.assertEqual(hit.view_id, view.view_id)
        result, rows = rows_of(plan, self.graph, HEAD)
        self.assertEqual(hit.columns, tuple(result.variables))  # the plan's names
        self.assertEqual(row_set(hit.rows), row_set(rows))
        self.assertEqual([s.text for s in hit.sentences], [s.text for s in view.sentences])
        self.assertEqual([s.evidence for s in hit.sentences],
                         [s.evidence for s in view.sentences])

    def test_resident_store(self):
        views = Views(self.reference, "push_confirm", local_filters=True)
        for view in self.reference.views():
            with self.subTest(view=view.view_id):
                plan = plan_of(renamed(view.query))
                self.check_hit(views.hit(plan), view, plan)
                self.assertIs(views.hit(plan_of(view.query)), view)

    def test_template_serialisation(self):
        views = SerialisedViews(HISTORY, ViewConfig(), VOCABULARY)
        for view in self.reference.views():
            with self.subTest(view=view.view_id):
                views.on_read(self.graph, HEAD, "r")
                plan = plan_of(renamed(view.query))
                self.check_hit(views.hit(plan), view, plan)

    def test_read_time_template_source(self):
        views = ReadTimeViews(HISTORY, ViewConfig(), VOCABULARY, "template")
        for view in self.reference.views():
            with self.subTest(view=view.view_id):
                plan = plan_of(renamed(view.query))
                result = execute_query(plan.compiled, self.graph, HEAD)
                shown = views.present(plan, result, self.graph, HEAD, "r",
                                      lambda mid: None)
                self.assertEqual(shown.view_id, view.view_id)
                self.assertEqual(sorted(t for t, _, _ in shown.sentences),
                                 sorted(s.text for s in view.sentences))
                answers = sorted(i for _, rows, _ in shown.sentences for i in rows)
                self.assertEqual(answers, list(range(len(result.answers))))

    def test_a_different_speaker_is_no_hit(self):
        views = Views(self.reference, "push_confirm", local_filters=True)
        for view in self.reference.views():
            text = to_text(view.query)
            if "[user, " not in text:
                continue
            with self.subTest(view=view.view_id):
                other = parse(text.replace("[user, ", "[assistant, "))
                self.assertIsNone(views.hit(plan_of(renamed(other))))


class StalenessOnHitTest(unittest.TestCase):
    """A hit is served only after the read's staleness check: views marked stale by later writes
    are repaired by `on_read` before `hit`, so a hit equals executing the plan at the read."""

    def test_hits_after_writes_hold_the_rows_at_the_read(self):
        graph = ClaimStore(HISTORY, "rdf11")
        views = Views(ViewStore(HISTORY, config=ViewConfig(), vocabulary=VOCABULARY),
                      "push_confirm", local_filters=True)
        marked = set()
        for cs in changesets():
            graph.commit(cs)
            marks, _ = views.on_commit(cs, graph)
            if cs.version > 5:
                marked |= {m.view_id for m in marks}
        self.assertTrue(marked)
        stale_before = {v.view_id for v in views.store.views()
                        if row_set(v.rows) != row_set(
                            rows_of(plan_of(v.query), graph, HEAD)[1])}
        decisions, _ = views.on_read(graph, HEAD, "r")
        self.assertTrue({d.view_id for d in decisions} >= stale_before)
        hit_stale = 0
        for view in views.store.views():
            with self.subTest(view=view.view_id):
                plan = plan_of(renamed(view.query))
                hit = views.hit(plan)
                self.assertIsNotNone(hit)
                self.assertEqual(row_set(hit.rows), row_set(rows_of(plan, graph, HEAD)[1]))
                hit_stale += view.view_id in stale_before
        self.assertGreater(hit_stale, 0, "the fixture should make some hit view stale")


if __name__ == "__main__":
    unittest.main()
