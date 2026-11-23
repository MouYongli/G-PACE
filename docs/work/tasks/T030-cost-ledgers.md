---
id: T030
title: Cost ledgers and amortisation tooling
created: 2026-11-23
---

# T030 · Cost ledgers and amortisation tooling

## Goal

The cost side of plan section 8: per-call records aggregated into three ledgers (logical tokens, tokens actually computed after prefix caching, GPU seconds), plus the scripts that draw quality-versus-token curves, cumulative-token curves over reads, M* over the cache ratio and cost per successful task.

## Scope

- In scope:
  - Failed attempts are counted.
  - Embedding tokens, database CPU, latency and tool calls are listed separately; judge calls are evaluation overhead.
- Out of scope: Running experiments.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Ledger totals reconcile with per-call logs on a fixture run.
- [ ] The cached full-history row is measured, not estimated.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` cost package and CLI.

## Log

- 2026-11-23: created from the full project DAG.
