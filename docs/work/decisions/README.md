# Decisions

A decision records a choice that constrains later work: context, options, the choice, its consequences and when to revisit it. Its status (`proposed`, `accepted`, `superseded`, `rejected`) and date live in `../plan/plan.yaml`. A replaced decision keeps its file; the new one links to it and the old one gets a log entry.

## Index

| ID | Title | Description |
| --- | --- | --- |
| [D001](D001-shared-benchmark-storage.md) | Shared benchmark storage and run artifacts | Data and run artifacts in the main checkout, located through `PROJECT_ROOT` |
| [D002](D002-evaluation-aggregation.md) | Evaluation aggregation | Report each benchmark separately; no unregistered overall score |
| [D003](D003-agent-workspace-layout.md) | Agent workspace layout and language policy | `.agents/` as single source, worktrees, language policy, docs layout |
| [D004](D004-python-and-inference-environment.md) | Python version and inference environment | Python 3.12; CPU-only research environment; separate vLLM serving environment over HTTP |
| [D005](D005-contribution-wording.md) | Wording of the proposition and contribution scope | Phase 0 gate: what the paper claims as new after the novelty check |
| [D006](D006-model-lineup.md) | Model line-up and judge snapshot | Contemporary small model, long-context second reader, larger same-family writer and judge snapshot |
| [D007](D007-gate-evidence-placement.md) | Phase 1 gate: evidence placement | Where each claim's primary evidence sits after the pilot measurements |
| [D008](D008-gate-paper-framing.md) | Phase 2 gate: paper framing | Whether view maintenance remains a cost claim |
| [D009](D009-gate-extraction-bottleneck.md) | Phase 3 gate: extraction bottleneck | What the extracted-graph results allow the paper to claim; main extraction granularity |
| [D010](D010-gate-role-claims.md) | Phase 4 gate: role and open-predicate claims | How far the role and open-predicate claims are narrowed |
| [D011](D011-vocabulary-go-no-go.md) | Whether to run vocabulary evolution | Go or no-go for the optional phase 5 |
| [D012](D012-configuration-lock.md) | Configuration lock | Freeze of configuration, splits, judging rules, budgets and non-inferiority margins |
| [D013](D013-code-structure.md) | Code structure and dependency rules | Packages of `src/grace/`, their import rules and how experiments run in stages; layout in `../plan/structure.md` |


## Template

```markdown
---
id: D<NNN>
title: <title>
created: <YYYY-MM-DD>
---

# D<NNN> · <title>

## Context

## Options

## Decision

## Consequences

## Revisit when

## Log

- <YYYY-MM-DD>: proposed.
```
