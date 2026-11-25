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
