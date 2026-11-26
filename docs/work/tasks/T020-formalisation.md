---
id: T020
title: Final formalisation and proof
created: 2026-11-23
---

# T020 · Final formalisation and proof

## Goal

The final text of the formal part: the four entry kinds, two-level staleness, the observation, the soundness proposition and its exactness conditions (about one page of main text), plus the complete proof, the list of fragment assumptions and the full IR grammar for the supplementary material.

## Scope

- In scope:
  - Wording follows D005.
  - The proof covers negation, distinct count and latest-state selection by structural induction.
- Out of scope: New invalidation algorithms or complexity results.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Every assumption used in the proof is listed and matched to an implementation check in T017 or T019.

## Deliverables

`paper/` formalisation section and supplementary proof.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-26: manager session m01-T020 started (Issue #108, branch `task/T020-formalisation`, base `da699da5f3cfd416e75a89382b455b821edca257`). Status to record: `T020: planned -> active`.
- 2026-11-26: formal part written: main text `paper/latex/sections/preliminaries.tex`; supplement `paper/latex/supplement.tex` (model, time-travel stability, soundness with per-change-set and local-filter corollaries, exactness with count and latest refinements, over-approximation examples, fragment assumptions A1-A9, IR grammar). Assumption-to-check table and 16 plan/code discrepancies in `docs/research/formalisation.md`; exactness checked on fixtures by `tests/integration/test_formalisation.py`. No worker sessions, no model calls. Status to record: `T020: active -> review`.
