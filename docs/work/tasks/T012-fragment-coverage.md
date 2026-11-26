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
- 2026-11-25: rebased onto `origin/main` `54f3bdd` (D007 second-annotator record, PR #50); `make test` (257 tests, including the byte-for-byte sheet reproduction against `$PROJECT_ROOT/data`) and `make lint` pass. Acceptance: labels (agent pre-annotation) and guideline committed; coverage reported as preliminary; human labels and kappa open.
- 2026-11-25: PR #54 merged. The user accepted tie rule T1 of the guideline: a relative time expression resolved against its own session date at write time keeps the question in the fragment (57 of the 263 preliminary `in_fragment` labels rely on it).
- 2026-11-25: the user named a graduate research assistant as the second annotator (D007); they label the 100 overlap questions.
- 2026-11-26: first annotation round recorded by the integration owner on the user's instruction (user decision of 2026-11-26). The label files are not committed; only the numbers below are recorded, and annotators are recorded anonymously. `anonymous_1` labelled the 100 questions with `overlap = yes`; `anonymous_2` labelled the other 208. This deviates from section 7 of the guideline (annotator A labels all 308 and annotator B the 100 overlap questions): the two label sets do not overlap, so no human Cohen's kappa exists for this round, and coverage is computed from the union of the two sets. The exported files carried `codex` in the `annotator` column. Coverage: in_fragment 262/308 = 85.1% (Wilson 95% 80.7-88.6%); anonymous_1 85/100 = 85.0%, anonymous_2 177/208 = 85.1%. Out of fragment: open_reasoning 21, common_sense 5, date_arithmetic 4, other 16 (annotation_error 10, image_only 6). By category: multi-hop 65/69 (94%), single-hop 128/143 (90%), temporal 64/70 (91%), open-domain 5/26 (19%); by history: conv-26 130/152 (86%), conv-49 132/156 (85%). Flags: relative_time 62 (tie rule T1), partial_image 6; operations: filter 35, join 20, latest 9, count 3. Against the agent pre-annotation (not a human annotator, so not human agreement): observed agreement 0.906, kappa 0.646 over five classes; 0.925, kappa 0.703 in versus out (anonymous_1 0.910 / 0.666; anonymous_2 0.904 / 0.636). Coverage is far above one half, so the D007 option 'lower the expectation for RQ1 on LoCoMo' is not triggered by this round. T012 is marked done with a remark: **after all other work is finished, a second group of annotators re-annotates, following the guideline, with the second annotator labelling all 308 questions**; human kappa, adjudication and the final coverage figure come from that round, and any change to these numbers is recorded here.
- 2026-11-26: the user handed T012 to the integration owner of this round (the earlier manager session `m01-T012` no longer handles it); the second-round re-annotation is coordinated from there.
