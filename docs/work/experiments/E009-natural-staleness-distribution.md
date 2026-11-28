---
id: E009
title: Natural staleness distribution
created: 2026-11-23
---

# E009 · Natural staleness distribution

## Question

How often do answer and citation staleness occur in natural dialogue, by change type, and how much do the citation-based strategies miss there? This is the empirical answer for RQ2; it repeats E002 with the formal writer and compiler.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | LoCoMo development histories with manually corrected extraction; LongMemEval development histories |
| Systems and baselines | Template views of plan section 5.4, re-evaluated after every message; no answering LLM |
| Metrics | Occurrences per thousand messages by change type; ratio of citation to answer staleness; misses of the two citation-based strategies |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E009-natural-staleness-distribution.yaml` (to be created) |

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
- 2026-11-28: preparation of the corrected LoCoMo input (worker w01-correction, outside this node's runs): correction page `web/human-reviewer/locomo/correction/`, agent pre-review `docs/research/annotations/locomo-correction/proposals-agent-w01.jsonl` of the shared ingest E007-20261128T174115Z-1b02 (final writer), and `python -m grace.cli.annotate.locomo_correction apply`, which writes the corrected change sets in the ingest's format. The human correction itself is pending.
