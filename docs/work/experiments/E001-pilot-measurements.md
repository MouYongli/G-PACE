---
id: E001
title: Pilot measurements
created: 2026-11-21
---

# E001 · Pilot measurements

## Question

On the development histories of each benchmark, how long are the histories, what does full-history reading cost, what cache ratio is achieved in practice, and how often is a rendered view read again after an invalidating update (natural update density)? Plan section 9, phase 1. If natural update density is low, view maintenance is positioned for high-revision workloads and RQ2 rests mainly on the controlled sequences, MultiWOZ and HaluMem. The MultiWOZ offer-turn census (T006) and the LoCoMo read points (T007) are separate tasks of the same phase.

## Design

Written on 2026-11-25 before the first formal run. Config: `configs/experiments/E001-pilot-measurements.yaml`; driver: `uv run python -m grace.cli.pilot` (subcommands `probe`, `plan`, `system`, `summary`); statistics: `src/grace/eval/analysis/metrics/pilot.py`.

| Item | Value |
| --- | --- |
| Benchmarks and splits | Development splits of the six benchmarks (`docs/research/benchmarks.md`): locomo `dev` (2 histories, 308 reads), longmemeval-s `dev` (98, 98), multiwoz `dev` (1,000, 7,374 state reads), halumem-medium `dev` (4, 709), memoryagentbench `dev` (9, 137), and change-seq: the T015 development smoke set (run `T015-devsmoke-20261125T023552Z`, 25 sequences, 1,145 reads of the primary schedules; template renderer, development families only), read through the change-seq adapter with an inline benchmark config because `configs/benchmarks/change-seq.yaml` is not bound yet. Native read schedule of every benchmark. No held-out data |
| Systems and baselines | T003 baselines as frozen in `configs/engines/`: full history with and without prefix caching (`full-history-cached`, `full-history`); last-k; text retrieval (`bm25`, `dense`, `rrf`); rolling summary (`summary-reuse`, `summary-rewrite`); fixed-schema slot table (`slot-table`). Answering model Qwen3-8B (`configs/models/qwen3-8b.yaml`, thinking disabled, temperature 0), embedding Qwen3-Embedding-0.6B; vLLM on GPU 0, ports 8100 and 8101, `--max-model-len 32768`, prompt-token details on |
| Runs | (1) `probe`, CPU only, no model: every history and every read's full-history answer prompt counted with the pinned tokenizer and chat template, exactly as the raw-text engine and the harness render them; gold copied into the run as files for the update-density analysis. (2) cell `full-cached`: `full-history-cached` at budget `full` on every development history, server with prefix caching (multiwoz in 8 shards). (3) cell `full-uncached`: `full-history` at budget `full` on the server restarted without prefix caching, on locomo, longmemeval-s, memoryagentbench (all), multiwoz (100 dialogues), halumem-medium (1 user), change-seq (5 sequences). (4) cell `baselines`: last-k, bm25, dense, rrf and summary-reuse at memory level 1024, prefix caching on, on locomo and memoryagentbench (all), longmemeval-s (3), multiwoz (50), halumem-medium (1), change-seq (5); cell `baselines-write` (added 2026-11-25, see Log): summary-rewrite and slot-table on the same subsample without halumem-medium and with one longmemeval-s history. Subsamples are the histories with the smallest `sha256("grace-E001:<history_id>")`, so smaller samples are contained in larger ones |
| Metrics | History length distribution (messages and tokens per history, tokens per message; percentiles 10/25/50/75/90). Full-history cost: logical input of the full-history prompt at every read (no window), the interleaved accounting of plan 8.2 (each read pays the fixed parts and the messages added since the previous read of the history), their ratio as the upper bound on prefix reuse, and the share of reads whose prompt plus output reserve exceeds the 32,768-token window; measured logical and computed tokens by ledger category from `calls.jsonl`. Measured cache ratio: cache-hit share of answer input (`cached_input_tokens / input_tokens`) per benchmark under its read protocol, and the compute ratio $c$ of cached input from a least-squares fit of call latency on new, cached and output tokens over the answer calls of the cached and uncached cells. Natural update density from the gold annotations each benchmark has: MultiWOZ (state reads after a changed or revised slot since the previous read; revisions per 1,000 messages), HaluMem (update memory points per 1,000 messages; reads citing an updated memory point), LongMemEval (knowledge-update stratum share), MemoryAgentBench (conflict-resolution share), change-seq (controlled reference: reads of a view that became answer-stale since its previous read). LoCoMo has no update annotation (left to E002). Cost record definitions: `docs/research/contracts.md#cost-ledger`; T030 owns the ledger package, E001 sums `calls.jsonl` directly |
| Window decision (T003 open question) | Decided before the first run: yes. The raw-text engine's full-history context is limited to the model window less the fixed prompt parts and the output reserve, so that an overflowing history is truncated with a disclosure instead of being rejected by the server (T003 smoke runs: 111 of 137 halumem-medium reads and the longmemeval-s read became `invalid` through HTTP 400). New engine parameter `prompt_reserve_tokens` (default 0 keeps the old behaviour); its value for `full-history`, `full-history-cached` and `last-k` follows a fixed rule from the probe run: output reserve (256, `budgets.yaml`) + the largest fixed prompt part on any development read + 64, rounded up to a multiple of 128. It is set in the three engine configs after the probe and before the first system run |
| Seeds and budget | Decoding seed 0, temperature 0. Memory levels: `full` (full-history cells), 1024 tokens (other baselines). Output reserve 256 tokens, one further retrieval per read, 3 transport attempts and 2 logical attempts per call (`configs/common/budgets.yaml`, T004) |
| Frozen before the first run | Prompts (`configs/common/prompts.yaml`), tokenizer and chat template pins, budgets and judge prompts of T004 unchanged; engine parameters of T003 unchanged except `prompt_reserve_tokens` above |
| Judging | Not run in this round. D006 has E001 judge the pilot predictions with the primary judge (DeepSeek-V4-Flash, at least two B200 GPUs, not allocated) and the secondary judge (Azure gpt-4.1-mini, paid). The `summary` step counts the judgeable predictions (answer outputs of question reads in the `full-cached` and `baselines` cells) and estimates the judge input; the judge stage waits for the user's approval of GPUs and spend |

## Acceptance

- [ ] Every number traces to a run report.
- [ ] Prompts, counters, budgets and judges are frozen (T004) before the first formal run.

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |

## Results

Not run.

## Conclusion

Pending.

## Log

- 2026-11-21: created from plan section 9, phase 1.
- 2026-11-22: research question numbering and baseline names aligned with plan v3.
- 2026-11-25: manager session `m01-E001` started on `task/E001-pilot-measurements` from `main` at `795cb9e`; Issue #69. Design written before the first formal run (above), including the decision on the T003 window question.
- 2026-11-25: probe run `E001-20261125T180821Z-b7d9` completed (code `1665757`). By the design rule it gives `prompt_reserve_tokens` 1024 (largest fixed prompt part 592 tokens, on a MultiWOZ state read), so the full-history context window is 31,744 tokens; set in `full-history`, `full-history-cached` and `last-k` before the first system run. Config fix before the first system run: vLLM 0.34 names the switch `--disable-prefix-caching` (the design text had the wrong flag name; the condition is unchanged).
- 2026-11-25: design change before any baseline run: the full-cached cell runs at about 2 to 5 s per call on the shared GPU 0, so the two baselines with one sequential model call per written message (`summary-rewrite`, `slot-table`) move to a cell `baselines-write` without halumem-medium (about 3,400 messages per user) and with one longmemeval-s history; the other five baselines keep the `baselines` subsample.
