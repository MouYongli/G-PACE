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
