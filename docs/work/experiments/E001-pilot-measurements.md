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

- [x] Every number traces to a run report: 60 runs (1 probe, 59 system), each with `report.yaml`; aggregation in `E001-summary/summary-20261125T1940Z/summary.json` with the checksum of every input `run.json`.
- [x] Prompts, counters, budgets and judges are frozen (T004) before the first formal run (unchanged; only the engine parameter `prompt_reserve_tokens` was added, by the rule written into the design before the probe).
- [ ] Judging of the pilot predictions with the primary and the secondary judge (D006): not run, waits for the user's approval of GPUs and Azure spend (see Results, "Judging").

## Runs

Reports are under `$PROJECT_ROOT/runs/E001/artifacts/manager/E001/<run-id>/report.yaml`; the cell is in brackets. Code SHAs are full in each `run.json`: `1665757` probe; `d3cab7b` full-cached, baselines, baselines-write; `a532b68` full-uncached.

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| `E001-20261125T180821Z-b7d9` | 2026-11-25 | completed | `1665757` | `runs/E001/artifacts/manager/E001/E001-20261125T180821Z-b7d9/report.yaml` (probe) |
| `E001-20261125T181643Z-4db0` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181643Z-4db0/report.yaml` (full-cached) |
| `E001-20261125T181644Z-4e97` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181644Z-4e97/report.yaml` (full-cached) |
| `E001-20261125T181646Z-27cf` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181646Z-27cf/report.yaml` (full-cached) |
| `E001-20261125T181646Z-d959` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181646Z-d959/report.yaml` (full-cached) |
| `E001-20261125T181652Z-53b7` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181652Z-53b7/report.yaml` (full-cached) |
| `E001-20261125T181657Z-2b1c` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181657Z-2b1c/report.yaml` (full-cached) |
| `E001-20261125T181657Z-45aa` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181657Z-45aa/report.yaml` (full-cached) |
| `E001-20261125T181657Z-5b39` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181657Z-5b39/report.yaml` (full-cached) |
| `E001-20261125T181657Z-6b52` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181657Z-6b52/report.yaml` (full-cached) |
| `E001-20261125T181657Z-6eac` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181657Z-6eac/report.yaml` (full-cached) |
| `E001-20261125T181657Z-8977` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181657Z-8977/report.yaml` (full-cached) |
| `E001-20261125T181657Z-fb84` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181657Z-fb84/report.yaml` (full-cached) |
| `E001-20261125T181658Z-5ddb` | 2026-11-25 | completed | `d3cab7b` | `runs/E001/artifacts/manager/E001/E001-20261125T181658Z-5ddb/report.yaml` (full-cached) |
| `E001-20261125T184148Z-74ee` | 2026-11-25 | completed | `a532b68` | `runs/E001/artifacts/manager/E001/E001-20261125T184148Z-74ee/report.yaml` (full-uncached) |
| `E001-20261125T184149Z-d01c` | 2026-11-25 | completed | `a532b68` | `runs/E001/artifacts/manager/E001/E001-20261125T184149Z-d01c/report.yaml` (full-uncached) |
| `E001-20261125T184150Z-d6a1` | 2026-11-25 | completed | `a532b68` | `runs/E001/artifacts/manager/E001/E001-20261125T184150Z-d6a1/report.yaml` (full-uncached) |
| `E001-20261125T184150Z-ed78` | 2026-11-25 | completed | `a532b68` | `runs/E001/artifacts/manager/E001/E001-20261125T184150Z-ed78/report.yaml` (full-uncached) |
| `E001-20261125T184156Z-4848` | 2026-11-25 | completed | `a532b68` | `runs/E001/artifacts/manager/E001/E001-20261125T184156Z-4848/report.yaml` (full-uncached) |
| `E001-20261125T184201Z-0c91` | 2026-11-25 | completed | `a532b68` | `runs/E001/artifacts/manager/E001/E001-20261125T184201Z-0c91/report.yaml` (full-uncached) |
| `E001-20261125T182211Z-238f` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182211Z-238f/report.yaml` (baselines) |
| `E001-20261125T182212Z-2cd5` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182212Z-2cd5/report.yaml` (baselines) |
| `E001-20261125T182212Z-9709` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182212Z-9709/report.yaml` (baselines) |
| `E001-20261125T182212Z-f6b5` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182212Z-f6b5/report.yaml` (baselines) |
| `E001-20261125T182213Z-25aa` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182213Z-25aa/report.yaml` (baselines) |
| `E001-20261125T182213Z-516a` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182213Z-516a/report.yaml` (baselines) |
| `E001-20261125T182213Z-5232` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182213Z-5232/report.yaml` (baselines) |
| `E001-20261125T182213Z-9d59` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182213Z-9d59/report.yaml` (baselines) |
| `E001-20261125T182213Z-b40d` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182213Z-b40d/report.yaml` (baselines) |
| `E001-20261125T182213Z-d6b4` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182213Z-d6b4/report.yaml` (baselines) |
| `E001-20261125T182214Z-19a7` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182214Z-19a7/report.yaml` (baselines) |
| `E001-20261125T182214Z-430f` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182214Z-430f/report.yaml` (baselines) |
| `E001-20261125T182214Z-4916` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182214Z-4916/report.yaml` (baselines) |
| `E001-20261125T182214Z-7a57` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182214Z-7a57/report.yaml` (baselines) |
| `E001-20261125T182214Z-abfd` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182214Z-abfd/report.yaml` (baselines) |
| `E001-20261125T182214Z-afa8` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182214Z-afa8/report.yaml` (baselines) |
| `E001-20261125T182214Z-d52c` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182214Z-d52c/report.yaml` (baselines) |
| `E001-20261125T182214Z-d8ea` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182214Z-d8ea/report.yaml` (baselines) |
| `E001-20261125T182215Z-19d5` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182215Z-19d5/report.yaml` (baselines) |
| `E001-20261125T182215Z-86ed` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182215Z-86ed/report.yaml` (baselines) |
| `E001-20261125T182220Z-25d1` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182220Z-25d1/report.yaml` (baselines) |
| `E001-20261125T182220Z-e5f7` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182220Z-e5f7/report.yaml` (baselines) |
| `E001-20261125T182221Z-37da` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182221Z-37da/report.yaml` (baselines) |
| `E001-20261125T182221Z-b860` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182221Z-b860/report.yaml` (baselines) |
| `E001-20261125T182221Z-f25e` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182221Z-f25e/report.yaml` (baselines) |
| `E001-20261125T182226Z-4e10` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182226Z-4e10/report.yaml` (baselines) |
| `E001-20261125T182226Z-76c0` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182226Z-76c0/report.yaml` (baselines) |
| `E001-20261125T182227Z-3ccc` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182227Z-3ccc/report.yaml` (baselines) |
| `E001-20261125T182227Z-3ff9` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182227Z-3ff9/report.yaml` (baselines) |
| `E001-20261125T182227Z-c083` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182227Z-c083/report.yaml` (baselines) |
| `E001-20261125T182206Z-a115` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182206Z-a115/report.yaml` (baselines-write) |
| `E001-20261125T182206Z-c9b2` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182206Z-c9b2/report.yaml` (baselines-write) |
| `E001-20261125T182206Z-e613` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182206Z-e613/report.yaml` (baselines-write) |
| `E001-20261125T182207Z-6a24` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182207Z-6a24/report.yaml` (baselines-write) |
| `E001-20261125T182208Z-552c` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182208Z-552c/report.yaml` (baselines-write) |
| `E001-20261125T182208Z-9539` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182208Z-9539/report.yaml` (baselines-write) |
| `E001-20261125T182215Z-1826` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182215Z-1826/report.yaml` (baselines-write) |
| `E001-20261125T182216Z-feaf` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182216Z-feaf/report.yaml` (baselines-write) |
| `E001-20261125T182221Z-5590` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182221Z-5590/report.yaml` (baselines-write) |
| `E001-20261125T182221Z-6ce5` | 2026-11-25 | completed | `1414833` | `runs/E001/artifacts/manager/E001/E001-20261125T182221Z-6ce5/report.yaml` (baselines-write) |

## Results

All numbers come from `completed` runs; every row names its run or the summary that aggregates them. Aggregation: `runs/E001/artifacts/manager/E001-summary/summary-20261125T1940Z/summary.json` (code `1b04dc8`, inputs: the probe run and all 59 system runs, each with its `run.json` checksum). Probe numbers: `E001-20261125T180821Z-b7d9/pilot-probe.json`. Tokens are counted with the pinned Qwen3-8B tokenizer and chat template. No answer is scored yet (judging not run), so nothing here is a quality claim.

### History lengths and full-history cost (probe `E001-20261125T180821Z-b7d9`)

"Full-history input" is the answer prompt with the whole visible history at every read, without a window. "Interleaved accounting" is plan 8.2: each read pays its fixed prompt parts and the messages added since the previous read of the same history. "Prefix-reuse bound" is one minus their ratio.

| Benchmark | Histories | Messages p50 (min–max) | Tokens per history p50 (min–max) | Reads | Full-history input, all reads | Interleaved accounting (8.2) | Prefix-reuse bound | Reads over 32,768 window |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| locomo | 2 | 464 (419–509) | 25,946 (23,985–27,908) | 308 | 8,150,114 | 202,639 | 0.975 | 0 (0.000) |
| longmemeval-s | 98 | 493 (396–616) | 120,927 (117,606–125,387) | 98 | 11,894,777 | 11,894,777 | 0.000 | 98 (1.000) |
| multiwoz | 1000 | 14 (4–34) | 356 (81–864) | 7374 | 5,779,304 | 4,693,720 | 0.188 | 0 (0.000) |
| halumem-medium | 4 | 3,420 (2,658–3,482) | 292,486 (233,895–301,165) | 709 | 99,833,205 | 1,475,846 | 0.985 | 611 (0.862) |
| memoryagentbench | 9 | 111 (23–116) | 333,476 (7,079–365,515) | 137 | 21,347,753 | 1,873,021 | 0.912 | 97 (0.708) |
| change-seq | 25 | 200 (200–200) | 5,665 (5,492–6,192) | 1145 | 4,373,939 | 701,333 | 0.840 | 0 (0.000) |

- Only LoCoMo, MultiWOZ and the change-seq smoke set fit Qwen3-8B's 32,768-token window. Every LongMemEval-S history (p50 120,927 tokens), every HaluMem-Medium user (p50 292,486) and 7 of 9 MemoryAgentBench contexts (p50 333,476) exceed it, so the full-history baseline on Qwen3-8B reads a truncated, disclosed window there (611 of 709 HaluMem reads, all 98 LongMemEval-S reads, 97 of 137 MemoryAgentBench reads).
- The largest fixed prompt part (system message, request, chat template) is 592 tokens (a MultiWOZ state read with its 30 slot names); hence `prompt_reserve_tokens` 1024 and a full-history context window of 31,744 tokens.

### Measured cache ratio and cost (full-history cells, answer calls)

`full-cached`: server with prefix caching; `full-uncached`: server with `--disable-prefix-caching`. Hit ratio = server-reported `cached_input_tokens / input_tokens`; computed tokens = input − cached + output. No uncached run reported a cached token (`apc_off_runs_with_cached_tokens: []`). No full-history call failed: with the 1,024-token reserve, no prompt was rejected by the server (T003's smoke runs lost 111 of 137 HaluMem reads and the LongMemEval-S read to HTTP 400).

| Benchmark | Cell | Runs | Reads | Outputs | Input tokens | Cached | Hit ratio | Computed tokens | Failed calls |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| locomo | full-cached (completed) | `E001-20261125T181644Z-4e97` | 308 | answer 259, invalid 22, unknown 27 | 8,885,744 | 8,821,184 | 0.993 | 87,308 | 0 |
| locomo | full-uncached (completed) | `E001-20261125T184148Z-74ee` | 308 | answer 263, invalid 18, unknown 27 | 8,800,501 | 0 | 0.000 | 8,822,503 | 0 |
| longmemeval-s | full-cached (completed) | `E001-20261125T181652Z-53b7` | 98 | answer 15, invalid 5, unknown 78 | 3,338,591 | 235,840 | 0.071 | 3,105,482 | 0 |
| longmemeval-s | full-uncached (completed) | `E001-20261125T184156Z-4848` | 98 | answer 15, invalid 5, unknown 78 | 3,338,591 | 0 | 0.000 | 3,341,559 | 0 |
| multiwoz | full-cached (completed) | 8 shards | 7374 | invalid 39, state 7335 | 5,824,875 | 4,220,416 | 0.725 | 2,309,803 | 0 |
| multiwoz | full-uncached (completed) | `E001-20261125T184201Z-0c91` | 761 | invalid 4, state 757 | 604,780 | 0 | 0.000 | 677,531 | 0 |
| halumem-medium | full-cached (completed) | `E001-20261125T181646Z-27cf` | 709 | answer 344, invalid 66, unknown 299 | 23,635,025 | 18,698,816 | 0.791 | 4,995,210 | 0 |
| halumem-medium | full-uncached (completed) | `E001-20261125T184150Z-ed78` | 178 | answer 89, invalid 20, unknown 69 | 6,152,447 | 0 | 0.000 | 6,167,810 | 0 |
| memoryagentbench | full-cached (completed) | `E001-20261125T181643Z-4db0` | 137 | answer 67, invalid 17, unknown 53 | 4,296,337 | 4,088,960 | 0.952 | 214,930 | 0 |
| memoryagentbench | full-uncached (completed) | `E001-20261125T184149Z-d01c` | 137 | answer 67, invalid 17, unknown 53 | 4,313,033 | 0 | 0.000 | 4,320,205 | 0 |
| change-seq | full-cached (completed) | `E001-20261125T181646Z-d959` | 1145 | answer 678, invalid 26, unknown 441 | 4,545,392 | 4,332,928 | 0.953 | 265,220 | 0 |
| change-seq | full-uncached (completed) | `E001-20261125T184150Z-d6a1` | 301 | answer 176, invalid 10, unknown 115 | 1,221,995 | 0 | 0.000 | 1,236,940 | 0 |

- Under end-of-history reading with many questions per history (LoCoMo 0.993, MemoryAgentBench 0.952) and under the interleaved change-seq schedule (0.953) almost all input is a cache hit; with prefix caching LoCoMo costs 87,308 computed tokens for 308 reads against 8,822,503 without (about 1 %). The measured hit ratio exceeds the probe's prefix-reuse bound wherever the fixed system message dominates (MultiWOZ 0.725 against 0.188): the bound charges the fixed parts at full price, the server caches the system message too.
- One read per history (LongMemEval-S) caches only the system message: 0.071.
- A sliding window breaks prefix reuse: on HaluMem, where 86 % of reads truncate the oldest messages, the hit ratio is 0.791 (reads of the same session share a prefix), against the unwindowed bound of 0.985.
- Compute ratio $c$ of cached input (latency fit `latency = a + b_new·new + b_cached·cached + b_out·output` over answer calls of both cells): pooled $c$ = 0.081 (11,886 calls, R² 0.475); per benchmark the fit is unstable (negative coefficients on change-seq, HaluMem, MemoryAgentBench; 0.80 on LoCoMo; none on LongMemEval-S). Latency is dominated by decoding and by load: GPU 0 ran another user's job at about 100 % utilisation and up to 50 E001 runs shared the server. $c$ is therefore **not measured reliably** by E001; the token-level hit ratio above is. For reference, T030 measured LoCoMo conv-26 on its own server (runs `T030-20261125T175342Z-756d`, cached, mean answer latency 378 ms; `T030-20261125T180458Z-d447`, uncached, 812 ms).

### Other baselines at memory level 1024 (`baselines`, `baselines-write`)

Logical tokens by ledger category (A = answering, W = write-side summary or extraction calls); outputs are counts of predictions, not scores.

| Benchmark | Engine | Status | Reads | Outputs | A logical | A hit ratio | W logical | Embedding |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| locomo | bm25 | completed | 308 | answer 225, unknown 83 | 463,756 | 0.306 | – | – |
| locomo | dense | completed | 308 | answer 264, unknown 44 | 465,056 | 0.315 | – | 40,751 |
| locomo | last-k | completed | 308 | answer 33, unknown 275 | 464,526 | 0.962 | – | – |
| locomo | rrf | completed | 308 | answer 264, unknown 44 | 464,854 | 0.310 | – | 40,751 |
| locomo | summary-reuse | completed | 308 | answer 102, invalid 3, unknown 203 | 473,304 | 0.962 | 95,378 | – |
| locomo | slot-table | completed | 308 | answer 22, invalid 1, unknown 285 | 458,762 | 0.954 | 531,021 | – |
| locomo | summary-rewrite | completed | 308 | answer 24, unknown 284 | 385,817 | 0.952 | 813,867 | – |
| longmemeval-s | bm25 | completed | 3 | answer 3 | 4,577 | 0.287 | – | – |
| longmemeval-s | dense | completed | 3 | answer 3 | 4,598 | 0.257 | – | 318,841 |
| longmemeval-s | last-k | completed | 3 | answer 1, unknown 2 | 4,529 | 0.258 | – | – |
| longmemeval-s | rrf | completed | 3 | answer 2, unknown 1 | 4,622 | 0.339 | – | 318,841 |
| longmemeval-s | summary-reuse | completed | 3 | unknown 3 | 4,540 | 0.299 | 446,867 | – |
| longmemeval-s | slot-table | completed | 1 | answer 1 | 1,520 | 0.258 | 456,555 | – |
| longmemeval-s | summary-rewrite | completed | 1 | unknown 1 | 1,500 | 0.301 | 598,079 | – |
| multiwoz | bm25 | completed | 397 | invalid 4, state 393 | 332,901 | 0.631 | – | – |
| multiwoz | dense | completed | 397 | invalid 2, state 395 | 355,234 | 0.863 | – | 30,293 |
| multiwoz | last-k | completed | 397 | invalid 1, state 396 | 354,497 | 0.753 | – | – |
| multiwoz | rrf | completed | 397 | invalid 2, state 395 | 355,307 | 0.896 | – | 30,293 |
| multiwoz | summary-reuse | completed | 397 | invalid 2, state 395 | 351,488 | 0.731 | 18,450 | – |
| multiwoz | slot-table | completed | 397 | invalid 10, state 387 | 378,293 | 0.744 | 425,723 | – |
| multiwoz | summary-rewrite | completed | 397 | invalid 1, state 396 | 339,630 | 0.611 | 154,063 | – |
| halumem-medium | bm25 | completed | 178 | answer 104, invalid 1, unknown 73 | 270,726 | 0.371 | – | – |
| halumem-medium | dense | completed | 178 | answer 94, invalid 3, unknown 81 | 276,283 | 0.377 | – | 199,965 |
| halumem-medium | last-k | completed | 178 | answer 20, unknown 158 | 268,387 | 0.806 | – | – |
| halumem-medium | rrf | completed | 178 | answer 106, invalid 3, unknown 69 | 276,673 | 0.382 | – | 199,979 |
| halumem-medium | summary-reuse | completed | 178 | answer 40, invalid 1, unknown 137 | 275,340 | 0.865 | 452,489 | – |
| memoryagentbench | bm25 | completed | 137 | answer 77, unknown 60 | 154,298 | 0.467 | – | – |
| memoryagentbench | dense | completed | 137 | answer 48, unknown 89 | 155,739 | 0.488 | – | 1,805,423 |
| memoryagentbench | last-k | completed | 137 | answer 10, unknown 127 | 140,254 | 0.913 | – | – |
| memoryagentbench | rrf | completed | 137 | answer 63, invalid 1, unknown 73 | 154,612 | 0.551 | – | 1,805,423 |
| memoryagentbench | summary-reuse | completed | 137 | answer 17, invalid 1, unknown 119 | 197,906 | 0.912 | 1,637,765 | – |
| memoryagentbench | slot-table | completed | 137 | answer 3, unknown 134 | 203,289 | 0.912 | 4,159,145 | – |
| memoryagentbench | summary-rewrite | completed | 137 | answer 14, unknown 123 | 164,859 | 0.920 | 2,539,289 | – |
| change-seq | bm25 | completed | 301 | answer 138, invalid 2, unknown 161 | 331,491 | 0.510 | – | – |
| change-seq | dense | completed | 301 | answer 179, invalid 6, unknown 116 | 347,436 | 0.523 | – | 21,956 |
| change-seq | last-k | completed | 301 | answer 101, unknown 200 | 325,317 | 0.792 | – | – |
| change-seq | rrf | completed | 301 | answer 178, invalid 6, unknown 117 | 345,870 | 0.514 | – | 21,956 |
| change-seq | summary-reuse | completed | 301 | answer 165, invalid 13, unknown 123 | 461,962 | 0.887 | 67,663 | – |
| change-seq | slot-table | completed | 301 | answer 102, invalid 6, unknown 193 | 427,831 | 0.806 | 507,014 | – |
| change-seq | summary-rewrite | completed | 301 | answer 102, unknown 199 | 300,224 | 0.816 | 705,962 | – |

- The per-message writers are expensive relative to the histories they read: `slot-table` spends 531,021 W tokens on LoCoMo's two histories (about 6.5 % of their 8.15 M unwindowed full-history input) and 4.16 M on MemoryAgentBench (19 % of 21.3 M); `summary-rewrite` 813,867 on LoCoMo. With prefix caching, full-history reading of LoCoMo computes only 87,308 tokens, an order of magnitude less than either writer's W.

### Natural update density (probe, from gold annotations)

| Benchmark | Measure | Value |
| --- | --- | --- |
| locomo | none | no update annotation in the gold data; measured by E002 (extraction) |
| longmemeval-s | reads in question_type=knowledge-update | 15 / 98 (0.153061) |
| multiwoz | slot revisions (changed or removed) per 1,000 messages | 37.768 (502 + 55) |
| multiwoz | re-reads after any state change; after a revision | 4194 / 6374 (0.657986); 518 / 6374 (0.081268) |
| halumem-medium | update memory points per 1,000 messages | 55.855 (725 of 3190) |
| halumem-medium | reads citing an updated memory point | 372 / 709 (0.524683) |
| memoryagentbench | reads in competency=conflict_resolution | 80 / 137 (0.583942) |
| change-seq (controlled) | messages making a view answer-stale, per 1,000 | 117.0 |
| change-seq (controlled) | reads of a view made answer-stale since its previous read | 374 / 1145 (0.326638) |

- Natural revision is not rare where it is annotated: in MultiWOZ 8.1 % of state re-reads follow a revision of an already-set slot (37.8 revisions or removals per 1,000 messages) and 65.8 % follow some change of the state; in HaluMem 22.7 % of memory points are updates (55.9 per 1,000 messages) and 52.5 % of questions cite an updated memory point. LongMemEval-S (15.3 % knowledge-update questions) and MemoryAgentBench (58.4 % conflict-resolution questions) only label the question stratum. LoCoMo has no update annotation; E002 measures it there.
- These are answer-level changes visible in gold, not the seven change types of plan 6.4 and not view staleness; how many of them the citation-based strategies miss is E002's question.

### Judging (not run; open item)

The `full-cached`, `baselines` and `baselines-write` cells hold 18,679 predictions, of which 3,868 are `answer` outputs of question reads (the rest are MultiWOZ states, scored by rule, and `unknown` / `invalid`). Rendering the blind-judge prompt for each gives 1,193,392 input tokens (counted with the Qwen3-8B tokenizer as a proxy) and at most 38,680 output tokens. Secondary judge (Azure gpt-4.1-mini, D006's third-party prices): about USD 0.65 for all 3,868. Primary judge (DeepSeek-V4-Flash-0731, 166.9 GB of weights): at least two B200 GPUs reserved for a single serving session; 1.2 M input tokens is minutes of prefill, so the reservation is dominated by loading the model (order of one hour in total). Open before judging (D006): DeepSeek-V4-Flash token counting (no Jinja chat template) and thinking mode.

## Conclusion

- Full-history reading with prefix caching is cheap whenever many reads share one history prefix (LoCoMo, MemoryAgentBench, change-seq: hit ratios 0.95 to 0.99), and the cost argument for GRACE on LoCoMo has to beat about 87 K computed tokens for 308 reads, not 8.8 M. It does not help with one read per history (LongMemEval-S, 0.07) or when the window slides (HaluMem, 0.79). This supports plan 8.2's insistence on the cached row and on payback curves over $c$ (T013, T030).
- Qwen3-8B's window holds only LoCoMo, MultiWOZ and change-seq; on LongMemEval-S, HaluMem and most of MemoryAgentBench the primary model's full-history baseline is a disclosed truncation, so the long-context answering models of D006 carry the full-history comparison there.
- T003 window question: decided yes and implemented (`prompt_reserve_tokens` 1024); no full-history prompt was rejected in the 11,554 full-history reads of both cells.
- Natural update density is substantial where gold annotates it (MultiWOZ, HaluMem), so RQ2 need not rest on the controlled sequences alone; LoCoMo's density is left to E002.
- The compute ratio $c$ was not measured reliably on a shared GPU; a dedicated latency probe on an exclusive GPU (or T030's measurement) should supply it.
- E001 stays open for the judging step (GPUs and Azure spend need the user's approval).

## Log

- 2026-11-21: created from plan section 9, phase 1.
- 2026-11-22: research question numbering and baseline names aligned with plan v3.
- 2026-11-25: manager session `m01-E001` started on `task/E001-pilot-measurements` from `main` at `795cb9e`; Issue #69. Design written before the first formal run (above), including the decision on the T003 window question.
- 2026-11-25: probe run `E001-20261125T180821Z-b7d9` completed (code `1665757`). By the design rule it gives `prompt_reserve_tokens` 1024 (largest fixed prompt part 592 tokens, on a MultiWOZ state read), so the full-history context window is 31,744 tokens; set in `full-history`, `full-history-cached` and `last-k` before the first system run. Config fix before the first system run: vLLM 0.34 names the switch `--disable-prefix-caching` (the design text had the wrong flag name; the condition is unchanged).
- 2026-11-25: design change before any baseline run: the full-cached cell runs at about 2 to 5 s per call on the shared GPU 0, so the two baselines with one sequential model call per written message (`summary-rewrite`, `slot-table`) move to a cell `baselines-write` without halumem-medium (about 3,400 messages per user) and with one longmemeval-s history; the other five baselines keep the `baselines` subsample.
- 2026-11-25: design change before the first `full-uncached` run: instead of restarting the 8100 server (which would stop the running `baselines-write` runs, hours of sequential summary and extraction calls), the uncached condition gets its own Qwen3-8B server on port 8101 with `--disable-prefix-caching`, started after every embedding user (dense, rrf) had finished and the embedding server was stopped; both servers share GPU 0 (and the GPU's other tenant), so latencies of the two conditions are taken under different, uncontrolled load. The compute-ratio fit is therefore reported per condition as well as pooled. Each uncached run is checked for zero server-reported cached tokens (integration-owner note from T030: an engine config's `prefix_caching` never reaches the server).
- 2026-11-25: all 59 system runs completed (13 full-cached incl. 8 multiwoz shards, 6 full-uncached, 30 baselines, 10 baselines-write); no failed run. Servers stopped and the `compute.yaml` entry removed. Summary `E001-summary/summary-20261125T1940Z` (code `1b04dc8`, after merging `main` at `cf686d7`); reports written for all 60 runs. Results and Conclusion filled from completed runs. The compute ratio fit is reported as unreliable (shared GPU). Judging not run: open item for the user.
