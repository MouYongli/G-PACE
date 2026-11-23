---
id: T015
title: Controlled change-sequence generator
created: 2026-11-23
---

# T015 · Controlled change-sequence generator

## Goal

The generator designed in T008: natural English dialogues whose ground truth is a program event log, covering the seven change classes of plan section 6.4, with a gold claim graph at every version, a read schedule with gold answers and witnesses, and per-message answer and citation staleness for every template view.

## Scope

- In scope:
  - Controlled variables: change mix, revision density, read interval, reads per history, history length.
  - Surface text rendered by a model that no evaluated system uses.
  - Development and held-out template families are disjoint.
- Out of scope: Auditing the sequences (T016).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Gold graphs validate against the shapes of T014.
- [ ] Invalidation truth agrees with re-evaluating each view on the gold graph at every version.
- [ ] `make test` and `make lint` pass.

## Deliverables

Generator under `src/grace/`; configs; generated development sequences in a run directory.

## Log

- 2026-11-23: created from the full project DAG.
