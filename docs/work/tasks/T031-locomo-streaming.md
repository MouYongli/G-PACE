---
id: T031
title: LoCoMo streaming harness
created: 2026-11-23
---

# T031 · LoCoMo streaming harness

## Goal

The evidence-anchored streaming protocol of plan section 6.5: each question is asked at v(q) and again at N, writing continues after every read, and ephemeral products are discarded after each question.

## Scope

- In scope:
  - Read-point list from T007; the 13 questions with missing evidence are excluded.
  - Consistency between the two answers is scored against the same gold.
- Out of scope: Deciding whether streaming goes into the main text (D007).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Two question orders give the same index version and evidence input for each question.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` evaluation package.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-28: implemented (w01-T031, PR to main). The LoCoMo adapter emits `read_tasks.streaming.jsonl` from the committed T007 list (`configs/benchmarks/locomo.yaml` adapter option `streaming_read_points`); read points are recomputed from the records and must equal the list, else loading fails. Dev: 595 reads of 302 questions (308 minus the 6 dev questions T007 excludes), identical to the T007 dev artefact. The shared harness runs it (`drive --schedule streaming`); new flags `--task`, `--read-order reversed`, `--state-probe` (fails the run if answering or `end_read` changes engine state; per-read version, state and evidence digests in `run.log`). `grace.cli.streaming consistency` scores the v(q) and N answers of a run against the same gold (official LoCoMo F1, answer change, separately for the audit's evidence-error questions); unregistered analysis, not a `score` run.
- 2026-11-28: acceptance test `tests/integration/test_locomo_streaming.py`: two read orders give the same engine version, index state (saved state without event logs) and evidence input for every read, for bm25, rrf, full-history, summary-rewrite and default GRACE on the fixture, and for GRACE with a scripted writer and planner (claim graph, views, flush inside the first read). GRACE's `view_events.jsonl` records the triggering read and timings, so it is left out of the cross-order fingerprint.
- 2026-11-28: smoke (not formal runs) on LoCoMo dev conv-26, questions q0, q1 (audit evidence error), q2, q7, q15 at v(q) and N = 419, budget 1,024, shared Qwen3-8B and Qwen3-Embedding-0.6B, code 9481eb1: rrf `T031-20261128T013353Z-9cf1` and default GRACE `T031-20261128T013409Z-fdf8` in `runs/T031/artifacts/w01-T031/T031/`; 10 reads each, both completed, state unchanged after `end_read` on all 10 reads; consistency outputs in `runs/T031/artifacts/w01-T031/consistency-<run-id>/`. GRACE made 61 writer calls, all triggered by writes; none fell inside a read in this smoke.
- 2026-11-28: open: change sets and stale marks committed by a flush inside `read` are not in `changesets.jsonl` or `traces/write.jsonl`, and there is no end-of-history hook (T026 log); streaming write-cost and over-marking counts depend on that fix. Registering the consistency metric in `configs/common/scorers.yaml` needs the contract owner and the user.
