---
id: E004
title: "Scale experiment: push, pull, hybrid"
created: 2026-11-23
---

# E004 · Scale experiment: push, pull, hybrid

## Question

At what number of standing views, write rate and graph size does push filtering become cheaper than re-querying at read time? Serves RQ2. If re-querying is never more expensive in the tested range, RQ2 narrows to 'exact staleness checks are cheap'.

## Design

Written on 2026-11-25 before the first formal run. Config: `configs/experiments/E004-scale-experiment.yaml`; driver: `uv run python -m grace.cli.scale` (subcommands `plan`, `run`, `summary`); probe: `src/grace/eval/runner/probes/scale.py`; statistics: `src/grace/eval/analysis/metrics/scale.py` (reads run files only).

| Item | Value |
| --- | --- |
| Benchmarks and splits | No benchmark data. Synthetic graphs scaled from the T015 generator (`changeseq-generator-2`, development families only: hotel-stay, apartment-search, train-travel, flight-travel, car-rental; held-out families are refused by the probe). A graph is `blocks` generated sequences (512 messages each, density 10, default change mix), one per block with seed `sequence_seed(seed, "E004-<family>-<index>")`, families cycled. Entity and entry IDs of block i get the prefix `b<iiii>-`, so blocks share no entity, claim or message (attribution speakers `user`, `assistant` are kept). The change sets of all blocks are interleaved round robin into one history. Messages 1-256 of every block are committed before measuring (the graph size); messages 257-512 form the measured window |
| Factors | Graph size: blocks 4, 16, 64, 256 (about 43 claims, 70 attributions and 1,300 triples per block at the prefix head). Standing views: 12, 48, 192, 768 drawn by a seeded permutation from the bindings the graph admits (nested across sizes; a size above the admitted bindings is not run). Write rate: 1, 4, 16, 64, 256 committed change sets (messages, including empty ones) between consecutive reads. Read scope: each read checks either all standing views or 4 views drawn per read (seeded, identical for every arm). View mix: `five` (list, current, count, constraints, choice) and `six` (the full main configuration, adding pending) |
| Grid | `five`: blocks {16, 64, 256} x views {12, 48, 192, 768}; `six`: blocks {4, 16} x views {12, 48}; each x read scope {4, all} x writes per read {1, 4, 16, 64, 256}. Cells whose window is shorter than 16 x writes per read are skipped and listed in `graph.json` (blocks 4: writes per read 256). Why `six` is smaller: in calibration on prototype graphs (not formal runs) the compiled `pending` query (one NOT EXISTS, constants bound with `VALUES`) grew roughly quadratically with the graph and was two orders of magnitude slower than the same SPARQL with its constants inlined, so pull with pending views at 64 or more blocks would exceed the budget. The formal runs measure this as a diagnostic (below) |
| Systems | Three T019 arms of `configs/views/staleness.yaml`: push = `claim_pattern_filters` (claim-pattern push with local filters, rebuild marked views without confirmation), pull = `requery` (re-query every view a read checks, compare fingerprints), hybrid = `push_confirm` (claim-pattern marks, re-query only marked views at read). Template rendering, no model call |
| Measurement | One measurement is one arm over 16 read periods of the window. Per period: write-side decision time (`match_ms` of the strategy log, pattern matching on change-set records, no database), wall time of the strategy's `write` calls, commit time (equal for every arm; not part of the decision cost), and per read the strategy's database time (`check_db_ms` of the fingerprint re-query plus `maintain_db_ms` of re-evaluations during maintenance) and the read's wall time; views repaired and how. The graph prefix is built once per run and copied per measurement (`fork_store`); views are built at the prefix head before timing starts; `gc.collect()` before each measurement |
| Metrics | Database time per write (`write_ms`) and per read (`read_ms`); decision cost per read period `period_ms = w * write_ms + read_ms` and per write; ratio of push and hybrid to pull, paired within (cell, seed, repetition), geometric mean with a percentile bootstrap interval (2,000 replicates); crossover against pull along writes per read, standing views and blocks (log-linear interpolation of the log ratio between adjacent levels), with bootstrap median and 95% interval and the share of replicates that never cross. LLM tokens: zero by construction (template rendering); the check that pull and hybrid repair exactly the same views at every read stands in for "equal tokens" and must find no difference |
| Noise | CPU shared with other users (224 logical CPUs). Recorded: CPU model, cores, affinity and load average per run (`machine.json`); 1-minute load average before and after, wall and CPU time of every measurement. 3 repetitions per (cell, seed), arm order rotated per repetition; coefficient of variation across repetitions (timing noise) and across seeds (graph realisation) per cell and arm |
| Diagnostics | Per run, the main query of each of the 15 bindings of block 0 timed at the prefix head (minimum of 3) as compiled and with its single-IRI `VALUES` constants inlined, with row counts of both (must agree); the compiled `pending` query only up to 16 blocks |
| Seeds and budget | Seeds 1 and 2 (block generation, view choice, read draws). 30 runs (one per mix, blocks, seed, views; `five` with 768 views needs 64 blocks), at most 10 concurrently, each capped at 8 hours (a run that exceeds the cap fails and is reported) |
| Frozen before the first run | Generator version, families, the T019 arms and their options, the T018 template families and view config (`state_speaker: user`, as in the T019 replay), the grid above |

## Acceptance

- [ ] Design (grid, seeds, repetitions, budget) written before the first formal run.
- [ ] Database time per write and per read for push, pull and hybrid; crossover point with uncertainty.
- [ ] Every number traces to a run report.

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |

## Results

Not run.

## Conclusion

Pending.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session m01-E004 started (Issue #94, branch `task/E004-scale-experiment`, base `63f9d4fff7021651c9626af18bdc0a25ce50e557`). Status to record: `E004: planned -> active`.
- 2026-11-25: calibration on prototype graphs (not formal runs, no numbers quoted from it): view queries of the five families grow about linearly with the graph; the compiled `pending` query grows about quadratically and is two orders of magnitude slower than with constants inlined, which bounds the `six` grid. Design written above before the first formal run.
