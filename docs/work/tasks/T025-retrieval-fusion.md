---
id: T025
title: Retrieval channels, routing and fusion
created: 2026-11-23
---

# T025 · Retrieval channels, routing and fusion

## Goal

The retrieval side of plan section 5.5: BM25, dense and graph candidates mapped to one evidence ID space, rule-based routing with an always-three-channels fallback, and RRF fusion with weighted fusion as an alternative.

## Scope

- In scope:
  - Each channel can be switched off with the total number of candidates held fixed.
  - Routing rules, weights and thresholds are tuned on development data only.
- Out of scope: Selecting what goes into the prompt (T026).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Evidence recall of each channel is reported on the development set.
- [ ] Channel switches are covered by tests.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` retrieval package.

## Log

- 2026-11-23: created from the full project DAG.
