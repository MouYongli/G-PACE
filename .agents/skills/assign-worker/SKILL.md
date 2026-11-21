---
name: assign-worker
description: Create a worker branch and its assignment. Use when a manager dispatches a subtask to a new or resumed worker session.
---

# Assign a Worker

Run from the manager's worktree. Placeholders: `T<NNN>`, `<sub>` (short subtask slug).

1. Make sure the contract sections, fixtures and tests the worker depends on are committed and pushed on the task branch.
2. Create the worker branch (not a worktree; the worker's tool creates its own worktree) and its run directory:

   ```bash
   PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")}"
   base=$(git rev-parse HEAD)
   git branch "worker/T<NNN>-<sub>" "$base"
   mkdir -p "$PROJECT_ROOT/runs/T<NNN>/artifacts/<sub>"
   cp .agents/skills/assign-worker/worker-assignment.yaml "$PROJECT_ROOT/runs/T<NNN>/assignments/<sub>.yaml"
   ```

3. Fill every field of the assignment. `WRITE_SCOPE` lists paths or globs; it must not overlap with any other active worker's scope or include `docs/research/contracts.md`.
4. Tell the user to start a worker session (a Claude Code tab in its own worktree, or a Codex app thread in worktree mode) and to send this first message:

   ```text
   ROLE=worker. Read $PROJECT_ROOT/runs/T<NNN>/assignments/<sub>.yaml and follow .agents/roles/worker.md.
   ```

   Write the absolute assignment path in the message you give the user.

Do not dispatch when the base is not pushed or when write scopes overlap.
