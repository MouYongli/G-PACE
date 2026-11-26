---
id: E011
title: "Ablation B: attribution guard, representation, time"
created: 2026-11-23
---

# E011 · Ablation B: attribution guard, representation, time

## Question

Does the attribution guard let the system answer both 'what was requested' and 'what is selected now', and is the gain due to the guard, to structure or to open predicates? Serves RQ1. If tagged hybrid retrieval obtains most of the gain attributed to the guard, the conclusion narrows to 'speaker and dialogue-act information helps'.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | MultiWOZ 2.4 turns after an offer (development); controlled sequences (late corrections, as-known pairs); LoCoMo and LongMemEval development slices |
| Systems and baselines | Attribution guard (off, on) x representation (slot table, open-predicate claim graph) x time (single, bitemporal); tagged hybrid retrieval; the 'system values are not written' rule |
| Metrics | Paired correctness of original constraint and current selection; original-constraint retention; stale-value use; share of the gain attributed to the guard that the tagged arm obtains |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E011-ablation-b-attribution-guard.yaml` (to be created) |

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
- 2026-11-24: renamed from `E011-ablation-b-roles.md` and retitled to follow the plan terminology (attribution guard instead of roles).
