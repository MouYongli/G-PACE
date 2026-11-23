---
id: E020
title: "Formal run: optional benchmarks and systems"
created: 2026-11-23
---

# E020 · Formal run: optional benchmarks and systems

## Question

Do the write path and the multi-read cost results hold on HaluMem and MemoryAgentBench, and how do Mem0g and Graphiti compare under the common protocol? Supporting evidence for graph quality, RQ2 and RQ3.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | HaluMem-Medium; MemoryAgentBench LongMemEval(S*) and FactConsolidation 6K and 32K |
| Systems and baselines | Full system; Mem0g; Graphiti (same backbone and native backbone) |
| Metrics | Operation-level correctness of extraction and update; QA accuracy; cumulative tokens over reads |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E020-formal-optional.yaml` (to be created) |

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
