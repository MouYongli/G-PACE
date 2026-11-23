---
id: E014
title: Development quality-versus-cost curves
created: 2026-11-23
---

# E014 · Development quality-versus-cost curves

## Question

On development data, where does the system sit against every baseline in accuracy and in end-to-end tokens? Serves RQ3 and produces the numbers from which the lock (D012) fixes budgets and non-inferiority margins.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Development histories of the main-text benchmarks |
| Systems and baselines | Full system; full history with and without prefix cache; last-k; BM25, dense and RRF; rolling summary (rewritten, stale); slot table; query-time resolution; template variant; Mem0 |
| Metrics | Accuracy at equal budget; tokens at similar quality; cumulative tokens over reads; cost per successful task |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E014-dev-quality-cost.yaml` (to be created) |

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
