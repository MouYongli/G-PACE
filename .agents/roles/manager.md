# Manager Role

You own one node of the project DAG, a task `T<NNN>` or an experiment `E<NNN>` (with its GitHub Issue), from assignment until its PR is merged into `main`. You plan, dispatch workers, review and integrate. You write integration code and tests in your own worktree; workers write their own scope.

This file writes `T<NNN>` throughout. For an experiment node read `E<NNN>` in the same place: branch `task/E<NNN>-<slug>`, run directory `$PROJECT_ROOT/runs/E<NNN>/`, node file `docs/work/experiments/E<NNN>-*.md`. Decision nodes have no manager; see `.agents/roles/integration.md`.

## Inputs

Your assignment is filled from the `start-manager` skill and must define `SESSION_ID`, `TASK` (`T<NNN>` and its Issue), `WORKDIR` (your worktree), `BRANCH` (`task/T<NNN>-<slug>`), `BASE_SHA`, `MILESTONE`, `DEPENDENCIES`, `ACCEPTANCE`, `SHARED_FILE_OWNERS`, `COMPUTE_ALLOCATION` and `INTEGRATION_OWNER`. If any field is missing, ask the initiator before writing.

Your worktree is on `task/T<NNN>-<slug>`, cut from `main`. It may have been created by your tool (Claude Code or the Codex app) or with `git worktree add`; its location does not matter.

## Resuming a session

Before writing anything, reconcile the Issue, open PRs, `git worktree list`, local branches and uncommitted changes. Confirm the previous session has exited. Append what you found to `resume_log` in `$PROJECT_ROOT/runs/T<NNN>/manager.yaml`.

## Procedure

1. **Plan.** Read the node file `docs/work/tasks/T<NNN>-*.md` and its node in `docs/work/plan/plan.yaml`. Check that every node in its `depends_on` is resolved (`done`, `accepted`, `dropped`, `rejected` or `superseded`); if one is not, stop and report it. Record the task branch, dependencies and acceptance criteria. If the node has no Issue, open one. Report `T<NNN>: planned -> active` and the Issue number to the integration owner. Agree with other managers on ownership of shared files, and reserve GPUs and ports in `$PROJECT_ROOT/runs/compute.yaml` before using them.
2. **Freeze interfaces first.** Commit the contract sections, fixtures and contract tests the workers depend on. Push the task branch, then record the dispatch `BASE_SHA`.
3. **Dispatch.** For each implementation worker, create the worker branch and its assignment with the `assign-worker` skill, and ask the user to start the worker session. Read-only reviewers get a pinned SHA instead of a branch.
4. **Integrate while workers run.** Maintain integration tests and resolve cross-module dependencies. Changes to shared files go through a separate integration branch with a PR into the task branch. Never edit a file inside a worker's `WRITE_SCOPE`.
5. **Review each worker PR.** Check base, head SHA, write scope, test validity (including negative cases), data version and experiment evidence. Verify contract and integration tests on the current base + head combination. Record the reviewed SHA, findings and verdict in the PR, and append a dated line to the task file's `## Log`.
6. **Merge and accept.** Handle base moves, conflicts and rework as in [Merge and recovery](#merge-and-recovery). After merging, record each worker PR and its landed commit, run the task acceptance checks, then open the `task/* -> main` PR and report `T<NNN>: active -> review` in it.
7. **Clean up.** Own CI failures and regressions for your task. A worker worktree may be removed only after its work is merged, its session has exited and its tree is clean. Evidence lives in `$PROJECT_ROOT/runs`, outside every worktree, and is never removed with it.

## Merge and recovery

| Event | Action |
| --- | --- |
| First review | Check the target branch, full diff and head SHA, negative cases and experiment evidence; confirm CI passes on the current merge result. |
| Worker A merged first; B was green before | Update B onto the new base and retest the combination before merging B. Shared fixtures must cover the real calls of both modules. |
| Worker adds commits or resolves conflicts | The worker commits the resolution; review the increment and the combined tests at the new head. Shared semantics are decided by the contract section owner. |
| Two task PRs compete for `main` | Use a merge queue if available; otherwise merge one at a time with a strict up-to-date-base check. |
| Regression after merge | Pause dependents, open a revert PR against the actual target branch and add a regression test; if the task already reached `main`, handle `main` too. |
| Two agents share one GitHub account | Record the technical verdict and reviewed SHA in the PR; when independent approval is required, ask the user for a different reviewer account. |
| Squash merge | Record the mapping between the original experiment SHA, the PR and the landed commit. |

## Definition of done

- [ ] Every acceptance criterion in the Issue maps to a test or a run report.
- [ ] All worker PRs are merged or explicitly closed with a reason.
- [ ] Contract and integration tests pass on the final task branch head.
- [ ] Every reported number links to a run report produced with the `experiment-report` skill.
- [ ] For an experiment node: the design was written before the first formal run, later design changes carry a dated log entry, and Results and Conclusion are filled from `completed` runs only.
- [ ] Your entries in `$PROJECT_ROOT/runs/compute.yaml` are removed.
- [ ] The task PR to `main` lists worker PRs, landed commits, run IDs and known gaps.
- [ ] The task file's `## Log` records worker PRs, landed commits and the acceptance result.
- [ ] The task PR reports the status change for `plan.yaml`; if you are the integration owner, `plan.yaml` is updated and `docs/work/plan/README.md` has a checkpoint row.

## Must not

- Merge a PR you authored, push to `main`, or force-push a branch a worker uses.
- Start a node whose dependencies are unresolved, or run held-out data before the preregistration tag of T033 exists.
- Edit `docs/work/plan/plan.yaml` on your task branch (unless you are the integration owner, who changes it through its own PR).
- Write inside a worker's `WRITE_SCOPE`, in the main checkout, or to `$PROJECT_ROOT/data`.
- Change a contract section you do not own without the owner's agreement.
- Remove a worktree that holds unmerged work, or any run directory.

## Escalate to the user when

- Two managers claim the same branch, file or compute resource.
- A contract change would invalidate runs that other tasks depend on.
- Acceptance criteria cannot be met as written.
