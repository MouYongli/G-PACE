---
id: E014
title: Development quality-versus-cost curves
created: 2026-11-23
---

# E014 · Development quality-versus-cost curves

## Question

On development data, where does the system sit against every baseline in accuracy and in end-to-end tokens? Serves RQ3 and produces the numbers from which the lock (D012) fixes budgets and non-inferiority margins. The LoCoMo cost claim waits for this experiment (user decision 2026-11-28, after E007's break-even with a read-side proxy).

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | LoCoMo dev (conv-26, conv-49; 308 end-of-history reads, categories 1-4); LongMemEval-S dev main-text strata (67 histories), quality only (plan 8.4) |
| Systems and baselines | GRACE main configuration (`grace.yaml`); template serialisation (`grace-template.yaml`); query-time resolution, no views (`grace-append-only.yaml`); fixed slot table inside GRACE (`grace-slots.yaml`); full history with and without prefix cache; last-k; BM25, dense, RRF; rolling summary reused (stale) and rewritten; T003 slot table; Mem0 (T029 adapter, local Qwen3-8B, no paid service) |
| Metrics | LoCoMo rule-based F1 at budgets 256, 512, 1,024 (full for the full-history rows); mean system tokens per read with the ingestion spread over the reads; tokens at similar quality; cumulative cost over reads; cost per successful read (F1 >= 0.5; no judge); break-even M*(c) and c* against full history with prefix cache |
| Seeds and budget | Seed 0, temperature 0; budgets 256 / 512 / 1,024 / full |
| Config | `configs/experiments/E014-dev-quality-cost.yaml` |
| Analysis | `python -m grace.cli.quality_cost` (`src/grace/eval/analysis/metrics/cost/quality_cost.py`) over a runs manifest |

Models: GRACE writer Qwen3-32B (shared server, port 8253, session units); planner, rendering and answering of every system Qwen3-8B (shared server, port 8252); embeddings Qwen3-Embedding-0.6B (8251). GRACE read-side variants read from the shared main-configuration ingest `E006-20261128T082608Z-21cb` (E006); the template variant reads the graph at read time and is free on the read side (`stages.py`), so it shares that ingest and its write cost; append-only and slots changed the writer-side extension and have their own ingests (`E014-20261128T090613Z-acd7`, `-ece7`). Every write record counts (contract 0.2.2: flush and finish commits are in the ingest calls), so W is complete here, not E007's lower bound.

Reuse of earlier runs. The E001 LoCoMo runs of full history (cached `E001-20261125T181644Z-4e97`, uncached `E001-20261125T184148Z-74ee`) and of last-k, BM25, dense, RRF at 1,024 were reused: no change since their SHAs (`d3cab7b`, `a532b68`, `1414833`) to the raw and retrieval engines, their configs, the answer prompt or the answering path that affects a baseline (the only answering change, `retrieve_refused`, applies only to an engine reporting a spent extra retrieval). The summary and slot-table baselines and Mem0 were rerun as ingest + read so that all three budgets share one write; their 1,024 reads reproduce the earlier runs (summary-reuse 0.097 vs E001 0.097; slot-table 0.017 vs 0.014; summary-rewrite 0.017 vs 0.010; Mem0 0.362 vs T029 0.369 / 0.376 per history).

Cached tokens on the Qwen3-8B server. The shared server at 8252 runs without `--enable-prompt-tokens-details`, so every new run's Qwen3-8B record has `cached_input_tokens` 0 although the server caches prefixes. Servers were not restarted. Three accountings, all in every table of the analysis:

- `reported`: as recorded; no cache credit for Qwen3-8B calls of new runs (upper bound of their cost);
- `imputed`: cached = the block-aligned (16) token length of the prompt's fixed system message (answer 432, plan-query and its repair 2,272, render 352, summary 208, extract-slots 224), a lower bound;
- `probe`: cached = mean cached tokens per call measured for that call type on a server that reports them. GRACE: probe read run `E014-20261128T090613Z-f238` (shared ingest, conv-26, budget 1,024, chat calls on the Qwen3-32B server, same tokenizer and prompts; 161 plan calls 2,488 of 2,844 input tokens cached, 14 repair 2,816 of 3,050, 164 answer 478 of 1,488); Mem0's extraction calls (`external`): T029 run `T029-20261125T180237Z-27cb` (420 calls, 7,940 of 8,725 cached). The probe is the main accounting below; `reported` is shown for the cost claim because it is the most conservative.

Reused E001 and T029 runs and the Qwen3-32B writer report their cached tokens and are never changed; the uncached full-history run ran without prefix caching (zero is real; exempt in the config). c, the price of a cache-hit token relative to a full one, is not measured here: the marks are T013's measured values on Qwen3-8B (`T013-20261126T044914Z-811f`; warm-read median-latency ratio 0.130, pooled fit 0.191; both end-to-end latency ratios and upper bounds of the GPU compute ratio, which T013 puts at plausibly 0.05-0.10). Compute weighting: Qwen3-32B tokens x4.0 (parameter ratio 32.8 B / 8.2 B, E007's assumption), Qwen3-8B x1; embedding tokens are reported apart.

## Acceptance

- [x] Every number traces to a run report (E014 runs below, each with `report.yaml`; reused E001 and T029 runs have their own reports; the analysis directory lists its inputs).

## Runs

Run directories: `runs/E014/artifacts/w01-E014/E014/<run-id>/` (`report.yaml` in each). Reused runs (reports in their own directories): `E001-20261125T181644Z-4e97` (full history cached), `E001-20261125T184148Z-74ee` (uncached), `E001-20261125T182212Z-9709` (last-k), `E001-20261125T182211Z-238f` (BM25), `E001-20261125T182212Z-f6b5` (dense), `E001-20261125T182212Z-2cd5` (RRF), all at 1,024 or full; `T029-20261125T180237Z-27cb` (Mem0 cache probe for `external` calls and reproduction check; `T029-20261125T180237Z-4f63` reproduction check); shared GRACE ingests `E006-20261128T082608Z-21cb` (LoCoMo) and `E006-20261128T083145Z-6288` (LongMemEval-S). Analysis output (not a run stage): `E014-analysis-locomo-dev-20261128T093538Z` (code `4af4755`).

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| `E014-20261128T090613Z-14f0` | 2026-11-28 | completed | `286b69c` | locomo: read grace-template @1024, upstream `E006-20261128T082608Z-21cb` |
| `E014-20261128T090613Z-1b57` | 2026-11-28 | completed | `286b69c` | locomo: read grace @256, upstream `E006-20261128T082608Z-21cb` |
| `E014-20261128T090613Z-5f08` | 2026-11-28 | completed | `286b69c` | locomo: read grace @1024, upstream `E006-20261128T082608Z-21cb` |
| `E014-20261128T090613Z-a081` | 2026-11-28 | completed | `286b69c` | locomo: read grace-template @256, upstream `E006-20261128T082608Z-21cb` |
| `E014-20261128T090613Z-a854` | 2026-11-28 | completed | `286b69c` | locomo: read grace @512, upstream `E006-20261128T082608Z-21cb` |
| `E014-20261128T090613Z-acd7` | 2026-11-28 | completed | `286b69c` | locomo: ingest grace-append-only |
| `E014-20261128T090613Z-b749` | 2026-11-28 | completed | `286b69c` | locomo: read grace-template @512, upstream `E006-20261128T082608Z-21cb` |
| `E014-20261128T090613Z-ece7` | 2026-11-28 | completed | `286b69c` | locomo: ingest grace-slots |
| `E014-20261128T090613Z-f238` | 2026-11-28 | completed | `286b69c` | locomo: read grace @1024, upstream `E006-20261128T082608Z-21cb` (cache probe, Qwen3-32B chat) |
| `E014-20261128T090720Z-1811` | 2026-11-28 | completed | `286b69c` | locomo: system rrf @512 |
| `E014-20261128T090720Z-3295` | 2026-11-28 | completed | `286b69c` | locomo: system last-k @256 |
| `E014-20261128T090720Z-64fc` | 2026-11-28 | completed | `286b69c` | locomo: system rrf @256 |
| `E014-20261128T090720Z-84b2` | 2026-11-28 | completed | `286b69c` | locomo: ingest slot-table |
| `E014-20261128T090720Z-97ab` | 2026-11-28 | completed | `286b69c` | locomo: ingest summary-rewrite |
| `E014-20261128T090720Z-a5fc` | 2026-11-28 | completed | `286b69c` | locomo: ingest summary-reuse |
| `E014-20261128T090720Z-a946` | 2026-11-28 | completed | `286b69c` | locomo: system dense @256 |
| `E014-20261128T090720Z-afa3` | 2026-11-28 | completed | `286b69c` | locomo: system dense @512 |
| `E014-20261128T090720Z-c4f1` | 2026-11-28 | completed | `286b69c` | locomo: ingest mem0 |
| `E014-20261128T090720Z-cfdb` | 2026-11-28 | completed | `286b69c` | locomo: system last-k @512 |
| `E014-20261128T090720Z-e2cf` | 2026-11-28 | completed | `286b69c` | locomo: system bm25 @512 |
| `E014-20261128T090720Z-f221` | 2026-11-28 | completed | `286b69c` | locomo: system bm25 @256 |
| `E014-20261128T091301Z-aa65` | 2026-11-28 | completed | `b3c01ca` | locomo: read slot-table @256, upstream `E014-20261128T090720Z-84b2` |
| `E014-20261128T091301Z-dfb6` | 2026-11-28 | completed | `b3c01ca` | locomo: read summary-reuse @1024, upstream `E014-20261128T090720Z-a5fc` |
| `E014-20261128T091301Z-fd75` | 2026-11-28 | completed | `b3c01ca` | locomo: read slot-table @512, upstream `E014-20261128T090720Z-84b2` |
| `E014-20261128T091302Z-2839` | 2026-11-28 | completed | `b3c01ca` | locomo: read slot-table @1024, upstream `E014-20261128T090720Z-84b2` |
| `E014-20261128T091302Z-8a80` | 2026-11-28 | completed | `b3c01ca` | locomo: read summary-reuse @256, upstream `E014-20261128T090720Z-a5fc` |
| `E014-20261128T091302Z-917b` | 2026-11-28 | completed | `b3c01ca` | locomo: score of `E014-20261128T090720Z-1811` |
| `E014-20261128T091302Z-d40f` | 2026-11-28 | completed | `b3c01ca` | locomo: read summary-reuse @512, upstream `E014-20261128T090720Z-a5fc` |
| `E014-20261128T091303Z-0634` | 2026-11-28 | completed | `b3c01ca` | locomo: score of `E014-20261128T090720Z-64fc` |
| `E014-20261128T091303Z-a7a4` | 2026-11-28 | completed | `b3c01ca` | locomo: score of `E014-20261128T090720Z-3295` |
| `E014-20261128T091304Z-33f7` | 2026-11-28 | completed | `b3c01ca` | locomo: score of `E014-20261128T090720Z-afa3` |
| `E014-20261128T091304Z-80ce` | 2026-11-28 | completed | `b3c01ca` | locomo: score of `E014-20261128T090720Z-a946` |
| `E014-20261128T091305Z-805c` | 2026-11-28 | completed | `b3c01ca` | locomo: score of `E014-20261128T090720Z-cfdb` |
| `E014-20261128T091306Z-508a` | 2026-11-28 | completed | `b3c01ca` | locomo: score of `E014-20261128T090720Z-e2cf` |
| `E014-20261128T091306Z-e28e` | 2026-11-28 | completed | `b3c01ca` | locomo: score of `E014-20261128T090720Z-f221` |
| `E014-20261128T091340Z-5c48` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T090613Z-14f0` |
| `E014-20261128T091341Z-23dd` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T090613Z-5f08` |
| `E014-20261128T091341Z-3f18` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T090613Z-1b57` |
| `E014-20261128T091342Z-5709` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T090613Z-a081` |
| `E014-20261128T091343Z-2622` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T090613Z-b749` |
| `E014-20261128T091343Z-d7b0` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T090613Z-a854` |
| `E014-20261128T091349Z-19ca` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E001-20261125T181644Z-4e97` |
| `E014-20261128T091350Z-0b3b` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E001-20261125T182212Z-9709` |
| `E014-20261128T091350Z-b5f1` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E001-20261125T184148Z-74ee` |
| `E014-20261128T091351Z-3323` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E001-20261125T182211Z-238f` |
| `E014-20261128T091352Z-47d7` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E001-20261125T182212Z-2cd5` |
| `E014-20261128T091352Z-fadc` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E001-20261125T182212Z-f6b5` |
| `E014-20261128T091353Z-e0ab` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E001-20261125T182213Z-25aa` |
| `E014-20261128T091354Z-8590` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E001-20261125T182206Z-c9b2` |
| `E014-20261128T091354Z-e69a` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E001-20261125T182207Z-6a24` |
| `E014-20261128T091355Z-6a6b` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `T029-20261125T180237Z-27cb` |
| `E014-20261128T091356Z-4649` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `T029-20261125T180237Z-4f63` |
| `E014-20261128T091429Z-34f7` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T091301Z-dfb6` |
| `E014-20261128T091429Z-8dfa` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T091301Z-aa65` |
| `E014-20261128T091430Z-c823` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T091301Z-fd75` |
| `E014-20261128T091431Z-9920` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T091302Z-2839` |
| `E014-20261128T091431Z-c444` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T091302Z-8a80` |
| `E014-20261128T091432Z-a03a` | 2026-11-28 | completed | `f8d7fd9` | locomo: score of `E014-20261128T091302Z-d40f` |
| `E014-20261128T091701Z-0086` | 2026-11-28 | completed | `4af4755` | locomo: read grace-append-only @256, upstream `E014-20261128T090613Z-acd7` |
| `E014-20261128T091701Z-18e7` | 2026-11-28 | completed | `4af4755` | locomo: read grace-append-only @1024, upstream `E014-20261128T090613Z-acd7` |
| `E014-20261128T091701Z-3e27` | 2026-11-28 | completed | `4af4755` | locomo: read mem0 @1024, upstream `E014-20261128T090720Z-c4f1` |
| `E014-20261128T091701Z-aebb` | 2026-11-28 | completed | `4af4755` | locomo: read grace-append-only @512, upstream `E014-20261128T090613Z-acd7` |
| `E014-20261128T091701Z-bfa0` | 2026-11-28 | completed | `4af4755` | locomo: read mem0 @256, upstream `E014-20261128T090720Z-c4f1` |
| `E014-20261128T091701Z-cf86` | 2026-11-28 | completed | `4af4755` | locomo: read mem0 @512, upstream `E014-20261128T090720Z-c4f1` |
| `E014-20261128T092038Z-060a` | 2026-11-28 | completed | `4af4755` | locomo: read grace-slots @256, upstream `E014-20261128T090613Z-ece7` |
| `E014-20261128T092038Z-2ed5` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T091701Z-0086` |
| `E014-20261128T092038Z-4547` | 2026-11-28 | completed | `4af4755` | locomo: read grace-slots @1024, upstream `E014-20261128T090613Z-ece7` |
| `E014-20261128T092039Z-01f0` | 2026-11-28 | completed | `4af4755` | locomo: read grace-slots @512, upstream `E014-20261128T090613Z-ece7` |
| `E014-20261128T092039Z-75d2` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T091701Z-18e7` |
| `E014-20261128T092039Z-8944` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T091701Z-3e27` |
| `E014-20261128T092040Z-0b86` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T091701Z-aebb` |
| `E014-20261128T092041Z-4283` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T091701Z-bfa0` |
| `E014-20261128T092041Z-ac02` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T091701Z-cf86` |
| `E014-20261128T092108Z-9fef` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system bm25 @1024 |
| `E014-20261128T092108Z-ef96` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system last-k @512 |
| `E014-20261128T092109Z-0b0d` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system last-k @1024 |
| `E014-20261128T092109Z-3d3f` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system rrf @512 |
| `E014-20261128T092109Z-3e0b` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system rrf @1024 |
| `E014-20261128T092109Z-4b73` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system dense @512 |
| `E014-20261128T092109Z-80b3` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system bm25 @256 |
| `E014-20261128T092109Z-af74` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system rrf @256 |
| `E014-20261128T092109Z-bb06` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system last-k @256 |
| `E014-20261128T092109Z-c07e` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system dense @1024 |
| `E014-20261128T092109Z-c5be` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system bm25 @512 |
| `E014-20261128T092109Z-cc1e` | 2026-11-28 | completed | `4af4755` | longmemeval-s: system dense @256 |
| `E014-20261128T092732Z-34b1` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T092038Z-060a` |
| `E014-20261128T092732Z-7892` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T092038Z-4547` |
| `E014-20261128T092733Z-1557` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T092039Z-01f0` |
| `E014-20261128T093500Z-0d52` | 2026-11-28 | completed | `4af4755` | locomo: read summary-rewrite @256, upstream `E014-20261128T090720Z-97ab` |
| `E014-20261128T093500Z-4de2` | 2026-11-28 | completed | `4af4755` | locomo: read summary-rewrite @512, upstream `E014-20261128T090720Z-97ab` |
| `E014-20261128T093500Z-92e3` | 2026-11-28 | completed | `4af4755` | locomo: read summary-rewrite @1024, upstream `E014-20261128T090720Z-97ab` |
| `E014-20261128T093527Z-46f6` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T093500Z-0d52` |
| `E014-20261128T093528Z-53a2` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T093500Z-4de2` |
| `E014-20261128T093529Z-ce75` | 2026-11-28 | completed | `4af4755` | locomo: score of `E014-20261128T093500Z-92e3` |
| `E014-20261128T093829Z-cc16` | 2026-11-28 | failed | `4af4755` | longmemeval-s: read grace @1024, upstream `E006-20261128T083145Z-6288` |
| `E014-20261128T093829Z-cffb` | 2026-11-28 | failed | `4af4755` | longmemeval-s: read grace @256, upstream `E006-20261128T083145Z-6288` |
| `E014-20261128T093829Z-ede7` | 2026-11-28 | failed | `4af4755` | longmemeval-s: read grace @512, upstream `E006-20261128T083145Z-6288` |
| `E014-20261128T093929Z-9179` | 2026-11-28 | failed | `4af4755` | longmemeval-s: read grace @256, upstream `E006-20261128T083145Z-6288` |
| `E014-20261128T093929Z-9d08` | 2026-11-28 | failed | `4af4755` | longmemeval-s: read grace @1024, upstream `E006-20261128T083145Z-6288` |
| `E014-20261128T093929Z-bb4a` | 2026-11-28 | failed | `4af4755` | longmemeval-s: read grace @512, upstream `E006-20261128T083145Z-6288` |

## Results

All numbers come from completed runs in Runs; quality from the E014 score runs of each system or read run (registered LoCoMo F1, categories 1-4, invalid outputs count as 0); cost from analysis output `E014-analysis-locomo-dev-20261128T093538Z` (code `4af4755`; under `runs/E014/artifacts/w01-E014/E014/`; `inputs.json` lists every run with the SHA-256 of its `run.json`; manifest `runs/E014/artifacts/w01-E014/manifest-locomo-dev.yaml`). Curve data files there: `cumulative.csv` (cumulative cost per read per history, systems at 1,024 and the full-history rows, every accounting, weighting and c mark, measured read order and one seed-0 draw), `break-even.csv` (M*(c) on c = 0, 0.01, ..., 1 plus the marks, per GRACE variant, budget and history), `c-star.json`, `crossings.json`, `quality.csv`, `ledgers.csv`, `success.csv`, `similar-quality.csv`, `cache.json`. No figures (matplotlib is not installed).

### LoCoMo dev: accuracy and tokens per read (308 reads)

Tokens per read = all system tokens of the run (W + U + A, the ingestion included) / 308. Columns: logical (c = 1); computed with the imputed cache (c = 0); priced at c = 0.130 under the imputed and the probe accounting; priced at c = 0.130 under the probe accounting with Qwen3-32B tokens x4. Rows at 1,024 for last-k, BM25, dense and RRF and the full-history rows are E001 runs (cache reported by their server); all other rows are E014 runs on the 8252 server.

| System | Budget | F1 | F1>=0.5 | unknown / invalid | logical / read | computed (imputed) / read | c=0.13 imputed / read | c=0.13 probe / read | c=0.13 probe, compute-weighted / read |
|---|---|---|---|---|---|---|---|---|---|
| grace | 256 | 0.266 | 90 | 84 / 0 | 6,097 | 1,816 | 2,373 | 1,949 | 3,469 |
| grace | 512 | 0.314 | 101 | 54 / 1 | 6,405 | 2,094 | 2,654 | 2,224 | 3,743 |
| grace | 1024 | 0.342 | 106 | 43 / 0 | 6,906 | 2,596 | 3,156 | 2,727 | 4,246 |
| grace-template | 256 | 0.261 | 87 | 84 / 0 | 6,111 | 1,822 | 2,380 | 1,956 | 3,475 |
| grace-template | 512 | 0.313 | 102 | 56 / 1 | 6,385 | 2,088 | 2,647 | 2,220 | 3,739 |
| grace-template | 1024 | 0.341 | 106 | 42 / 0 | 6,899 | 2,596 | 3,155 | 2,727 | 4,247 |
| grace-append-only | 256 | 0.254 | 83 | 91 / 0 | 6,099 | 1,837 | 2,391 | 1,968 | 3,571 |
| grace-append-only | 512 | 0.301 | 95 | 56 / 1 | 6,370 | 2,101 | 2,656 | 2,231 | 3,834 |
| grace-append-only | 1024 | 0.339 | 106 | 45 / 0 | 6,894 | 2,612 | 3,168 | 2,741 | 4,344 |
| grace-slots | 256 | 0.133 | 42 | 171 / 1 | 3,912 | 784 | 1,191 | 1,070 | 1,983 |
| grace-slots | 512 | 0.140 | 46 | 158 / 2 | 4,170 | 1,046 | 1,452 | 1,332 | 2,244 |
| grace-slots | 1024 | 0.168 | 56 | 150 / 0 | 4,693 | 1,557 | 1,965 | 1,844 | 2,757 |
| full-history-cached | full | 0.359 | 114 | 27 / 22 | 28,924 | 283 | 4,007 | 4,007 | 4,007 |
| full-history | full | 0.365 | 116 | 27 / 18 | 28,644 | 28,644 | 28,644 | 28,644 | 28,644 |
| last-k | 256 | 0.001 | 0 | 304 / 0 | 748 | 316 | 373 | 333 | 333 |
| last-k | 512 | 0.003 | 0 | 296 / 0 | 998 | 566 | 622 | 582 | 582 |
| last-k | 1024 | 0.014 | 2 | 275 / 0 | 1,508 | 75 | 262 | 262 | 262 |
| bm25 | 256 | 0.199 | 68 | 138 / 2 | 758 | 322 | 378 | 338 | 338 |
| bm25 | 512 | 0.246 | 80 | 103 / 2 | 1,012 | 577 | 634 | 593 | 593 |
| bm25 | 1024 | 0.283 | 89 | 83 / 0 | 1,506 | 1,054 | 1,113 | 1,113 | 1,113 |
| dense | 256 | 0.257 | 82 | 90 / 0 | 757 | 324 | 380 | 340 | 340 |
| dense | 512 | 0.306 | 98 | 64 / 0 | 1,010 | 578 | 634 | 594 | 594 |
| dense | 1024 | 0.343 | 107 | 44 / 0 | 1,510 | 1,046 | 1,106 | 1,106 | 1,106 |
| rrf | 256 | 0.261 | 88 | 89 / 1 | 759 | 324 | 381 | 341 | 341 |
| rrf | 512 | 0.313 | 100 | 60 / 1 | 1,014 | 579 | 636 | 595 | 595 |
| rrf | 1024 | 0.347 | 108 | 44 / 0 | 1,509 | 1,052 | 1,111 | 1,111 | 1,111 |
| summary-reuse | 256 | 0.035 | 8 | 251 / 0 | 1,057 | 548 | 614 | 574 | 574 |
| summary-reuse | 512 | 0.061 | 16 | 230 / 0 | 1,317 | 809 | 875 | 835 | 835 |
| summary-reuse | 1024 | 0.097 | 27 | 201 / 2 | 1,847 | 1,336 | 1,402 | 1,362 | 1,362 |
| summary-rewrite | 256 | 0.001 | 0 | 304 / 0 | 4,021 | 2,973 | 3,109 | 3,069 | 3,069 |
| summary-rewrite | 512 | 0.016 | 4 | 273 / 0 | 4,267 | 3,219 | 3,355 | 3,315 | 3,315 |
| summary-rewrite | 1024 | 0.017 | 4 | 270 / 0 | 4,744 | 3,696 | 3,832 | 3,792 | 3,792 |
| slot-table | 256 | 0.005 | 1 | 301 / 1 | 2,462 | 1,351 | 1,496 | 1,455 | 1,455 |
| slot-table | 512 | 0.007 | 1 | 288 / 1 | 2,728 | 1,618 | 1,762 | 1,722 | 1,722 |
| slot-table | 1024 | 0.017 | 4 | 285 / 1 | 3,214 | 2,105 | 2,249 | 2,209 | 2,209 |
| mem0 | 256 | 0.333 | 113 | 74 / 0 | 27,343 | 26,911 | 26,967 | 6,024 | 6,024 |
| mem0 | 512 | 0.339 | 113 | 64 / 1 | 27,609 | 27,174 | 27,231 | 6,288 | 6,288 |
| mem0 | 1024 | 0.362 | 119 | 60 / 2 | 28,069 | 27,630 | 27,687 | 6,743 | 6,743 |

Per category at 1,024 (F1, categories 1 / 2 temporal / 3 / 4): GRACE 0.320 / 0.081 / 0.130 / 0.519; RRF 0.292 / 0.081 / 0.200 / 0.530; dense 0.340 / 0.083 / 0.173 / 0.502; Mem0 0.341 / 0.217 / 0.191 / 0.473; full history (cached) 0.439 / 0.054 / 0.105 / 0.516.

GRACE's read cost is dominated by the planner: at 1,024, U (plan and repair) is 1,351,267 logical tokens against A (answer) 470,098 and W (writer) 305,791 over both histories (`ledgers.csv`); with the probe cache U falls to 190,995 computed tokens. GRACE and its template variant differ by at most 0.005 F1 and 7 tokens per read at every budget: no view rendering call was made at read time in any GRACE read run (no `render` records), so on LoCoMo end-of-history reads the views did not contribute.

### Tokens at similar quality

Reference GRACE at 1,024 (F1 0.342). Cheapest budget of each system within 0.01 F1 (target 0.332), logical tokens per read: RRF 1,024 (0.347; 1,509), dense 1,024 (0.343; 1,510), GRACE 1,024 (6,906), template 1,024 (6,899), append-only 1,024 (0.339; 6,894), Mem0 256 (0.333; 27,343), full history (0.359-0.365; 28,644-28,924). Within 0.03 (target 0.312): RRF 512 (0.313; 1,014), GRACE 512 (0.314; 6,405), template 512 (6,385). BM25, last-k, both summaries and both slot tables reach neither target. At similar quality RRF needs about a fifth of GRACE's logical tokens per read and a quarter to two fifths at c = 0.130 with the probe cache (1,111 vs 2,727 at 1,024; 595 vs 2,224 at 512).

### Cost per successful read (F1 >= 0.5; tokens at c = 0.130, probe accounting)

RRF 1,024: 3,169 (108 successes); dense 3,184 (107); BM25 3,851 (89); GRACE 7,923 (106); template 7,925 (106); append-only 7,966 (106); GRACE slots 10,143 (56); full history cached 10,825 (114); summary-reuse 15,536 (27); Mem0 17,454 (119); last-k 40,278 (2); full history uncached 76,056 (116); slot table 170,082 (4); summary-rewrite 292,005 (4) (`success.csv`, all ledgers and budgets there). Success is rule-based (no judge runs before T035).

### Break-even against full history with prefix cache (LoCoMo cost claim)

W per history at c = 0.130: GRACE 73,253 (conv-26) / 82,758 (conv-49) tokens, compute-weighted 293,013 / 331,034. Warm full-history read at c = 0.130: 3,440 / 4,272 tokens; GRACE read (U + A, probe) 2,159 / 2,280 (`break-even.csv`). M* = ceil(W / Delta); c* = smallest c from which M* stays within the history's own reads (152 / 156). GRACE main configuration:

| Budget | Accounting | Weighting | c* conv-26 / conv-49 | Delta at c = 0.130 | M* at c = 0.130 | M* at c = 0.191 |
| --- | --- | --- | --- | --- | --- | --- |
| 1,024 | reported | tokens | 0.24 / 0.21 | -2,284 / -1,827 | none / none | none / 779 |
| 1,024 | imputed | tokens | 0.12 / 0.10 | 875 / 1,539 | 84 / 54 | 35 / 28 |
| 1,024 | probe | tokens | 0.10 / 0.08 | 1,281 / 1,991 | 58 / 42 | 30 / 25 |
| 1,024 | reported | compute x4 | 0.31 / 0.27 | -2,284 / -1,827 | none / none | none / 3,113 |
| 1,024 | imputed | compute x4 | 0.19 / 0.16 | 875 / 1,539 | 335 / 216 | 140 / 110 |
| 1,024 | probe | compute x4 | 0.17 / 0.14 | 1,281 / 1,991 | 229 / 167 | 120 / 98 |
| 512 | probe | tokens | 0.07 / 0.06 | 1,777 / 2,502 | 42 / 34 | 26 / 22 |
| 512 | probe | compute x4 | 0.14 / 0.12 | 1,777 / 2,502 | 165 / 133 | 101 / 86 |
| 256 | probe | tokens | 0.06 / 0.05 | 2,054 / 2,773 | 36 / 30 | 23 / 21 |
| 256 | probe | compute x4 | 0.13 / 0.11 | 2,054 / 2,773 | 143 / 120 | 92 / 81 |

Template variant: within 0.01 of the main configuration in every cell (same W). Append-only at 1,024, probe: tokens c* 0.10 / 0.08, compute 0.18 / 0.14. GRACE slots at 1,024, probe: tokens 0.06 / 0.05, compute 0.10 / 0.09, but at F1 0.168 it is not quality-matched. Measured cumulative curves (run order, probe, c = 0.130, tokens): GRACE 1,024 crosses below full history cached at read 47 (conv-26) and 28 (conv-49) and ends at 401,352 / 438,503 against 543,493 / 690,569 tokens (-26% / -37%); compute-weighted it does not cross on conv-26 (621,112 vs 543,493 after 152 reads, +14%) and crosses only at read 154 of 156 on conv-49 (686,779 vs 690,569). At c = 0.191 compute-weighted: crossing at reads 113 / 83 (`crossings.json`).

Quality match: full history cached scores 0.359 F1 (0.365 uncached) against GRACE's 0.342 at 1,024, so GRACE is 0.017 F1 below its cost comparator; under plan 8 the cost difference is interpreted on quality-matched pairs only, and this pair matches only within a 0.02 margin.

### LongMemEval-S dev

Not scored: its registered metrics are judge metrics only (official and blind judge; `configs/common/scorers.yaml`), and no local judge runs before T035. Baseline predictions exist for judging later (67 reads each; last-k, BM25, dense, RRF at 256 / 512 / 1,024; context tokens per read 228-999, logical tokens per read 743-1,528; unknown outputs: last-k 66-67, BM25 26-27, dense 19-32, RRF 19-28). The full-history baseline does not fit Qwen3-8B's 32,768-token window on LongMemEval-S (the plan's long-context answering model is not served) and was not run. GRACE reads on the shared ingest `E006-20261128T083145Z-6288` fail while restoring the snapshot (two defects in GRACE's snapshot restore, see Log); no GRACE prediction exists for LongMemEval-S.

## Conclusion

- Accuracy at equal budget (LoCoMo dev): GRACE 0.266 / 0.314 / 0.342 at 256 / 512 / 1,024 is level with RRF (0.261 / 0.313 / 0.347) and dense (0.257 / 0.306 / 0.343), below Mem0 (0.333 / 0.339 / 0.362, which leads mainly on temporal questions: 0.217 vs 0.081) and below full history (0.359 / 0.365). The template variant (no rendering) and query-time resolution (no views) tie with the main configuration within 0.013 F1 at every budget; RQ3's premise that LLM-rendered views are needed for accuracy is not supported on LoCoMo end-of-history reads, where no view was rendered at read time. Summaries, last-k and both slot tables are far below (F1 at most 0.17).
- Tokens at similar quality: RRF reaches GRACE's quality with about 1,500 logical tokens per read against GRACE's 6,900 (1,111 vs 2,727 at c = 0.130 with the probe cache). GRACE's extra cost is the planner (64% of its logical tokens at 1,024), not the writer.
- LoCoMo cost claim against full history with prefix cache, stated plainly: in tokens it holds only with cache credit for GRACE's own Qwen3-8B read calls. With the measured probe cache, c* is 0.08-0.10 at 1,024 (0.05-0.07 at 256 and 512), below the measured warm-read c of 0.130, with payback after 42-58 reads; without any cache credit for those calls (`reported`) there is no payback point below c 0.21-0.24. Compute-weighted (Qwen3-32B tokens x4) it does not hold at the measured warm-read c: c* 0.14-0.17 at 1,024 (0.11-0.14 at 256 and 512), payback after 167-229 reads (beyond conv-26's 152, within conv-49's 156 only by the formula; the measured curve crosses at read 154 of 156); it holds at the pooled c of 0.191 (98-120 reads). Both c marks are upper bounds of the compute ratio (T013: GPU-only plausibly 0.05-0.10); at c below about 0.08-0.10 GRACE does not pay back even in tokens. GRACE also scores 0.017 F1 below this comparator. The cost claim on LoCoMo therefore does not hold robustly; it holds in tokens at c >= 0.10 with prefix-cached planner and answer prompts, and in compute only at c >= 0.14-0.17.
- For D012: at budget 512 GRACE loses 0.028 F1 against 1,024 and RRF ties GRACE at every budget, so a non-inferiority margin of 0.01-0.03 F1 against RRF would hold or fail on noise (rerun noise 0.003, E013; writer reruns move Mem0 by 0.01). Budgets 512 and 1,024 are the informative levels; 256 costs 0.08-0.09 F1 against 1,024 for GRACE and the retrieval baselines (Mem0 0.03).

Open items: LongMemEval-S scoring (judge, T035) and GRACE's LongMemEval-S reads (snapshot-restore defects); the cached-token split of the 8252 server is a probe measurement on the Qwen3-32B server, not a measurement of the runs themselves; c is T013's latency-based upper bound, not a GPU compute ratio; no GPU-seconds ledger (shared servers, no accounting); Graphiti and Mem0g not run (optional).

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-28: worker session `w01-E014` (directed by `s00-super`, no manager layer) on `task/E014-dev-quality-cost`; Issue #172. Config `configs/experiments/E014-dev-quality-cost.yaml` written and committed first (`286b69c`). Shared servers used as reserved by s00-super (8251, 8252, 8253); none started, stopped or restarted.
- 2026-11-28: analysis tooling `grace.cli.quality_cost` and `eval/analysis/metrics/cost/quality_cost.py` (three cache accountings, compute weighting, break-even per history, cumulative curves, cost per success); `grace.cli.locomo_score` now also scores `read` runs (the contract allows a score run's upstream to be a system or read run).
- 2026-11-28: the 8252 server reports no cached tokens; handled with the `imputed` (static prompt prefix, lower bound) and `probe` accountings (Design). Probe run `E014-20261128T090613Z-f238` sends GRACE's planner and answering calls to the Qwen3-32B server only to measure cached tokens per call type; its answers are not a result.
- 2026-11-28: LoCoMo runs and analysis complete (Results). GRACE's LongMemEval-S reads failed twice while restoring the shared ingest snapshot, both defects in GRACE's snapshot restore, outside this node's scope: (1) `context/memory/history/log.py` `MessageLog.restore` splits the JSONL file with `str.splitlines()`, which also splits on U+2028 inside message text (histories `0ddfec37_abs`, `f9e8c073`) -> `JSONDecodeError` (runs `E014-20261128T093829Z-cc16`, `-cffb`, `-ede7`); (2) with those two histories left out, `context/views/view.py` `View.from_record` cannot re-parse a stored view query whose entity ID starts with a digit (`...50mm_f_1_8_prime_lens`, histories `41698283`, `7405e8b1`) -> `QueryTypeError` (runs `E014-20261128T093929Z-9179`, `-9d08`, `-bb4a`). Reported to s00-super; LongMemEval-S scoring is also blocked on a judge (T035).
