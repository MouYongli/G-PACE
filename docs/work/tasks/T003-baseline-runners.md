---
id: T003
title: Baseline runners
created: 2026-11-21
---

# T003 · Baseline runners

## Goal

Runnable baselines needed by the pilot: same-reader full history, text retrieval (BM25, dense, RRF), rolling summary with recent raw text, and the fixed-schema slot table with roles and provenance, all producing predictions and cost-ledger entries under the T001 contracts.

## Scope

- In scope: the four baseline families above on the primary model.
- Out of scope: external memory systems and the remaining baselines of plan section 7.2 (milestone M4).
- Candidate worker subtasks: one per baseline family.

## Acceptance

- [ ] Each baseline runs end to end on fixtures and on one development history per benchmark.
- [ ] Every run writes `run.json`, predictions and cost-ledger entries that pass the contract tests.

## Deliverables

`src/grace/` baseline modules and their configs.

## Log

- 2026-11-21: created from plan section 9, phase 1.
- 2026-11-22: "JSON state table" renamed to "relational state table" to match plan v3.
- 2026-11-23: "relational state table" replaced by the fixed-schema slot table, following the revised plan (section 7.2): a relational encoding with the same fields is the same data model as the graph and is not compared.
