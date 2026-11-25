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
- [x] Official scorers reproduce the reference numbers on their published examples.
- [ ] The blind judge's agreement with human labels on a calibration sample is reported.

## Deliverables

`configs/` prompt and budget files, `src/grace/` scorer and judge wrappers, an evaluation section update in `docs/research/contracts.md` (through its owner).

## Log

- 2026-11-21: created from plan section 9, phase 1.
- 2026-11-25: manager session `m01-T004` started on `task/T004-prompts-counters-judges` from `main` at 985d232e4b4c148ba628d22a18e6eff99995c7cd; Issue #32. Dependencies T001 (done) and D013 (accepted) resolved. Dispatched in parallel with T002, T003 and T014; no worker sessions (the manager wrote the code), no compute.
- 2026-11-25: the user's dispatch made the T004 manager owner of the Evaluation section of `docs/research/contracts.md`; rewritten as version 0.2, keyed by `read_id` and gold `annotation`.
- 2026-11-25: delivered `llm/` (records, tokens, prompts, structured, client), `eval/analysis/judging/` (blind judge, LongMemEval official judge, human-label agreement) and `eval/analysis/metrics/` (alignment, LoCoMo F1, JGA and slot F1, `metrics.json`); prompts answer, summary, judge and five LongMemEval judge templates; pins in `configs/common/prompts.yaml`, `budgets.yaml`, `scorers.yaml`, `configs/judges/` and candidate tokenizer pins in `configs/models/` (D006 still proposed).
- 2026-11-25: acceptance: item 1 met for prompts, tokenizers and chat templates of the cached candidates and for judge prompts; the judge model snapshot waits for D006. Item 2 not met: no upstream reference outputs are available offline, so the scorers are checked on hand-computed cases only and stay `verified: false`. Item 3 not met: protocol and code path are in place; the agreement needs human labels and a judge run (E001).
- 2026-11-25: merged `main` at f7397a9 (T003, PR #39). `llm/records.CallLedger` also offers `new_id`, `append` and `records`, so the harness's interim `harness/ledger.py` can be replaced without other changes; `thinking` is an explicit per-model setting, passed to the server as `chat_template_kwargs`. Switching T003's harness to `llm/` and `resources/prompts/` is left as a follow-up for the harness owner.
- 2026-11-25: manager session `m01-T004b` resumed on `task/T004-scorer-upstream` from `main` at 9fdde49 for acceptance item 2. Upstream code downloaded at pinned commits into `$PROJECT_ROOT/runs/T004/artifacts/upstream/` and run in isolated `uv run --no-project` environments with upstream's pinned versions; inputs from development splits (LoCoMo conv-26/conv-49, LongMemEval-S dev, MultiWOZ dev) plus synthetic strings; no model called. Evidence: `runs/T004/artifacts/scorer-upstream/`.
- 2026-11-25: LoCoMo F1 (snap-research/locomo 3eb6f2c): two bugs found and fixed, then 0 of 8,228 rows differ (exact float equality, under nltk 3.8.1 and 3.10.4): the multi-answer mean now uses `numpy.mean` like upstream (6 last-bit differences with `sum()`), and article removal uses the `regex` module like upstream (`re` treats combining marks differently; 36 probe rows). `verified: true` for `f1` and `f1-adversarial`. LongMemEval official judge (xiaowu0162/LongMemEval 9e0b455): template choice and rendered messages identical to `get_anscheck_prompt` on 588 prompts (98 dev questions x 6 responses); the reply rule now counts an empty reply as incorrect like upstream (was `invalid`); `verified: true` with deviations listed in the judge config. MultiWOZ JGA and slot F1: no upstream implements the registered definition (MultiWOZ 2.4 repo has no evaluator; Tomiinek/MultiWOZ_Evaluation cd3f0ee is 2.2-only, fuzzy-matched, pooled slot F1); deviation recorded, `verified: false`. HaluMem and MemoryAgentBench have no registered metric yet. Regression test `tests/analysis/test_upstream_scorers.py` with synthetic fixtures in `tests/fixtures/upstream/`. Item 2 met for the registered official scorers; item 3 still waits for E001.
- 2026-11-25: PR #52 merged. No upstream publishes examples with reference scores, so the user accepted exact equality with upstream's code at a pinned commit, on development-split and synthetic inputs, as meeting acceptance item 2. MultiWOZ JGA and slot F1 keep their recorded deviation.
