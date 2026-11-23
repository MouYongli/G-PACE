---
id: E008
title: Ablation A on extracted graphs
created: 2026-11-23
---

# E008 · Ablation A on extracted graphs

## Question

With extracted graphs, how much stale content reaches the reader under each strategy, and how much of it is due to extraction and not to detection? Serves RQ2.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Controlled change sequences, development template families, extracted graphs |
| Systems and baselines | The eight strategies of T019; references: re-querying (graph) and the event log (end to end) |
| Metrics | Miss and over-marking rates against re-querying; end-to-end miss rate against the event log; the difference as extraction-induced misses; rebuild tokens |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E008-ablation-a-extracted.yaml` (to be created) |

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
