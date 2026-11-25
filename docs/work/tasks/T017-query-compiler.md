---
id: T017
title: Query IR and compiler
created: 2026-11-23
---

# T017 · Query IR and compiler

## Goal

The typed intermediate representation and the deterministic compiler of plan section 5.3. It covers the six operations of the fragment (plan section 3.3), takes the cutoff version as a parameter, projects the claims and attributions behind each answer, and issues the second query that fetches evidence.

## Scope

- In scope:
  - Grammar, type checker and parameterised SPARQL templates.
  - Witness projection and the two-step evidence query.
  - Scope notes for empty results and counts, generated at read time.
- Out of scope: Producing the IR from a natural-language task (T023).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [x] Compiled queries return the gold answers and witnesses on fixture graphs for every operation.
- [x] Time-travel reads at a past version are unchanged by later appends.
- [x] `make test` and `make lint` pass.

## Deliverables

`src/grace/` query package (`src/grace/context/pipeline/query/`); grammar document [`docs/research/query-ir.md`](../../research/query-ir.md).

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-T017` started on `task/T017-query-compiler` from `main` at 2304a4714cdd262941846cd764c9fbd818e155a4; Issue #58. No workers: the manager writes the code.
- 2026-11-25: IR, text grammar, type checker, compiler (main, count and evidence queries), execution with witnesses and evidence, scope notes and grammar document written; unit tests for grammar and rejections, integration tests on a fixture history in both serialisations (every operation, current and historical state, valid time, time travel, entity merges).
- 2026-11-25: PR #60 reviewed and merged; acceptance met. Open questions for the user: joins across merged entities, polarity in attribution constraints, and the owner of `patterns.py`.
- 2026-11-25: manager session `m01-T017b` on `fix/T017-latest-witnesses` from `main` at b3fce95b70ed185d12b09ce16520212d8b10a8a0 fixed T015 finding F2: `LATEST` now selects the latest claim of the labelled pattern first (its key is the maximum row key over its rows, the latest version at which it was confirmed) and then keeps every row of that claim, so a restated claim keeps its earlier witnesses (plan 3.4, change-sequences.md 6.2 V2). Regression test added (`LatestTest.test_latest_keeps_every_witness_of_the_selected_claim`, fails on the old code); the F2 `expectedFailure` in the cross-check tests is removed. Cross-check rerun `T017-crosscheck-20261125T180937Z` (code `678125a`, clean; upstream `T015-devsmoke-20261125T023552Z`, rdf11 and rdf12 identical): own-positive graph 0 value and 0 label disagreements of 75,375 pairs (V2 witness disagreements 2,929 -> 0); full graph 14,772 value (was 16,782) and 475 label disagreements, all explained by the attribution-constraint gap F1, 0 unexplained (was 5,858 over both modes). F1 and the V3 witness convention stay open for the user.
