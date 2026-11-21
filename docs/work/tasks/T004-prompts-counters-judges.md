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

`configs/` prompt and budget files, `src/gpace/` scorer and judge wrappers, an evaluation section update in `docs/research/contracts.md` (through its owner).

## Log

- 2026-11-21: created from plan section 9, phase 1.
