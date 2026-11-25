---
id: E002
title: Rough natural staleness distribution
created: 2026-11-23
---

# E002 · Rough natural staleness distribution

## Question

How often do the seven change types of plan section 6.4 occur per thousand messages in natural dialogue, and how many are missed by citation-based dependencies? Serves RQ2. If the three missed types are rare, view maintenance is positioned for high-revision workloads.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | LoCoMo development histories (conv-26, conv-49); LongMemEval development histories |
| Systems and baselines | One-off extraction prompt and hand-written queries over the template views of plan section 5.4; no answering LLM |
| Metrics | Occurrences per thousand messages by change type; ratio of citation to answer staleness; misses of the two citation-based strategies |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E002-rough-staleness-distribution.yaml` (to be created) |

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
