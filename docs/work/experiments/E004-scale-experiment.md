---
id: E004
title: "Scale experiment: push, pull, hybrid"
created: 2026-11-23
---

# E004 · Scale experiment: push, pull, hybrid

## Question

At what number of standing views, write rate and graph size does push filtering become cheaper than re-querying at read time? Serves RQ2. If re-querying is never more expensive in the tested range, RQ2 narrows to 'exact staleness checks are cheap'.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Synthetic graphs scaled from the generator: standing views x write rate x graph size |
| Systems and baselines | Claim-pattern push, re-query with fingerprints, push filter plus read-time confirmation |
| Metrics | Database time per write and per read; the crossover point; LLM tokens (equal for pull and hybrid by construction) |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E004-scale-experiment.yaml` (to be created) |

## Acceptance

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
