---
id: E004
title: "Scale experiment: push, pull, hybrid"
created: 2026-11-23
---

# E004 · Scale experiment: push, pull, hybrid

## Question

At what number of standing views, write rate and graph size does push filtering become cheaper than re-querying at read time? Serves RQ2. If re-querying is never more expensive in the tested range, RQ2 narrows to 'exact staleness checks are cheap'.

## Design

Written on 2026-11-25 before the first formal run; version 2 of the same day (view mix `four` replaces `five`, see Log) before any run of version 2. Config: `configs/experiments/E004-scale-experiment.yaml`; driver: `uv run python -m grace.cli.scale` (subcommands `plan`, `run`, `summary`); probe: `src/grace/eval/runner/probes/scale.py`; statistics: `src/grace/eval/analysis/metrics/scale.py` (reads run files only).

| Item | Value |
| --- | --- |
| Benchmarks and splits | No benchmark data. Synthetic graphs scaled from the T015 generator (`changeseq-generator-2`, development families only: hotel-stay, apartment-search, train-travel, flight-travel, car-rental; held-out families are refused by the probe). A graph is `blocks` generated sequences (512 messages each, density 10, default change mix), one per block with seed `sequence_seed(seed, "E004-<family>-<index>")`, families cycled. Entity and entry IDs of block i get the prefix `b<iiii>-`, so blocks share no entity, claim or message (attribution speakers `user`, `assistant` are kept). The change sets of all blocks are interleaved round robin into one history. Messages 1-256 of every block are committed before measuring (the graph size); messages 257-512 form the measured window |
| Factors | Graph size: blocks 4, 16, 64, 256 (about 43 claims, 70 attributions and 1,300 triples per block at the prefix head). Standing views: 8, 32, 128, 512 drawn by a seeded permutation from the bindings the graph admits (nested across sizes; a size above the admitted bindings is not run). Write rate: 1, 4, 16, 64, 256 committed change sets (messages, including empty ones) between consecutive reads. Read scope: each read checks either all standing views or 4 views drawn per read (seeded, identical for every arm). View mix: `four` (list, current, count, constraints) and `six` (the full main configuration, adding pending and choice) |
| Grid | `four`: blocks {16, 64, 256} x views {8, 32, 128, 512}; `six`: blocks {4, 16} x views {8, 32}; each x read scope {4, all} x writes per read {1, 4, 16, 64, 256}. Cells whose window is shorter than 16 x writes per read are skipped and listed in `graph.json` (blocks 4: writes per read 256). Why `six` is smaller and `four` leaves out two families: the compiled queries of `pending` (calibration on prototype graphs) and of `choice` (seen in the aborted version-1 runs) take seconds per view from 16 to 64 blocks on and grow faster than the graph; in calibration the `pending` query was two orders of magnitude faster with its constants inlined instead of bound with `VALUES`. Pull over such views at 64 or more blocks would exceed the budget. The formal runs measure this as a diagnostic (below) |
| Systems | Three T019 arms of `configs/views/staleness.yaml`: push = `claim_pattern_filters` (claim-pattern push with local filters, rebuild marked views without confirmation), pull = `requery` (re-query every view a read checks, compare fingerprints), hybrid = `push_confirm` (claim-pattern marks, re-query only marked views at read). Template rendering, no model call |
| Measurement | One measurement is one arm over 16 read periods of the window. Per period: write-side decision time (`match_ms` of the strategy log, pattern matching on change-set records, no database), wall time of the strategy's `write` calls, commit time (equal for every arm; not part of the decision cost), and per read the strategy's database time (`check_db_ms` of the fingerprint re-query plus `maintain_db_ms` of re-evaluations during maintenance) and the read's wall time; views repaired and how. The graph prefix is built once per run and copied per measurement (`fork_store`); views are built at the prefix head before timing starts; `gc.collect()` before each measurement |
| Metrics | Database time per write (`write_ms`) and per read (`read_ms`); decision cost per read period `period_ms = w * write_ms + read_ms` and per write; ratio of push and hybrid to pull, paired within (cell, seed, repetition), geometric mean with a percentile bootstrap interval (2,000 replicates); crossover against pull along writes per read, standing views and blocks (log-linear interpolation of the log ratio between adjacent levels), with bootstrap median and 95% interval and the share of replicates that never cross. LLM tokens: zero by construction (template rendering); the check that pull and hybrid repair exactly the same views at every read stands in for "equal tokens" and must find no difference |
| Noise | CPU shared with other users (224 logical CPUs). Recorded: CPU model, cores, affinity and load average per run (`machine.json`); 1-minute load average before and after, wall and CPU time of every measurement. 3 repetitions per (cell, seed), arm order rotated per repetition; coefficient of variation across repetitions (timing noise) and across seeds (graph realisation) per cell and arm |
| Diagnostics | Per run, the main query of each of the 15 bindings of block 0 timed at the prefix head (minimum of 3) as compiled and with its single-IRI `VALUES` constants inlined, with row counts of both (must agree); the compiled `pending` and `choice` queries only up to 64 blocks |
| Seeds and budget | Seeds 1 and 2 (block generation, view choice, read draws). 30 runs (one per mix, blocks, seed, views; `four` with 512 views needs 57 blocks), at most 10 concurrently, each capped at 8 hours (a run that exceeds the cap fails and is reported) |
| Frozen before the first run | Generator version, families, the T019 arms and their options, the T018 template families and view config (`state_speaker: user`, as in the T019 replay), the grid above |

## Acceptance

- [x] Design (grid, seeds, repetitions, budget) written before the first formal run (version 1 at `9038ce2`; version 2 at `fac294f`, written after the version-1 runs were stopped and before any version-2 run; Log).
- [x] Database time per write and per read for push, pull and hybrid; crossover point with uncertainty (Results; summary `summary-20261125T2216Z`).
- [x] Every number traces to a run report: 40 runs with `report.yaml` (30 completed, 10 failed and unused); the Results are copied from the summary over the 30 completed runs.

## Runs

Reports are under `$PROJECT_ROOT/runs/E004/artifacts/manager/E004/<run-id>/report.yaml`; the bracket gives view mix, blocks, seed and standing views. Code SHAs are full in each `run.json`: `9038ce2` design version 1 (10 runs, all `failed`: stopped by the manager, see Log), `fac294f` design version 2 (30 runs, all `completed`). Aggregation over the 30 completed runs: `runs/E004/artifacts/manager/E004-summary/summary-20261125T2216Z/summary.json` (SHA-256 `922d28f1a0624ea1e19318d5be8a33bc07f2ba121c29c7df9d6cb675f2f009b6`), which records the run ID and `run.json` checksum of every input.

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| `E004-20261125T202555Z-0e13` | 2026-11-25 | failed | `9038ce2` | `runs/E004/artifacts/manager/E004/E004-20261125T202555Z-0e13/report.yaml` (five, 256 blocks, seed 1, 48 views) |
| `E004-20261125T202555Z-1c87` | 2026-11-25 | failed | `9038ce2` | `runs/E004/artifacts/manager/E004/E004-20261125T202555Z-1c87/report.yaml` (five, 256 blocks, seed 1, 768 views) |
| `E004-20261125T202555Z-20b6` | 2026-11-25 | failed | `9038ce2` | `runs/E004/artifacts/manager/E004/E004-20261125T202555Z-20b6/report.yaml` (five, 64 blocks, seed 2, 768 views) |
| `E004-20261125T202555Z-4def` | 2026-11-25 | failed | `9038ce2` | `runs/E004/artifacts/manager/E004/E004-20261125T202555Z-4def/report.yaml` (five, 256 blocks, seed 2, 192 views) |
| `E004-20261125T202555Z-a3a1` | 2026-11-25 | failed | `9038ce2` | `runs/E004/artifacts/manager/E004/E004-20261125T202555Z-a3a1/report.yaml` (five, 64 blocks, seed 1, 768 views) |
| `E004-20261125T202555Z-a665` | 2026-11-25 | failed | `9038ce2` | `runs/E004/artifacts/manager/E004/E004-20261125T202555Z-a665/report.yaml` (five, 256 blocks, seed 2, 48 views) |
| `E004-20261125T202555Z-a9c8` | 2026-11-25 | failed | `9038ce2` | `runs/E004/artifacts/manager/E004/E004-20261125T202555Z-a9c8/report.yaml` (five, 64 blocks, seed 2, 192 views) |
| `E004-20261125T202555Z-b389` | 2026-11-25 | failed | `9038ce2` | `runs/E004/artifacts/manager/E004/E004-20261125T202555Z-b389/report.yaml` (five, 64 blocks, seed 1, 192 views) |
| `E004-20261125T202555Z-ced3` | 2026-11-25 | failed | `9038ce2` | `runs/E004/artifacts/manager/E004/E004-20261125T202555Z-ced3/report.yaml` (five, 256 blocks, seed 1, 192 views) |
| `E004-20261125T202555Z-ee25` | 2026-11-25 | failed | `9038ce2` | `runs/E004/artifacts/manager/E004/E004-20261125T202555Z-ee25/report.yaml` (five, 256 blocks, seed 2, 768 views) |
| `E004-20261125T203615Z-0d06` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T203615Z-0d06/report.yaml` (four, 256 blocks, seed 2, 512 views) |
| `E004-20261125T203615Z-136e` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T203615Z-136e/report.yaml` (six, 16 blocks, seed 1, 32 views) |
| `E004-20261125T203615Z-1b00` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T203615Z-1b00/report.yaml` (four, 64 blocks, seed 1, 512 views) |
| `E004-20261125T203615Z-3366` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T203615Z-3366/report.yaml` (six, 16 blocks, seed 2, 32 views) |
| `E004-20261125T203615Z-5647` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T203615Z-5647/report.yaml` (four, 256 blocks, seed 1, 32 views) |
| `E004-20261125T203615Z-68fc` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T203615Z-68fc/report.yaml` (four, 256 blocks, seed 2, 128 views) |
| `E004-20261125T203615Z-838e` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T203615Z-838e/report.yaml` (four, 64 blocks, seed 2, 512 views) |
| `E004-20261125T203615Z-8986` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T203615Z-8986/report.yaml` (four, 256 blocks, seed 1, 128 views) |
| `E004-20261125T203615Z-bcb2` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T203615Z-bcb2/report.yaml` (four, 256 blocks, seed 2, 32 views) |
| `E004-20261125T203615Z-f477` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T203615Z-f477/report.yaml` (four, 256 blocks, seed 1, 512 views) |
| `E004-20261125T205613Z-5ddb` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T205613Z-5ddb/report.yaml` (four, 64 blocks, seed 1, 128 views) |
| `E004-20261125T205709Z-26ad` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T205709Z-26ad/report.yaml` (four, 64 blocks, seed 2, 128 views) |
| `E004-20261125T210056Z-f4a0` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T210056Z-f4a0/report.yaml` (six, 16 blocks, seed 1, 8 views) |
| `E004-20261125T210223Z-8fb1` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T210223Z-8fb1/report.yaml` (six, 16 blocks, seed 2, 8 views) |
| `E004-20261125T210353Z-6698` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T210353Z-6698/report.yaml` (six, 4 blocks, seed 1, 32 views) |
| `E004-20261125T210625Z-5603` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T210625Z-5603/report.yaml` (six, 4 blocks, seed 2, 32 views) |
| `E004-20261125T210710Z-08dd` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T210710Z-08dd/report.yaml` (four, 16 blocks, seed 1, 128 views) |
| `E004-20261125T210713Z-fc4f` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T210713Z-fc4f/report.yaml` (four, 16 blocks, seed 2, 128 views) |
| `E004-20261125T210718Z-aa07` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T210718Z-aa07/report.yaml` (four, 256 blocks, seed 1, 8 views) |
| `E004-20261125T211019Z-f75b` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211019Z-f75b/report.yaml` (four, 256 blocks, seed 2, 8 views) |
| `E004-20261125T211033Z-cb59` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211033Z-cb59/report.yaml` (four, 64 blocks, seed 1, 32 views) |
| `E004-20261125T211035Z-5edd` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211035Z-5edd/report.yaml` (four, 64 blocks, seed 2, 32 views) |
| `E004-20261125T211152Z-af3b` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211152Z-af3b/report.yaml` (six, 4 blocks, seed 1, 8 views) |
| `E004-20261125T211204Z-7d2b` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211204Z-7d2b/report.yaml` (six, 4 blocks, seed 2, 8 views) |
| `E004-20261125T211247Z-296f` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211247Z-296f/report.yaml` (four, 16 blocks, seed 1, 32 views) |
| `E004-20261125T211258Z-fd4e` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211258Z-fd4e/report.yaml` (four, 16 blocks, seed 2, 32 views) |
| `E004-20261125T211302Z-d766` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211302Z-d766/report.yaml` (four, 64 blocks, seed 1, 8 views) |
| `E004-20261125T211411Z-253a` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211411Z-253a/report.yaml` (four, 64 blocks, seed 2, 8 views) |
| `E004-20261125T211423Z-b0e7` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211423Z-b0e7/report.yaml` (four, 16 blocks, seed 1, 8 views) |
| `E004-20261125T211524Z-31ca` | 2026-11-25 | completed | `fac294f` | `runs/E004/artifacts/manager/E004/E004-20261125T211524Z-31ca/report.yaml` (four, 16 blocks, seed 2, 8 views) |

## Results

All numbers below are copied from `runs/E004/artifacts/manager/E004-summary/summary-20261125T2216Z/summary.json` (design version 2, 30 completed runs, 2,628 measurements: 146 cells x 3 arms x 2 seeds x 3 repetitions; `six` at 4 blocks has no writes-per-read 256 cell). Version-1 runs are not used. Times are milliseconds of wall-clock on a shared machine (Intel Xeon Platinum 8570, 224 logical CPUs; 1-minute load average 7.7-45.6 during the measurements; CPU time / wall time 0.995-1.006 per measurement, so no measurement waited for a CPU). "Write ms" is the write-side decision time per committed change set (claim-pattern matching on change-set records, no database); "read ms" is the database time per read (fingerprint re-query, or re-evaluation of a marked view); a period is w writes plus one read.

**Checks.** Pull and hybrid repaired exactly the same views with the same actions at every read in every one of the 876 measurement pairs (`repairs_differ_pull_hybrid: 0`), so they spend the same LLM tokens by construction; no LLM call was made (`llm_calls: 0`). Compiled and inlined variants of every diagnostic query returned the same rows.

**Noise.** Median coefficient of variation of the period cost across the 3 repetitions of the same seed is 0.015 (90th percentile 0.049, maximum 0.155); across the 2 seeds (different blocks, views and read draws) it is 0.19 (90th percentile 1.13). Graph realisation dominates timing noise; every interval below is a bootstrap over the 6 (seed, repetition) pairs of a cell.

#### Graphs and query time per family

Median time of the main query of block 0's views at the prefix head, as compiled / with single-IRI `VALUES` constants inlined (diagnostic; `-`: not run above 64 blocks).

| Mix | Blocks | Claims | Triples | Query ms by family (compiled / inlined, median over block 0) |
| --- | --- | --- | --- | --- |
| four (seed 1) | 16 | 685 | 21145 | choice 0.898/0.668; constraints 0.190/0.193; count 0.863/0.793; current 1.43/1.26; list 0.882/0.795; pending 509/3.67 |
| four (seed 2) | 16 | 694 | 21097 | choice 0.877/0.674; constraints 0.195/0.152; count 1.09/0.960; current 1.28/1.18; list 1.09/0.948; pending 953/5.60 |
| four (seed 1) | 64 | 2729 | 84180 | choice 0.960/0.818; constraints 0.244/0.195; count 3.02/2.76; current 5.03/4.74; list 3.14/2.86; pending 8022/17.46 |
| four (seed 2) | 64 | 2718 | 84419 | choice 0.952/0.829; constraints 0.249/0.189; count 4.09/3.71; current 4.74/4.52; list 4.10/3.76; pending 15004/33.56 |
| four (seed 1) | 256 | 10882 | 335935 | choice -/0.854; constraints 0.274/0.219; count 14.59/13.58; current 33.80/31.38; list 15.04/13.54; pending -/83.84 |
| four (seed 2) | 256 | 10829 | 336528 | choice -/0.855; constraints 0.269/0.218; count 18.00/16.52; current 29.80/25.25; list 18.38/17.38; pending -/151 |
| six (seed 1) | 4 | 183 | 5553 | choice 0.863/0.640; constraints 0.190/0.149; count 0.415/0.355; current 0.752/0.662; list 0.419/0.367; pending 35.68/0.898 |
| six (seed 2) | 4 | 177 | 5263 | choice 0.864/0.639; constraints 0.198/0.163; count 0.441/0.381; current 0.641/0.590; list 0.440/0.373; pending 57.77/1.46 |
| six (seed 1) | 16 | 685 | 21145 | choice 0.868/0.670; constraints 0.197/0.153; count 0.912/0.805; current 1.36/1.24; list 0.909/0.815; pending 502/3.54 |
| six (seed 2) | 16 | 694 | 21097 | choice 0.871/0.663; constraints 0.193/0.153; count 1.08/0.953; current 1.30/1.18; list 1.09/0.955; pending 940/5.56 |

#### Cost of one view: write-side matching against re-query

From the cells with read scope `all` and one write per read: hybrid write ms per standing view stays near 1 microsecond (0.83-2.03 us) from 16 to 256 blocks, while pull read ms per view grows with the graph: 1.6-1.9 ms at 16 blocks (about 690 claims), 3.0-6.6 ms at 64 blocks (about 2,700 claims), 25-37 ms at 256 blocks (about 10,900 claims) for the `four` mix, and 9-11 ms at 4 blocks and 61-122 ms at 16 blocks for `six`, where `pending` dominates.

#### Selected cells

Medians over the 6 pairs; hybrid / pull is the geometric mean of the paired ratio of period cost with its 95% bootstrap interval. Push is within 0.88-1.10 of hybrid in every cell (same marks, same database work; it differs only in rebuilding over-marked views without confirmation). The full table of 146 cells is `cells` in the summary.

| Mix | Blocks | Views | Scope | w | push write ms | pull read ms | hybrid read ms | hybrid / pull [95% CI] |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| four | 16 | 8 | 4 | 1 | 0.00953 | 6.23 | 0 | 0.0015 [0.0013, 0.0017] |
| four | 16 | 8 | 4 | 64 | 0.00794 | 7.84 | 1.84 | 0.297 [0.282, 0.31] |
| four | 16 | 8 | 4 | 256 | 0.00903 | 14.2 | 8.95 | 0.793 [0.77, 0.814] |
| four | 16 | 8 | all | 1 | 0.00922 | 12.7 | 0 | 0.0007 [0.0006, 0.0008] |
| four | 16 | 8 | all | 64 | 0.00815 | 15.3 | 2.09 | 0.169 [0.165, 0.174] |
| four | 16 | 8 | all | 256 | 0.00913 | 28.6 | 13.1 | 0.536 [0.519, 0.552] |
| four | 16 | 32 | 4 | 1 | 0.0272 | 6 | 0.0599 | 0.0104 [0.0054, 0.0212] |
| four | 16 | 32 | 4 | 64 | 0.0239 | 7.2 | 3.59 | 0.72 [0.7, 0.74] |
| four | 16 | 32 | 4 | 256 | 0.0265 | 13.2 | 11.1 | 1.36 [1.33, 1.39] |
| four | 16 | 32 | all | 1 | 0.0268 | 50 | 0.0828 | 0.0014 [0.0007, 0.003] |
| four | 16 | 32 | all | 64 | 0.0239 | 58.4 | 9.95 | 0.198 [0.193, 0.205] |
| four | 16 | 32 | all | 256 | 0.0264 | 104 | 48.5 | 0.531 [0.515, 0.549] |
| four | 64 | 8 | 4 | 1 | 0.0137 | 12.5 | 0 | 0.001 [0.001, 0.0011] |
| four | 64 | 8 | 4 | 64 | 0.0106 | 15.5 | 1.46 | 0.1 [0.0572, 0.176] |
| four | 64 | 8 | 4 | 256 | 0.0107 | 19.4 | 4.17 | 0.355 [0.348, 0.364] |
| four | 64 | 8 | all | 1 | 0.0125 | 24 | 0 | 0.0006 [0.0005, 0.0006] |
| four | 64 | 8 | all | 64 | 0.0106 | 30.4 | 1.45 | 0.0511 [0.0302, 0.0866] |
| four | 64 | 8 | all | 256 | 0.0107 | 38 | 4.43 | 0.188 [0.185, 0.191] |
| four | 64 | 32 | 4 | 1 | 0.0343 | 24.6 | 0.0301 | 0.0024 [0.0016, 0.0036] |
| four | 64 | 32 | 4 | 64 | 0.0295 | 28.6 | 3.42 | 0.182 [0.15, 0.22] |
| four | 64 | 32 | 4 | 256 | 0.0296 | 34 | 19.3 | 0.769 [0.739, 0.799] |
| four | 64 | 32 | all | 1 | 0.0341 | 190 | 0.0299 | 0.0003 [0.0002, 0.0005] |
| four | 64 | 32 | all | 64 | 0.0299 | 212 | 11.5 | 0.0606 [0.0567, 0.0651] |
| four | 64 | 32 | all | 256 | 0.0301 | 259 | 46.7 | 0.208 [0.202, 0.214] |
| four | 64 | 512 | 4 | 1 | 0.512 | 26.7 | 0 | 0.0195 [0.0187, 0.0204] |
| four | 64 | 512 | 4 | 64 | 0.422 | 35.2 | 6.41 | 0.995 [0.896, 1.12] |
| four | 64 | 512 | 4 | 256 | 0.423 | 38.8 | 24.7 | 3.44 [3.17, 3.72] |
| four | 64 | 512 | all | 1 | 0.518 | 3.27e+03 | 2.48 | 0.0009 [0.0008, 0.001] |
| four | 64 | 512 | all | 64 | 0.435 | 3.5e+03 | 132 | 0.0454 [0.0451, 0.0458] |
| four | 64 | 512 | all | 256 | 0.414 | 4.15e+03 | 576 | 0.165 [0.161, 0.169] |
| four | 256 | 8 | 4 | 1 | 0.0141 | 109 | 0 | 0.0001 [0.0001, 0.0001] |
| four | 256 | 8 | 4 | 64 | 0.012 | 144 | 1.51 | 0.0118 [0.0071, 0.0198] |
| four | 256 | 8 | 4 | 256 | 0.0122 | 148 | 6.46 | 0.062 [0.0577, 0.0661] |
| four | 256 | 8 | all | 1 | 0.0158 | 291 | 0 | 0.0001 [0.0001, 0.0001] |
| four | 256 | 8 | all | 64 | 0.0123 | 307 | 1.58 | 0.0058 [0.0036, 0.0093] |
| four | 256 | 8 | all | 256 | 0.0121 | 317 | 6.69 | 0.0316 [0.0282, 0.0354] |
| four | 256 | 32 | 4 | 1 | 0.0439 | 143 | 2.93 | 0.0037 [0.0008, 0.0181] |
| four | 256 | 32 | 4 | 64 | 0.0326 | 154 | 14.6 | 0.0799 [0.047, 0.136] |
| four | 256 | 32 | 4 | 256 | 0.0325 | 159 | 30.6 | 0.243 [0.23, 0.256] |
| four | 256 | 32 | all | 1 | 0.0443 | 1.19e+03 | 3.08 | 0.0004 [0.0001, 0.0026] |
| four | 256 | 32 | all | 64 | 0.0321 | 1.03e+03 | 14.2 | 0.0116 [0.0062, 0.0214] |
| four | 256 | 32 | all | 256 | 0.0319 | 1.08e+03 | 42 | 0.0457 [0.0387, 0.0539] |
| four | 256 | 512 | 4 | 1 | 0.583 | 113 | 0 | 0.0057 [0.0052, 0.0063] |
| four | 256 | 512 | 4 | 64 | 0.442 | 110 | 6.83 | 0.314 [0.301, 0.328] |
| four | 256 | 512 | 4 | 256 | 0.436 | 114 | 38.1 | 1.32 [1.27, 1.37] |
| four | 256 | 512 | all | 1 | 0.53 | 1.29e+04 | 7.71 | 0.0004 [0.0002, 0.0009] |
| four | 256 | 512 | all | 64 | 0.447 | 1.43e+04 | 137 | 0.0115 [0.0107, 0.0124] |
| four | 256 | 512 | all | 256 | 0.455 | 1.5e+04 | 584 | 0.0456 [0.0427, 0.0484] |
| six | 4 | 8 | 4 | 1 | 0.0103 | 37 | 0 | 0.0003 [0.0002, 0.0003] |
| six | 4 | 8 | 4 | 64 | 0.0117 | 135 | 26.3 | 0.0907 [0.0416, 0.197] |
| six | 4 | 8 | all | 1 | 0.00981 | 73 | 0 | 0.0001 [0.0001, 0.0001] |
| six | 4 | 8 | all | 64 | 0.0115 | 256 | 33.1 | 0.0644 [0.0305, 0.136] |
| six | 4 | 32 | 4 | 1 | 0.0285 | 38.2 | 0 | 0.0008 [0.0006, 0.0012] |
| six | 4 | 32 | 4 | 64 | 0.0333 | 156 | 65.7 | 0.51 [0.411, 0.631] |
| six | 4 | 32 | all | 1 | 0.0294 | 349 | 0.0703 | 0.0003 [0.0002, 0.0003] |
| six | 4 | 32 | all | 64 | 0.0335 | 1.28e+03 | 241 | 0.185 [0.172, 0.198] |
| six | 16 | 8 | 4 | 1 | 0.0137 | 213 | 0.17 | 0.0015 [0.001, 0.0024] |
| six | 16 | 8 | 4 | 64 | 0.0101 | 303 | 1.31 | 0.0325 [0.0072, 0.146] |
| six | 16 | 8 | 4 | 256 | 0.0112 | 707 | 56 | 0.0882 [0.0174, 0.447] |
| six | 16 | 8 | all | 1 | 0.0133 | 488 | 0.184 | 0.0007 [0.0005, 0.0011] |
| six | 16 | 8 | all | 64 | 0.01 | 666 | 1.7 | 0.0178 [0.0034, 0.0935] |
| six | 16 | 8 | all | 256 | 0.0112 | 1.42e+03 | 58.6 | 0.0635 [0.0104, 0.387] |
| six | 16 | 32 | 4 | 1 | 0.0432 | 440 | 0 | 0.0001 [0.0001, 0.0001] |
| six | 16 | 32 | 4 | 64 | 0.0356 | 788 | 216 | 0.286 [0.271, 0.302] |
| six | 16 | 32 | 4 | 256 | 0.039 | 2.03e+03 | 872 | 0.422 [0.289, 0.623] |
| six | 16 | 32 | all | 1 | 0.0433 | 3.89e+03 | 0.267 | 0.0001 [0.0001, 0.0001] |
| six | 16 | 32 | all | 64 | 0.0358 | 6.37e+03 | 598 | 0.106 [0.086, 0.132] |
| six | 16 | 32 | all | 256 | 0.039 | 1.47e+04 | 2.7e+03 | 0.175 [0.0962, 0.317] |

Over all 146 cells, hybrid and push are each cheaper than pull with the whole 95% interval below 1 in 139 cells, more expensive in 6, undecided in 1 (`four`, 64 blocks, 512 views, scope 4, w = 64: 0.995 [0.896, 1.12]).

#### Crossover against pull

Linear interpolation of the log cost ratio in log of the axis; 95% bootstrap interval over pairs; share of 2,000 replicates that are cheaper at every level / cross / dearer at every level. Only comparisons that are not cheaper than pull in every replicate are listed.

#### Crossover along writes_per_read

| mix | blocks | views | read_scope | arm | kind | crossover | 95% CI | share cheaper/crosses/dearer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| four | 16 | 32 | 4 | push | crosses | 129 | [124.054, 134.048] | 0.0/1.0/0.0 |
| four | 16 | 32 | 4 | hybrid | crosses | 131 | [125.925, 135.634] | 0.0/1.0/0.0 |
| four | 16 | 128 | 4 | push | crosses | 55.50 | [53.008, 58.193] | 0.0/1.0/0.0 |
| four | 16 | 128 | 4 | hybrid | crosses | 55.00 | [52.379, 57.912] | 0.0/1.0/0.0 |
| four | 64 | 128 | 4 | push | crosses | 179 | [174.053, 183.271] | 0.0/1.0/0.0 |
| four | 64 | 128 | 4 | hybrid | crosses | 178 | [170.163, 183.136] | 0.0/1.0/0.0 |
| four | 64 | 512 | 4 | push | crosses | 65.76 | [59.674, 71.68] | 0.0/1.0/0.0 |
| four | 64 | 512 | 4 | hybrid | crosses | 64.36 | [56.728, 71.892] | 0.0/1.0/0.0 |
| four | 256 | 512 | 4 | push | crosses | 197 | [189.782, 203.859] | 0.0/1.0/0.0 |
| four | 256 | 512 | 4 | hybrid | crosses | 196 | [190.365, 202.554] | 0.0/1.0/0.0 |
| six | 16 | 8 | 4 | push | cheaper_everywhere | - | [254.135, 255.609] | 0.9885/0.0115/0.0 |
| six | 16 | 8 | 4 | hybrid | cheaper_everywhere | - | [255.46, 255.932] | 0.9845/0.0155/0.0 |

48 of 60 comparisons along writes_per_read are cheaper than pull at every level in every bootstrap replicate.

#### Crossover along views

| mix | blocks | read_scope | writes_per_read | arm | kind | crossover | 95% CI | share cheaper/crosses/dearer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| four | 16 | 4 | 64 | push | crosses | 90.50 | [82.617, 100.456] | 0.0/1.0/0.0 |
| four | 16 | 4 | 64 | hybrid | crosses | 88.48 | [79.583, 99.568] | 0.0/1.0/0.0 |
| four | 16 | 4 | 256 | push | crosses | 14.30 | [13.529, 15.165] | 0.0/1.0/0.0 |
| four | 16 | 4 | 256 | hybrid | crosses | 14.49 | [13.792, 15.191] | 0.0/1.0/0.0 |
| four | 64 | 4 | 64 | push | cheaper_everywhere | - | [455.775, 510.806] | 0.7055/0.2945/0.0 |
| four | 64 | 4 | 64 | hybrid | cheaper_everywhere | - | [435.178, 510.122] | 0.5375/0.4625/0.0 |
| four | 64 | 4 | 256 | push | crosses | 60.34 | [56.843, 63.813] | 0.0/1.0/0.0 |
| four | 64 | 4 | 256 | hybrid | crosses | 57.86 | [53.671, 61.929] | 0.0/1.0/0.0 |
| four | 256 | 4 | 256 | push | crosses | 359 | [342.064, 377.166] | 0.0/1.0/0.0 |
| four | 256 | 4 | 256 | hybrid | crosses | 359 | [343.113, 375.655] | 0.0/1.0/0.0 |
| six | 16 | 4 | 256 | push | cheaper_everywhere | - | [8.034, 8.196] | 0.985/0.015/0.0 |
| six | 16 | 4 | 256 | hybrid | cheaper_everywhere | - | [8.003, 8.084] | 0.984/0.016/0.0 |

84 of 96 comparisons along views are cheaper than pull at every level in every bootstrap replicate.

#### Crossover along blocks

| mix | views | read_scope | writes_per_read | arm | kind | crossover | 95% CI | share cheaper/crosses/dearer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| four | 32 | 4 | 256 | push | crosses | 33.39 | [31.526, 35.305] | 0.0/1.0/0.0 |
| four | 32 | 4 | 256 | hybrid | crosses | 33.83 | [32.019, 35.92] | 0.0/1.0/0.0 |
| four | 128 | 4 | 64 | push | crosses | 18.39 | [17.562, 19.228] | 0.0/1.0/0.0 |
| four | 128 | 4 | 64 | hybrid | crosses | 18.58 | [17.677, 19.499] | 0.0/1.0/0.0 |
| four | 128 | 4 | 256 | push | crosses | 97.26 | [93.655, 101.58] | 0.0/1.0/0.0 |
| four | 128 | 4 | 256 | hybrid | crosses | 97.91 | [93.42, 103.948] | 0.0/1.0/0.0 |
| four | 512 | 4 | 64 | push | cheaper_everywhere | - | [64.127, 70.751] | 0.715/0.285/0.0 |
| four | 512 | 4 | 64 | hybrid | cheaper_everywhere | - | [64.206, 73.397] | 0.528/0.472/0.0 |
| four | 512 | 4 | 256 | push | dearer_everywhere | - | None | 0.0/0.0/1.0 |
| four | 512 | 4 | 256 | hybrid | dearer_everywhere | - | None | 0.0/0.0/1.0 |

102 of 112 comparisons along blocks are cheaper than pull at every level in every bootstrap replicate.

## Conclusion

In the tested range (4-256 blocks, about 180-10,900 claims; 8-512 standing views; 1-256 writes per read), re-querying at read time is **not** cheaper than push filtering except in one corner. When a read checks every standing view, push and hybrid are cheaper than pull in every cell, by a factor of about 2 to 10,000 (paired ratio 0.0001-0.54, every upper 95% bound at most 0.56); at the largest write rate tested (256 writes per read) hybrid still costs 0.03-0.54 of pull. Pull is cheaper only when a read checks a few views (4) while many views stand and many writes arrive between reads: the crossover in writes per read is about 55 (95% interval 52-58) at 16 blocks and 128 views, 64 (57-72) at 64 blocks and 512 views, 178 (170-183) at 64 blocks and 128 views, and 196 (190-203) at 256 blocks and 512 views. It moves to higher write rates as the graph grows, because write-side matching costs about 1 microsecond per standing view per write regardless of graph size, while a re-query costs milliseconds and grows with the graph. A rule that fits every measured cell: hybrid is cheaper than pull when (writes per read) x (standing views) x 1 us is below (views checked per read) x (re-query time per view).

So the narrowing condition of RQ2 ("read-time re-query with fingerprints is not more expensive in any stratum") is **not** met in this range, and RQ2 does not narrow on cost grounds. The plan's expectation (5.4) that pull is enough at dialogue scale holds only in absolute terms: at 16 blocks pull costs 6-50 ms per read for 8-32 views of the `four` mix, which is small next to an LLM call, but it is not cheaper than push filtering. Pull and hybrid repair the same views, so hybrid's saving is database time only.

Two limits of the evidence. (1) The `pending` and `choice` families are measured only on small graphs (`six`, up to 16 blocks), because their compiled queries are pathologically slow: the compiled `pending` query takes 500-950 ms at 16 blocks and 8-15 s at 64 blocks, against 3.5-34 ms for the same SPARQL with its constants inlined instead of bound with `VALUES`. This is a property of the current compiler with pyoxigraph 0.5.13, not of the staleness strategies, and it inflates pull (and every re-evaluation) wherever these families stand; a compiler change that inlines single-IRI constants would be needed before these families can be measured at scale. (2) The graphs interleave independent generated sequences, so each write touches one block's views; a history whose writes concentrate on the standing views would mark more views per write and move the crossover to lower write rates. The write-side cost also reflects T019's matching, which loops over every view for every change set; an index from predicates to views would lower it further.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session m01-E004 started (Issue #94, branch `task/E004-scale-experiment`, base `63f9d4fff7021651c9626af18bdc0a25ce50e557`). Status to record: `E004: planned -> active`.
- 2026-11-25: calibration on prototype graphs (not formal runs, no numbers quoted from it): view queries of the five families grow about linearly with the graph; the compiled `pending` query grows about quadratically and is two orders of magnitude slower than with constants inlined, which bounds the `six` grid. Design written above before the first formal run.
- 2026-11-25: first formal launch of design version 1 at `9038ce2` (10 runs of view mix `five` started, 20:25 UTC). The `choice` views with an accepted candidate took seconds per query at 64 blocks (the five-family calibration had timed only block 0, whose choice views were empty), so the `five` grid could not finish in budget. All 10 runs were stopped at 20:35 UTC and marked `failed` with the cause; their reports are in the Runs table and none of their numbers is used. Design version 2: view mix `four` (list, current, count, constraints) replaces `five`, standing views 8, 32, 128, 512, `six` with 8 and 32 views; the compiled `choice` query joins `pending` among the families timed only up to 64 blocks.
- 2026-11-25: design version 2 launched at `fac294f` (30 runs, 10 at a time, 20:36-22:15 UTC); all 30 `completed`. Reports written for all 40 runs; summary `summary-20261125T2216Z`. Results and Conclusion filled from the 30 completed runs. Status to record: `E004: active -> review` with the PR.
