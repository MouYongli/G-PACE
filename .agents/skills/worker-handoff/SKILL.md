---
name: worker-handoff
description: Hand a finished or blocked subtask back to the parent manager. Use when a worker has opened its PR, or must stop because it is blocked.
---

# Worker Handoff

1. Push your branch and make sure the PR against `PR_BASE` is open.
2. Copy `handoff.yaml` from this skill to the `HANDOFF` path from your assignment and fill every field. Use full SHAs.
3. List every acceptance criterion with the test or run report that shows it, and the actual result. Write `not verified` instead of omitting an item.
4. Stop writing to the worktree. Resume only when the manager sends rework requests.
