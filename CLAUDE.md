# Claude Code Instructions

@AGENTS.md

## Claude Code Notes

Everything in `AGENTS.md` applies. This section lists only what is specific to Claude Code.

- `.claude/settings.json` enforces part of the hard rules: it denies force-pushes and reading `.env` files. It does not block pushes to `main` or writes to `data/`; the hard rules in `AGENTS.md` still forbid both, and read-only file permissions on `$PROJECT_ROOT/data` are the real protection for the data. Do not work around a denied action; ask the user.
- Start manager, worker and integration sessions in their own worktree (Claude Code's worktree support or `git worktree add`), never in the main checkout. Worktrees created inside the repository under `.claude/worktrees/` are git-ignored.
- `.claude/skills` is a symlink to `.agents/skills`. Edit skills under `.agents/skills/` so Codex sees the same version.
- Use the `reviewer` subagent (`.claude/agents/reviewer.md`) for read-only review of a pinned SHA. Long-running manager and worker sessions are separate Claude Code sessions started in their own worktree, not subagents.
- Do not add role or template files under `.claude/`; shared rules belong in `.agents/`.
