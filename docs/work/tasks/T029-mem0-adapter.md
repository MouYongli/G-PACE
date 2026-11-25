---
id: T029
title: Mem0 adapter
created: 2026-11-23
---

# T029 · Mem0 adapter

## Goal

Mem0 running under this project's protocol with the same answering LLM, answer prompt, budgets and ledger (plan section 7.2), with the adaptation, version and failure rate recorded.

## Scope

- In scope:
  - Pin the version; publish the adapter patch.
  - Record how the evidence set shown to the answering LLM is extracted.
- Out of scope: Mem0g and Graphiti (T034).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Runs on the LoCoMo development histories with all calls in the ledger.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` baseline adapter.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-T029` started on `task/T029-mem0-adapter` from `main` at `795cb9e`; Issue #71. No workers dispatched: the adapter was written in the manager worktree.
- 2026-11-25: version pinned: `mem0ai==2.2.1` (latest release, 2026-09-25), plain install without the `nlp` and `extras` extras. Its add pipeline is ADD-only ("additive extraction"): one LLM call per `add` with the last ten messages, the ten most similar existing memories and the new messages; no UPDATE or DELETE step. Without spaCy and fastembed, Mem0's entity boost and BM25 keyword channel are off and search is semantic only; the adapter refuses to run if either package is importable, so a change of environment cannot change the system silently.
- 2026-11-25: adapter patch (`src/grace/eval/engines/baselines/mem0.py`, documented in its docstring): Mem0's LLM and embedder replaced by objects that call the harness's `ModelPort` (extraction `external`/`write`/`W`, embeddings `embed`), its provider clients never built; `response_format: json_object` dropped (the port has no such option), output checked with Mem0's own parsing and retried once on invalid output like every engine; the extraction prompt's Observation Date and Current Date set to the message's time instead of the wall clock; telemetry and remote notices off, `MEM0_DIR` in a temporary directory; in-memory Qdrant and SQLite per history. Embedded in process, no service started.
- 2026-11-25: adaptation choices: one Mem0 scope per history and one `add` per message (Mem0's own LoCoMo script uses one scope per speaker and pairs of messages, which doubles the write calls); messages passed as `<speaker>: <text>` with role `user` (assistant turns `assistant`); query embedded with the same Qwen3-Embedding instruction as the dense baseline, at read time only; `top_k` 20 and `threshold` 0.1 (Mem0 defaults) and `max_tokens` 2,000 (Mem0's LLM default) as placeholders until fixed on development data.
- 2026-11-25: evidence set shown to the answering LLM: the memories Mem0's `search` returns for the question, in Mem0's ranking, packed into the read budget; each memory is one fragment `[<message id>] (<message time>) <memory text>` citing the message whose `add` produced it. A further-retrieval request is searched the same way and its new memories follow the original ones.
- 2026-11-25: harness change, additive: the deterministic fake responder (`harness/models.py`) answers Mem0's extraction prompt with one memory, so the fixture runs exercise stored memories. `tests/integration/test_baseline_runs.py` now expects ten engine configs.
