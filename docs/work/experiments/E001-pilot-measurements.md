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
| Judging | Not run in this round. D006 has E001 judge the pilot predictions with the primary judge (DeepSeek-V4-Flash, at least two B200 GPUs, not allocated) and the secondary judge (Azure gpt-4.1-mini, paid). The `summary` step counts the judgeable predictions (answer outputs of question reads in the `full-cached` and `baselines` cells) and estimates the judge input; the judge stage waits for the user's approval of GPUs and spend. Secondary judge approved and run on 2026-11-26 (judge-stage design in the Log of that date); primary judge still waiting |

## Acceptance

- [x] Every number traces to a run report: 60 runs (1 probe, 59 system), each with `report.yaml`; aggregation in `E001-summary/summary-20261125T1940Z/summary.json` with the checksum of every input `run.json`.
- [x] Prompts, counters, budgets and judges are frozen (T004) before the first formal run (unchanged; only the engine parameter `prompt_reserve_tokens` was added, by the rule written into the design before the probe).
- [x] Judging of the pilot predictions with the secondary judge (Azure gpt-4.1-mini, D006): done on 2026-11-26 after the user's approval, all 3,868 judgeable predictions, 0 judge-invalid (see Results, "Judging").
- [ ] Judging of the pilot predictions with the primary judge (DeepSeek-V4-Flash, at least two B200 GPUs): moved to T035 (user decision of 2026-11-26); not part of E001.
- [ ] Judge calibration against human labels (`configs/judges/blind.yaml`, 200 reads, two annotators): moved to T035 (user decision of 2026-11-26); not part of E001.

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
| `E001-20261126T024046Z-5db8` | 2026-11-26 | completed | `dcb56ca` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024046Z-5db8/report.yaml` (judge of `E001-20261125T181644Z-4e97`; smoke, 1 call) |
| `E001-20261126T024308Z-e3be` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024308Z-e3be/report.yaml` (judge of `E001-20261125T181643Z-4db0`; memoryagentbench, 67 judgements) |
| `E001-20261126T024328Z-75ab` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024328Z-75ab/report.yaml` (judge of `E001-20261125T181644Z-4e97`; locomo, 259 judgements) |
| `E001-20261126T024419Z-b248` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024419Z-b248/report.yaml` (judge of `E001-20261125T181646Z-27cf`; halumem-medium, 344 judgements) |
| `E001-20261126T024531Z-fb18` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024531Z-fb18/report.yaml` (judge of `E001-20261125T181646Z-d959`; change-seq, 678 judgements) |
| `E001-20261126T024744Z-dd91` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024744Z-dd91/report.yaml` (judge of `E001-20261125T181652Z-53b7`; longmemeval-s, 15 judgements) |
| `E001-20261126T024747Z-9e81` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024747Z-9e81/report.yaml` (judge of `E001-20261125T182206Z-a115`; memoryagentbench, 14 judgements) |
| `E001-20261126T024751Z-4eeb` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024751Z-4eeb/report.yaml` (judge of `E001-20261125T182206Z-c9b2`; locomo, 22 judgements) |
| `E001-20261126T024755Z-fae6` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024755Z-fae6/report.yaml` (judge of `E001-20261125T182206Z-e613`; memoryagentbench, 3 judgements) |
| `E001-20261126T024756Z-1f09` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024756Z-1f09/report.yaml` (judge of `E001-20261125T182207Z-6a24`; locomo, 24 judgements) |
| `E001-20261126T024801Z-d455` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024801Z-d455/report.yaml` (judge of `E001-20261125T182208Z-552c`; change-seq, 102 judgements) |
| `E001-20261126T024852Z-eacc` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024852Z-eacc/report.yaml` (judge of `E001-20261125T182208Z-9539`; change-seq, 102 judgements) |
| `E001-20261126T024912Z-ea80` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024912Z-ea80/report.yaml` (judge of `E001-20261125T182211Z-238f`; locomo, 225 judgements) |
| `E001-20261126T024956Z-647a` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T024956Z-647a/report.yaml` (judge of `E001-20261125T182212Z-2cd5`; locomo, 264 judgements) |
| `E001-20261126T025136Z-9eb7` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025136Z-9eb7/report.yaml` (judge of `E001-20261125T182212Z-9709`; locomo, 33 judgements) |
| `E001-20261126T025143Z-f45f` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025143Z-f45f/report.yaml` (judge of `E001-20261125T182212Z-f6b5`; locomo, 264 judgements) |
| `E001-20261126T025235Z-88e2` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025235Z-88e2/report.yaml` (judge of `E001-20261125T182213Z-25aa`; locomo, 102 judgements) |
| `E001-20261126T025315Z-c828` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025315Z-c828/report.yaml` (judge of `E001-20261125T182213Z-516a`; memoryagentbench, 63 judgements) |
| `E001-20261126T025327Z-77cc` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025327Z-77cc/report.yaml` (judge of `E001-20261125T182213Z-5232`; memoryagentbench, 77 judgements) |
| `E001-20261126T025342Z-61b8` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025342Z-61b8/report.yaml` (judge of `E001-20261125T182213Z-9d59`; memoryagentbench, 17 judgements) |
| `E001-20261126T025346Z-d204` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025346Z-d204/report.yaml` (judge of `E001-20261125T182213Z-b40d`; memoryagentbench, 48 judgements) |
| `E001-20261126T025419Z-d4fa` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025419Z-d4fa/report.yaml` (judge of `E001-20261125T182213Z-d6b4`; memoryagentbench, 10 judgements) |
| `E001-20261126T025421Z-50f7` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025421Z-50f7/report.yaml` (judge of `E001-20261125T182214Z-19a7`; halumem-medium, 104 judgements) |
| `E001-20261126T025442Z-064e` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025442Z-064e/report.yaml` (judge of `E001-20261125T182214Z-430f`; change-seq, 165 judgements) |
| `E001-20261126T025535Z-4ce3` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025535Z-4ce3/report.yaml` (judge of `E001-20261125T182214Z-4916`; halumem-medium, 20 judgements) |
| `E001-20261126T025539Z-d1e3` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025539Z-d1e3/report.yaml` (judge of `E001-20261125T182214Z-7a57`; change-seq, 178 judgements) |
| `E001-20261126T025616Z-1e3f` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025616Z-1e3f/report.yaml` (judge of `E001-20261125T182214Z-abfd`; halumem-medium, 106 judgements) |
| `E001-20261126T025656Z-17bc` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025656Z-17bc/report.yaml` (judge of `E001-20261125T182214Z-afa8`; halumem-medium, 40 judgements) |
| `E001-20261126T025704Z-ac59` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025704Z-ac59/report.yaml` (judge of `E001-20261125T182214Z-d52c`; change-seq, 179 judgements) |
| `E001-20261126T025813Z-07e3` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025813Z-07e3/report.yaml` (judge of `E001-20261125T182214Z-d8ea`; change-seq, 138 judgements) |
| `E001-20261126T025841Z-6fe8` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025841Z-6fe8/report.yaml` (judge of `E001-20261125T182215Z-19d5`; change-seq, 101 judgements) |
| `E001-20261126T025900Z-1394` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025900Z-1394/report.yaml` (judge of `E001-20261125T182215Z-86ed`; halumem-medium, 94 judgements) |
| `E001-20261126T025949Z-f402` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025949Z-f402/report.yaml` (judge of `E001-20261125T182216Z-feaf`; longmemeval-s, 1 judgements) |
| `E001-20261126T025950Z-bc47` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025950Z-bc47/report.yaml` (judge of `E001-20261125T182220Z-25d1`; longmemeval-s, 3 judgements) |
| `E001-20261126T025951Z-d4bc` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025951Z-d4bc/report.yaml` (judge of `E001-20261125T182221Z-37da`; longmemeval-s, 3 judgements) |
| `E001-20261126T025952Z-48b4` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025952Z-48b4/report.yaml` (judge of `E001-20261125T182221Z-b860`; longmemeval-s, 2 judgements) |
| `E001-20261126T025953Z-cb2d` | 2026-11-26 | completed | `4f6cf17` | `runs/E001/artifacts/m01-E001b/E001/E001-20261126T025953Z-cb2d/report.yaml` (judge of `E001-20261125T182221Z-f25e`; longmemeval-s, 1 judgements) |

Judge runs of session `m01-E001b` (secondary judge, Azure gpt-4.1-mini) are listed above after the system runs; their reports are under `$PROJECT_ROOT/runs/E001/artifacts/m01-E001b/E001/<run-id>/report.yaml`, code `dcb56ca` (smoke) and `4f6cf17` (all others), full SHAs in each `run.json`.

## Results

All numbers come from `completed` runs; every row names its run or the summary that aggregates them. Aggregation: `runs/E001/artifacts/manager/E001-summary/summary-20261125T1940Z/summary.json` (code `1b04dc8`, inputs: the probe run and all 59 system runs, each with its `run.json` checksum). Probe numbers: `E001-20261125T180821Z-b7d9/pilot-probe.json`. Tokens are counted with the pinned Qwen3-8B tokenizer and chat template. No answer is scored with a registered metric; the secondary-judge numbers in "Judging" are descriptive development numbers from an uncalibrated judge, so nothing here is a quality claim.

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

### Judging (secondary judge done; primary judge and human calibration open)

Estimate (summary `summary-20261125T1940Z`): the `full-cached`, `baselines` and `baselines-write` cells hold 18,679 predictions, of which 3,868 are `answer` outputs of question reads (the rest are MultiWOZ states, scored by rule, and `unknown` / `invalid`). Rendering the blind-judge prompt for each gives 1,193,392 input tokens (counted with the Qwen3-8B tokenizer as a proxy) and at most 38,680 output tokens. Secondary judge (Azure gpt-4.1-mini, D006's third-party prices): about USD 0.65 for all 3,868.

**Secondary judge, measured (2026-11-26).** Azure gpt-4.1-mini (`comparison_model` of `configs/judges/blind.yaml`, server model `gpt-4.1-mini-2025-04-14`), 36 judge runs (one per system run with judgeable predictions; the 15 MultiWOZ runs of the three cells and two longmemeval-s runs without `answer` predictions have none), code `4f6cf17`, plus the smoke run `E001-20261126T024046Z-5db8` (code `dcb56ca`, one call, verdict CORRECT, 285 prompt and 2 completion tokens). Aggregation: `runs/E001/artifacts/m01-E001b/E001-summary/judge-summary-20261126T0300Z/judge-summary.json` (code `4f6cf17`, checksums of the probe and all 36 judge `run.json`).

- Judged: 3,868 of 3,868 judgeable predictions (matches the estimate's count); CORRECT 1,830, INCORRECT 2,038, judge-invalid 0 (no unparsable verdict, no content-filter refusal, no failed judgement). 3,883 call attempts: 15 attempts failed transiently and succeeded on the client's retry (their HTTP cause is not kept; only the last attempt's status is recorded).
- Usage and spend (server-reported): 1,159,092 prompt tokens (proxy count 1,193,392, so the Qwen3-8B proxy overcounts by 3%), 0 cached, 9,774 completion tokens; USD 0.5799 for the full run plus USD 0.0001 for the smoke call, at 0.484 / 0.121 / 1.936 USD per million (input / cached / output), against the estimate of USD 0.65 and the session cap of USD 2.00. Output is about 2.5 tokens per verdict, not the budgeted 10.

Per benchmark, all three cells pooled (secondary judge only, development data). `accuracy` is over all question reads of the runs: answer reads take the verdict, `unknown` is correct exactly on tasks the gold marks as unanswerable (LoCoMo category 5, `abstention`, change-seq `expected_abstention`), `invalid` predictions count as wrong, judge-invalid leaves the denominator (none here). `answer correct` is CORRECT / judged answers. This is not a registered metric: only LoCoMo and LongMemEval-S register a judged metric, with other populations (LoCoMo categories 1 to 4).

| Benchmark | Question reads | answer | unknown | invalid | CORRECT | INCORRECT | judge-invalid | accuracy | answer correct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| locomo | 2,464 | 1,193 | 1,245 | 26 | 508 | 685 | 0 | 0.2062 | 0.4258 |
| longmemeval-s | 111 | 25 | 81 | 5 | 20 | 5 | 0 | 0.2252 | 0.8000 |
| halumem-medium | 1,599 | 708 | 817 | 74 | 407 | 301 | 0 | 0.2545 | 0.5749 |
| memoryagentbench | 1,096 | 299 | 778 | 19 | 76 | 223 | 0 | 0.0839 | 0.2542 |
| change-seq | 3,252 | 1,643 | 1,550 | 59 | 819 | 824 | 0 | 0.5670 | 0.4985 |
| total | 8,522 | 3,868 | 4,471 | 183 | 1,830 | 2,038 | 0 | (not pooled across benchmarks) | |

Per cell and engine (accuracy / answer correct; reads as in the cell's subsample, see Design):

| Cell · engine | locomo | longmemeval-s | halumem-medium | memoryagentbench | change-seq |
| --- | --- | --- | --- | --- | --- |
| full-cached · full-history-cached | 0.4156 / 0.4942 (308) | 0.1633 / 0.7333 (98) | 0.3300 / 0.6802 (709) | 0.1241 / 0.2239 (137) | 0.6218 / 0.5192 (1,145) |
| baselines · bm25 | 0.3149 / 0.4311 (308) | 0.6667 / 0.6667 (3) | 0.3090 / 0.5288 (178) | 0.1314 / 0.2078 (137) | 0.5216 / 0.4638 (301) |
| baselines · dense | 0.3831 / 0.4470 (308) | 1.0000 / 1.0000 (3) | 0.2472 / 0.4681 (178) | 0.1022 / 0.2500 (137) | 0.6246 / 0.5587 (301) |
| baselines · rrf | 0.3929 / 0.4583 (308) | 0.6667 / 1.0000 (3) | 0.3090 / 0.5189 (178) | 0.1460 / 0.2857 (137) | 0.6445 / 0.5955 (301) |
| baselines · last-k | 0.0130 / 0.1212 (308) | 0.3333 / 1.0000 (3) | 0.0674 / 0.6000 (178) | 0.0438 / 0.4000 (137) | 0.5183 / 0.5446 (301) |
| baselines · summary-reuse | 0.1104 / 0.3333 (308) | no answer (3) | 0.0393 / 0.1750 (178) | 0.0438 / 0.2353 (137) | 0.5415 / 0.4242 (301) |
| baselines-write · summary-rewrite | 0.0097 / 0.1250 (308) | no answer (1) | not run | 0.0584 / 0.4286 (137) | 0.4884 / 0.4412 (301) |
| baselines-write · slot-table | 0.0097 / 0.1364 (308) | 1.0000 / 1.0000 (1) | not run | 0.0219 / 0.3333 (137) | 0.4219 / 0.2647 (301) |

Reading: the judge works end to end on development data at about USD 0.15 per thousand verdicts; it produced no invalid verdict. The pilot predictions are dominated by `unknown` (4,471 of 8,522 question reads), which the judge never sees. On change-seq a large share of the accuracy comes from correct abstentions (`expected_abstention`), so it is not comparable with the other benchmarks. Cells with 1 to 3 longmemeval-s reads say nothing. None of these numbers is a comparison between systems: the subsamples are small, the judge is the secondary one and uncalibrated, and the reads are development data.

Still open: the primary judge (DeepSeek-V4-Flash-0731) over the same predictions, which gives the agreement between the two judges D006 asks for; and the human calibration sample (200 reads stratified by benchmark and verdict, two annotators, `configs/judges/blind.yaml`), which these 3,868 verdicts now make possible to draw. Primary judge (DeepSeek-V4-Flash-0731, 166.9 GB of weights): at least two B200 GPUs reserved for a single serving session; 1.2 M input tokens is minutes of prefill, so the reservation is dominated by loading the model (order of one hour in total). Open before judging (D006): DeepSeek-V4-Flash token counting (no Jinja chat template) and thinking mode.

## Conclusion

- Full-history reading with prefix caching is cheap whenever many reads share one history prefix (LoCoMo, MemoryAgentBench, change-seq: hit ratios 0.95 to 0.99), and the cost argument for GRACE on LoCoMo has to beat about 87 K computed tokens for 308 reads, not 8.8 M. It does not help with one read per history (LongMemEval-S, 0.07) or when the window slides (HaluMem, 0.79). This supports plan 8.2's insistence on the cached row and on payback curves over $c$ (T013, T030).
- Qwen3-8B's window holds only LoCoMo, MultiWOZ and change-seq; on LongMemEval-S, HaluMem and most of MemoryAgentBench the primary model's full-history baseline is a disclosed truncation, so the long-context answering models of D006 carry the full-history comparison there.
- T003 window question: decided yes and implemented (`prompt_reserve_tokens` 1024); no full-history prompt was rejected in the 11,554 full-history reads of both cells.
- Natural update density is substantial where gold annotates it (MultiWOZ, HaluMem), so RQ2 need not rest on the controlled sequences alone; LoCoMo's density is left to E002.
- The compute ratio $c$ was not measured reliably on a shared GPU; a dedicated latency probe on an exclusive GPU (or T030's measurement) should supply it.
- Secondary judging is done (3,868 verdicts, 0 invalid, USD 0.58). E001 stays open for the primary judge (GPUs need the user's approval) and the human calibration of the judge.

## Log

- 2026-11-21: created from plan section 9, phase 1.
- 2026-11-22: research question numbering and baseline names aligned with plan v3.
- 2026-11-25: manager session `m01-E001` started on `task/E001-pilot-measurements` from `main` at `795cb9e`; Issue #69. Design written before the first formal run (above), including the decision on the T003 window question.
- 2026-11-25: probe run `E001-20261125T180821Z-b7d9` completed (code `1665757`). By the design rule it gives `prompt_reserve_tokens` 1024 (largest fixed prompt part 592 tokens, on a MultiWOZ state read), so the full-history context window is 31,744 tokens; set in `full-history`, `full-history-cached` and `last-k` before the first system run. Config fix before the first system run: vLLM 0.34 names the switch `--disable-prefix-caching` (the design text had the wrong flag name; the condition is unchanged).
- 2026-11-25: design change before any baseline run: the full-cached cell runs at about 2 to 5 s per call on the shared GPU 0, so the two baselines with one sequential model call per written message (`summary-rewrite`, `slot-table`) move to a cell `baselines-write` without halumem-medium (about 3,400 messages per user) and with one longmemeval-s history; the other five baselines keep the `baselines` subsample.
- 2026-11-25: design change before the first `full-uncached` run: instead of restarting the 8100 server (which would stop the running `baselines-write` runs, hours of sequential summary and extraction calls), the uncached condition gets its own Qwen3-8B server on port 8101 with `--disable-prefix-caching`, started after every embedding user (dense, rrf) had finished and the embedding server was stopped; both servers share GPU 0 (and the GPU's other tenant), so latencies of the two conditions are taken under different, uncontrolled load. The compute-ratio fit is therefore reported per condition as well as pooled. Each uncached run is checked for zero server-reported cached tokens (integration-owner note from T030: an engine config's `prefix_caching` never reaches the server).
- 2026-11-25: all 59 system runs completed (13 full-cached incl. 8 multiwoz shards, 6 full-uncached, 30 baselines, 10 baselines-write); no failed run. Servers stopped and the `compute.yaml` entry removed. Summary `E001-summary/summary-20261125T1940Z` (code `1b04dc8`, after merging `main` at `cf686d7`); reports written for all 60 runs. Results and Conclusion filled from completed runs. The compute ratio fit is reported as unreliable (shared GPU). Judging not run: open item for the user.
- 2026-11-26: user decision: "E001 评判批准，用 Azure 跑" (E001 judging approved, run it with Azure). Scope as interpreted for manager session `m01-E001b` (branch `task/E001-judging` from `main` at `3143ab3`): run the secondary judge only, Azure gpt-4.1-mini as defined by `comparison_model` in `configs/judges/blind.yaml` (prompt `judge`, parse `one_word`, temperature 0, `max_tokens` 10, seed 0; frozen by T004 and unchanged). The primary judge (DeepSeek-V4-Flash, at least two B200 GPUs) is not approved by this decision and stays an open gap; which judge is primary is unchanged (D006). Spend cap for the session USD 2.00 (prices used: gpt-4.1-mini Sweden Central regional, input 0.484, cached input 0.121, output 1.936 USD per million tokens).
- 2026-11-26: judge-stage design, written before the first judge call. One `judge` run per completed system run of the `judging` cells (`full-cached`, `baselines`, `baselines-write`) that has at least one `answer` prediction of a question read (contracts.md: a judge run has exactly one upstream run); runs without such predictions (all MultiWOZ runs: state reads, scored by rule) get no judge run. Gold comes from `load_split` (manifests verified), one annotation per task. Driver `uv run python -m grace.cli.pilot judge` (stage code `grace.cli.run.judge`; judge `grace.eval.analysis.judging.judge.blind_judge`; all calls through `grace.llm.client`), four concurrent calls, `max_attempts` 3 (budgets.yaml). The remote judge has no local tokenizer, so `calls.jsonl` `input_tokens` is the Qwen3-8B count (proxy, as in the estimate) and the server's `usage` is kept per judgement in `judge-usage.jsonl`; spend is computed from it. A failed or content-filtered call gives verdict `invalid` (counted as `n_judge_invalid`, cause in `judge-usage.jsonl`); an authentication error, five failed calls in a row, or a spend projection above the cap after 10% of the calls stops the stage. Before the full run, one smoke judge run with a single call (`--limit 1`) checks the deployment. The estimate's count (3,868 judgeable predictions over the three cells) matches the config's `judging.cells`; the design table above said "`full-cached` and `baselines`" and omitted `baselines-write`, which the estimate did include. The summary `judge-summary` reports, per cell, engine and benchmark, the judged counts and a descriptive accuracy over all question reads (unknown correct on abstention tasks, invalid predictions wrong, judge-invalid excluded); it is not a registered metric (only LoCoMo and LongMemEval-S register a judged metric in `configs/common/scorers.yaml`).
- 2026-11-26: smoke judge run `E001-20261126T024046Z-5db8` completed (code `dcb56ca`): one call, verdict CORRECT, server model `gpt-4.1-mini-2025-04-14`. First full invocation stopped before any call: loading MultiWOZ gold (several annotations per task) for runs that have no `answer` prediction; fixed by skipping such runs before loading gold (code `4f6cf17`, test added); no run directory was created. Full invocation: 36 judge runs completed, no failed run, 3,868 verdicts (CORRECT 1,830, INCORRECT 2,038, invalid 0, content-filtered 0), USD 0.5799 server-reported spend (smoke USD 0.0001). Reports written for all 37 runs; summary `m01-E001b/E001-summary/judge-summary-20261126T0300Z`. Results ("Judging") filled from completed runs. Primary judge and human calibration remain open.
- 2026-11-26: user decision: the primary-judge run (DeepSeek-V4-Flash) and the judge calibration against human labels move to T035 ("Audit, judge calibration and uncertainty"); E001 closes with the system runs and the secondary-judge results (PR #105). The pilot predictions and secondary-judge verdicts in `runs/E001/` stay the input for that work. T013 no longer waits on the judging.
