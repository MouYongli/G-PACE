---
id: D001
title: Shared benchmark storage and run artifacts
created: 2026-11-21
---

# D001 · Shared benchmark storage and run artifacts

## Context

Several manager and worker sessions on one machine work in separate worktrees of one repository and read the same large inputs. Worktrees may be created by Claude Code, the Codex app or `git worktree add`, at locations we do not control. Git-ignored files (a `data` symlink, a `.env`) are not present in new worktrees.

## Decision

- Benchmarks live in `$PROJECT_ROOT/data/<benchmark>/<version>/` and run artifacts in `$PROJECT_ROOT/runs/`, both in the main checkout and git-ignored.
- `PROJECT_ROOT` is an exported environment variable if set, otherwise the parent of the shared git directory: `dirname "$(git rev-parse --path-format=absolute --git-common-dir)"`. This works from any worktree without setup.
- `configs/paths.yaml` names the shared directories relative to `PROJECT_ROOT`. Tracked files never contain absolute paths; each `run.json` records the resolved absolute paths.
- The data maintainer publishes each version with its manifest and then makes it read-only (`chmod -R a-w`).

## Consequences

- New worktrees work immediately; no link script, no per-worktree configuration.
- Removing a worktree never removes data or evidence.
- Read-only protection comes from file permissions; `.claude/settings.json` cannot cover `$PROJECT_ROOT/data` when a session runs in another worktree.

## Revisit when

Moving to multiple machines or a separate data disk: set `PROJECT_ROOT` explicitly, or extend `configs/paths.yaml` with per-machine overrides through environment variables.

## Log

- 2026-11-21: accepted (2026-11-21; replaces the earlier per-checkout `data` symlink design).
