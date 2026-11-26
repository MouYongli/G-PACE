---
id: T007
title: LoCoMo evidence-anchored read points
created: 2026-11-22
---

# T007 · LoCoMo evidence-anchored read points

## Goal

Decide whether the evidence-anchored streaming protocol for LoCoMo (plan section 6.5) produces enough interleaving of reads and writes to test maintenance cost on natural data. For each question compute $v(q)$, the end of the session containing its latest annotated evidence turn, and describe how read points spread over each history.

## Scope

- In scope: LoCoMo categories 1 to 4; per-question $v(q)$; distribution of $v(q)$ relative to history length; the share of questions with $v(q)$ before the final session; messages and tokens written between adjacent read points; exclusion lists (13 questions with missing or unresolvable evidence; questions on the independent audit's evidence-error list); a proposed promotion threshold computed on the development histories (conv-26, conv-49) only.
- Out of scope: any LLM run; re-annotating answers; held-out histories when setting the threshold.
- Candidate worker subtasks: one worker for the script and report.
- Dependency note: the data is downloaded with T010 (`scripts/data/b2_locomo.sh`); only the LoCoMo adapter of T002 is needed besides.

## Acceptance

- [x] Read-point list ($v(q)$ per question) and summary statistics recorded in a run directory with code SHA, data checksum and command.
- [x] Exclusions listed with reasons and counts.
- [x] A threshold for promoting streaming to the main text, set on development histories and stated before held-out statistics are inspected.

## Deliverables

Bash entry point under `scripts/` calling Python under `src/grace/cli/`, the read-point list as a config under `configs/benchmarks/`, a short report linked from this file.

- Report: [`docs/research/locomo-read-points.md`](../../research/locomo-read-points.md)
- Read-point list and threshold: `configs/benchmarks/read-points/locomo.yaml`
- Entry point: `scripts/locomo_read_points.sh` → `src/grace/cli/data/locomo_read_points.py`; logic in `src/grace/eval/datasets/benchmarks/locomo_read_points.py`; tests in `tests/unit/test_locomo_read_points.py`

## Log

- 2026-11-22: created from plan section 9, phase 1 (registered by T005).
- 2026-11-22: paths and dependencies updated after T009 (package `grace`) and T010 (downloads) were merged.
- 2026-11-25: manager session `m01-T007` started on `task/T007-locomo-read-points` from `9fdde49b5022e5cef0bae94e68073444b1702d15`; Issue #48.
- 2026-11-25: dev stage run at code `9b6f0453ab801e928afcb5624201a8c8ee599b1f` (`$PROJECT_ROOT/runs/T007/artifacts/read-points-dev-20261125T005427Z`): 308 questions, 6 excluded (evidence missing 2, unresolved 4), 13 reported separately (audit `WRONG_CITATION`), 289 streaming; share with $v(q)<N$ 0.969; 19 and 25 distinct read points (every session end is a read point); gaps between adjacent read points median 19.5 messages, 613.5 Qwen3-8B tokens (min 405).
- 2026-11-25: promotion threshold fixed from the development histories only, before any held-out statistic was computed (`configs/benchmarks/read-points/locomo.yaml#promotion_threshold`). Streaming enters the main text if, on held-out streaming questions, all hold: pooled share with $v(q)<N$ ≥ 0.5; median distinct read points per history (N included) ≥ 5; median tokens between adjacent read points ≥ 256. Rationale in the config: majority reading of "substantial share"; several read-invalidate-read cycles per view; new text per gap at least the smallest answer memory budget (256 tokens). Values set by principle, not fitted to the dev values.
- 2026-11-25: all stage run at code `d77ab6344eb6c3ccf7e1d229be209efad8a64ee1` (`$PROJECT_ROOT/runs/T007/artifacts/read-points-all-20261125T005549Z`), held-out annotations read with `--held-out-annotation-only` (counting only, no system run). 1,540 questions: 13 excluded (evidence missing 4, unresolved 9), 53 reported separately (audit `WRONG_CITATION`; 4 more are among the 13), 1,474 streaming; 99 audit answer errors carried as a label. Held-out: share with $v(q)<N$ 0.968, median 29.5 distinct read points per history, median 579 tokens between adjacent read points. All three threshold criteria hold: streaming qualifies for the main text. Dev numbers reproduced exactly. Report: `docs/research/locomo-read-points.md`.
- 2026-11-25: acceptance: read-point list and statistics with code SHA, data checksum and command in the run directories (met); exclusions with reasons and counts (met); threshold set on dev and committed in `d77ab63` before held-out statistics (met). `make test` and `make lint` green. Status for plan.yaml: `T007: active -> review`.
- 2026-11-25: PR #51 reviewed and merged; acceptance met.
