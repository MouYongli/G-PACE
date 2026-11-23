---
id: T005
title: Research plan v3
created: 2026-11-22
---

# T005 · Research plan v3

## Goal

A self-contained v3 research plan in English. It organises the evaluation around read protocols (end of history, per turn, interleaved), so that maintenance claims rest only on settings where reads interleave with writes, and trims the evaluation to what a 15-page main text can carry. Sections 6 (evaluation protocol), 7 (models, baselines, ablations) and 9.2 (main text and supplementary material) are rewritten; other sections are aligned with them. The tracked work files are aligned with v3 at the same time.

The v3 text is kept out of git at the plan owner's request until it is approved; `docs/research/plan.md` is replaced by it in a later commit of this task.

## Scope

- In scope: the v3 plan text; registering the phase 1 follow-up tasks T006, T007 and T008; aligning `plan.yaml` milestone gates, the `docs/research/benchmarks.md` registry, E001, T002, T003 and the task index with v3.
- Out of scope: the project rename and environment (done in T009); benchmark downloads (T010); `docs/research/contracts.md`.
- Candidate worker subtasks: none.

## Acceptance

- [ ] The plan reads as one document, with no references to earlier versions.
- [ ] Every benchmark, baseline and ablation named in plan sections 6 and 7 is consistent with sections 4, 5, 8, 9 and 10, and with the registry in `docs/research/benchmarks.md`.
- [ ] `docs/research/plan.md` carries the approved v3 text.
- [ ] `make test` and `make lint` pass.

## Deliverables

v3 plan text (then `docs/research/plan.md`); task files T006, T007, T008; `plan.yaml` nodes T005 to T008 and aligned gates; aligned registry, E001, T002, T003 and task index.

## Log

- 2026-11-22: created at the user's request; manager session m01-T005 on `task/T005-plan-v3`.
- 2026-11-22: v3 drafted and kept outside git pending approval; T006, T007, T008 registered; plan.yaml gates, benchmark registry, E001, T002, T003 and task index aligned with v3.
- 2026-11-23: v3 drafts revised after an external review (formal model with four entry kinds, two-level staleness, template-serialisation arm, hybrid detection arm, minimal core, phase 0). Closed at the user's request. The work files were merged in PR #5; the v3 text itself stays outside git as drafts in the main checkout, so `docs/research/plan.md` still carries the earlier text and the third acceptance item is not met. Replacing `plan.md` needs a follow-up once the user approves the drafts.
