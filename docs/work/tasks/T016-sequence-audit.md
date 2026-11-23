---
id: T016
title: Sequence audit
created: 2026-11-23
---

# T016 · Sequence audit

## Goal

Evidence that the generated text says what the event log says (plan section 6.4, validity): two annotators judge, message by message, whether text and events agree.

## Scope

- In scope:
  - At least 5 sequences per template family.
  - Cohen's kappa and the disagreement rate are reported.
- Out of scope: Changing the generator design.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Audit records are committed.
- [ ] Template families with systematic mismatches are fixed in T015 or excluded, with the reason recorded.

## Deliverables

Audit records under `docs/research/`.

## Log

- 2026-11-23: created from the full project DAG.
