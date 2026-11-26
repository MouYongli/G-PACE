---
id: T028
title: MultiWOZ state prediction and baselines
created: 2026-11-23
---

# T028 · MultiWOZ state prediction and baselines

## Goal

Everything specific to MultiWOZ (plan section 6.5): the projection from the claim graph to official slots, scoring of original-constraint retention and of paired correctness with the derived gold of T006, and the baselines: ReacTOD reproduced on Qwen3-8B, deterministic overwrite on official slots, the 'system values are not written' rule, and direct state output by the answering LLM.

## Scope

- In scope:
  - One prediction file is scored against 2.4, 2.2 and 2.1.
  - No look-ahead and no gold-state backfill.
- Out of scope: Any cost argument on MultiWOZ.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Scores of the reproduced ReacTOD are compared with its published 2.1 number and the gap is explained.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` MultiWOZ package.

## Log

- 2026-11-23: created from the full project DAG.
