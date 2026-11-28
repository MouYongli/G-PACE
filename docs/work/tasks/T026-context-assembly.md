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
- 2026-11-28: smoke (not a formal run) `T026-smoke-20261128T002210Z-b2d1` at 0faba89, in `runs/T026/artifacts/w01-T026/`: BM25 -> assembler -> shared answer prompt on Qwen3-8B, LoCoMo dev conv-26, first 8 questions, budgets 256/512/1,024/full x default/truncate (64 reads, 64 answer calls). No context over budget, no token-count mismatch, no citation outside the shown evidence. Without planner variables the demand is the single `answer` variable, so greedy and truncation chose the same contexts in most reads; the comparison needs the planner's variables (engine). An earlier smoke `T026-smoke-20261128T002110Z-a358` showed contexts without dates for LoCoMo (messages carry only segment times); fixed in 0faba89.
- 2026-11-28: review of PR #146 at f5fbe64 (s00-super, independent reviewer). Fixes: a summary is expanded only when its raw text fits the room left and the result leaves strictly fewer variables open, otherwise the summary is kept and no expansion is spent; expanded messages get lexical coverage only; `answer_items` requires `version_of`, `stamp_of` and `retired_of`, fails on unknown evidence messages or entries, stamps the maximum of witness and evidence versions and carries `retired`; valid-time values must be ISO 8601; expanded message IDs are deduplicated; a two-hop group with a dropped member is dropped whole (reason `group`).
- 2026-11-28: decisions of s00-super recorded. (3) Rank truncation runs under the same conditions as greedy except the selection rule: same rank-order fill (skip what does not fit or adds no new message, keep filling), no assembler expansion, the same answering-LLM `retrieve` option; each assembly record carries `utilisation` (tokens / budget) and `expansions_used`. (4) One extra retrieval per read in total: the assembler's query expansion and the LLM's `retrieve` share one counter (`retrieval_used`); a query expansion counts as the read's retrieval; no query is proposed for a variable that is open only because a supporting candidate did not fit. Chosen option: at a read whose retrieval the assembler used, the LLM's `retrieve` output is resolved as `unknown` (keeps the pinned answer prompt identical for every system); enforcing it needs the engine to expose `retrieval_used` in the read trace and the answer parser in `eval/runner/harness/answer.py` to honour it, planned with the engine PR. (8) `support_threshold` and the new `support_stem` are marked as unfrozen placeholders in `configs/assembly/`. Scope extension: T026 also owns `src/grace/context/engine.py` (GraceEngine), in a second PR on `task/T026-engine` after #146 is merged; T026 stays active until then. `structure.md` and `structure_full.md` list `items.py` and `assemble.py` (edit allowed by s00-super).
- 2026-11-28: PR #146 merged (main f330a2b). Engine PR started on `task/T026-engine` (scope extension by s00-super).
- 2026-11-28: `src/grace/context/engine.py` (GraceEngine): write = updater (log append, extraction, commit) -> text indexes -> views (staleness strategy, materialisation); read = flush -> planner and query -> view checks and hits -> retrieval (BM25, dense, graph) -> assembly, with one restricted query for a pending expansion. Components are injected (`Components`; `NoViews` is the empty view component); `configs/engines/grace.yaml` names the component configs; the harness builds it through the new `config/registry.py` (lazy import path, so `runner/harness/` still imports only `api.py`), with a three-line fallback in `eval/runner/harness/drive.py`. `current_only` is False for a query with `AT known=r0 < version` or historical state (review follow-up c). Assembler follow-ups: a rejected summary falls back to the query for unsupported variables; valid times must be ISO extended dates or date-times.
- 2026-11-28: one retrieval per read end to end: `ReadTrace` gains `retrieval_used`, `utilisation`, `expansions_used` (contracts.md "Experiment run" 0.2.1, approved by the integration owner); `eval/runner/harness/answer.py` resolves a `retrieve` output as `unknown` when `retrieval_used` is set (`Answered.retrieve_refused`, prediction metadata `retrieve_refused`).
- 2026-11-28: smoke (not a formal run) `T026-smoke-20261128T005319Z-15ad` at b69a1e8 in `runs/T026/artifacts/w01-T026/`: default GRACE on LoCoMo dev conv-26, first 120 messages written (18 writer calls; 115 claims, 250 attributions, 62 resident views), first 8 questions at version 120 x budgets 256 / 1,024 / full, Qwen3-8B and Qwen3-Embedding-0.6B shared servers. 24 reads: trace fields present in all, none over budget, none with two extra retrievals (2 reads used the assembler's query expansion, 1 `retrieve` output was refused as unknown, no further retrieval was served), 0 view hits; 26 planner calls needed 20 repairs. Known open issue: when one write commits several versions (segment extraction), `WriteResult` carries only the latest change set; all change sets are in the engine snapshot (`store/changesets.jsonl`).
- 2026-11-28: review of PR #151 (s00-super, merge with follow-ups). Fixed: `GraceEngine.from_port` fails without the run's chat client unless `allow_no_client` is set (the harness sets it only for the fake backend and records it under `engine_settings` in the resolved config); `EngineLLMModel` exposes `client`, `decoding` and `observe`; the engine's writer, planner and LLM-rendering calls go through `ObservedClient`, so the gold-sentinel audit (`observed`) sees their prompts; the run seed is put into the writer, planner and rendering decodings, which the resolved config records (`engine_settings`); call IDs are no longer duplicated after a further retrieval. New scripted-writer and scripted-planner tests cover flush before a read, a pending unit, a view hit, a vocabulary change, `answer_items` stamping and retirement, a time-travel read keeping the retired answer, and save/restore with a graph and views.
- 2026-11-28: OPEN (blocks staleness runs and W accounting; contract change, the user's approval needed, handled by s00-super): (1) change sets and stale marks committed by a flush inside `read` are not reported in any write trace, and `WriteResult` carries only the last change set when one write commits several versions; (6) there is no end-of-history hook, so a unit still open at the last message is extracted only by a later read (or never, under end-of-history reading).
