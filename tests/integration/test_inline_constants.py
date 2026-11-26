"""Inlined single-IRI constants (T017 compiler, E004 follow-up of 2026-11-26).

`CompiledQuery.bind` writes an entity constant whose equivalence class has one member directly
into its triples instead of binding it with a one-row `VALUES` block (pyoxigraph 0.5.13
evaluates the `VALUES` form of `pending` and `choice` orders of magnitude slower, E004). These
tests check that the change preserves semantics and cannot be abused:

- the old (`inline=False`) and new bound texts return identical rows, row by row, for every
  query of the T017 fixture suite at every version and in both serialisations, with and without
  entity merges, and for every binding of all six template families on scaled E004 graphs (main
  query, member query and count query), at the prefix head and later in the window;
- classes with several members keep their `VALUES` block;
- entity IDs and literals that contain IRI delimiters, placeholders (`%r%`, `%k0%`) or compiler
  variable names (`?_k0`) are matched exactly and change nothing else in the query;
- an IRI that is not a valid IRIREF is refused before substitution.
"""

from __future__ import annotations

import re
import unittest
from unittest import mock

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entities import EntityEquivalence
from grace.context.memory.graph.entries import Entity, Value
from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.query import compile as compiler
from grace.context.pipeline.query.compile import CompiledQuery, compile_query
from grace.context.pipeline.query.execute import equivalence_classes, run
from grace.context.pipeline.query.grammar import parse
from grace.context.pipeline.query.ir import ClaimPattern, Filter, Op, Query, Var
from grace.context.views.rebuild import Compiled
from grace.context.views.store import ViewStore
from grace.context.views.template_families import FAMILIES, ViewConfig
from grace.eval.runner.probes import scale
from tests.integration.test_query_compiler import (
    HEAD,
    MODES,
    SUITE,
    att,
    build_store,
    claim,
    ev,
)

_PROJECT = re.compile(r"^SELECT (?:DISTINCT )?(.*?) WHERE", re.DOTALL)
_COLUMN = re.compile(r"\?(\w+)\)?$")


def columns(sparql: str) -> list[str]:
    """Projected variable names of a SELECT (plain variables and `(... AS ?v)`)."""
    head = _PROJECT.match(sparql).group(1)
    out = []
    for token in re.findall(r"\(.*?\)|\?\w+", head):
        out.append(_COLUMN.search(token).group(1))
    return out


def rows(store: ClaimStore, sparql: str, cutoff: int) -> list[tuple]:
    names = columns(sparql)
    return sorted(tuple(str(sol[n]) for n in names) for sol in store.query(sparql, cutoff))


def old_bind(compiled: CompiledQuery, classes=None) -> tuple[str, str | None]:
    """The bound text as compiled before the change: every placeholder replaced in place."""
    classes = classes or {}
    texts = [compiled.main, compiled.count]
    for placeholder, entity, sep in compiled.constants:
        members = sorted(set(classes.get(entity, ())) | {entity})
        value = sep.join(f"<{compiler.rdf.entity_iri(m).value}>" for m in members)
        texts = [t.replace(placeholder, value) if t is not None else None for t in texts]
    return texts[0], texts[1]


class Equivalent:
    def assert_same(self, store: ClaimStore, compiled: CompiledQuery, cutoff: int, msg) -> None:
        _, classes = equivalence_classes(store, cutoff)
        old_main, old_count = compiled.bind(classes, inline=False)
        self.assertEqual((old_main, old_count), old_bind(compiled, classes), msg)
        new_main, new_count = compiled.bind(classes)
        self.assertEqual(rows(store, new_main, cutoff), rows(store, old_main, cutoff), msg)
        if old_count is not None:
            self.assertEqual(rows(store, new_count, cutoff), rows(store, old_count, cutoff), msg)


class FixtureSuiteTest(Equivalent, unittest.TestCase):
    def test_every_suite_query_at_every_version(self):
        for mode in MODES:
            store = build_store(mode)
            for text in SUITE:
                compiled = compile_query(parse(text), mode)
                for version in range(HEAD + 1):
                    self.assert_same(store, compiled, version, (mode, text, version))

    def test_the_new_text_has_no_single_member_values_block(self):
        compiled = compile_query(parse(SUITE[1]))  # request1 twice, user twice
        self.assertEqual(len(compiled.values_vars), 4)
        self.assertEqual(compiled.main.count("VALUES ?_k"), 4)  # the compiled text is unchanged
        main, _ = compiled.bind()
        self.assertNotIn("VALUES", main)
        self.assertNotIn("?_k", main)
        self.assertNotIn("%k", main)
        self.assertIn("rdf:subject <https://", main)
        old, _ = compiled.bind(inline=False)
        self.assertEqual(old.count("VALUES ?_k"), 4)


class MergeTest(Equivalent, unittest.TestCase):
    def setUp(self):
        self.store = ClaimStore("merge")
        self.store.commit(ChangeSet("merge", 1, claims=(
            claim("c1", "train7143", "scheduledArrival", Value("20:38:00", "time"), 1),
            claim("c2", "request1", "selectedService", "train7143", 1)),
            attributions=(att("a1", "c1", 1, "system", "inform"),
                          att("a2", "c2", 1, "system", "offer")),
            evidence_links=(ev("e1", "c1", 1), ev("e2", "c2", 1))))
        self.store.commit(ChangeSet("merge", 2, entity_merges=(
            EntityEquivalence("q1", "TR7143", "train7143", 2),)))

    def test_merged_constants_keep_values_and_rows_agree(self):
        compiled = compile_query(parse(
            "SELECT ?a ?t WHERE { (TR7143, scheduledArrival, ?a) [system, inform] . "
            "(request1, selectedService, ?t) FILTER(?t = TR7143) }"))
        for version in (0, 1, 2):
            self.assert_same(self.store, compiled, version, version)
        _, classes = equivalence_classes(self.store, 2)
        main, _ = compiled.bind(classes)
        # TR7143 has two members at version 2: its VALUES block stays; request1 and the speaker
        # have one member and are inlined; the FILTER constant is an IN list either way.
        self.assertEqual(main.count("VALUES ?_k"), 1)
        self.assertRegex(main, r"VALUES \?_k\d+ \{ <[^>]+/TR7143> <[^>]+/train7143> \}")
        self.assertIn("IN (<", main)
        self.assertEqual([a.values for a in run(compiled.query, self.store, 2).answers],
                         [(Value("20:38:00", "time"), Entity("TR7143"))])


class SixFamiliesTest(Equivalent, unittest.TestCase):
    """Every binding of all six template families on a scaled E004 graph."""

    @classmethod
    def setUpClass(cls):
        made = [scale.generate_block(i, master_seed=11, length=80, density=30.0,
                                     families=("hotel-stay", "apartment-search", "train-travel",
                                               "flight-travel", "car-rental"))
                for i in range(3)]
        cls.graph = scale.build_graph(made, 40, "inline-six")

    def test_all_families_agree_at_several_versions(self):
        self.assertEqual(set(FAMILIES), {"list", "current", "count", "constraints", "pending",
                                         "choice"})
        views = ViewStore(self.graph.history_id, config=ViewConfig(state_speaker="user"))
        bindings = scale.admitted(self.graph.bindings, FAMILIES)
        self.assertEqual({b.family for b in bindings}, set(FAMILIES))
        store = scale.fork_store(self.graph.store)
        checkpoints = {store.head, store.head + 40, store.head + 120}
        nonempty = {f: 0 for f in FAMILIES}
        for cs in [None, *self.graph.window]:
            if cs is not None:
                store.commit(cs)
            if store.head not in checkpoints:
                continue
            for b in bindings:
                query, _ = views.bind(b)
                c = Compiled.of(query, store.mode)
                for part in (c.main, c.members):
                    if part is None:
                        continue
                    self.assert_same(store, part, store.head, (b.view_id, store.head))
                main, _ = c.main.bind({})
                self.assertNotIn("VALUES", main)
                if rows(store, main, store.head):
                    nonempty[b.family] += 1
        # the comparison is not vacuous: every family has views with rows
        self.assertTrue(all(nonempty.values()), nonempty)


HOSTILE = ("x> } ; ?s ?p ?o . { <y", "a b", "%k0%", "%r%", "?_k0", 'q"uote', "back\\slash",
           "unicode-é", "percent%25")


class InjectionTest(Equivalent, unittest.TestCase):
    def setUp(self):
        self.store = ClaimStore("hostile")
        claims = tuple(claim(f"c{i}", e, "p", Value(e, "string"), 1)
                       for i, e in enumerate(HOSTILE))
        self.store.commit(ChangeSet("hostile", 1, claims=claims,
                                    attributions=tuple(att(f"a{i}", f"c{i}", 1, "user", "inform")
                                                       for i in range(len(HOSTILE))),
                                    evidence_links=tuple(ev(f"e{i}", f"c{i}", 1)
                                                         for i in range(len(HOSTILE)))))

    def test_hostile_entity_ids_match_exactly(self):
        for i, entity in enumerate(HOSTILE):
            query = Query((Var("v"),), (ClaimPattern(Entity(entity), "p", Var("v")),))
            compiled = compile_query(query)
            self.assert_same(self.store, compiled, 1, entity)
            answers = run(query, self.store, 1).answers
            self.assertEqual([a.values for a in answers], [(Value(entity, "string"),)], entity)
            self.assertEqual(answers[0].witnesses[0].claims, (f"c{i}",))

    def test_hostile_literals_are_not_substituted(self):
        for entity in HOSTILE:
            query = Query((Var("s"),), (ClaimPattern(Var("s"), "p", Var("v")),),
                          filters=(Filter(Var("v"), Op.EQ, Value(entity, "string")),))
            compiled = compile_query(query)
            self.assertNotIn("%r%\"", compiled.main)
            self.assert_same(self.store, compiled, 1, entity)
            self.assertEqual([a.values for a in run(query, self.store, 1).answers],
                             [(Entity(entity),)], entity)

    def test_invalid_iri_is_refused(self):
        compiled = compile_query(parse("SELECT ?v WHERE { (a, p, ?v) }"))
        fake = mock.Mock()
        fake.value = "urn:x> } ; ?s ?p ?o . { <y"
        with mock.patch.object(compiler.rdf, "entity_iri", return_value=fake):
            with self.assertRaises(ValueError):
                compiled.bind()
            with self.assertRaises(ValueError):
                compiled.bind(inline=False)


if __name__ == "__main__":
    unittest.main()
