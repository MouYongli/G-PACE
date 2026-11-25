---
id: E010
title: Ablation C on extracted graphs
created: 2026-11-23
---

# E010 · Ablation C on extracted graphs

## Question

With extracted graphs, which source of view content serves the answering LLM best, and how often do standing views serve a read at all? Serves RQ3 and RQ2. A low hit rate means maintenance conclusions rest on the controlled sequences alone.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Controlled sequences; LoCoMo development histories |
| Systems and baselines | Template serialisation; LLM rendering of query results; LLM rewriting from raw text; each with and without source annotation; equal display budget |
| Metrics | Answer accuracy; correctness after rebuild; render-check failures; wrong citations; rendering cost; view hit rate |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E010-ablation-c-extracted.yaml` (to be created) |

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
