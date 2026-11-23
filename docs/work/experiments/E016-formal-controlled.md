---
id: E016
title: "Formal run: controlled sequences"
created: 2026-11-23
---

# E016 · Formal run: controlled sequences

## Question

On held-out template families, do the staleness results hold, and in which region of revision density and reads per history is maintaining views cheaper than full history and query-time resolution? Primary evidence for RQ2 and for the maintenance part of RQ3.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Controlled change sequences, held-out template families; gold and extracted graphs |
| Systems and baselines | The eight strategies; full history with prefix cache; query-time resolution; template variant |
| Metrics | Miss and over-marking rates; end-to-end miss rate; rebuild tokens; total cost over revision density x reads per history, with the regions where the system does not win |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E016-formal-controlled.yaml` (to be created) |

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
