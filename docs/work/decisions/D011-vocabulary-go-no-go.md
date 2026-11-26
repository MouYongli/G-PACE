---
id: D011
title: Whether to run vocabulary evolution
created: 2026-11-23
---

# D011 · Whether to run vocabulary evolution

## Context

Phase 5 is conditional: a vocabulary-maintenance call is added only if the frozen vocabulary shows real naming conflicts in the extracted graphs (plan section 9, phase 5).

## Options

- Accept: run T032 and E015.
- Reject: keep the frozen vocabulary with aliases; mark T032 and E015 as dropped.

## Decision

Pending. To be taken when the nodes this decision depends on are resolved.

## Consequences

If rejected, D012 proceeds without E015.

## Revisit when

Predicate miss rates on held-out histories turn out high.

## Log

- 2026-11-23: proposed as part of the full project DAG.
