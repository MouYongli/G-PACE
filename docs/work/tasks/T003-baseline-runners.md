---
id: T003
title: Baseline runners
created: 2026-11-21
---

# T003 · Baseline runners

## Goal

Runnable baselines needed by the pilot: same-reader full history, text retrieval (BM25, dense, RRF), rolling summary with recent raw text, and the role-aware JSON state table, all producing predictions and cost-ledger entries under the T001 contracts.

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
