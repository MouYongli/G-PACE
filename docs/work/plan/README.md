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
| 2026-11-23 | M0 | T011 done: dependency mechanisms of MemShift, Martin et al. (2010), Tether, StateMem and StateGraph compared with section and page anchors; both searches recorded; plan sections 2 and 3 carry no provisional wording. Gate applied through D005 (accepted, option 2): no novelty claimed for claim-pattern granularity | PR #15 (merge 454a99d), reviewed at 7c26e86, fixes 91e7897; PR #16 (merge a528cda); `docs/research/literature.md`; sources in `$PROJECT_ROOT/runs/T011/artifacts/reading/` | Data-citation papers (Buneman and Silvello; Davidson et al.; Wu et al.; ProvCite) and search B items read only at abstract or snippet level; repeat the searches before the paper is finalised | Start M1 nodes; revisit D005 if the owed full texts show a citation-level precedent |
| 2026-11-25 | M2 | E004 done: push and hybrid cost about 1 µs per standing view per write regardless of graph size; pull with fingerprints is cheaper only when a read checks few views (4) while many views stand and many writes fall between reads (crossovers 55 to 196 writes per read, 95% bootstrap intervals in the experiment file). Pull and hybrid repair identical views and actions in all 876 pairs; no model calls. The cost-based narrowing of RQ2 does not apply | PR #99 (merge 2c45bc6), head af10bd6, runs at fac294f (30 completed; 10 version-1 runs failed by design change, numbers unused); `runs/E004/artifacts/manager/` | Template families `pending` and `choice` measured only up to 16 blocks because compiled queries bind single-IRI constants through `VALUES` (slow in pyoxigraph 0.5.13), so their pull cost is overstated; synthetic writes touch one block's views each; `fork_store` copies `ClaimStore` private state | D008 once E003 and E005 resolve; optional compiler fix (inline single-IRI constants), then rerun the six-family mix on large graphs |
| 2026-11-26 | M2 | E005 done: on gold graphs with the rendering check fixed (T018: every LLM sentence must also name the binding subject), LLM rendering is worse than template serialisation at the primary budget (1024: -0.016, 95% CI [-0.024, -0.007]; 512: -0.005 [-0.021, +0.009]). The overturn condition of the RQ3 premise (template serialisation is not worse in answer accuracy) holds within E005's scope. The fix explains about 4 of the 13 points of the constraints (V4) deficit; the rest comes from how Qwen3-8B phrases constraints under the frozen render prompt | PR #103 (merge a530a2e), head a92be13, system runs at 0753fc2, score runs at 67a21f8; `runs/E005/artifacts/manager/E005-summary-rerun/`; change-seq set match registered in `configs/common/scorers.yaml` | One model renders and answers (Qwen3-8B), one seed, development data, gold graphs, five families as clusters; rendering-check fallback rose to 0.078 at 1024; the render prompt is frozen, so a better prompt or renderer is a new experiment; the change-seq benchmark card and `configs/benchmarks/change-seq.yaml` are still pending (data owner) | D008 once E003 resolves (after T016's human labels, about two days) |
