---
id: E021
title: Robustness checks
created: 2026-11-23
---

# E021 · Robustness checks

## Question

Do the first conclusions and the key failure modes hold on the contemporary small model (core), and on the long-context second reader, the recommended decoding setting and with a reranker switched on for all methods (optional)? If they hold only on the primary model, the claimed scope is restricted.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Preregistered stratified subsets of the main-text benchmarks |
| Systems and baselines | Contemporary small model; long-context second reader; temperature 0.7; cross-encoder reranking for every method |
| Metrics | The primary metrics of E016 to E018 and their paired differences |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E021-robustness.yaml` (to be created) |

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
