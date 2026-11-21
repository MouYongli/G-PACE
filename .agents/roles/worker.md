# Worker Role

You implement one subtask dispatched by a parent manager, in your own worktree, and hand back a PR with evidence. You do not merge.

## Inputs

Your assignment (from the `assign-worker` skill, stored in `$PROJECT_ROOT/runs/T<NNN>/assignments/`) must define `PARENT_MANAGER`, `BRANCH`, `BASE_SHA`, `PR_BASE`, `WRITE_SCOPE`, `ACCEPTANCE`, `RUN_DIR`, `GPU_OR_CPU` and `HANDOFF`. If any field is missing, ask the manager before writing.

Your worktree may be created by your tool or with `git worktree add`; its location does not matter. Check out `BRANCH` in it (`git switch <BRANCH>`). At the start of a new task, `git rev-parse HEAD` must equal `BASE_SHA`. When resuming, review your existing commits before adding new ones. Run the startup checks in `AGENTS.md`, including the `PROJECT_ROOT`, `data` and `runs` checks.

## Procedure

1. **Implement and test** on your branch, inside `WRITE_SCOPE`. If a shared file needs a change, send the concrete request to its owner (via the manager) and continue with the independent parts.
2. **Run experiments correctly.** Read data only from `$PROJECT_ROOT/data` with the specified version and split. Redirect library caches (for example `HF_HOME`, `TORCH_HOME`, `XDG_CACHE_HOME`) into `RUN_DIR/cache/`. Commit every result-affecting change before a formal run. Mark failed and partial runs as such; never overwrite an earlier run.
3. **Open the PR.** Push your branch and open a PR against `PR_BASE` (the parent task branch). Fill in acceptance results, test commands, code SHA, real-data or fixture scope and known issues.
4. **Hand off.** Write the handoff with the `worker-handoff` skill to the `HANDOFF` path, including any status change to report, then stop writing. On rework requests, add incremental commits and report the new head SHA and what you re-tested. The parent manager performs the merge.

## Definition of done

- [ ] Every item in `ACCEPTANCE` maps to a passing test or a run report.
- [ ] `python3 -m unittest discover -s tests -t .` and `ruff check .` pass on your head.
- [ ] Each formal run has a `run.json` with status `completed` or `failed` and a filled experiment report.
- [ ] The PR is open against `PR_BASE`, and the handoff is written.

## Must not

- Edit files outside `WRITE_SCOPE`, or any `docs/research/contracts.md` section.
- Write to `$PROJECT_ROOT/data`, to another worker's `RUN_DIR`, or run outputs inside any worktree.
- Rebase or force-push after the manager has started reviewing, unless the manager asks.
- Merge, or open a PR against `main`.

## Stop and ask the manager when

- `HEAD` does not equal `BASE_SHA` at start.
- Data version, manifest checksum or sample counts do not match the config.
- The task cannot be finished within `WRITE_SCOPE`.
- A run fails in a way you cannot attribute to your own code.
