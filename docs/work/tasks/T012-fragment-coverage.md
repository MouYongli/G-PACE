---
id: T012
title: Fragment coverage annotation
created: 2026-11-23
---

# T012 · Fragment coverage annotation

## Goal

A labelled table stating, for each of the 308 LoCoMo development questions (conv-26, conv-49), whether it can be expressed in the query fragment of plan section 3.3 and, if not, why. Coverage is the upper bound of graph-channel accuracy (plan section 6.5).

## Scope

- In scope:
  - Annotation guideline with the fragment's six operations and the out-of-fragment classes (open reasoning, date arithmetic, common sense, other).
  - Two annotators overlap on 100 questions; Cohen's kappa is reported.
- Out of scope: Any system run; held-out histories.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Per-question labels and the guideline are committed.
- [ ] Coverage and kappa are reported with counts per class.

## Deliverables

Annotation file and guideline under `docs/research/`; summary in the task log.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-T012` started on `task/T012-fragment-coverage` from base `9fdde49b5022e5cef0bae94e68073444b1702d15`; Issue #47. Dev split loaded through `load_split` (manifest `c6836966…88ae7` verified; 2 histories, 928 messages, 308 questions) into `runs/T012/artifacts/locomo-dev/`. No model calls.
- 2026-11-25: guideline `docs/research/fragment-coverage.md`, sheet `docs/research/annotations/fragment-coverage/sheet.csv` (308 dev questions, empty annotator columns), overlap set of 100 (stratified by history × category, seed `T012-overlap-v1`), code (`eval/datasets/benchmarks/locomo_annotation.py`, `eval/analysis/annotation/fragment.py`, `cli/annotate/fragment.py`, `scripts/annotation/fragment-coverage.sh`) and unit tests committed.
- 2026-11-25: agent pre-annotation `labels-agent-m01-T012.csv` (`annotator: agent-m01-T012`; a model pre-annotation, not a human annotator). Preliminary coverage from it: in_fragment 263/308 = 85.4% (Wilson 95% 81.0–88.9%); open_reasoning 21, date_arithmetic 3, common_sense 7, other 14 (image_only 12, annotation_error 2). Of the 263, 57 rely on write-time relative-time resolution (T1) and 11 are partly image-dependent; counting both as outside gives 195/308 = 63.3%. By category in_fragment: 1: 64/69, 2: 66/70, 3: 1/26, 4: 132/143. Evidence: `runs/T012/artifacts/coverage-agent-m01-T012.{json,md}`. Preliminary only; not the human coverage figure of plan 6.5.
- 2026-11-25: the two-annotator part and Cohen's kappa wait until the user names the second annotator under decision D007 (section "Also recorded here"); no annotator is assumed and no placeholder second label set is made. Kappa: pending.
