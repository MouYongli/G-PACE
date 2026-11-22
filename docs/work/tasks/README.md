# Tasks

A task is a unit of work owned by one manager session and delivered by one task PR into `main`. It may contain several worker subtasks. Status, owner, dates and dependencies live in `../plan/plan.yaml`; this folder holds the content.

The integration owner adds a row here when a task is created. The task's manager keeps its `## Log` up to date on the task branch.

## Index

| ID | Title | Description |
| --- | --- | --- |
| [T001](T001-record-contracts.md) | Record contracts | History, message and question records plus the token-cost ledger |
| [T002](T002-benchmark-adapters.md) | Benchmark adapters | Adapters for the development histories of all benchmarks |
| [T003](T003-baseline-runners.md) | Baseline runners | Full history, text retrieval, rolling summary and JSON state table |
| [T004](T004-prompts-counters-judges.md) | Prompts, counters, judges | Frozen English prompts, token counters, budgets and judges |
| [T009](T009-env-setup.md) | Python and inference environment | Python 3.12, research and vLLM serving environments (D004) |

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
