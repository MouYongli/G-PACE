"""Evidence-driven context assembly (plan 5.5; T026).

- `items`: the candidate type `Item` that the engine builds from retrieval candidates, query
  answers, views and summaries, and helpers for messages and query results.
- `demand`: the variables an answer needs (`Demand`, from the planner's variables) and lexical
  support of variables by items.
- `filter`: filter by knowledge version, valid time, scope and attribution (`Constraints`).
- `select`: greedy selection by new coverage per added token; rank truncation as the contrast.
- `expand`: at most one expansion per read: a summary into raw text, or a further restricted
  query handed back to the engine.
- `layout`: serialisation into the fixed layout with citations; the token ledger.
- `assemble`: `Assembler`, which runs the steps within a token budget (`AssemblyConfig`, files
  `configs/assembly/*.yaml`).

This package imports only `context/api.py` and `context/memory/history/` (structure.md). It never
calls `pipeline/query/` or `pipeline/retrieval/`: the engine runs them and hands their results in
as items, and runs a pending query expansion itself.
"""
