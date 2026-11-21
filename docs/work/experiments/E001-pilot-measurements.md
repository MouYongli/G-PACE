---
id: E001
title: Pilot measurements
created: 2026-11-21
---

# E001 · Pilot measurements

## Question

On the development histories of each benchmark, how long are the histories, what does full-history reading cost, what cache ratio is achieved in practice, and how often is a rendered view read again after an invalidating update (natural update density)? Plan section 9, phase 1. If natural update density is low, view maintenance is positioned for high-revision workloads and RQ4 relies mainly on MultiWOZ, HaluMem and the controlled sequences.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Development histories of all six benchmarks |
| Systems and baselines | Full history, text retrieval, rolling summary, JSON state table (T003) |
| Metrics | History length distribution, full-history cost, measured cache ratio, natural update density; cost per `docs/research/contracts.md` (cost ledger, from T001) |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E001-pilot-measurements.yaml` (to be created) |

## Acceptance

- [ ] Every number traces to a run report.
- [ ] Prompts, counters, budgets and judges are frozen (T004) before the first formal run.

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |

## Results

Not run.

## Conclusion

Pending.

## Log

- 2026-11-21: created from plan section 9, phase 1.
