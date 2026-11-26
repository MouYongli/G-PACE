---
id: T032
title: Vocabulary maintenance call
created: 2026-11-23
---

# T032 · Vocabulary maintenance call

## Goal

The vocabulary-maintenance call of plan sections 5.2 and 5.6: triggered when a candidate predicate has no mapping or keeps failing type checks, it proposes an alias, a new predicate or a split; the program validates and commits it, and new predicates start local to the current history.

## Scope

- In scope:
  - At most one proposal per message.
  - A vocabulary version change invalidates all standing views of the history; the events and rebuild tokens are reported.
- Out of scope: Learned routing or fusion.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Old vocabulary versions stay readable and affected queries recompile.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` vocabulary package.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-24: renamed from `T032-vocabulary-role.md` and retitled to follow the plan terminology (an LLM call, not a role).
