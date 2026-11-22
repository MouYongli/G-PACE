---
id: T007
title: LoCoMo evidence-anchored read points
created: 2026-11-22
---

# T007 · LoCoMo evidence-anchored read points

## Goal

Decide whether the evidence-anchored streaming protocol for LoCoMo (plan section 6.5) produces enough interleaving of reads and writes to test maintenance cost on natural data. For each question compute $v(q)$, the end of the session containing its latest annotated evidence turn, and describe how read points spread over each history.

## Scope

- In scope: LoCoMo categories 1 to 4; per-question $v(q)$; distribution of $v(q)$ relative to history length; the share of questions with $v(q)$ before the final session; messages and tokens written between adjacent read points; exclusion lists (13 questions with missing or unresolvable evidence; questions on the independent audit's evidence-error list); a proposed promotion threshold computed on the development histories (conv-26, conv-49) only.
- Out of scope: any LLM run; re-annotating answers; held-out histories when setting the threshold.
- Candidate worker subtasks: one worker for the script and report.
- Dependency note: the data is downloaded with T010 (`scripts/data/b2_locomo.sh`); only the LoCoMo adapter of T002 is needed besides.

## Acceptance

- [ ] Read-point list ($v(q)$ per question) and summary statistics recorded in a run directory with code SHA, data checksum and command.
- [ ] Exclusions listed with reasons and counts.
- [ ] A threshold for promoting streaming to the main text, set on development histories and stated before held-out statistics are inspected.

## Deliverables

Bash entry point under `scripts/` calling Python under `src/grace/cli/`, the read-point list as a config under `configs/benchmarks/`, a short report linked from this file.

## Log

- 2026-11-22: created from plan section 9, phase 1 (registered by T005).
- 2026-11-22: paths and dependencies updated after T009 (package `grace`) and T010 (downloads) were merged.
