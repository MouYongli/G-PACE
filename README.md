# G-PACE

Research repository for G-PACE, worked on by Codex and Claude Code sessions in manager and worker roles. This checkout (the main checkout, `PROJECT_ROOT`) stays on `main`; managers and workers each work in their own git worktree. Work is planned as a DAG of milestones, tasks, experiments and decisions in `docs/work/plan/plan.yaml`.

## Getting started

1. Read `AGENTS.md` (Chinese translation: `AGENTS.zh-CN.md`) and `docs/README.md`.
2. Review the research plan `docs/research/plan.md`, then delete the temporary `docs/research/plan.zh-CN.v1.md`.
3. Bind the benchmarks: fill in `configs/benchmarks/<slug>.yaml` and the cards in `docs/research/benchmarks.md`.
4. Place the real data under `data/<benchmark>/<version>/` in this checkout, then make it read-only with `chmod -R a-w data`. Create `runs/`. Both are git-ignored; every worktree finds them through `PROJECT_ROOT` (see `AGENTS.md`). CI uses the synthetic fixtures in `tests/fixtures/`.
5. Install [uv](https://docs.astral.sh/uv/), then run `make setup`, `make test` and `make lint`.
6. On GitHub, add branch rules for `main` and `task/*`: require PRs, the `contracts` and `lint` status checks, and an up-to-date base.
7. Open the plan viewer (see `docs/README.md`), create an Issue for each task you start, record it in `plan.yaml`, and start each manager session in its own worktree with the `start-manager` skill.

## Where things are

| Topic | Location |
| --- | --- |
| Agent rules | `AGENTS.md`, `.agents/roles/` |
| Procedures and forms | `.agents/skills/` |
| Claude Code configuration | `.claude/` |
| Naming conventions, file shapes, lookup paths | `docs/README.md` |
| Research plan, benchmarks, literature, contracts | `docs/research/` |
| Project DAG, status and viewer | `docs/work/plan/` |
| Tasks, experiments, decisions | `docs/work/tasks/`, `docs/work/experiments/`, `docs/work/decisions/` |
| Shared paths and configs | `configs/` |
| Manuscript | `paper/` |

Benchmark configs are placeholders until the data is bound; experiment results stay empty until real runs complete.
