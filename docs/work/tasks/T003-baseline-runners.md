---
id: T003
title: Baseline runners
created: 2026-11-21
---

# T003 · Baseline runners

## Goal

Runnable baselines needed by the pilot: full history with the same answering LLM, text retrieval (BM25, dense, RRF), rolling summary with recent raw text, and the fixed-schema slot table with speaker and communicative-function fields and provenance, all producing predictions and cost-ledger entries under the T001 contracts.

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
- 2026-11-25: manager session `m01-T003` started on `task/T003-baseline-runners` from `main` at `985d232`; Issue #31. No workers dispatched: the four baseline families were written in the manager worktree.
- 2026-11-25: the `ContextEngine` interface (`src/grace/context/api.py`) landed first in its own PR #35 (head `6264bd4`, merged as `23d14fb`), so that T002 and T014 can use its types.
- 2026-11-25: slot-table question settled (T027 has no manager yet; record it in the T027 Log when it starts): this task writes a standalone pilot slot table, `eval/engines/baselines/slots.py`, with no attribution guard and no bitemporality; T027 writes the slot-table representation for ablation B inside the GRACE assembly (`context/`). Code cannot be shared, because `context/` never imports `eval/` (D013 import rules); what is shared is the frozen slot inventory and function list, which live in config (`configs/engines/slot-table.yaml`) and which T027 should read from the same place.
- 2026-11-25: interpretation of the two rolling-summary variants (plan 7.2): "rewritten after every update" rewrites the whole summary whenever messages leave the recent window; "reused without rewriting" appends a summary block per `block_size` leaving messages and never revises earlier blocks.
- 2026-11-25: interim pieces to replace when their owners land: the calls.jsonl writer (`harness/ledger.py`) by `llm/records.py` (T004); the fake-only backend by `llm/client.py` (T004); placeholder prompts (summary, slot extraction, answer) by `resources/prompts/` through `llm/prompts.py` (T004); the record loader (`harness/inputs.py`, fixture and `dev*` splits only) by `eval/datasets/benchmarks/splits.py` (T002). `context/memory/index/` holds only message chunking, BM25 and exact cosine for the retrieval baselines; T025 owns the package.
- 2026-11-25: acceptance on fixtures: all nine engine configs run end to end on all six fixture benchmarks at full and 24-token budgets, and on the LoCoMo streaming schedule with further retrieval; run.json, predictions and calls.jsonl pass the contract checks; the gold-sentinel test passes with a positive control. Runs on one development history per benchmark are not done: they need T002's converted records and T004's model client (known gap in the task PR).
