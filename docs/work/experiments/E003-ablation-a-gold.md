---
id: E003
title: Ablation A on gold graphs
created: 2026-11-23
---

# E003 · Ablation A on gold graphs

## Question

On gold graphs, how many stale views does each strategy miss and how many does it mark needlessly, by change type? Serves RQ2. This is a correctness check and a measurement of over-marking, not an empirical finding (plan section 6.4).

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Controlled change sequences, development template families, gold graphs |
| Systems and baselines | The eight strategies of T019; re-querying is the reference |
| Metrics | Miss rate and over-marking rate against re-querying; agreement with full rebuild; rebuild tokens; answer and citation staleness reported separately |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E003-ablation-a-gold.yaml` (to be created) |

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
