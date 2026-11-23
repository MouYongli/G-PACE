---
id: T018
title: Views and rendering
created: 2026-11-23
---

# T018 · Views and rendering

## Goal

Query-defined views as in plan sections 3.4 and 5.4: the six template families, the view store, template serialisation and LLM rendering of result rows, per-row binding of sentences, the render check, partial rebuild on answer staleness and programmatic citation repair.

## Scope

- In scope:
  - View store with query, bound text, witnesses, evidence, dependency patterns and cutoff version.
  - Render check: every value of a row appears in its sentence and nothing else does; failures fall back to the template.
  - Instantiation threshold per binding; standing versus ephemeral views.
- Out of scope: Deciding when a view is stale (T019).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Rebuilt views equal a full rebuild on fixtures.
- [ ] Citation repair makes no LLM call; the ledger shows it.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` view package; rendering prompt registered with T004.

## Log

- 2026-11-23: created from the full project DAG.
