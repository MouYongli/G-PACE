---
id: E018
title: "Formal run: LoCoMo"
created: 2026-11-23
---

# E018 · Formal run: LoCoMo

## Question

On the eight held-out histories, how do accuracy, evidence recall and cumulative cost compare with the baselines, and what do later writes cost under streaming? Serves RQ1, the amortisation part of RQ3 and natural over-marking for RQ2.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | LoCoMo held-out histories, categories 1 to 4 (1,232 questions); also reported without the 99 audited questions; category 5 listed separately |
| Systems and baselines | Full system; all main-text baselines; ablation D |
| Metrics | Token-F1 and calibrated blind accuracy; strict and lenient evidence recall; view hit rate; cumulative tokens over reads; under streaming, answer consistency between v(q) and N, over-marking and rebuild tokens |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E018-formal-locomo.yaml` (to be created) |

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
