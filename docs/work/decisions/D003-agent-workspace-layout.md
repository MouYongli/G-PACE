---
id: D003
title: Agent workspace layout and language policy
created: 2026-11-21
---

# D003 · Agent workspace layout and language policy

## Context

The repository is worked on by Codex and Claude Code sessions in manager and worker roles. The initial layout duplicated `.agents/` into `.claude/` file by file, kept role and template files in `.claude/` that Claude Code does not interpret, wrote all documents in Chinese, and specified interfaces in four very short files under `docs/contracts/`.

## Decision

1. **Single source of truth for agent rules.** `.agents/` holds tool-neutral content: `roles/` (manager, worker, reviewer) and `skills/` (procedures with their form templates, in `SKILL.md` format). Both tools reach the roles through `AGENTS.md`; `CLAUDE.md` imports `AGENTS.md`.
2. **Tool-specific directories hold only native configuration.** `.claude/` contains `settings.json` (permission deny rules), `agents/reviewer.md` (read-only review subagent) and a `skills` symlink to `.agents/skills`. A `.codex/config.toml` may be added for Codex sandbox and approval settings.
3. **Templates become skills.** Forms are YAML files bundled with the skill that uses them (`start-manager`, `assign-worker`, `worker-handoff`, `experiment-report`), so they are filled as part of a procedure and are machine-readable.
4. **One contracts file.** Interfaces live in `docs/research/contracts.md`, one section per interface with an owner and a version, alongside the executable side in `tests/contracts/` and `tests/fixtures/`. It sits under `docs/research/` because it defines how things are measured, not process documentation (`docs/work/`). Split it into a directory when JSON Schemas are added, a section exceeds about 100 lines, or two owners change it concurrently.
5. **Language.** All repository files are in English. `AGENTS.zh-CN.md` is the only translated file: a Chinese translation of the canonical `AGENTS.md`, updated in the same PR, with a test that checks the heading structure matches. `CLAUDE.md` has no translation because it only imports `AGENTS.md` and adds a few Claude Code notes. Agents converse with the user in Chinese.
6. **Project scaffolding.** Add `pyproject.toml` (Python >= 3.10, ruff), the `src/gpace/` package, and `paper/` for the manuscript and figure scripts.
7. **One repository, many worktrees.** The main checkout stays on `main` as the human's workspace. Managers work on `task/T<NNN>-<slug>` worktrees cut from `main`; workers on `worker/T<NNN>-<sub>` worktrees cut from the task branch. Worktree location is left to the tool that creates it. Shared data and run artifacts are located through `PROJECT_ROOT` and `configs/paths.yaml` (D001); the data link script is removed.
8. **Research versus work.** `docs/research/` holds what is studied and how it is measured (`plan.md`, `benchmarks.md`, `literature.md`, `contracts.md`). `docs/work/` holds dated work records: `tasks/T<NNN>`, `experiments/E<NNN>` (design, runs and results in one file) and `decisions/D<NNN>`, each with YAML front matter and a dated log. Naming conventions and lookup paths are in `docs/README.md`. Merge and recovery rules are in `.agents/roles/manager.md`; GitHub branch rule setup is in the root `README.md`.
9. **The plan is a DAG in the repository.** `docs/work/plan/plan.yaml` holds milestones (one per phase of plan section 9, each with a gate) and nodes (tasks, experiments, decisions) with dependencies, status and dates. It is the single source of status; GitHub Issues are for discussion only. Only the integration owner edits it, through PRs to `main`, because status edits from task branches would be invisible on `main` until merged and would conflict. Progress is derived from it; verified progress is logged as checkpoints in `docs/work/plan/README.md`. `docs/work/plan/index.html` visualizes it (Cytoscape.js with dagre, loaded from a CDN) and needs a local HTTP server; `tests/docs/test_plan.py` validates it.

## Consequences

- Rules are edited in one place; Claude Code and Codex cannot drift apart.
- Long-running manager and worker sessions remain separate sessions in their own worktrees; Claude Code subagents are used only for short read-only reviews.
- Manager and worker branches share one git directory, so a manager sees worker commits without fetching; PRs still go through GitHub.
- The Codex repository skill path (`.agents/skills`) should be re-checked against current Codex documentation when Codex is first used on this repository.

## Revisit when

Either tool adds native support for role definitions of long-running sessions, or the Codex skill location changes.

## Log

- 2026-11-21: accepted (2026-11-21).
