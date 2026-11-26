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
- 2026-11-25: manager session `m01-T017c` on `feat/T017-attribution-default` from `main` at 59a0dd1e14de62016c8eebb33df56e1ef828a701 (rebased onto cf686d77bc1f817f9cd4a5f123d7073df2705bda) implemented the user's decision on T015 finding F1: `[u, f]` by default requires an own, positive, not derived attribution; `mode=_`, `polarity=_` and `derived=_` relax each default explicitly (query-ir.md sections 2, 4, 6; open question 2 resolved). Tests cover the defaults and relaxation in both serialisations, including time-travel stability; the F1 `expectedFailure` in the cross-check tests is removed and the planner devset F1 count drops from 26 to 0. Cross-check rerun `T017-crosscheck-20261125T190606Z` (code `4d7bfa9`, clean; upstream `T015-devsmoke-20261125T023552Z`): on the full graph 0 value disagreements (was 14,772) and 0 label disagreements (was 475) per mode, own-positive graph still 0. Raw V3 witness differences, a separate convention matter: 5,288 per mode on both graphs (full was 7,241). Planner devset `T017-plannerdev-20261125T190925Z` (rules only, no model calls): every annotated IR now executes correctly on the unfiltered graph (99 of 99), and all 31 rule-routed plans are correct. Follow-up for `views/` (T019, read only here): the dependency matcher still checks only speaker and function, so it over-marks attributions the compiled query rejects (sound, less precise), and `DependencyPattern.to_record` does not record relaxed defaults.
- 2026-11-26: user decision (E004 follow-up), implemented by manager session m01-E004b on `task/E004-inline-constants` from `main` at `3143ab337cf080b3511698d5b01e5f2361f4d961`: `CompiledQuery.bind` now writes an entity constant whose equivalence class has one member directly into its triple patterns instead of binding it with a one-row `VALUES` block (pyoxigraph 0.5.13 evaluated the `VALUES` form of the `pending` and `choice` view queries two to three orders of magnitude slower, E004); merged classes keep `VALUES`. `bind(inline=False)` reproduces the previous text. `CompiledQuery.main` is unchanged; the executed text changes for every query with an entity constant (deliberate, user-approved). Literals write `%` and `?` as code-point escapes (a literal containing `%r%` or `%k0%` was previously substituted), and IRIs are checked to be valid IRI references before substitution. Tests: `tests/integration/test_inline_constants.py` (old and new texts return identical rows for the fixture suite at every version in both serialisations, with merges, and for every binding of all six template families on scaled graphs; hostile entity IDs and literals; invalid IRIs refused). Grammar document updated (query-ir.md, section on claim patterns).
