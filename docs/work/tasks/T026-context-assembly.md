---
id: T026
title: Evidence-demand assembly
created: 2026-11-23
---

# T026 · Evidence-demand assembly

## Goal

The assembler of plan section 5.5: list the variables a read must fill, filter candidates by version, valid time, scope and role, select greedily by new coverage per token, expand a summary or issue one more bounded query when variables stay open, and serialise the fixed working-context layout.

## Scope

- In scope:
  - Budgets of 256, 512 and 1,024 tokens and the full history.
  - Rank truncation as the comparison mode.
  - Reader output contract: answer, state, one extra retrieval, or unknown.
- Out of scope: Baseline systems (T027).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] The assembled context never exceeds the budget; token counts match the ledger.
- [ ] Every reader answer records the evidence IDs shown.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` assembly package.

## Log

- 2026-11-23: created from the full project DAG.
