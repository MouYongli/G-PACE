---
id: E006
title: Graph quality
created: 2026-11-23
---

# E006 · Graph quality

## Question

How good is the extracted graph itself: claim precision, recall and F1, role and time fields, and how often a restatement counts as independent evidence? Serves all three research questions as the error source of the graph channel.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Annotated segments from T024; controlled sequences with gold graphs |
| Systems and baselines | Primary writer at the main configuration |
| Metrics | Claim precision, recall, F1; shape conformance and retries; whether the cited span entails the claim; role and time accuracy; answer coverage upper bound |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E006-graph-quality.yaml` (to be created) |

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
