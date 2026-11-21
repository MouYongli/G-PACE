# Experiments

An experiment answers one question under fixed conditions. Its file holds the design, the list of runs and the results, so everything about it is in one place. Status and dates live in `../plan/plan.yaml`; the config lives in `configs/experiments/E<NNN>-<slug>.yaml`.

The design is written before the first formal run and is not changed afterwards without a dated log entry. Runs and results are filled in with the `experiment-report` skill, and only from `completed` runs.

## Index

| ID | Title | Description |
| --- | --- | --- |
| [E001](E001-pilot-measurements.md) | Pilot measurements | Plan phase 1: costs, lengths, cache ratio and update density on development histories |

## Template

```markdown
---
id: E<NNN>
title: <title>
created: <YYYY-MM-DD>
---

# E<NNN> · <title>

## Question

The question and the research question it serves (link to `docs/research/plan.md`), with the result that would change the plan.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | |
| Systems and baselines | |
| Metrics | links to `docs/research/contracts.md` sections |
| Seeds and budget | |
| Config | `configs/experiments/E<NNN>-<slug>.yaml` |

## Acceptance

- [ ] Every number traces to a run report.

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |

## Results

Filled only from completed runs; report scored and invalid counts with every metric.

## Conclusion

What the results support, what they do not, and what follows for the plan.

## Log

- <YYYY-MM-DD>: created.
```
