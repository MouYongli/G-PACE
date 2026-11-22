---
id: T009
title: Python and inference environment
created: 2026-11-22
---

# T009 · Python and inference environment

## Goal

The research and serving environments of decision D004 exist and are documented: Python 3.12 everywhere, a CPU-only research environment with the phase 1 dependencies, and a separate vLLM serving environment with a launcher, so that T003, T004 and E001 can call local models.

## Scope

- In scope: renaming the package and project from `gpace`/G-PACE to `grace`/GRACE (from branch `chore/rename-grace`); `pyproject.toml`, `uv.lock`, `.python-version`, CI Python version, Makefile targets, `envs/serve/` and its lock, `scripts/serve-model.sh`, AGENTS.md and its translation, README.md, `docs/README.md`, D004.
- Out of scope: choosing the judge provider; reserving GPUs; external baseline environments (Mem0, Graphiti); the `environment` field of the experiment-run contract (requested from its owner).
- Candidate worker subtasks: none.

## Acceptance

- [ ] `make clean-all && make setup` builds the research environment on Python 3.12; `make test` and `make lint` pass.
- [ ] `make setup-serve` builds the serving environment; vLLM imports and its torch sees the B200 GPUs.
- [ ] A smoke test serves a small cached model on a reserved GPU and answers one request through the OpenAI client (run once GPUs are agreed).

## Deliverables

The files in scope; decision D004.

## Log

- 2026-11-22: created at the user's request; branch `task/T009-env-setup`.
- 2026-11-22: rename commit from `chore/rename-grace` cherry-picked onto this branch; stale worktree record pruned.
