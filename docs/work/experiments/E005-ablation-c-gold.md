---
id: E005
title: Ablation C on gold graphs
created: 2026-11-23
---

# E005 · Ablation C on gold graphs

## Question

Does an LLM-rendered view help the reader more than a template serialisation of the same result rows? This is the premise of RQ3. If the template ties, nothing expensive needs caching and the paper becomes 'a staleness criterion plus computing at query time'.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Controlled change sequences, development template families, gold graphs |
| Systems and baselines | Template serialisation; LLM rendering; raw-text window as reference; equal display budget |
| Metrics | Reader accuracy and the paired difference; render-check failure rate; rendering tokens on the write side |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E005-ablation-c-gold.yaml` (to be created) |

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
