---
id: T013
title: Write-budget estimate and break-even curves
created: 2026-11-23
---

# T013 · Write-budget estimate and break-even curves

## Goal

A paper calculation of writer tokens per history at each extraction granularity (per message, per segment, per session), compared with full-history reading with prefix caching as a function of the cache ratio c (plan section 8.4). It fixes the order of magnitude of the write budget and the starting granularity for the writer (T022).

## Scope

- In scope:
  - Recount tokens per LoCoMo history with the primary model's tokenizer.
  - Break-even reads M* as a curve over c from 0 to 1, with the measured c from E001 marked.
- Out of scope: Measured writer costs (E007).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [x] The calculation is reproducible from a committed script and config.
- [x] A go or no-go statement on token savings for LoCoMo is written down.
- [x] `make test` and `make lint` pass.

## Deliverables

Script under `src/grace/cli/`; note in the task log.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-26: manager session `m01-T013` started on `task/T013-write-budget` from `main` at `da699da`; Issue #109. No workers dispatched (one script, one config, one test file).
- 2026-11-26: method. Script `grace.cli.write_budget` (`estimate`, `measure-c`), config `configs/experiments/T013-write-budget.yaml`, tests `tests/integration/test_write_budget.py`. Writer tokens are a paper model (no GRACE writer before T022): per call a cacheable prefix (instructions, schema, vocabulary, examples; priced at c after the first call of a history), candidate context, the preceding messages, the unit's messages counted with the pinned Qwen3-8B tokenizer as the raw-text engine renders them, and output per message and per call; three scenarios (low, central, high) bracket the unknowns. Granularities: message, segments of 4, 8 and 16 messages inside a session, session. Read side priced from measured records at every c (T030's rule `input - (1 - c) * cached + output`): the cached full-history row is E001 `E001-20261125T181644Z-4e97` (warm reads), GRACE's answer call is proxied by E001's rrf at memory level 1024 (`E001-20261125T182212Z-2cd5`), U_i is one planner call per read on the pinned plan-query prompt (2,265 tokens) in the central scenario. M*(c) = ceil(W(c) / Delta(c)) of plan 8.2; c* is the smallest c at which M* is at most the history's own reads. Measured writers (E001 slot-table, summary-rewrite; T034 Graphiti) are priced the same way as reference rows.
- 2026-11-26: c. E001's fit is unreliable (shared GPU) and T030's 0.385 is an upper bound including decoding, so c was measured on an exclusive GPU: run `T013-20261126T044914Z-811f` (code `e259240`; Qwen3-8B, vLLM 0.34.0, GPU 2 reserved in `compute.yaml` and released; `nvidia-smi` showed only the server's processes before, every 20 trials and after; 140 calls with one output token, 135 in the fit). Pooled latency fit c = 0.191 (bootstrap 95% 0.179-0.204, R² 0.992); in the regime of a warm LoCoMo full-history read (24,576 cached + 128 new tokens) the median-latency ratio is 0.130. Reliability: this is an end-to-end latency ratio; it includes server-side CPU work that grows with prompt length (template, tokenisation, block hashing; a diagnostic local tokenisation of a 24,576-token prompt took 30-40 ms against 57 ms extra warm latency), so the GPU-only compute ratio is lower, plausibly 0.05-0.1, and is not separated. For billing (APIs), Azure gpt-4.1-mini's cached-input ratio is 0.25 (T034 prices).
- 2026-11-26: estimate run `T013-20261126T045532Z-268f` (code `0ed0c83`, completed; report.yaml in the run). Histories: conv-26 419 messages, 19 sessions, 23,984 tokens, 152 reads; conv-49 509, 25, 27,908, 156. Cached full history over all reads: 3.93 M / 4.98 M logical, 38 K / 49 K computed tokens. Central writer, W logical (c = 1) / computed (c = 0) per history, conv-26 and conv-49: message 1.28 M / 235 K and 1.55 M / 279 K; segment-8 242 K / 92 K and 294 K / 109 K; session 120 K / 75 K and 150 K / 90 K. Delta(c) > 0 only from c = 0.06 (conv-26) and 0.04 (conv-49): below that GRACE's read (about 1,050 uncached answer tokens plus planning) costs more than a warm full-history read (about 93-134 computed tokens), and no writer pays back. c* (payback within the history's reads), central scenario, conv-26 / conv-49: message 0.173 / 0.143; segment-4 0.093 / 0.076; segment-8 0.083 / 0.068; segment-16 0.079 / 0.064; session 0.075 / 0.061 (low scenario 0.042-0.086, high 0.109-0.86). M* at c = 0.130 (warm-read regime), central: message 211 / 172 (more than the 152 / 156 reads), segment-8 64 / 52, session 47 / 38. Total tokens over all reads at c = 0.130, GRACE central against cached full history: message -15% / -2% (GRACE costs more), segment-8 +33% / +43% saving, session +38% / +48%; at c = 0.191: message +8% / +18%, segment-8 +48% / +56%, session +53% / +60%. Measured writers at c = 0.130: slot-table M* 45 / 36, summary-rewrite 167 / 85, Graphiti 3,413 / 2,827 (about 6-7 M tokens per history; never pays back). Figure `break-even.png`, curves `curves.csv`.
- 2026-11-26: go/no-go on token savings for LoCoMo: conditional go, with batch extraction only. Per-message extraction is a no-go: it needs c above 0.14-0.17 in the central scenario and does not pay back at the measured warm-read c of 0.13; Graphiti-style multi-call per-message writers are far out (M* in the thousands). Segment (8 or more messages) and session extraction pay back within LoCoMo's own questions for c above about 0.06-0.09 (central), and the measured c (0.13-0.19, an upper bound) is above that, but the margin is small and the GPU-only compute ratio may lie near the Delta = 0 boundary (0.04-0.06), where nothing pays back. Hence the paper does not claim a single token saving on LoCoMo: it reports the curve over c with the measured c marked and states that payback on LoCoMo needs c of at least about 0.06-0.09; robust cost claims rest on settings with less prefix sharing (LongMemEval-S hit ratio 0.07, HaluMem windowed 0.79, E001) or more reads per write. The writer budget per LoCoMo history is about 120-300 K logical tokens (central, session to segment-8), or 80-135 K priced at c = 0.130, the order of magnitude of plan 8.4 (about 100 K).
- 2026-11-26: recommended starting granularity for T022: segments of 8 messages inside a session, with a fixed instruction prefix laid out for the prefix cache. It spends about 35-40% more writer tokens than session extraction (at c = 0.130: 112 K / 133 K against 81 K / 98 K) but its total saving over all reads is only about 5 points lower and its c* is close (0.068-0.083 against 0.061-0.075) while keeping units short (at most 754 tokens of messages against up to 2,045 for a session), which bounds extraction difficulty for an 8B writer and the partial-segment catch-up before a read (plan 8.4). Session extraction is the cheaper ablation-G arm; per-message extraction is kept only as a reference arm.
- 2026-11-26: acceptance. Reproducible from the committed script and config (two runs above, code_dirty false); go/no-go written above; `make test` (656 tests, 3 skipped) and `make lint` pass.
