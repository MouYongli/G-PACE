# Decisions

A decision records a choice that constrains later work: context, options, the choice, its consequences and when to revisit it. Its status (`proposed`, `accepted`, `superseded`, `rejected`) and date live in `../plan/plan.yaml`. A replaced decision keeps its file; the new one links to it and the old one gets a log entry.

## Index

| ID | Title | Description |
| --- | --- | --- |
| [D001](D001-shared-benchmark-storage.md) | Shared benchmark storage and run artifacts | Data and run artifacts in the main checkout, located through `PROJECT_ROOT` |
| [D002](D002-evaluation-aggregation.md) | Evaluation aggregation | Report each benchmark separately; no unregistered overall score |
| [D003](D003-agent-workspace-layout.md) | Agent workspace layout and language policy | `.agents/` as single source, worktrees, language policy, docs layout |

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
