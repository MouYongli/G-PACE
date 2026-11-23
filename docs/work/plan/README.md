# Project Plan

The project is planned on two levels:

- **Plan level: milestones** `M<N>`. One per implementation phase of `docs/research/plan.md` (section 9). A milestone only groups nodes; it carries no dependencies of its own. Each milestone has a gate: the result that would narrow the claim instead of adding components. A decision node (`gate_node`) applies the gate, so the gate is part of the graph.
- **Execution level: nodes.** Tasks `T<NNN>`, experiments `E<NNN>` and decisions `D<NNN>`, each attached to a milestone (or to none, for project-wide decisions) and linked by dependencies.

The nodes form a directed acyclic graph. An edge means "the first node must be resolved before the second starts"; nodes without an unresolved dependency can run in parallel. The plan fixes order only, not durations. There is no artificial start node: nodes with an empty `depends_on` are the starts. There is one end node (`end`, the paper), and every milestone node leads to a deliverable. An optional node that is not run is set to `dropped` (or its decision to `rejected`), which resolves it and releases the nodes that depend on it.

`plan.yaml` is the single source of structure, status and dates. `index.html` visualizes it; see "Viewing the plan" in `docs/README.md`.

## Editing rules

- Only the integration owner edits `plan.yaml`, through a PR to `main`. Managers report status changes (for example `T003: active -> review`) in their PR or handoff; they do not edit `plan.yaml` on their task branch.
- Every node must have a file, and every file in `tasks/`, `experiments/` and `decisions/` must have a node. `tests/docs/test_plan.py` checks this, unique IDs, valid statuses, existing dependencies and the absence of cycles.
- Set `start` when a node becomes `active` (or `proposed`), and `finish` when it becomes `done`, `dropped`, `accepted`, `rejected` or `superseded`. Dates are `YYYY-MM-DD`.
- Update `updated:` at the top of `plan.yaml` with every change.

## Schema

Top-level fields: `project`, `updated`, `repo`, `end` (the end node), `deliverables` (nodes that are project outputs), `optional` (nodes outside the minimal publishable core of research plan section 9.3).

Milestone fields: `id`, `title`, `due`, `gate`, optional `gate_node` (the decision node that applies the gate), `conditional` and `status` (overrides the derived status). Order between milestones is derived from node dependencies that cross milestones.

Node fields:

| Field | Values |
| --- | --- |
| `id` | `T<NNN>`, `E<NNN>` or `D<NNN>` |
| `type` | `task`, `experiment`, `decision` |
| `title` | Short title, same as the file's front matter |
| `milestone` | A milestone ID, or `null` |
| `status` | Tasks and experiments: `planned`, `active`, `review`, `done`, `blocked`, `dropped`. Decisions: `proposed`, `accepted`, `superseded`, `rejected` |
| `depends_on` | Node IDs that must finish first; may cross milestones |
| `issue` | GitHub Issue number or `null` |
| `owner` | Manager session ID or person, or `null` |
| `start`, `finish` | `YYYY-MM-DD` or `null` |
| `file` | Path relative to this folder |

A milestone's derived status: `done` when all its nodes are resolved (`done`, `accepted`, `rejected`, `superseded`, or `dropped`); `blocked` if any node is blocked; `active` if any task or experiment has started or any node is resolved (a `proposed` decision does not count as started); otherwise `planned`.

The viewer derives the rest from the graph: a node's wave (1 if all its dependencies are resolved, otherwise one more than the largest wave among its unresolved dependencies), which nodes are ready, and the longest remaining chain.

## Checkpoints

Progress beyond status: an entry here records what was verified end to end, with evidence. Only items with evidence count as verified. Maintained by the integration owner.

| Date | Milestone | Verified scope | Evidence (PRs, SHA, run IDs) | Unverified and blockers | Next action |
| --- | --- | --- | --- | --- | --- |
