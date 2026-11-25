---
id: T015
title: Controlled change-sequence generator
created: 2026-11-23
---

# T015 · Controlled change-sequence generator

## Goal

The generator designed in T008: natural English dialogues whose ground truth is a program event log, covering the seven change types of plan section 6.4, with a gold claim graph at every version, a read schedule with gold answers and witnesses, and per-message answer and citation staleness for every template view.

## Scope

- In scope:
  - Controlled variables: change mix, revision density, read interval, reads per history, history length.
  - Surface text rendered by a model that no evaluated system uses.
  - Development and held-out template families are disjoint.
- Out of scope: Auditing the sequences (T016).
- Layout (decision D013): the generator goes to `src/grace/eval/datasets/changeseq/`, its grammar and template families to `resources/changeseq/`, and the adapter that reads the generated dataset to `src/grace/eval/datasets/benchmarks/`. From `src/grace/context/` the generator imports only `memory/graph/`, for the entry types of the gold graph.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Gold graphs validate against the shapes of T014.
- [ ] Invalidation truth is computed as the design of T008 prescribes; if that is from the event log without the query compiler, the generator does not import `context/pipeline/query/`.
- [ ] Invalidation truth agrees with re-evaluating each view on the gold graph at every version. With an independent ground truth this check also tests the compiler.
- [ ] `make test` and `make lint` pass.

## Deliverables

Generator under `src/grace/eval/datasets/changeseq/`; configs; generated development sequences in a run directory.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-24: layout and the acceptance item on the invalidation ground truth added from decision D013.
