---
id: E007
title: "Ablation G: writer scale, thinking, granularity"
created: 2026-11-23
---

# E007 · Ablation G: writer scale, thinking, granularity

## Question

How much graph quality and answer accuracy does a larger writer or thinking recover, and what do the three extraction granularities cost? Serves RQ3. The granularity result fixes the main configuration (plan section 8.4).

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Controlled sequences; LoCoMo development histories |
| Systems and baselines | Writer: primary versus larger same-family model; thinking off versus on; granularity per message, per segment, per session |
| Metrics | Writer tokens; graph quality as in E006; answer accuracy; parse-failure and repair rates |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E007-ablation-g-writer.yaml` (to be created) |

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
- 2026-11-26: design inputs from the T022 writer smoke comparison (PR #129), recorded by the integration owner on user decisions: one prompt round on development data to raise Qwen3-32B extraction coverage (45/136 empty units in the smoke run), before the configuration lock (D012), with the same prompt then used for every writer arm; report empty-patch rate and output tokens next to quality (Qwen3-32B used about 2.7 times fewer output tokens than Qwen3-8B on the same input); session granularity needs larger schema array bounds (claims 32, stances 16, same_as 8 are sized for segment-8) and a re-pinned schema.
