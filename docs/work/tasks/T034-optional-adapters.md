---
id: T034
title: Optional benchmark and system adapters
created: 2026-11-23
---

# T034 · Optional benchmark and system adapters

## Goal

Adapters for the summary-table benchmarks and the optional external systems (plan sections 6.3 and 7.2).

## Scope

- In scope:
  - Decide how the claim graph projects onto HaluMem's per-session extracted memories before writing its adapter.
  - MemoryAgentBench: LongMemEval(S*) and the 6K and 32K FactConsolidation variants only.
  - Graphiti: publish the adaptation and failure rate; keep a row with its native backbone.
- Out of scope: Redistributing re-annotated HaluMem data (licence CC BY-NC-ND 4.0).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Each adapter loads its development data through the common record contracts.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` adapters; `configs/benchmarks/`.

## Log

- 2026-11-23: created from the full project DAG.
