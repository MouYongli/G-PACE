---
id: T017
title: Query IR and compiler
created: 2026-11-23
---

# T017 · Query IR and compiler

## Goal

The typed intermediate representation and the deterministic compiler of plan section 5.3. It covers the six operations of the fragment (plan section 3.3), takes the cutoff version as a parameter, projects the claims and attributions behind each answer, and issues the second query that fetches evidence.

## Scope

- In scope:
  - Grammar, type checker and parameterised SPARQL templates.
  - Witness projection and the two-step evidence query.
  - Scope notes for empty results and counts, generated at read time.
- Out of scope: Producing the IR from a natural-language task (T023).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Compiled queries return the gold answers and witnesses on fixture graphs for every operation.
- [ ] Time-travel reads at a past version are unchanged by later appends.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` query package; grammar document.

## Log

- 2026-11-23: created from the full project DAG.
