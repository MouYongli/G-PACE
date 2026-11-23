---
id: E007
title: "Ablation G: writer scale, thinking, granularity"
created: 2026-11-23
---

# E007 · Ablation G: writer scale, thinking, granularity

## Question

How much graph and downstream quality does a larger writer or thinking recover, and what do the three extraction granularities cost? Serves RQ3. The granularity result fixes the main configuration (plan section 8.4).

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Controlled sequences; LoCoMo development histories |
| Systems and baselines | Writer: primary versus larger same-family model; thinking off versus on; granularity per message, per segment, per session |
| Metrics | Writer tokens; graph quality as in E006; downstream accuracy; parse-failure and repair rates |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E007-ablation-g-writer.yaml` (to be created) |

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
