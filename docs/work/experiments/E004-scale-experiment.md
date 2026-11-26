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

### Addendum: design version 3 (2026-11-26)

Written on 2026-11-26, before any run of version 3, after the user decided to fix the query compiler and rerun all six template families on large graphs. Version 2 above, its config and its 30 runs stay as they are; the Results of version 2 stay visible below, and version 3 adds its own Runs and Results.

| Item | Version 3 |
| --- | --- |
| Compiler change | `CompiledQuery.bind` (T017, `src/grace/context/pipeline/query/compile.py`) writes an entity constant whose equivalence class at the cut-off has one member directly into its triple patterns instead of binding it with `VALUES ?_k<j> { <iri> }`; a class with several members (entity merges) keeps its `VALUES` block. The compiled text (`CompiledQuery.main`) is unchanged; only the executed, bound text changes, for every family (subject, speaker and object constants). Literals now write `%` and `?` as code-point escapes, so a literal can no longer collide with a placeholder. Rows are identical by construction and by test (`tests/integration/test_inline_constants.py`: the T017 fixture suite at every version in both serialisations, with and without merges, and every binding of all six families on scaled graphs). This deliberately changes the query text the engine runs, which every timing of version 2 depends on; it is user-approved (2026-11-26) |
| Config | `configs/experiments/E004-scale-experiment-v3.yaml` (version 3); the version-2 config is not edited |
| Grid | `six` and `four` each on blocks {16, 64, 256} x views {8, 32, 128, 512}, a number of views above the admitted bindings not run (`six`: 15 per block, so 16 blocks x 512 views is not run; `four`: 9 per block, so 16 blocks x 512 views is not run); each x read scope {4, all} x writes per read {1, 4, 16, 64, 256}; seeds 1 and 2; 44 runs. Everything else (generator, families, prefix, arms, repetitions, reads, measurement, statistics, caps: 8 h per run, at most 10 concurrently) is unchanged |
| Why `four` is rerun | The change alters the executed text of all four `four` families too (version 2 diagnostics: their inlined form was 3-20% faster), so pull costs and the crossovers move; a like-for-like comparison of `six` and `four` needs both on the same code. `four` costs about 1.6 h of wall time for its longest run |
| Diagnostics | Per run, block 0's 15 bindings plus a seeded sample of 12 bindings per family from the other blocks (block 0's `choice` views are often empty), timed at the prefix head (minimum of 3) in the engine's text (`compiled`) and as the probe's independent inlining of the pre-change `VALUES` form (`inlined`; `inlined_text_equal` records whether the two texts are identical); block 0's bindings also in the pre-change `VALUES` form (`values`), for `pending` and `choice` only up to 64 blocks. Row counts of all forms must agree |
| Expectations (from calibration, not formal) | On a 64-block graph the pre-change `VALUES` form of one `pending` view took 20 s and of one `choice` view 3.5 s; the inlined forms took 0.2-54 ms and 0.7-47 ms. On 256 blocks the inlined `pending` query takes up to about 200 ms |

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

### Runs of design version 3 (2026-11-26)

Code `aa2c5470d73eaf04f90be72244de1035e48579f9` (clean worktree in every `run.json`), config `configs/experiments/E004-scale-experiment-v3.yaml`; 44 runs launched 02:42 UTC, at most 10 concurrently, all `completed` by 04:32 UTC (longest run 1.8 h, under the 8 h cap). Launch log, order and exit codes: `runs/E004/artifacts/manager/E004-v3-launch/`. Aggregation over the 44 runs: `runs/E004/artifacts/manager/E004-summary/summary-20261126T0433Z/summary.json` (SHA-256 `cb4048ff3b0b99fb82fe79caef2382483ad4299fbbcecf3c876b5b8b308f26dd`). The later commits on the branch change only a docstring and this file.

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| `E004-20261126T024252Z-0af9` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T024252Z-0af9/report.yaml` (six, 256 blocks, seed 1, 128 views) |
| `E004-20261126T024252Z-2edb` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T024252Z-2edb/report.yaml` (four, 256 blocks, seed 2, 512 views) |
| `E004-20261126T024252Z-357c` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T024252Z-357c/report.yaml` (six, 256 blocks, seed 1, 512 views) |
| `E004-20261126T024252Z-5506` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T024252Z-5506/report.yaml` (six, 256 blocks, seed 1, 32 views) |
| `E004-20261126T024252Z-7abe` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T024252Z-7abe/report.yaml` (four, 256 blocks, seed 2, 128 views) |
| `E004-20261126T024252Z-8c87` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T024252Z-8c87/report.yaml` (four, 256 blocks, seed 1, 512 views) |
| `E004-20261126T024252Z-aa52` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T024252Z-aa52/report.yaml` (six, 256 blocks, seed 2, 512 views) |
| `E004-20261126T024252Z-ad52` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T024252Z-ad52/report.yaml` (four, 256 blocks, seed 1, 128 views) |
| `E004-20261126T024252Z-bb78` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T024252Z-bb78/report.yaml` (six, 256 blocks, seed 2, 128 views) |
| `E004-20261126T024252Z-f342` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T024252Z-f342/report.yaml` (six, 256 blocks, seed 2, 32 views) |
| `E004-20261126T025933Z-a222` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T025933Z-a222/report.yaml` (four, 256 blocks, seed 1, 32 views) |
| `E004-20261126T030056Z-de09` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T030056Z-de09/report.yaml` (four, 256 blocks, seed 2, 32 views) |
| `E004-20261126T031429Z-c253` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T031429Z-c253/report.yaml` (six, 256 blocks, seed 1, 8 views) |
| `E004-20261126T031452Z-757f` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T031452Z-757f/report.yaml` (six, 256 blocks, seed 2, 8 views) |
| `E004-20261126T031530Z-c59f` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T031530Z-c59f/report.yaml` (four, 256 blocks, seed 1, 8 views) |
| `E004-20261126T031706Z-9197` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T031706Z-9197/report.yaml` (four, 256 blocks, seed 2, 8 views) |
| `E004-20261126T031853Z-61e6` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T031853Z-61e6/report.yaml` (six, 64 blocks, seed 1, 512 views) |
| `E004-20261126T031920Z-bffd` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T031920Z-bffd/report.yaml` (six, 64 blocks, seed 2, 512 views) |
| `E004-20261126T032809Z-1133` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T032809Z-1133/report.yaml` (four, 64 blocks, seed 1, 512 views) |
| `E004-20261126T032946Z-33fb` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T032946Z-33fb/report.yaml` (four, 64 blocks, seed 2, 512 views) |
| `E004-20261126T033137Z-2200` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T033137Z-2200/report.yaml` (six, 64 blocks, seed 1, 128 views) |
| `E004-20261126T033149Z-1935` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T033149Z-1935/report.yaml` (six, 64 blocks, seed 2, 128 views) |
| `E004-20261126T034244Z-0d25` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T034244Z-0d25/report.yaml` (four, 64 blocks, seed 1, 128 views) |
| `E004-20261126T034416Z-82e5` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T034416Z-82e5/report.yaml` (four, 64 blocks, seed 2, 128 views) |
| `E004-20261126T034917Z-018e` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T034917Z-018e/report.yaml` (six, 64 blocks, seed 1, 32 views) |
| `E004-20261126T035012Z-9318` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035012Z-9318/report.yaml` (six, 64 blocks, seed 2, 32 views) |
| `E004-20261126T035158Z-a579` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035158Z-a579/report.yaml` (four, 64 blocks, seed 1, 32 views) |
| `E004-20261126T035258Z-d422` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035258Z-d422/report.yaml` (four, 64 blocks, seed 2, 32 views) |
| `E004-20261126T035302Z-5dee` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035302Z-5dee/report.yaml` (six, 64 blocks, seed 1, 8 views) |
| `E004-20261126T035338Z-27f9` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035338Z-27f9/report.yaml` (six, 64 blocks, seed 2, 8 views) |
| `E004-20261126T035543Z-821f` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035543Z-821f/report.yaml` (four, 64 blocks, seed 1, 8 views) |
| `E004-20261126T035650Z-91df` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035650Z-91df/report.yaml` (four, 64 blocks, seed 2, 8 views) |
| `E004-20261126T035811Z-6ca8` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035811Z-6ca8/report.yaml` (six, 16 blocks, seed 1, 128 views) |
| `E004-20261126T035816Z-c94a` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035816Z-c94a/report.yaml` (six, 16 blocks, seed 2, 128 views) |
| `E004-20261126T035828Z-7c35` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035828Z-7c35/report.yaml` (four, 16 blocks, seed 1, 128 views) |
| `E004-20261126T035911Z-e5cb` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T035911Z-e5cb/report.yaml` (four, 16 blocks, seed 2, 128 views) |
| `E004-20261126T040048Z-b3be` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T040048Z-b3be/report.yaml` (six, 16 blocks, seed 1, 32 views) |
| `E004-20261126T040138Z-5a93` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T040138Z-5a93/report.yaml` (six, 16 blocks, seed 2, 32 views) |
| `E004-20261126T040142Z-54e1` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T040142Z-54e1/report.yaml` (four, 16 blocks, seed 1, 32 views) |
| `E004-20261126T040146Z-2a29` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T040146Z-2a29/report.yaml` (four, 16 blocks, seed 2, 32 views) |
| `E004-20261126T040146Z-6beb` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T040146Z-6beb/report.yaml` (six, 16 blocks, seed 1, 8 views) |
| `E004-20261126T040209Z-bc75` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T040209Z-bc75/report.yaml` (six, 16 blocks, seed 2, 8 views) |
| `E004-20261126T040226Z-3296` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T040226Z-3296/report.yaml` (four, 16 blocks, seed 1, 8 views) |
| `E004-20261126T040248Z-5900` | 2026-11-26 | completed | `aa2c547` | `runs/E004/artifacts/manager/E004/E004-20261126T040248Z-5900/report.yaml` (four, 16 blocks, seed 2, 8 views) |

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

### Results of design version 3 (addendum, 2026-11-26)

All numbers below are copied from `runs/E004/artifacts/manager/E004-summary/summary-20261126T0433Z/summary.json` (44 completed runs at `aa2c547`, 3,960 measurements: 220 cells x 3 arms x 2 seeds x 3 repetitions). The version-2 results above are not changed; where this section compares with them, "v2" means `summary-20261125T2216Z`. Machine as above; 1-minute load average 3.7-30.4 during the measurements; CPU time / wall time 0.996-1.007 per measurement.

**Checks.** Pull and hybrid repaired exactly the same views with the same actions at every read in every measurement pair (`repairs_differ_pull_hybrid: 0`); `llm_calls: 0`. In every run and family the engine's text and the probe's independent inlining of the pre-change text are identical (`inlined_text_equal`), and all timed forms returned the same row counts (`rows_agree`).

**Noise.** Median coefficient of variation of the period cost across the 3 repetitions of a seed 0.015 (90th percentile 0.053, maximum 0.170); across the 2 seeds 0.19 (90th percentile 1.05).

**The compiler change removes the `pending` and `choice` pathology.** For block 0's `pending` views the pre-change `VALUES` form took 501-948 ms at 16 blocks and 8,030-15,000 ms at 64 blocks; the engine's text now takes 3.3-5.8 ms and 14.8-28 ms, and 78-147 ms at 256 blocks (where the old form was not timed). Over the sample of 12 other `pending` views per graph the median is 0.2-77 ms and the maximum 8.5-8.6 ms (16 blocks), 31-50 ms (64 blocks) and 149-248 ms (256 blocks). `choice` views cost under 1 ms when empty and up to 11 ms (16 blocks), 44 ms (64 blocks) and 103 ms (256 blocks) in the sample; few sampled `choice` views have rows (0-2 of 12), so its cost with an accepted candidate rests on few views. For the four other families the change is small: their engine text is 0-20% faster than the old `VALUES` form, and pull over `four` costs a median 0.90 (10th-90th percentile 0.79-0.95) of its v2 value in matching cells.

#### Graphs and query time per family (v3)

| Mix | Blocks | Seed | Claims | Triples | Block-0 median ms, engine text / probe-inlined / pre-change VALUES (`-`: not timed) | Sample of 12 other views per family: median / max ms (views with rows) |
| --- | --- | --- | --- | --- | --- | --- |
| four | 16 | 1 | 685 | 21145 | choice 0.665/0.632/0.879; constraints 0.154/0.145/0.188; count 0.75/0.748/0.872; current 1.24/1.22/1.36; list 0.765/0.76/0.876; pending 3.37/3.13/501 | choice 0.638/11.3 (0); constraints 0.15/1.64 (7); count 0.868/1.72 (11); current 1.29/2.42 (12); list 0.683/2.22 (10); pending 2.75/8.45 (0) |
| four | 16 | 2 | 694 | 21097 | choice 0.682/0.635/0.875; constraints 0.158/0.152/0.198; count 0.975/0.962/1.1; current 1.18/1.16/1.28; list 0.995/0.947/1.11; pending 5.61/5.58/948 | choice 0.632/0.653 (0); constraints 0.154/1.9 (10); count 0.977/2.08 (11); current 0.873/2.12 (12); list 0.68/2.39 (10); pending 0.183/8.51 (1) |
| four | 64 | 1 | 2729 | 84180 | choice 0.814/0.683/0.916; constraints 0.186/0.18/0.236; count 2.73/2.71/3.1; current 4.71/4.45/4.86; list 2.84/2.74/3.04; pending 14.8/14/8.03e+03 | choice 0.745/34.9 (1); constraints 0.156/8.82 (7); count 3.25/8.49 (9); current 3.71/9.49 (12); list 3.6/9.2 (11); pending 12.4/41.9 (1) |
| four | 64 | 2 | 2718 | 84419 | choice 0.834/0.696/0.918; constraints 0.175/0.173/0.219; count 3.55/3.5/3.95; current 4.43/4.34/4.62; list 3.67/3.58/4; pending 26.2/24.9/1.5e+04 | choice 0.664/0.693 (0); constraints 0.179/5.24 (8); count 4.06/14.2 (9); current 4.49/10.7 (12); list 3.96/14.8 (11); pending 13.6/31.4 (3) |
| four | 256 | 1 | 10882 | 335935 | choice 0.82/0.782/-; constraints 0.212/0.197/0.267; count 10.9/10.4/11.3; current 25.6/26.2/27.1; list 11.8/11.2/12.1; pending 77.9/79.8/- | choice 0.868/102 (2); constraints 0.193/28.4 (7); count 15/36.9 (10); current 25.1/77.5 (12); list 22.4/40 (10); pending 0.265/151 (1) |
| four | 256 | 2 | 10829 | 336528 | choice 0.825/0.762/-; constraints 0.217/0.206/0.262; count 14.5/14.5/15.8; current 23.5/25.4/27.1; list 16.4/15.5/16.2; pending 147/154/- | choice 0.732/103 (0); constraints 0.193/26.1 (7); count 5.54/21.8 (12); current 19/56.4 (12); list 11.3/52.7 (11); pending 74.2/245 (1) |
| six | 16 | 1 | 685 | 21145 | choice 0.659/0.629/0.858; constraints 0.16/0.147/0.195; count 0.774/0.758/0.875; current 1.24/1.24/1.35; list 0.779/0.754/0.878; pending 3.29/3.11/501 | choice 0.636/11.3 (0); constraints 0.153/1.61 (7); count 0.889/1.79 (11); current 1.31/2.48 (12); list 0.681/2.21 (10); pending 2.8/8.64 (0) |
| six | 16 | 2 | 694 | 21097 | choice 0.669/0.63/0.89; constraints 0.16/0.152/0.204; count 0.975/0.983/1.1; current 1.2/1.17/1.29; list 1.01/0.988/1.13; pending 5.8/5.61/940 | choice 0.632/0.652 (0); constraints 0.154/1.94 (10); count 1/2.14 (11); current 0.876/2.17 (12); list 0.698/2.46 (10); pending 0.187/8.54 (1) |
| six | 64 | 1 | 2729 | 84180 | choice 0.806/0.683/0.906; constraints 0.186/0.175/0.233; count 2.67/2.64/2.95; current 4.68/4.55/4.85; list 2.83/2.72/3.01; pending 16.7/16.1/8.05e+03 | choice 0.748/43.6 (1); constraints 0.163/9.29 (7); count 3.41/8.63 (9); current 3.82/10 (12); list 3.5/8.86 (11); pending 14.1/50.1 (1) |
| six | 64 | 2 | 2718 | 84419 | choice 0.817/0.689/0.921; constraints 0.186/0.177/0.236; count 3.65/3.65/3.99; current 4.49/4.38/4.56; list 3.64/3.6/3.97; pending 28/27.3/1.5e+04 | choice 0.669/0.719 (0); constraints 0.196/5.43 (8); count 4.07/14.2 (9); current 4.33/10.5 (12); list 3.84/14.2 (11); pending 15/31.7 (3) |
| six | 256 | 1 | 10882 | 335935 | choice 0.817/0.782/-; constraints 0.203/0.196/0.256; count 13.5/12.5/13.5; current 26.8/26.3/27.9; list 14.1/13.8/15.2; pending 77.7/76.1/- | choice 0.773/99.1 (2); constraints 0.194/37.2 (7); count 15.3/35.9 (10); current 21.3/76.1 (12); list 23.1/36.5 (10); pending 0.263/149 (1) |
| six | 256 | 2 | 10829 | 336528 | choice 0.829/0.772/-; constraints 0.212/0.203/0.258; count 15.3/15.2/16.5; current 22.5/22.3/25.3; list 15.2/15/16.5; pending 139/152/- | choice 0.708/99.5 (0); constraints 0.195/25.8 (7); count 5.7/21.2 (12); current 18.4/55.2 (12); list 9.52/44 (11); pending 76.5/248 (1) |


#### Selected cells (v3)

| Mix | Blocks | Views | Scope | w | push write ms | pull read ms | hybrid read ms | hybrid / pull [95% CI] |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| four | 16 | 128 | 4 | 1 | 0.103 | 8.03 | 0.301 | 0.0354 [0.0183, 0.0689] |
| four | 16 | 128 | 4 | 64 | 0.0906 | 9.51 | 5.38 | 1.18 [1.15, 1.23] |
| four | 16 | 128 | 4 | 256 | 0.0973 | 17.1 | 14.5 | 2.32 [2.24, 2.4] |
| four | 16 | 128 | all | 1 | 0.106 | 224 | 0.822 | 0.0041 [0.0034, 0.005] |
| four | 16 | 128 | all | 64 | 0.0915 | 266 | 40.9 | 0.174 [0.163, 0.186] |
| four | 16 | 128 | all | 256 | 0.0989 | 462 | 201 | 0.49 [0.487, 0.493] |
| four | 64 | 8 | 4 | 1 | 0.013 | 11 | 0 | 0.0012 [0.0011, 0.0013] |
| four | 64 | 8 | 4 | 64 | 0.0107 | 14.2 | 1.33 | 0.106 [0.0621, 0.181] |
| four | 64 | 8 | 4 | 256 | 0.0108 | 17.8 | 3.86 | 0.374 [0.366, 0.383] |
| four | 64 | 8 | all | 1 | 0.0125 | 22.4 | 0 | 0.0006 [0.0005, 0.0006] |
| four | 64 | 8 | all | 64 | 0.0108 | 27.5 | 1.3 | 0.055 [0.0335, 0.0901] |
| four | 64 | 8 | all | 256 | 0.0108 | 34.2 | 4.06 | 0.198 [0.195, 0.202] |
| four | 64 | 32 | 4 | 1 | 0.0335 | 22.2 | 0.0266 | 0.0025 [0.0017, 0.0037] |
| four | 64 | 32 | 4 | 64 | 0.0291 | 25.7 | 3.06 | 0.19 [0.156, 0.23] |
| four | 64 | 32 | 4 | 256 | 0.0294 | 30.9 | 16.4 | 0.771 [0.757, 0.787] |
| four | 64 | 32 | all | 1 | 0.0338 | 169 | 0.0256 | 0.0003 [0.0002, 0.0005] |
| four | 64 | 32 | all | 64 | 0.0295 | 187 | 10.1 | 0.0631 [0.059, 0.0675] |
| four | 64 | 32 | all | 256 | 0.0299 | 225 | 40.5 | 0.213 [0.21, 0.217] |
| four | 64 | 512 | 4 | 1 | 0.47 | 24 | 0 | 0.0193 [0.0188, 0.0198] |
| four | 64 | 512 | 4 | 64 | 0.407 | 29.3 | 5.84 | 1.09 [0.985, 1.19] |
| four | 64 | 512 | 4 | 256 | 0.412 | 34.8 | 22.2 | 3.69 [3.43, 3.98] |
| four | 64 | 512 | all | 1 | 0.474 | 2.93e+03 | 2.23 | 0.0009 [0.0008, 0.0011] |
| four | 64 | 512 | all | 64 | 0.406 | 3.05e+03 | 110 | 0.0447 [0.0443, 0.0451] |
| four | 64 | 512 | all | 256 | 0.411 | 3.66e+03 | 516 | 0.169 [0.164, 0.174] |
| four | 256 | 8 | 4 | 1 | 0.0142 | 115 | 0 | 0.0001 [0.0001, 0.0002] |
| four | 256 | 8 | 4 | 64 | 0.0121 | 136 | 1.56 | 0.0129 [0.0083, 0.0199] |
| four | 256 | 8 | 4 | 256 | 0.0123 | 139 | 6.57 | 0.0707 [0.0657, 0.076] |
| four | 256 | 8 | all | 1 | 0.0145 | 222 | 0 | 0.0001 [0.0001, 0.0001] |
| four | 256 | 8 | all | 64 | 0.0119 | 253 | 1.44 | 0.0067 [0.0044, 0.0101] |
| four | 256 | 8 | all | 256 | 0.0119 | 259 | 6.26 | 0.0371 [0.0311, 0.0444] |
| four | 256 | 32 | 4 | 1 | 0.0398 | 105 | 2.63 | 0.0048 [0.0009, 0.025] |
| four | 256 | 32 | 4 | 64 | 0.0316 | 125 | 11.7 | 0.0847 [0.0508, 0.141] |
| four | 256 | 32 | 4 | 256 | 0.032 | 135 | 26.9 | 0.256 [0.236, 0.274] |
| four | 256 | 32 | all | 1 | 0.0408 | 903 | 2.4 | 0.0005 [0.0001, 0.0032] |
| four | 256 | 32 | all | 64 | 0.0324 | 955 | 12.5 | 0.0119 [0.0062, 0.0231] |
| four | 256 | 32 | all | 256 | 0.0322 | 995 | 37.5 | 0.047 [0.0395, 0.056] |
| four | 256 | 512 | 4 | 1 | 0.549 | 89.3 | 0 | 0.0061 [0.0053, 0.007] |
| four | 256 | 512 | 4 | 64 | 0.407 | 82.3 | 5.74 | 0.385 [0.365, 0.405] |
| four | 256 | 512 | 4 | 256 | 0.405 | 88 | 29.6 | 1.52 [1.48, 1.57] |
| four | 256 | 512 | all | 1 | 0.579 | 1.26e+04 | 9.37 | 0.0005 [0.0002, 0.0011] |
| four | 256 | 512 | all | 64 | 0.41 | 1.14e+04 | 103 | 0.0115 [0.0114, 0.0116] |
| four | 256 | 512 | all | 256 | 0.436 | 1.35e+04 | 509 | 0.047 [0.0434, 0.0513] |
| six | 16 | 128 | 4 | 1 | 0.142 | 8.52 | 0 | 0.0164 [0.0143, 0.0187] |
| six | 16 | 128 | 4 | 64 | 0.128 | 11.1 | 5.03 | 1.19 [1.09, 1.29] |
| six | 16 | 128 | 4 | 256 | 0.138 | 19.9 | 13 | 2.41 [2.3, 2.54] |
| six | 16 | 128 | all | 1 | 0.148 | 264 | 0.592 | 0.0025 [0.0017, 0.0036] |
| six | 16 | 128 | all | 64 | 0.13 | 323 | 54.1 | 0.193 [0.187, 0.2] |
| six | 16 | 128 | all | 256 | 0.139 | 570 | 231 | 0.465 [0.43, 0.502] |
| six | 64 | 8 | 4 | 1 | 0.0187 | 35.1 | 0.747 | 0.0049 [0.0012, 0.0193] |
| six | 64 | 8 | 4 | 64 | 0.0154 | 42.2 | 5.84 | 0.118 [0.075, 0.188] |
| six | 64 | 8 | 4 | 256 | 0.0157 | 48.5 | 15.3 | 0.327 [0.235, 0.454] |
| six | 64 | 8 | all | 1 | 0.0192 | 71.9 | 0.794 | 0.0025 [0.0007, 0.0094] |
| six | 64 | 8 | all | 64 | 0.0156 | 84.2 | 11.8 | 0.092 [0.052, 0.162] |
| six | 64 | 8 | all | 256 | 0.0157 | 98 | 26.3 | 0.239 [0.168, 0.34] |
| six | 64 | 32 | 4 | 1 | 0.0469 | 30.2 | 0.585 | 0.0082 [0.0031, 0.0217] |
| six | 64 | 32 | 4 | 64 | 0.0425 | 32.4 | 6.25 | 0.267 [0.24, 0.296] |
| six | 64 | 32 | 4 | 256 | 0.0432 | 39.9 | 18 | 0.719 [0.682, 0.761] |
| six | 64 | 32 | all | 1 | 0.05 | 248 | 0.798 | 0.0012 [0.0004, 0.0036] |
| six | 64 | 32 | all | 64 | 0.0443 | 288 | 26.9 | 0.0778 [0.0477, 0.127] |
| six | 64 | 32 | all | 256 | 0.0442 | 344 | 70.8 | 0.213 [0.162, 0.282] |
| six | 64 | 512 | 4 | 1 | 0.705 | 29.5 | 0 | 0.0234 [0.0213, 0.0258] |
| six | 64 | 512 | 4 | 64 | 0.613 | 35.2 | 11.7 | 1.44 [1.36, 1.54] |
| six | 64 | 512 | 4 | 256 | 0.61 | 41.9 | 22.1 | 4.24 [4.13, 4.36] |
| six | 64 | 512 | all | 1 | 0.738 | 3.7e+03 | 3.86 | 0.0011 [0.0007, 0.0016] |
| six | 64 | 512 | all | 64 | 0.621 | 3.78e+03 | 590 | 0.164 [0.151, 0.18] |
| six | 64 | 512 | all | 256 | 0.611 | 4.49e+03 | 1.23e+03 | 0.308 [0.29, 0.327] |
| six | 256 | 8 | 4 | 1 | 0.0212 | 66.1 | 0 | 0.0004 [0.0002, 0.0008] |
| six | 256 | 8 | 4 | 64 | 0.0181 | 73.2 | 1.76 | 0.0455 [0.0208, 0.101] |
| six | 256 | 8 | 4 | 256 | 0.0181 | 77.8 | 2.08 | 0.103 [0.0565, 0.189] |
| six | 256 | 8 | all | 1 | 0.0207 | 132 | 0 | 0.0002 [0.0001, 0.0004] |
| six | 256 | 8 | all | 64 | 0.0184 | 141 | 2.58 | 0.031 [0.0145, 0.0661] |
| six | 256 | 8 | all | 256 | 0.0182 | 146 | 3.54 | 0.0686 [0.0371, 0.126] |
| six | 256 | 32 | 4 | 1 | 0.0571 | 101 | 0 | 0.0006 [0.0004, 0.0008] |
| six | 256 | 32 | 4 | 64 | 0.049 | 98 | 4.05 | 0.0645 [0.0389, 0.105] |
| six | 256 | 32 | 4 | 256 | 0.0453 | 105 | 13.3 | 0.242 [0.214, 0.273] |
| six | 256 | 32 | all | 1 | 0.0496 | 593 | 0 | 0.0001 [0.0001, 0.0001] |
| six | 256 | 32 | all | 64 | 0.0454 | 630 | 13.2 | 0.0259 [0.0238, 0.028] |
| six | 256 | 32 | all | 256 | 0.0454 | 693 | 36.2 | 0.0687 [0.0679, 0.0695] |
| six | 256 | 512 | 4 | 1 | 0.701 | 178 | 0 | 0.0044 [0.0038, 0.0051] |
| six | 256 | 512 | 4 | 64 | 0.613 | 155 | 39.8 | 0.506 [0.423, 0.605] |
| six | 256 | 512 | 4 | 256 | 0.612 | 175 | 84.7 | 1.36 [1.29, 1.44] |
| six | 256 | 512 | all | 1 | 0.757 | 1.63e+04 | 1.48 | 0.0001 [0.0001, 0.0002] |
| six | 256 | 512 | all | 64 | 0.681 | 1.68e+04 | 1.68e+03 | 0.105 [0.0963, 0.115] |
| six | 256 | 512 | all | 256 | 0.657 | 1.67e+04 | 2.89e+03 | 0.189 [0.179, 0.201] |

#### Crossover along writes_per_read (v3; comparisons not cheaper everywhere)

| mix | blocks | views | read_scope | arm | kind | crossover | 95% CI | share cheaper/crosses/dearer | v2 crossover |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| four | 16 | 32 | 4 | push | crosses | 126 | [123, 129] | 0.0/1.0/0.0 | 129 |
| four | 16 | 32 | 4 | hybrid | crosses | 129 | [124, 134] | 0.0/1.0/0.0 | 131 |
| four | 16 | 128 | 4 | push | crosses | 52.1 | [49.8, 54.6] | 0.0/1.0/0.0 | 55.5 |
| four | 16 | 128 | 4 | hybrid | crosses | 51.6 | [49.8, 53.4] | 0.0/1.0/0.0 | 55 |
| four | 64 | 128 | 4 | push | crosses | 160 | [156, 165] | 0.0/1.0/0.0 | 179 |
| four | 64 | 128 | 4 | hybrid | crosses | 161 | [157, 165] | 0.0/1.0/0.0 | 178 |
| four | 64 | 512 | 4 | push | crosses | 58.1 | [52, 65.1] | 0.0/1.0/0.0 | 65.8 |
| four | 64 | 512 | 4 | hybrid | crosses | 58.3 | [52.4, 64.9] | 0.0/1.0/0.0 | 64.4 |
| four | 256 | 512 | 4 | push | crosses | 167 | [163, 172] | 0.0/1.0/0.0 | 197 |
| four | 256 | 512 | 4 | hybrid | crosses | 168 | [163, 172] | 0.0/1.0/0.0 | 196 |
| six | 16 | 8 | 4 | push | cheaper_everywhere | - | [247, 250] | 0.9895/0.0105/0.0 | cheaper_everywhere |
| six | 16 | 8 | 4 | hybrid | cheaper_everywhere | - | [246, 249] | 0.978/0.022/0.0 | cheaper_everywhere |
| six | 16 | 32 | 4 | push | crosses | 187 | [143, 253] | 0.015/0.985/0.0 | cheaper_everywhere |
| six | 16 | 32 | 4 | hybrid | crosses | 187 | [145, 249] | 0.0135/0.9865/0.0 | cheaper_everywhere |
| six | 16 | 128 | 4 | push | crosses | 51.5 | [47.4, 56.2] | 0.0/1.0/0.0 | not run |
| six | 16 | 128 | 4 | hybrid | crosses | 51.6 | [47.5, 56.8] | 0.0/1.0/0.0 | not run |
| six | 64 | 128 | 4 | push | crosses | 119 | [116, 121] | 0.0/1.0/0.0 | not run |
| six | 64 | 128 | 4 | hybrid | crosses | 118 | [116, 121] | 0.0/1.0/0.0 | not run |
| six | 64 | 512 | 4 | push | crosses | 39.1 | [36.7, 41.8] | 0.0/1.0/0.0 | not run |
| six | 64 | 512 | 4 | hybrid | crosses | 39.2 | [36.7, 42.1] | 0.0/1.0/0.0 | not run |
| six | 256 | 128 | 4 | push | cheaper_everywhere | - | [243, 250] | 0.984/0.016/0.0 | not run |
| six | 256 | 128 | 4 | hybrid | cheaper_everywhere | - | [242, 248] | 0.982/0.018/0.0 | not run |
| six | 256 | 512 | 4 | push | crosses | 166 | [147, 182] | 0.0/1.0/0.0 | not run |
| six | 256 | 512 | 4 | hybrid | crosses | 166 | [147, 182] | 0.0/1.0/0.0 | not run |

64 of 88 comparisons along writes_per_read are cheaper than pull at every level in every bootstrap replicate.

#### Crossover along views (v3; comparisons not cheaper everywhere)

| mix | blocks | read_scope | writes_per_read | arm | kind | crossover | 95% CI | share cheaper/crosses/dearer | v2 crossover |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| four | 16 | 4 | 64 | push | crosses | 79 | [73.2, 86.2] | 0.0/1.0/0.0 | 90.5 |
| four | 16 | 4 | 64 | hybrid | crosses | 79.5 | [74.5, 85.2] | 0.0/1.0/0.0 | 88.5 |
| four | 16 | 4 | 256 | push | crosses | 14 | [13.2, 14.7] | 0.0/1.0/0.0 | 14.3 |
| four | 16 | 4 | 256 | hybrid | crosses | 13.8 | [12.8, 14.8] | 0.0/1.0/0.0 | 14.5 |
| four | 64 | 4 | 64 | push | crosses | 452 | [398, 488] | 0.1105/0.8895/0.0 | cheaper_everywhere |
| four | 64 | 4 | 64 | hybrid | crosses | 454 | [403, 488] | 0.114/0.886/0.0 | cheaper_everywhere |
| four | 64 | 4 | 256 | push | crosses | 53.3 | [51.5, 55.1] | 0.0/1.0/0.0 | 60.3 |
| four | 64 | 4 | 256 | hybrid | crosses | 53.7 | [51.9, 55.5] | 0.0/1.0/0.0 | 57.9 |
| four | 256 | 4 | 256 | push | crosses | 300 | [285, 313] | 0.0/1.0/0.0 | 359 |
| four | 256 | 4 | 256 | hybrid | crosses | 300 | [286, 313] | 0.0/1.0/0.0 | 359 |
| six | 16 | 4 | 64 | push | crosses | 87.2 | [72.2, 103] | 0.0/1.0/0.0 | cheaper_everywhere |
| six | 16 | 4 | 64 | hybrid | crosses | 87.9 | [72.9, 105] | 0.0/1.0/0.0 | cheaper_everywhere |
| six | 16 | 4 | 256 | push | crosses | 21.7 | [12.5, 31.7] | 0.0/0.979/0.021 | cheaper_everywhere |
| six | 16 | 4 | 256 | hybrid | crosses | 21.5 | [12.3, 31.3] | 0.0/0.983/0.017 | cheaper_everywhere |
| six | 64 | 4 | 64 | push | crosses | 268 | [252, 287] | 0.0/1.0/0.0 | not run |
| six | 64 | 4 | 64 | hybrid | crosses | 266 | [250, 287] | 0.0/1.0/0.0 | not run |
| six | 64 | 4 | 256 | push | crosses | 53.9 | [47.2, 58.2] | 0.0/1.0/0.0 | not run |
| six | 64 | 4 | 256 | hybrid | crosses | 55 | [51.4, 58] | 0.0/1.0/0.0 | not run |
| six | 256 | 4 | 256 | push | crosses | 207 | [143, 260] | 0.0/1.0/0.0 | not run |
| six | 256 | 4 | 256 | hybrid | crosses | 205 | [142, 258] | 0.0/1.0/0.0 | not run |

100 of 120 comparisons along views are cheaper than pull at every level in every bootstrap replicate.

#### Crossover along blocks (v3; comparisons not cheaper everywhere)

| mix | views | read_scope | writes_per_read | arm | kind | crossover | 95% CI | share cheaper/crosses/dearer | v2 crossover |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| four | 32 | 4 | 256 | push | crosses | 34.8 | [33.7, 36] | 0.0/1.0/0.0 | 33.4 |
| four | 32 | 4 | 256 | hybrid | crosses | 34.3 | [32.9, 35.8] | 0.0/1.0/0.0 | 33.8 |
| four | 128 | 4 | 64 | push | crosses | 20 | [19, 21] | 0.0/1.0/0.0 | 18.4 |
| four | 128 | 4 | 64 | hybrid | crosses | 20.1 | [19.3, 20.9] | 0.0/1.0/0.0 | 18.6 |
| four | 128 | 4 | 256 | push | crosses | 111 | [106, 116] | 0.0/1.0/0.0 | 97.3 |
| four | 128 | 4 | 256 | hybrid | crosses | 111 | [106, 116] | 0.0/1.0/0.0 | 97.9 |
| four | 512 | 4 | 64 | push | crosses | 71.7 | [66.9, 80.5] | 0.1045/0.8955/0.0 | cheaper_everywhere |
| four | 512 | 4 | 64 | hybrid | crosses | 71.4 | [67, 79.9] | 0.1035/0.8965/0.0 | cheaper_everywhere |
| four | 512 | 4 | 256 | push | dearer_everywhere | - | - | 0.0/0.0/1.0 | dearer_everywhere |
| four | 512 | 4 | 256 | hybrid | dearer_everywhere | - | - | 0.0/0.0/1.0 | dearer_everywhere |
| six | 8 | 4 | 256 | push | cheaper_everywhere | - | [16.4, 16.9] | 0.9835/0.0165/0.0 | not run |
| six | 8 | 4 | 256 | hybrid | cheaper_everywhere | - | [16.5, 17] | 0.988/0.012/0.0 | not run |
| six | 32 | 4 | 256 | push | crosses | 24.2 | [16.4, 32.4] | 0.0125/0.9875/0.0 | not run |
| six | 32 | 4 | 256 | hybrid | crosses | 23.9 | [16.6, 30.4] | 0.0155/0.9845/0.0 | not run |
| six | 128 | 4 | 64 | push | crosses | 24.2 | [20.8, 27.4] | 0.0/1.0/0.0 | not run |
| six | 128 | 4 | 64 | hybrid | crosses | 24.1 | [20.5, 27.5] | 0.0/1.0/0.0 | not run |
| six | 128 | 4 | 256 | push | crosses | 183 | [154, 235] | 0.0/0.986/0.014 | not run |
| six | 128 | 4 | 256 | hybrid | crosses | 185 | [156, 238] | 0.0/0.9815/0.0185 | not run |
| six | 512 | 4 | 64 | push | crosses | 104 | [94.2, 119] | 0.0/1.0/0.0 | not run |
| six | 512 | 4 | 64 | hybrid | crosses | 104 | [94.4, 119] | 0.0/1.0/0.0 | not run |
| six | 512 | 4 | 256 | push | dearer_everywhere | - | - | 0.0/0.0/1.0 | not run |
| six | 512 | 4 | 256 | hybrid | dearer_everywhere | - | - | 0.0/0.0/1.0 | not run |

138 of 160 comparisons along blocks are cheaper than pull at every level in every bootstrap replicate.

Over all 220 cells, hybrid (and push) is cheaper than pull with the whole 95% interval below 1 in 103 of 110 `four` cells (6 dearer, 1 undecided: 64 blocks, 512 views, scope 4, w = 64: 1.09 [0.985, 1.19]) and in 103 of 110 `six` cells (7 dearer, none undecided). With read scope `all`, hybrid costs 0.0001-0.55 of pull for `four` (largest upper bound 0.57) and 0.0001-0.46 for `six` (largest upper bound 0.61). Every cell where pull is cheaper has read scope 4 and w of 64 or 256.

**Pull per view with six families.** With scope `all` and w = 1, pull costs 1.9-2.2 ms per view at 16 blocks, 7.2-9.0 ms at 64 blocks and 16.5-32 ms at 256 blocks for `six`, against hybrid's write-side matching of 1.2-2.6 microseconds per view per write.

## Conclusion

In the tested range (4-256 blocks, about 180-10,900 claims; 8-512 standing views; 1-256 writes per read), re-querying at read time is **not** cheaper than push filtering except in one corner. When a read checks every standing view, push and hybrid are cheaper than pull in every cell, by a factor of about 2 to 10,000 (paired ratio 0.0001-0.54, every upper 95% bound at most 0.56); at the largest write rate tested (256 writes per read) hybrid still costs 0.03-0.54 of pull. Pull is cheaper only when a read checks a few views (4) while many views stand and many writes arrive between reads: the crossover in writes per read is about 55 (95% interval 52-58) at 16 blocks and 128 views, 64 (57-72) at 64 blocks and 512 views, 178 (170-183) at 64 blocks and 128 views, and 196 (190-203) at 256 blocks and 512 views. It moves to higher write rates as the graph grows, because write-side matching costs about 1 microsecond per standing view per write regardless of graph size, while a re-query costs milliseconds and grows with the graph. A rule that fits every measured cell: hybrid is cheaper than pull when (writes per read) x (standing views) x 1 us is below (views checked per read) x (re-query time per view).

So the narrowing condition of RQ2 ("read-time re-query with fingerprints is not more expensive in any stratum") is **not** met in this range, and RQ2 does not narrow on cost grounds. The plan's expectation (5.4) that pull is enough at dialogue scale holds only in absolute terms: at 16 blocks pull costs 6-50 ms per read for 8-32 views of the `four` mix, which is small next to an LLM call, but it is not cheaper than push filtering. Pull and hybrid repair the same views, so hybrid's saving is database time only.

Two limits of the evidence. (1) The `pending` and `choice` families are measured only on small graphs (`six`, up to 16 blocks), because their compiled queries are pathologically slow: the compiled `pending` query takes 500-950 ms at 16 blocks and 8-15 s at 64 blocks, against 3.5-34 ms for the same SPARQL with its constants inlined instead of bound with `VALUES`. This is a property of the current compiler with pyoxigraph 0.5.13, not of the staleness strategies, and it inflates pull (and every re-evaluation) wherever these families stand; a compiler change that inlines single-IRI constants would be needed before these families can be measured at scale. (2) The graphs interleave independent generated sequences, so each write touches one block's views; a history whose writes concentrate on the standing views would mark more views per write and move the crossover to lower write rates. The write-side cost also reflects T019's matching, which loops over every view for every change set; an index from predicates to views would lower it further.

**Addendum (design version 3, 2026-11-26).** With the compiler inlining single-member constants, all six families were measured on 16-256 blocks (about 690-10,900 claims) with 8-512 standing views. The conclusion above holds with six families on large graphs: when a read checks every standing view, push and hybrid are cheaper than pull in every cell (hybrid / pull at most 0.55 for `four` and 0.46 for `six`, every upper 95% bound at most 0.61); pull is cheaper only when a read checks 4 views while many views stand and many writes arrive between reads. The crossover in writes per read now lies between 39 (95% interval 37-42; `six`, 64 blocks, 512 views; hybrid) and 187 (145-249; `six`, 16 blocks, 32 views; hybrid); for `four` it moved down by 0-15% against v2 (52 instead of 55 at 16 blocks and 128 views; 58 instead of 64 at 64 blocks and 512 views; 161 instead of 178 at 64 blocks and 128 views; 168 instead of 196 at 256 blocks and 512 views), because pull became about 10% cheaper. The v2 range of 55-196 writes per read is therefore replaced by about 40-190 over both mixes; the direction and the order of magnitude are unchanged. The first limit stated above (pending and choice measured only on small graphs) is lifted; `choice` views with an accepted candidate are still rare in the generated graphs, so their cost rests on few views. The second limit (independent blocks, T019's per-view matching loop) still applies.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session m01-E004 started (Issue #94, branch `task/E004-scale-experiment`, base `63f9d4fff7021651c9626af18bdc0a25ce50e557`). Status to record: `E004: planned -> active`.
- 2026-11-25: calibration on prototype graphs (not formal runs, no numbers quoted from it): view queries of the five families grow about linearly with the graph; the compiled `pending` query grows about quadratically and is two orders of magnitude slower than with constants inlined, which bounds the `six` grid. Design written above before the first formal run.
- 2026-11-25: first formal launch of design version 1 at `9038ce2` (10 runs of view mix `five` started, 20:25 UTC). The `choice` views with an accepted candidate took seconds per query at 64 blocks (the five-family calibration had timed only block 0, whose choice views were empty), so the `five` grid could not finish in budget. All 10 runs were stopped at 20:35 UTC and marked `failed` with the cause; their reports are in the Runs table and none of their numbers is used. Design version 2: view mix `four` (list, current, count, constraints) replaces `five`, standing views 8, 32, 128, 512, `six` with 8 and 32 views; the compiled `choice` query joins `pending` among the families timed only up to 64 blocks.
- 2026-11-25: design version 2 launched at `fac294f` (30 runs, 10 at a time, 20:36-22:15 UTC); all 30 `completed`. Reports written for all 40 runs; summary `summary-20261125T2216Z`. Results and Conclusion filled from the 30 completed runs. Status to record: `E004: active -> review` with the PR.
- 2026-11-26: user decision: fix the query compiler (inline single-IRI constants instead of `VALUES`), then rerun all six template families on large graphs. Manager session m01-E004b on `task/E004-inline-constants` from `main` at `3143ab337cf080b3511698d5b01e5f2361f4d961`. Calibration on 16-, 64- and 256-block graphs (not formal runs): the change removes the `pending` and `choice` slowdown with identical row counts. Design version 3 written above before any version-3 run.
- 2026-11-26: design version 3 launched at `aa2c547` (44 runs, 10 at a time, 02:42-04:32 UTC); all 44 `completed`. Reports written for all 44 runs; summary `summary-20261126T0433Z`. Runs, Results and Conclusion addenda added; version-2 sections kept unchanged. The executed query text of every family changed deliberately with the compiler (user-approved); version-2 timings are not comparable cell by cell with version 3. Status: none proposed here (E004 is `done`; the integration owner decides how to record this follow-up).
