---
id: D012
title: Configuration lock
created: 2026-11-23
---

# D012 · Configuration lock

## Context

Before any held-out data is run, everything that can affect a result is frozen (plan section 9, phase 6). E015 is a dependency only if phase 5 runs; if D011 is rejected, E015 is dropped and does not hold the lock back.

## Options

- Main configuration: extraction granularity, routing, fusion, view templates and thresholds, vocabulary mode.
- Splits, exclusions, judge prompt and snapshot, budgets, non-inferiority margins per benchmark.

## Decision

Pending. To be taken when the nodes this decision depends on are resolved.

## Consequences

No tuning after the lock; every deviation is disclosed. Preregistration (T033) records the frozen files.

## Revisit when

Never; a change after the lock is a disclosed deviation, not a revision.

## Log

- 2026-11-23: proposed as part of the full project DAG.
