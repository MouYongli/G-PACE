---
id: T024
title: Graph-quality annotation
created: 2026-11-23
---

# T024 · Graph-quality annotation

## Goal

Human reference data for the extracted graphs (plan section 6.7): exhaustive claim annotation of 40 sampled segments of about 20 messages each, and manual correction of the extraction for the two LoCoMo development histories.

## Scope

- In scope:
  - Two annotators label independently, then merge; claim-level agreement is reported.
  - If hours overrun, reduce the number of segments first.
- Out of scope: Annotating held-out histories.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Annotations and the guideline are committed.
- [ ] Corrected graphs for conv-26 and conv-49 validate against the shapes of T014.

## Deliverables

Annotation files under `docs/research/` or the benchmark store, as the data owner decides.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-28: manager session `m01-T024` started on `task/T024-graph-quality-annotation` from `596aac197642b452d8487a7b3111b4c65c5636a8`; Issue #136. User decisions of the same day: (1) the 40 segments come from LoCoMo dev (16, 8 per history) and LongMemEval-S dev (24); (2) the segments are first annotated by independent Claude agent annotators, and a human review follows; (3) the correction of the conv-26 and conv-49 extraction waits until E007 fixes the writer prompt, so that the final writer's output is corrected.
- 2026-11-28: guideline `docs/research/graph-quality-annotation.md`, sample code (`eval/datasets/benchmarks/graph_quality_sample.py`, seed `T024-segments-v1`), label checks, agreement and merge (`eval/analysis/annotation/graph_quality.py`, `cli/annotate/graph_quality.py`, `scripts/annotation/graph-quality.sh`) and tests committed. Sample `docs/research/annotations/graph-quality/sample.json`: 40 segments, 578 messages (LoCoMo 16 segments, 289 messages, about 7,200 words; LongMemEval-S 24 whole haystack sessions, 12 evidence and 12 filler, 289 messages, about 51,000 words). Deviation from plan 6.7: LongMemEval-S segments are whole sessions of 8 to 14 messages (about 2,100 words each) instead of about 20 messages. Segment texts in `$PROJECT_ROOT/runs/T024/artifacts/sample/segments.jsonl` (not committed; reproduced by the sample command).
