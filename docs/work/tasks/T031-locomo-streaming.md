---
id: T031
title: LoCoMo streaming harness
created: 2026-11-23
---

# T031 · LoCoMo streaming harness

## Goal

The evidence-anchored streaming protocol of plan section 6.5: each question is asked at v(q) and again at N, writing continues after every read, and ephemeral products are discarded after each question.

## Scope

- In scope:
  - Read-point list from T007; the 13 questions with missing evidence are excluded.
  - Consistency between the two answers is scored against the same gold.
- Out of scope: Deciding whether streaming goes into the main text (D007).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Two question orders give the same index version and evidence input for each question.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` evaluation package.

## Log

- 2026-11-23: created from the full project DAG.
