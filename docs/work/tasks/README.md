# Tasks

A task is a unit of work owned by one manager session and delivered by one task PR into `main`. It may contain several worker subtasks. Status, owner, dates and dependencies live in `../plan/plan.yaml`; this folder holds the content.

The integration owner adds a row here when a task is created. The task's manager keeps its `## Log` up to date on the task branch.

## Index

| ID | Title | Description |
| --- | --- | --- |
| [T001](T001-record-contracts.md) | Record contracts | History, message and question records plus the token-cost ledger |
| [T002](T002-benchmark-adapters.md) | Benchmark adapters | Adapters for the development histories of all benchmarks |
| [T003](T003-baseline-runners.md) | Baseline runners | Full history, text retrieval, rolling summary and relational state table |
| [T004](T004-prompts-counters-judges.md) | Prompts, counters, judges | Frozen English prompts, token counters, budgets and judges |
| [T005](T005-plan-v3.md) | Research plan v3 | Self-contained plan with evaluation organised by read protocols |
| [T006](T006-multiwoz-offer-turns.md) | MultiWOZ offer-turn census | Counts of offer-acceptance and rejection turns; 2.2 versus 2.4 convention |
| [T007](T007-locomo-read-points.md) | LoCoMo evidence-anchored read points | Spread of $v(q)$ for the LoCoMo streaming protocol |
| [T008](T008-change-sequence-design.md) | Controlled change-sequence generator design | Design of the RQ2 primary benchmark |
| [T009](T009-env-setup.md) | Python and inference environment | Python 3.12, research and vLLM serving environments (D004) |
| [T010](T010-data-download.md) | Benchmark download scripts | Pinned downloads of the five benchmarks with verified manifests |

## Template

```markdown
---
id: T<NNN>
title: <title>
created: <YYYY-MM-DD>
---

# T<NNN> · <title>

## Goal

One paragraph: what exists when this task is done, and which plan section or research question it serves.

## Scope

- In scope:
- Out of scope:
- Candidate worker subtasks and write scopes:

## Acceptance

- [ ] Verifiable criterion, with the test or run report that will show it.

## Deliverables

Code paths, contract sections, configs, experiment IDs.

## Log

- <YYYY-MM-DD>: created.
```
