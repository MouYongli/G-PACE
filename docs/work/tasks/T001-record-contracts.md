---
id: T001
title: Record contracts
created: 2026-11-21
---

# T001 · Record contracts

## Goal

Replace the sample-level "Benchmark input" and "Prediction output" contracts with records that fit memory benchmarks: a history made of ordered messages, questions or state-tracking targets bound to a snapshot of that history, and predictions aligned to them. Add a token-cost ledger section so every system and baseline is billed the same way (plan sections 3, 6 and 8).

## Scope

- In scope: `docs/research/contracts.md` sections for history, message, question/target, prediction and cost ledger; synthetic fixtures; contract tests.
- Also in scope, from decision D013: three extensions of the "Experiment run" section, the move of the path files, and the import-rule test. The section is owned by the integration owner, who approves these changes in the task PR.
  - A run may name an upstream run by its run ID and read its files without writing to them. Runs are split into stages (system, judging, scoring), and under end-of-history reading one ingestion serves several read configurations.
  - The intermediate artefacts of a run are listed with their formats: `calls.jsonl`, working contexts, change sets, write and read traces, judgements.
  - `run.json` records the checksum of `resources/`, so that the configuration lock (D012) can be verified.
  - `configs/paths.yaml` moves to `configs/common/paths.yaml`, and `src/grace/paths.py` to `src/grace/config/paths.py`. The same PR updates every place that names the old paths: the imports in `src/grace/` and `tests/`, the "Experiment run" section, `docs/README.md`, `AGENTS.md` and `AGENTS.zh-CN.md`. The last three belong to the integration owner, who supplies or approves those edits.
- Out of scope: benchmark-specific adapters (T002), judges (T004).
- Candidate worker subtasks: none; the contract owner writes this directly.

## Acceptance

- [ ] Each of the six benchmarks in `docs/research/benchmarks.md` maps onto the records without loss of the fields the plan relies on (history unit, segment, message, timestamps, evidence IDs).
- [ ] Incremental ingestion and per-turn prediction (MultiWOZ) and end-of-history question answering (LoCoMo) are both expressible.
- [ ] Contract tests cover duplicate, missing and extra keys, shuffled order, and snapshot mismatch.
- [ ] The cost ledger defines which tokens are counted at write, plan, render and read time.
- [ ] The "Experiment run" section carries the three extensions above, with its `Version` line, fixtures and tests updated.
- [ ] The path files are at their new locations, no tracked file names the old ones, and `make test` passes.
- [ ] A test in `tests/contracts/` checks the import rules of `docs/work/plan/structure.md`. It passes while the packages do not exist yet and fails on the first forbidden import.

## Deliverables

Updated `docs/research/contracts.md`, `tests/fixtures/`, `tests/contracts/`.

## Log

- 2026-11-21: created from plan section 9, phase 1.
- 2026-11-24: scope extended by decision D013: extensions of the "Experiment run" section (upstream runs, intermediate artefacts, checksum of `resources/`) and the import-rule test.
- 2026-11-24: the user named the integration owner as owner of the "Experiment run" section; the move of `paths.yaml` and `paths.py` added to the scope.
