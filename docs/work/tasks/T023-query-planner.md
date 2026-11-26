---
id: T023
title: Query planner
created: 2026-11-23
---

# T023 · Query planner

## Goal

The planner of plan sections 5.3 and 5.6: rule templates map a task to the IR without an LLM call where they can; otherwise the planner LLM emits the IR, the variables to fill and fallback channels; parse or type failures fall back to text retrieval.

## Scope

- In scope:
  - At most one compile repair per read.
  - Relative time is converted to absolute intervals and never stored as a view.
- Out of scope: Retrieval and fusion (T025).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] On the annotated development subset, attribution, time filter and execution result of the IR are checked.
- [ ] Parse-failure and fallback rates are logged.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` planner package; planner prompt registered with T004.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session m01-T023 started on `task/T023-query-planner` (base `795cb9e`, rebased onto `313c5ac`); Issue #67. No workers: the manager wrote the code.
- 2026-11-25: planner implemented under `src/grace/context/pipeline/query/` (new files `rules.py`, `timeexpr.py`, `planner.py`; T017 files unchanged): rule templates (count, list, current) without an LLM call; planner LLM (prompt `plan-query`) emitting IR, variables to fill, fallback channels, time window and anchor; parse, type, vocabulary and time checks; at most one compile repair (prompt `plan-query-repair`); fallback to text retrieval (`bm25`, `dense`; channels are T025's). Relative time is resolved to absolute `start(?c)` windows at planning time and marks the query temporary (`Plan.view_eligible` false). Config `configs/common/planner.yaml`.
- 2026-11-25: annotated development subset `docs/research/annotations/planner-dev/` (99 cases: 89 change-seq dev-smoke questions with generator gold, 10 LoCoMo conv-26/conv-49 questions on a hand-built partial graph). Annotator: agent session m01-T023, not a human annotator. The annotated IR reproduces every gold answer on the endorsement-filtered graph; 26 cases are wrong on the unfiltered graph only because of gap F1 (query-ir.md 7.2: `[u, f]` cannot require own / positive / not derived).
- 2026-11-25: development check with Qwen3-8B (GPU 2, port 8104), run `T023-20261125T182048Z-bc05` at `8d2202e` (prompt iterated on this subset in three earlier runs, so these are development numbers, not an unbiased estimate): routes rule 31 / llm 64 / fallback 4 of 99; parse-failure rate 0.059, type 0.015, time 0.029 of 68 LLM-planned reads; repair rate 0.103, repair success 0.43; fallback rate 0.040. Checks over all 99: attribution 0.94, time 0.92, execution 0.67 (0.89 on the F1-filtered graph). LoCoMo time-window questions (4) all fell back on parse errors. Rules-only run: `T023-20261125T182149Z-9f31`.
- 2026-11-27: follow-up recorded by the integration owner (user decision, T014 log of the same date): at the planner's next change, entity names come from the graph through `display_name()` (contract "Claim graph" v0.3) instead of the T025 recall probe.
