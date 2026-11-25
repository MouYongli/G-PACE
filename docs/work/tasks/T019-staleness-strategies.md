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

- [ ] Claim-pattern strategies report no miss against re-querying on fixtures for all seven change types.
- [ ] Each strategy logs dirty marks, rebuilds and database time separately.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` staleness package.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-T019` started on `task/T019-staleness-strategies` (Issue #78); the manager writes the code itself this round, no worker branches. Dependency patterns (`views/dependencies.py`) assigned to T019 by the integration owner.
- 2026-11-25: implemented `src/grace/context/views/staleness/` (eight strategies, change-set matcher, logs) and `configs/views/staleness.yaml` (nine arms: claim-pattern push without and with local filters). Two additive hooks in `views/store.py`: `ViewStore.evaluate` and `maintain(..., evaluation=...)`, so a fingerprint check runs the view query once. Acceptance evidence is the test suite (`tests/integration/test_staleness.py`, `tests/unit/test_staleness_matching.py`): no miss of the claim-pattern strategies, predicate level and re-query against read-time re-query on the worked example (C1-C7) and on three generated development sequences, on the stored gold graph and its own-positive projection, read every version and every third; a negative control (push without negated patterns) does miss. Finding: on the stored gold graph the views go answer-stale on some C7a messages that the generator labels "neither"; this is F1 (`[u, f]` cannot require own, positive, not derived) and vanishes on the own-positive projection, where the views' re-query staleness equals the generator's labels at every version and binding.
