---
id: E012
title: "Ablation D: retrieval channels"
created: 2026-11-23
---

# E012 · Ablation D: retrieval channels

## Question

What does each channel contribute that the others do not, and is the graph gain due to retrieval or to role and time verification? Serves RQ1 and component claim C1.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | LoCoMo, LongMemEval-S and MultiWOZ development data |
| Systems and baselines | Remove BM25, dense or graph in turn with candidates and returned tokens fixed; graph channel switch x verification switch on the same candidates |
| Metrics | Slice accuracy; path evidence recall; stale-value use |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E012-ablation-d-channels.yaml` (to be created) |

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
