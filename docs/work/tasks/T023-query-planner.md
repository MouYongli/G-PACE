---
id: T023
title: Query planner
created: 2026-11-23
---

# T023 · Query planner

## Goal

The planner of plan sections 5.3 and 5.6: rule templates map a task to the IR without an LLM call where they can; otherwise the planner LLM emits the IR, the variables to fill and fallback channels; parse or type failures fall back to text retrieval.

## Scope

- In scope:
  - At most one compile repair per read.
  - Relative time is converted to absolute intervals and never persisted as a view.
- Out of scope: Retrieval and fusion (T025).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] On the annotated development subset, role, time filter and execution result of the IR are checked.
- [ ] Parse-failure and fallback rates are logged.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` planner package; planner prompt registered with T004.

## Log

- 2026-11-23: created from the full project DAG.
