---
id: T029
title: Mem0 adapter
created: 2026-11-23
---

# T029 · Mem0 adapter

## Goal

Mem0 running under this project's protocol with the same answering LLM, answer prompt, budgets and ledger (plan section 7.2), with the adaptation, version and failure rate recorded.

## Scope

- In scope:
  - Pin the version; publish the adapter patch.
  - Record how the evidence set shown to the answering LLM is extracted.
- Out of scope: Mem0g and Graphiti (T034).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Runs on the LoCoMo development histories with all calls in the ledger.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` baseline adapter.

## Log

- 2026-11-23: created from the full project DAG.
