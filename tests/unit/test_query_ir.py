"""Query representation, text grammar, type checker and compiler output (T017; plan 3.3, 5.3).

No store is needed here; execution on fixture graphs is in tests/integration/test_query_compiler.py.
"""

from __future__ import annotations

import datetime as dt
import unittest

from grace.context.memory.graph.entries import CommunicativeFunction, Entity, Value
from grace.context.pipeline.query.compile import absolutize, compile_query
from grace.context.pipeline.query.grammar import parse, to_text
from grace.context.pipeline.query.ir import (
    At,
    AttributionConstraint,
    ClaimPattern,
    CountDistinct,
    Filter,
    Latest,
    NotExists,
    Op,
    Query,
    QueryTypeError,
    ReadTime,
    Scope,
    State,
    Var,
    typecheck,
)

X, Y, T, C = Var("x"), Var("y"), Var("t"), Var("c")
ACCEPTED = """SELECT ?train ?arr WHERE {
  (request1, selectedService, ?train) [user, accept] AS ?c .
  (?train, scheduledArrival, ?arr)
} AT(known=r, state=current)"""

VALID = [
    ACCEPTED,
    'SELECT ?t WHERE { (?t, scheduledArrival, ?a) FILTER(?a <= "20:45:00"^^time) }',
    "SELECT ?t WHERE { (request1, selectedService, ?t) [system, offer] "
    "NOT EXISTS { (request1, selectedService, ?t) [user, accept] } }",
    "SELECT ?p COUNT(DISTINCT ?i) WHERE { (?p, playsInstrument, ?i) }",
    "SELECT ?t WHERE { (request1, selectedService, ?t) [_, accept] AS ?c } "
    "LATEST BY valid OF ?c",
    'SELECT ?x WHERE { (<id%20with%20spaces>, p, ?x, "work") [?u, _] } '
    'AT(known=4, valid="2023-06-01T10:00:00Z"^^dateTime, state=historical) WITHOUT PROVENANCE',
    'SELECT ?x WHERE { (s, p, ?x, default) . (?x, q, "a \\"quoted\\" text") . (?x, r, 42) '
    "FILTER(?x != Atlas) }",
    "SELECT ?p WHERE { (lina, ?p, true) }",
]


def rejects(test: unittest.TestCase, text: str, fragment: str) -> None:
    with test.assertRaises(QueryTypeError) as ctx:
        parse(text)
    test.assertIn(fragment, str(ctx.exception), text)


class GrammarTest(unittest.TestCase):
    def test_example_parses_to_the_expected_representation(self):
        q = parse(ACCEPTED)
        self.assertEqual(q.select, (Var("train"), Var("arr")))
        self.assertEqual(q.where[0], ClaimPattern(
            Entity("request1"), "selectedService", Var("train"), Scope.ANY,
            AttributionConstraint(Entity("user"), CommunicativeFunction.ACCEPT), C))
        self.assertEqual(q.where[1].object, Var("arr"))
        self.assertEqual(q.at, At())

    def test_round_trip_through_the_canonical_text(self):
        for text in VALID:
            q = parse(text)
            self.assertEqual(parse(to_text(q)), q, text)
            self.assertEqual(to_text(parse(to_text(q))), to_text(q))

    def test_literals(self):
        q = parse('SELECT ?s WHERE { (?s, p, "2023-05-25"^^date) . (?s, q, -3) . (?s, b, false) }')
        self.assertEqual([p.object for p in q.where],
                         [Value("2023-05-25", "date"), Value("-3", "integer"),
                          Value("false", "boolean")])
        rejects(self, 'SELECT ?s WHERE { (?s, p, "2023-13-01"^^date) }', "xsd:date")
        rejects(self, 'SELECT ?s WHERE { (?s, p, "x"^^float) }', "unknown datatype")

    def test_bracketed_entity_ids_are_percent_decoded(self):
        q = parse(VALID[5])
        self.assertEqual(q.where[0].subject, Entity("id with spaces"))

    def test_entity_named_like_an_aggregate_is_an_entity(self):
        q = parse("SELECT ?x WHERE { (max, likes, ?x) }")
        self.assertEqual(q.where[0].subject, Entity("max"))


class RejectionTest(unittest.TestCase):
    """Constructs outside the fragment fail with a message naming the construct."""

    def test_more_than_three_patterns(self):
        rejects(self, "SELECT ?a WHERE { (?a, p, ?b) . (?b, p, ?c) . (?c, p, ?d) . (?d, p, ?e) }",
                "limited to 3 claim patterns")

    def test_property_paths(self):
        for path in ("p/q", "p+", "p*", "p|q", "^p"):
            rejects(self, f"SELECT ?x WHERE {{ (a, {path}, ?x) }}", "property paths")

    def test_other_aggregates(self):
        for agg in ("SUM", "AVG", "MIN", "MAX", "SAMPLE", "GROUP_CONCAT"):
            rejects(self, f"SELECT {agg}(?x) WHERE {{ (a, p, ?x) }}", f"aggregate {agg}")
        rejects(self, "SELECT COUNT(?x) WHERE { (a, p, ?x) }", "COUNT(DISTINCT ?x)")
        rejects(self, "SELECT COUNT(DISTINCT *) WHERE { (a, p, ?x) }", "count one variable")

    def test_comparison_with_read_time(self):
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) AS ?c FILTER(start(?c) > now(-7)) }",
                "time of reading")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) } AT(valid=NOW)", "time of reading")

    def test_comparison_between_variables(self):
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) . (b, p, ?y) FILTER(?x < ?y) }",
                "only with constants")

    def test_sparql_constructs_outside_the_fragment(self):
        for word in ("OPTIONAL", "UNION", "MINUS", "BIND", "VALUES", "GRAPH"):
            rejects(self, f"SELECT ?x WHERE {{ (a, p, ?x) {word} {{ (b, p, ?x) }} }}", word)
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) } ORDER BY ?x", "ORDER")
        rejects(self, "SELECT * WHERE { (a, p, ?x) }", "SELECT *")
        rejects(self, "SELECT ?x WHERE { ?c a ?x }", "triple patterns")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) FILTER(?x > 1 || ?x < 0) }",
                "one comparison per FILTER")

    def test_negation_shape(self):
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) NOT EXISTS { (b, p, ?x) "
                      "NOT EXISTS { (c, p, ?x) } } }", "nested negation")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) NOT EXISTS { (b, p, ?x) . (c, p, ?x) } }",
                "exactly one claim pattern")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) NOT EXISTS { (b, p, ?x) } "
                      "NOT EXISTS { (c, p, ?x) } }", "only one NOT EXISTS")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) NOT EXISTS { (b, p, ?y) } }",
                "share a variable")
        rejects(self, "SELECT ?y WHERE { (a, p, ?x) NOT EXISTS { (?x, p, ?y) } }",
                "does not occur in a positive pattern")

    def test_ill_typed_queries(self):
        rejects(self, "SELECT ?y WHERE { (a, p, ?x) }", "does not occur in a positive pattern")
        rejects(self, "SELECT ?c WHERE { (a, p, ?x) AS ?c }", "labels name claims")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) FILTER(?z = 1) }", "not bound")
        rejects(self, "SELECT ?x WHERE { (?x, ?x, b) }", "used both as")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) FILTER(?x < Atlas) }", "only with = and !=")
        rejects(self, 'SELECT ?x WHERE { (a, p, ?x) AS ?c FILTER(end(?c) < "x") }',
                "xsd:date or xsd:dateTime")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) AS ?c FILTER(start(?d) < 1) }",
                "names no pattern label")
        rejects(self, "SELECT ?x COUNT(DISTINCT ?x) WHERE { (a, p, ?x) }",
                "also a grouping variable")
        rejects(self, "SELECT COUNT(DISTINCT ?x) WHERE { (a, p, ?x) AS ?c } "
                      "LATEST BY version OF ?c", "both count and select the latest")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) } LATEST BY version OF ?c",
                "labels no positive pattern")
        rejects(self, 'SELECT ?x WHERE { (a, p, ?x) } AT(valid="June")', "xsd")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) } AT(state=future)", "current or historical")
        rejects(self, "SELECT ?_x WHERE { (a, p, ?_x) }", "reserved")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) [_, _] }", "needs a speaker or a function")
        rejects(self, "SELECT ?x WHERE { (a, p, ?x) [u, greet] }", "unknown communicative")

    def test_representation_level_checks(self):
        pattern = ClaimPattern(Entity("a"), "p", X)
        with self.assertRaises(QueryTypeError):
            typecheck(Query((X,), ()))
        with self.assertRaises(QueryTypeError):
            typecheck(Query((X,), (pattern,) * 4))
        with self.assertRaisesRegex(QueryTypeError, "property paths"):
            typecheck(Query((X,), (ClaimPattern(Entity("a"), "p/q", X),)))
        with self.assertRaisesRegex(QueryTypeError, "time of reading"):
            typecheck(Query((X,), (pattern,), (Filter(X, Op.GT, ReadTime(-7)),)))
        with self.assertRaisesRegex(QueryTypeError, "time of reading"):
            typecheck(Query((X,), (pattern,),
                            negation=NotExists(ClaimPattern(X, "q", Y),
                                               (Filter(Y, Op.GT, ReadTime()),))))
        with self.assertRaisesRegex(QueryTypeError, "only COUNT"):
            typecheck(Query((), (pattern,), count="sum"))
        typecheck(Query((), (pattern,), count=CountDistinct(X)))
        typecheck(Query((X,), (ClaimPattern(Entity("a"), "p", X, label=C),),
                        latest=Latest(C), at=At(3, "2023-01-01", State.HISTORICAL)))

    def test_errors_are_collected(self):
        with self.assertRaises(QueryTypeError) as ctx:
            parse("SELECT ?y ?z WHERE { (a, p, ?x) }")
        self.assertIn("?y", str(ctx.exception))
        self.assertIn("?z", str(ctx.exception))


class CompilerOutputTest(unittest.TestCase):
    def test_compilation_is_deterministic(self):
        for text in VALID:
            for mode in ("rdf11", "rdf12"):
                a = compile_query(parse(text), mode)
                b = compile_query(parse(to_text(parse(text))), mode)
                self.assertEqual((a.main, a.count, a.evidence), (b.main, b.count, b.evidence))

    def test_cutoff_is_a_placeholder_not_a_variable_or_constant(self):
        compiled = compile_query(parse(ACCEPTED))
        self.assertIn("%r%", compiled.main)
        self.assertNotIn("?r ", compiled.main)
        fixed = compile_query(parse(ACCEPTED.replace("known=r", "known=4")))
        self.assertEqual(fixed.main, compiled.main)  # the cut-off is bound at execution

    def test_main_query_shape(self):
        compiled = compile_query(parse(ACCEPTED))
        main = compiled.main
        self.assertTrue(main.startswith("SELECT DISTINCT ?train ?arr ?c ?_a_c ?_c1 WHERE {"))
        self.assertIn("rdf:subject", main)
        self.assertIn("g:function gf:accept", main)
        self.assertEqual(main.count("FILTER NOT EXISTS { ?_s_"), 2)  # one per claim pattern
        self.assertNotIn("g:Correction", main)
        self.assertNotIn("wasDerivedFrom", main)  # evidence is a separate query
        self.assertIsNone(compiled.count)
        hist = compile_query(parse(ACCEPTED.replace("current", "historical"))).main
        self.assertEqual(hist.count("g:kind g:Correction"), 2)
        rdf12 = compile_query(parse(ACCEPTED), "rdf12").main
        self.assertIn("rdf:reifies <<(", rdf12)
        self.assertNotIn("rdf:subject", rdf12)

    def test_evidence_query_is_separate(self):
        compiled = compile_query(parse(ACCEPTED))
        self.assertIn("%claims%", compiled.evidence)
        self.assertIn("prov:wasDerivedFrom", compiled.evidence)
        self.assertIn("FILTER(?_ev <= %r%)", compiled.evidence)

    def test_count_query_uses_the_restricted_aggregate(self):
        compiled = compile_query(parse(VALID[3]))
        self.assertIn("(COUNT(DISTINCT ?i) AS ?_count)", compiled.count)
        self.assertTrue(compiled.count.endswith("GROUP BY ?p"))

    def test_bind_fills_entity_classes(self):
        compiled = compile_query(parse("SELECT ?x WHERE { (TR7143, p, ?x) }"))
        plain, _ = compiled.bind()
        self.assertIn("entity/TR7143>", plain)
        merged, _ = compiled.bind({"TR7143": ["TR7143", "train7143"]})
        self.assertIn("entity/train7143>", merged)
        self.assertNotIn("%k", merged)


class AbsolutizeTest(unittest.TestCase):
    def test_read_time_becomes_an_absolute_constant(self):
        q = parse("SELECT ?x WHERE { (a, p, ?x) AS ?c FILTER(start(?c) >= now(-7)) }", check=False)
        fixed = absolutize(q, dt.date(2023, 6, 8))
        self.assertTrue(fixed.temporary)
        self.assertEqual(fixed.filters[0].right, Value("2023-06-01", "date"))
        typecheck(fixed)
        self.assertIn("TEMPORARY", to_text(fixed))
        moment = absolutize(q, dt.datetime(2023, 6, 8, 12, 0, tzinfo=dt.UTC))
        self.assertEqual(moment.filters[0].right, Value("2023-06-01T12:00:00Z", "dateTime"))

    def test_query_without_relative_time_is_unchanged(self):
        q = parse(ACCEPTED)
        self.assertEqual(absolutize(q, dt.date(2023, 1, 1)), q)


if __name__ == "__main__":
    unittest.main()
