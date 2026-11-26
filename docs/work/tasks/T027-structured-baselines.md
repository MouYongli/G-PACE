---
id: T027
title: Structured and tagged baselines
created: 2026-11-23
---

# T027 · Structured and tagged baselines

## Goal

The baselines of plan section 7.2 that need the writer: a fixed-schema slot table with speaker and communicative-function fields and sources, an append-only memory that resolves conflicts at query time without caching, the template-serialisation variant of the system, and hybrid retrieval over chunks tagged with speaker and dialogue act.

## Scope

- In scope:
  - All use the same answering LLM, answer prompt and budgets.
  - Tags are predicted by the same writer and their tokens are charged.
- Out of scope: External systems (T029, T034).
- Layout (decision D013): a system that reuses the GRACE assembly is a config under `configs/engines/`, and the component it replaces lives in `src/grace/context/` next to the original. This holds for the template-serialisation variant, query-time resolution without views, and the slot table of ablation B. Only tagged hybrid retrieval, which does not use the GRACE assembly, goes to `src/grace/eval/engines/baselines/`.
- Open question, to settle with the manager of T003: whether the slot table of the phase 1 pilot and the slot table of ablation B are one implementation or two (see T003). Record the choice in both Logs.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Each baseline runs on the development set through the common runner and ledger.
- [ ] `make test` and `make lint` pass.

## Deliverables

Replacement components under `src/grace/context/` with their configs under `configs/engines/`; the tagged retrieval baseline under `src/grace/eval/engines/baselines/`.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-24: layout and the open question about the slot table added from decision D013.
