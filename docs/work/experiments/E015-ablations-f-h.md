---
id: E015
title: Ablations F and H; call-type invocation arm of G
created: 2026-11-23
---

# E015 · Ablations F and H; call-type invocation arm of G

## Question

Is constrained local vocabulary extension worth its cost against a frozen vocabulary with aliases, is RRF with rule routing enough, and do conditionally triggered calls beat fixed calls at equal call budget? Serves component claims C2, C3, C5 and C6.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Development histories of all main-text benchmarks; HaluMem where available |
| Systems and baselines | Frozen, frozen plus aliases, local evolution; fixed-schema temporal graph; rule routing versus always three channels; RRF versus weighted fusion; single call, fixed routing, conditionally triggered calls |
| Metrics | Predicate linking accuracy on unseen expressions; schema growth; prompt cost; quality and cost per read; trigger precision |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E015-ablations-f-h.yaml` (to be created) |

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
