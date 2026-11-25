---
id: T035
title: Audit, judge calibration and uncertainty
created: 2026-11-23
---

# T035 · Audit, judge calibration and uncertainty

## Goal

The checks that make the formal numbers reportable (plan sections 6.7 to 6.9): judge calibration with deliberately wrong vague answers as negative controls, agreement with the official LongMemEval judge, human audit of sampled items, the statistical analysis with paired tests and history as a random effect, and uncertainty reported by source.

## Scope

- In scope:
  - Stratified results by history length, revision frequency, reads per history and evidence spread.
  - Every deviation from the preregistration is listed.
- Out of scope: New runs.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] The blind judge's agreement with human labels on a calibration sample is reported (moved from T004, user decision 2026-11-25).
- [ ] Each table in the paper is regenerated from run reports by a committed script.
- [ ] `make test` and `make lint` pass.

## Deliverables

Analysis scripts under `src/grace/cli/`; tables under `paper/`.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: acceptance item on the blind judge's agreement with human labels moved here from T004 (user decision). T004 delivered the protocol and code path (`src/grace/eval/analysis/judging/`).
