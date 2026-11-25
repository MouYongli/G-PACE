---
id: T022
title: "Writer: extraction and graph update"
created: 2026-11-23
---

# T022 · Writer: extraction and graph update

## Goal

The write path of plan section 5.1: the writer extracts claim patches anchored to message spans; the program validates them and decides, by attribution and exclusivity rules, whether to append, supersede or keep claims side by side; entity alignment adds versioned equivalence entries.

## Scope

- In scope:
  - Output constrained by a JSON schema; failed patches leave the raw-text path intact.
  - Extraction granularity as a parameter (message, segment, session); knowledge versions follow the evidence message.
  - The writer never reads view text, staleness marks or fingerprints.
- Out of scope: Vocabulary evolution (T032).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Attribution-guard handling passes the three running examples of plan section 3.5 on fixtures.
- [ ] Every call, retry and failure is in the cost ledger.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` writer package; extraction prompt registered with T004.

## Log

- 2026-11-23: created from the full project DAG.
