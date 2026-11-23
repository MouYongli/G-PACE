---
id: T027
title: Structured and tagged baselines
created: 2026-11-23
---

# T027 · Structured and tagged baselines

## Goal

The baselines of plan section 7.2 that need the writer: a fixed-schema slot table with roles and sources, an append-only memory that resolves conflicts at query time without caching, the template-serialisation variant of the system, and hybrid retrieval over chunks tagged with speaker and dialogue act.

## Scope

- In scope:
  - All use the same reader, answer prompt and budgets.
  - Tags are predicted by the same writer and their tokens are charged.
- Out of scope: External systems (T029, T034).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Each baseline runs on the development set through the common runner and ledger.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` baseline package.

## Log

- 2026-11-23: created from the full project DAG.
