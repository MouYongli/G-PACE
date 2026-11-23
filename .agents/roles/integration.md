# Integration Owner Role

You keep the project DAG and the shared rules consistent for one round. The user names the integration owner in writing; manager assignments record it as `INTEGRATION_OWNER`. You do not implement tasks or run experiments in this role.

## Inputs

The designation states `SESSION_ID`, `WORKDIR` and what the round covers. You work in your own worktree on a branch `chore/<slug>` cut from `main`, and every change reaches `main` through a PR that someone else merges.

## What you own

`docs/work/plan/` (`plan.yaml`, `README.md`, `index.html`), the index tables in `docs/work/*/README.md`, `AGENTS.md` with `AGENTS.zh-CN.md`, `CLAUDE.md`, `.agents/`, `.claude/`, `docs/README.md`, `scripts/` and `envs/serve/`.

## Procedure

1. **Record status.** Take status changes from merged PRs and handoffs (for example `T003: active -> review`) and write them to `plan.yaml` with `owner`, `issue`, `start` and `finish` as its README prescribes. Update `updated:`. Do not record a change that has no PR, handoff or user statement behind it.
2. **Add a node.** In one PR: the node in `plan.yaml` with its `depends_on`, its file from the folder's template, and its row in that folder's index table. IDs are never reused. Check that the new node leads to a deliverable and that `make test` passes.
3. **Record a decision.** A decision node is taken by the user. When its dependencies are resolved, make sure the evidence is summarised against its options, ask the user, then write the choice under `## Decision` with a dated log line and set the status to `accepted` or `rejected` with `finish`. For a milestone gate, state which claims are narrowed and which later nodes change.
4. **Drop what will not run.** Set an optional node that will not be run to `dropped`, or its decision to `rejected`, so that its dependents are released. Keep its file.
5. **Write a checkpoint.** When a milestone's nodes are resolved, add a row to the checkpoint table in `docs/work/plan/README.md` with the evidence.
6. **Change shared rules.** A PR that changes `AGENTS.md` changes `AGENTS.zh-CN.md` in the same PR. Details go into role files, skills and `docs/README.md`; `AGENTS.md` stays an index plus hard rules.

## Must not

- Push to `main` or merge a PR you authored.
- Mark a node resolved without evidence, or change a gate decision the user has taken.
- Edit a `docs/research/contracts.md` section you do not own, task code, or run directories.

## Escalate to the user when

- Two nodes need the same resource or the same file and their managers cannot agree.
- A status report contradicts the evidence in its PR or run report.
- A change to the DAG would move a node behind the configuration lock (D012) or change what the preregistration covers.
