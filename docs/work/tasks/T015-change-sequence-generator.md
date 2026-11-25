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
- 2026-11-25: manager session `m01-T015` started on `task/T015-change-sequence-generator` from `2304a4714cdd262941846cd764c9fbd818e155a4`; Issue #59. Scope of this round: the generator core, no model calls.
- 2026-11-25: generator core implemented: event log with the seven change types and G1-G8 checks, gold claim graph on the T014 store (SHACL-validated), the six reference functions and Hist computed from the event log (no query compiler), per-message answer and citation staleness with change types and the section 4.2 invariants, an independent re-evaluation of every view on the gold graph at every version, read schedules U/A/P with questions, gold answers, witnesses and pairs, 20 scenario families with the committed split (5 development, 15 held-out), the `change-seq` adapter, and a deterministic template renderer (development and test renderer only). Deferred: the paper's model renderer (model not chosen, D006) and the cross-check against the compiled IR of T017.
- 2026-11-25: first development run `T015-devsmoke-20261125T023057Z` failed on the G1 check (a date correction reused an earlier claim's value and start); fixed in `fcb3aea`. Run `T015-devsmoke-20261125T023552Z` (code `fcb3aea`, clean, seed 20261125, `configs/changeseq/dev-smoke.yaml`) completed: 25 development-family sequences, 5,000 messages, 9,422 questions over 8 schedules, every check passed; a second run reproduced the dataset manifest byte for byte. Template renderer, no model calls, no held-out family generated.
