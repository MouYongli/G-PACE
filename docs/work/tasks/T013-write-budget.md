---
id: T013
title: Write-budget estimate and break-even curves
created: 2026-11-23
---

# T013 · Write-budget estimate and break-even curves

## Goal

A paper calculation of writer tokens per history at each extraction granularity (per message, per segment, per session), compared with full-history reading with prefix caching as a function of the cache ratio c (plan section 8.4). It fixes the order of magnitude of the write budget and the starting granularity for the writer (T022).

## Scope

- In scope:
  - Recount tokens per LoCoMo history with the primary model's tokenizer.
  - Break-even reads M* as a curve over c from 0 to 1, with the measured c from E001 marked.
- Out of scope: Measured writer costs (E007).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] The calculation is reproducible from a committed script and config.
- [ ] A go or no-go statement on token savings for LoCoMo is written down.
- [ ] `make test` and `make lint` pass.

## Deliverables

Script under `src/grace/cli/`; note in the task log.

## Log

- 2026-11-23: created from the full project DAG.
