---
id: T003
title: Baseline runners
created: 2026-11-21
---

# T003 · Baseline runners

## Goal

Runnable baselines needed by the pilot: same-reader full history, text retrieval (BM25, dense, RRF), rolling summary with recent raw text, and the fixed-schema slot table with roles and provenance, all producing predictions and cost-ledger entries under the T001 contracts.

## Scope

- In scope: the four baseline families above on the primary model.
- Out of scope: external memory systems and the remaining baselines of plan section 7.2 (milestone M4).
- Candidate worker subtasks: one per baseline family.
- Layout (decision D013): baselines go to `src/grace/eval/engines/baselines/` and implement the interface of `src/grace/context/api.py`; the first version of the harness goes to `src/grace/eval/runner/harness/`. A baseline imports nothing from `eval/datasets/`.
- Open question, to settle with the manager of T027 before the slot table is written: ablation B combines the fixed slot table with the attribution guard and bitemporality, so that version must use the GRACE assembly, which does not exist in phase 1. Either this task writes a standalone slot table for the pilot and T027 writes a second one inside the GRACE assembly, or one implementation is designed here so that T027 can reuse it. Record the choice in both Logs.

## Acceptance

- [ ] Each baseline runs end to end on fixtures and on one development history per benchmark.
- [ ] Every run writes `run.json`, predictions and cost-ledger entries that pass the contract tests.
- [ ] A test in `tests/contracts/` plants a sentinel string in the gold data of a fixture and asserts that it appears in no input any baseline receives from the harness.

## Deliverables

Baseline modules under `src/grace/eval/engines/baselines/`, the harness under `src/grace/eval/runner/harness/`, and one config per baseline under `configs/engines/`.

## Log

- 2026-11-21: created from plan section 9, phase 1.
- 2026-11-22: "JSON state table" renamed to "relational state table" to match plan v3.
- 2026-11-23: "relational state table" replaced by the fixed-schema slot table, following the revised plan (section 7.2): a relational encoding with the same fields is the same data model as the graph and is not compared.
- 2026-11-24: layout, the gold-sentinel test and the open question about the slot table added from decision D013.
