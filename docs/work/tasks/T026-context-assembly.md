---
id: T026
title: Evidence-demand assembly
created: 2026-11-23
---

# T026 · Evidence-demand assembly

## Goal

The assembler of plan section 5.5: list the variables a read must fill, filter candidates by version, valid time, scope and attribution, select greedily by new coverage per token, expand a summary or issue one more bounded query when variables stay open, and serialise the fixed working-context layout.

## Scope

- In scope:
  - Budgets of 256, 512 and 1,024 tokens and the full history.
  - Rank truncation as the comparison mode.
  - Output contract of the answering LLM: answer, state, one extra retrieval, or unknown.
- Out of scope: Baseline systems (T027).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] The assembled context never exceeds the budget; token counts match the ledger.
- [ ] Every answer of the answering LLM records the evidence IDs shown.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` assembly package.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-28: worker w01-T026 started on `task/T026-context-assembly` (Issue #138).
- 2026-11-28: implemented `src/grace/context/pipeline/assembly/` (`items`, `demand`, `filter`, `select`, `expand`, `layout`, `assemble`) and `configs/assembly/default.yaml` (greedy) and `truncate.yaml` (rank truncation). The package imports only `context/api.py` and `memory/history/`; the engine hands retrieval candidates, query answers, views and summaries in as `Item`s and runs a pending query expansion itself. Task and output contract stay in the shared answer prompt, outside the memory budget; the context text carries recent messages, verified state, evidence and open items. Variable support is program coverage plus a lexical rule; the verification call of plan 5.6 is not implemented. `context/engine.py` (GraceEngine) does not exist yet and is not part of this task.
- 2026-11-28: tests `tests/unit/test_assembly.py` (budget and ledger checks over 15 random pools x 3 budgets x 2 configurations x 2 counters, plus the pinned Qwen3-8B tokenizer; filter reasons; greedy, two-hop groups and truncation; summary and query expansion; layout) and `tests/integration/test_assembly_answer.py` (a BM25 -> assembler read path driven by the shared answering step at 256, 512, 1,024 and full: evidence IDs shown are recorded per answer; one further retrieval).
