---
id: E019
title: "Formal run: LongMemEval-S"
created: 2026-11-23
---

# E019 · Formal run: LongMemEval-S

## Question

With one question per history, where amortisation is least favourable, how do quality and reader-window use compare? Serves RQ1 and the adverse case of RQ3. Required for the paper, not for the preprint; it is the most compute-heavy item and runs after the core.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | LongMemEval-S (cleaned), held-out part of the knowledge-update, temporal-reasoning and multi-session strata |
| Systems and baselines | Full system; main-text baselines; full history by the long-context second reader |
| Metrics | Official per-type judged accuracy; session-level and turn-level evidence recall; the knowledge-update stratum is descriptive only |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E019-formal-longmemeval.yaml` (to be created) |

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
