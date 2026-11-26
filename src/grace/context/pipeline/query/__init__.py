"""Query intermediate representation, compilation and execution (plan 3.3, 5.3; T017).

- `ir`: the typed intermediate representation of the query fragment and its type checker.
- `grammar`: the text form of the representation (parser and printer); docs/research/query-ir.md.
- `compile`: representation -> parameterised SPARQL (main query, count query, evidence query).
- `execute`: run a compiled query at a cut-off version; answers, witnesses, evidence.
- `result`: result types, fingerprints and read-time scope notes.
"""
