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
- 2026-11-26: user decisions on the four open questions: (1) main-text compression deferred to T021, about 1.5 pages kept; (2) count and latest-by-version refinements stay in the supplement; (3) evidence recorded per answer: the formalisation models ev per answer, the code change (reference judgement, fingerprint, matcher) is assigned to `fix/T019-evidence-per-answer` and must merge before E003; (4) the `attribution: false` matcher option is removed, code change in the same branch.
- 2026-11-26: independent proof review of PR #112: no reasoning error and no counterexample to Proposition 2. Fixes applied: current state named in the main-text exactness statement and the decision defined; part (b) restated by mark level; constructed over-mark tests for (D1), (D2), (D3) and a (Q4) filter, positive test of part (b), programmatic (Q1)-(Q4) check (0 over-marks observed on the T019 fixtures); S5 names the unchecked parts of A3 and A6 (the A6 tie-break can miss a mark); entity representatives taken before grouping; evidence-free views; Example 1 and Remark 2 corrected; rebased onto main after #102 and #111.
- 2026-11-26: follow-up after PR #114 (manager session m01-T020b, branch `task/T020-per-answer-followup`): the (D3) check of `tests/integration/test_formalisation.py` compares evidence per answer, as the fingerprint does, and a new constructed test of part (b) covers a span already cited for another answer (replay counts unchanged: 193 marked, 16 violating (D3), 0 over-marks); `docs/research/formalisation.md` discrepancies 9 and 10 and the A9 (iii) row marked resolved by PR #114. Supplement `ev_t` (S1.4) checked against the plan 3.4 wording proposed in PR #114: same substance, no change.
