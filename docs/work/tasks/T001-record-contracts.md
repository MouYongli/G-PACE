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
- Out of scope: benchmark-specific adapters (T002), judges (T004).
- Candidate worker subtasks: none; the contract owner writes this directly.

## Acceptance

- [ ] Each of the six benchmarks in `docs/research/benchmarks.md` maps onto the records without loss of the fields the plan relies on (history unit, segment, message, timestamps, evidence IDs).
- [ ] Incremental ingestion and per-turn prediction (MultiWOZ) and end-of-history question answering (LoCoMo) are both expressible.
- [ ] Contract tests cover duplicate, missing and extra keys, shuffled order, and snapshot mismatch.
- [ ] The cost ledger defines which tokens are counted at write, plan, render and read time.

## Deliverables

Updated `docs/research/contracts.md`, `tests/fixtures/`, `tests/contracts/`.

## Log

- 2026-11-21: created from plan section 9, phase 1.
