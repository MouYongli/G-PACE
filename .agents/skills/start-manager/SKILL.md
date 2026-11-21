---
name: start-manager
description: Start or resume a manager session for one task T<NNN>. Use when a session is launched with ROLE=manager, or when a human asks to set up a new main task with its task branch and run directory.
---

# Start a Manager Session

All commands compute `PROJECT_ROOT` inline (see `AGENTS.md`).

1. Read `AGENTS.md`, `.agents/roles/manager.md`, the task file `docs/work/tasks/T<NNN>-*.md` and its node in `docs/work/plan/plan.yaml`.
2. Make sure your worktree is on the task branch. If it does not exist yet: `git fetch origin && git switch -c task/T<NNN>-<slug> origin/main`.
3. Create the run directory and the session record:

   ```bash
   PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")}"
   mkdir -p "$PROJECT_ROOT/runs/T<NNN>/"{assignments,handoffs,artifacts}
   cp .agents/skills/start-manager/manager-session.yaml "$PROJECT_ROOT/runs/T<NNN>/manager.yaml"
   ```

4. Fill every field. Use full 40-character SHAs. Write `none` when a field does not apply; leave nothing empty.
5. Run the startup checks from `AGENTS.md` and confirm `WORKDIR`, `BRANCH` and `BASE_SHA` match the output.
6. When resuming, reconcile the Issue, open PRs, `git worktree list` and uncommitted changes first, and append what you found under `resume_log`.
7. Post a short comment on the Issue with the session ID, branch and base SHA, append a dated line to the task file's `## Log`, and report `owner` and `T<NNN>: planned -> active` to the integration owner for `plan.yaml`.

Stop and ask the initiator if `TASK`, `ACCEPTANCE` or `INTEGRATION_OWNER` is unknown.
