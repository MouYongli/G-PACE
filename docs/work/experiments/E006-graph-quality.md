---
id: E006
title: Graph quality
created: 2026-11-23
---

# E006 · Graph quality

## Question

How good is the extracted graph itself: claim precision, recall and F1, attribution and time fields, and how often a restatement counts as independent evidence? Serves all three research questions as the error source of the graph channel.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Annotated segments from T024; controlled sequences with gold graphs |
| Systems and baselines | Primary writer at the main configuration |
| Metrics | Claim precision, recall, F1; shape conformance and retries; whether the cited span entails the claim; attribution and time accuracy; answer coverage upper bound |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E006-graph-quality.yaml` (to be created) |

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
- 2026-11-26: design inputs from the T022 writer smoke runs (PR #126, #129; runs under `runs/T022/artifacts/manager/T022/`), recorded by the integration owner on user decisions: measure both missed and spurious extraction against gold or human labels (writer scale trades precision for coverage: Qwen3-32B wrote 474 claims and left 45/136 units empty, Qwen3-8B wrote 957 with more noise); report quality per predicate, including catch-all predicates (no program-side blacklist is applied); measure the false-drop rate of the writer's evidence check on ended stances; separate writer errors from planner (T023) and fragment-selection errors in graph-channel misses (graph-channel R@20 was about 0.1 with either writer on LoCoMo dev); note that neither writer fills `valid_from`.
- 2026-11-27: design input recorded by the integration owner (user decision, T014 log of the same date): entity labels are immutable, so E006 also checks whether the writer's first-mention labels are correct surface names; a material error rate reopens the question of label correction.
