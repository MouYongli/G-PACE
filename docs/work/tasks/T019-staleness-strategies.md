---
id: T019
title: Staleness strategies
created: 2026-11-23
---

# T019 · Staleness strategies

## Goal

The eight staleness strategies of plan section 5.4 as interchangeable modules over one claim graph, with dependency patterns taken from the IR, including patterns inside negation and aggregation, attribution constraints and local filters.

## Scope

- In scope:
  - Never invalidate; rebuild every turn; used claims; used claims plus negation and aggregation patterns; predicate level; claim-pattern push; re-query with fingerprints; push filter plus read-time confirmation.
  - Answer, witness and evidence fingerprints.
  - Whole-history invalidation on vocabulary change or entity merge.
- Out of scope: Running the comparisons (E003, E004).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Claim-pattern strategies report no miss against re-querying on fixtures for all seven change classes.
- [ ] Each strategy logs dirty marks, rebuilds and database time separately.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` staleness package.

## Log

- 2026-11-23: created from the full project DAG.
