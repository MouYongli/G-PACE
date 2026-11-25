---
id: E013
title: "Ablation E: assembly"
created: 2026-11-23
---

# E013 · Ablation E: assembly

## Question

At the same token budget, does assembly by evidence demand raise full evidence hits and lower unsupported answers compared with a fused top-k? Serves component claim C4.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | LoCoMo and LongMemEval-S development data |
| Systems and baselines | Fixed top-k or RRF truncation versus evidence-demand assembly; expandable pointers versus summaries only |
| Metrics | Full evidence hit rate; unsupported answer rate; final prompt and total tokens |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E013-ablation-e-assembly.yaml` (to be created) |

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
- 2026-11-25: confirmed as optional (user, 2026-11-25); plan sections 7.3, 9 and 9.3 now say so.
