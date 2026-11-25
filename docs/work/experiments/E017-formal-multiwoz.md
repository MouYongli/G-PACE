---
id: E017
title: "Formal run: MultiWOZ"
created: 2026-11-23
---

# E017 · Formal run: MultiWOZ

## Question

On the 1,000 test dialogues, does the system keep the original constraint and report the current selection after a system offer? Primary evidence for the attribution-guard claim of RQ1, unless D007 moved it to the controlled sequences.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | MultiWOZ 2.4 test set, turn-by-turn reads; the same predictions scored against 2.2 and 2.1 |
| Systems and baselines | Full system; ablation B arms; ReacTOD; deterministic overwrite; 'system values are not written' rule; direct state output |
| Metrics | Paired correctness; original-constraint retention after an offer; stale-value use; JGA and slot F1 as reference; over-marking on turn-by-turn reads |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E017-formal-multiwoz.yaml` (to be created) |

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
