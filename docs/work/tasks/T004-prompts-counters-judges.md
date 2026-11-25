---
id: T004
title: Prompts, counters, judges
created: 2026-11-21
---

# T004 · Prompts, counters, judges

## Goal

Freeze what phase 1 must hold fixed: English prompts, the token counter and chat template, budgets, and the judges (official scorers and the calibrated blind LLM judge), so pilot numbers are comparable across systems.

## Scope

- In scope: prompt files, tokenizer and template pinning, budget table, scorer wrappers, judge calibration protocol.
- Out of scope: tuning prompts for the proposed system.

## Acceptance

- [ ] Prompts, tokenizer, chat template and judge versions are pinned in configs with checksums.
- [ ] Official scorers reproduce the reference numbers on their published examples.
- [ ] The blind judge's agreement with human labels on a calibration sample is reported.

## Deliverables

`configs/` prompt and budget files, `src/grace/` scorer and judge wrappers, an evaluation section update in `docs/research/contracts.md` (through its owner).

## Log

- 2026-11-21: created from plan section 9, phase 1.
- 2026-11-25: manager session `m01-T004` started on `task/T004-prompts-counters-judges` from `main` at 985d232e4b4c148ba628d22a18e6eff99995c7cd; Issue #32. Dependencies T001 (done) and D013 (accepted) resolved. Dispatched in parallel with T002, T003 and T014; no worker sessions (the manager wrote the code), no compute.
- 2026-11-25: the user's dispatch made the T004 manager owner of the Evaluation section of `docs/research/contracts.md`; rewritten as version 0.2, keyed by `read_id` and gold `annotation`.
- 2026-11-25: delivered `llm/` (records, tokens, prompts, structured, client), `eval/analysis/judging/` (blind judge, LongMemEval official judge, human-label agreement) and `eval/analysis/metrics/` (alignment, LoCoMo F1, JGA and slot F1, `metrics.json`); prompts answer, summary, judge and five LongMemEval judge templates; pins in `configs/common/prompts.yaml`, `budgets.yaml`, `scorers.yaml`, `configs/judges/` and candidate tokenizer pins in `configs/models/` (D006 still proposed).
- 2026-11-25: acceptance: item 1 met for prompts, tokenizers and chat templates of the cached candidates and for judge prompts; the judge model snapshot waits for D006. Item 2 not met: no upstream reference outputs are available offline, so the scorers are checked on hand-computed cases only and stay `verified: false`. Item 3 not met: protocol and code path are in place; the agreement needs human labels and a judge run (E001).
