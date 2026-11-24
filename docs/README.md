# Documentation

`research/` says **what** we study and **how** it is measured; it changes slowly. `work/` records **who does what, when, and with what status**; it changes daily and every file in it carries dates.

## File naming conventions

File and directory names are lowercase kebab-case, except the conventional `AGENTS.md`, `CLAUDE.md`, `README.md` and `SKILL.md`. Versions are tracked by git, not by file names; freeze a version with a git tag (for example `plan-v1`).

| Item | Pattern | Example |
| --- | --- | --- |
| Milestone | `M<N>`, defined only in `docs/work/plan/plan.yaml` | `M1` |
| Task | `docs/work/tasks/T<NNN>-<slug>.md` | `T001-record-contracts.md` |
| Experiment | `docs/work/experiments/E<NNN>-<slug>.md`; its config is `configs/experiments/E<NNN>-<slug>.yaml` | `E001-pilot-measurements.md` |
| Decision | `docs/work/decisions/D<NNN>-<slug>.md` | `D001-shared-benchmark-storage.md` |
| Task branch (manager) | `task/T<NNN>-<slug>`, cut from `main`; an experiment node uses `task/E<NNN>-<slug>` | `task/T001-record-contracts`, `task/E003-ablation-a-gold` |
| Integration branch | `chore/<slug>`, cut from `main` | `chore/register-T011` |
| Worker branch | `worker/T<NNN>-<sub>`, cut from the task branch at `BASE_SHA` | `worker/T002-locomo` |
| Manager session ID | `m<NN>-T<NNN>` or `m<NN>-E<NNN>` | `m01-T001` |
| Worker session ID | `m<NN>-T<NNN>-<sub>` | `m01-T002-locomo` |
| Run ID | `<experiment>-<YYYYMMDDTHHMMSSZ>-<4 hex>` (UTC) | `E001-20261121T093000Z-a1b2` |
| Benchmark slug | lowercase kebab-case, shared by config, fixtures and its section in `benchmarks.md` | `longmemeval-s` |
| Chinese translation | `<NAME>.zh-CN.md`, only for `AGENTS.md` | `AGENTS.zh-CN.md` |

IDs are never reused. A dropped task keeps its file and its ID with status `dropped`.

## Work files: shared shape

Every task, experiment and decision file starts with YAML front matter and ends with a dated log. Status and dates live only in `plan.yaml`, never in these files.

```markdown
---
id: T001
title: History, message and question record contracts
created: 2026-11-21
---

# T001 · History, message and question record contracts

(type-specific sections; see the README of the folder)

## Log

- 2026-11-21: created from plan section 9, phase 1.
```

## Lookup paths

`PROJECT_ROOT` is the main checkout (see `AGENTS.md`). Shared directories are defined in `configs/common/paths.yaml`, relative to `PROJECT_ROOT`.

Tracked files (present in every worktree):

| What | Path |
| --- | --- |
| Agent rules | `AGENTS.md`, `.agents/roles/` |
| Procedures and forms | `.agents/skills/` |
| Research plan, literature, benchmarks | `docs/research/plan.md`, `literature.md`, `benchmarks.md` |
| Measurement and interface rules | `docs/research/contracts.md` |
| Project DAG: milestones, status, dates, checkpoints | `docs/work/plan/plan.yaml`, `docs/work/plan/README.md` |
| Code structure: packages, dependency rules, files (decision D013) | `docs/work/plan/structure.md`, `docs/work/plan/structure_full.md` |
| Tasks, experiments, decisions | `docs/work/tasks/`, `docs/work/experiments/`, `docs/work/decisions/` |
| Shared paths, benchmark and experiment configs | `configs/` |
| GPU inference environment and launcher | `envs/serve/`, `scripts/serve-model.sh` |
| Benchmark download sources and scripts | `configs/data/sources.yaml`, `scripts/data/` (Python in `src/grace/cli/data/`) |

Runtime files (main checkout only, git-ignored):

| What | Path |
| --- | --- |
| Benchmark data (read-only) | `$PROJECT_ROOT/data/<benchmark>/<version>/` |
| Manager session record | `$PROJECT_ROOT/runs/T<NNN>/manager.yaml` |
| Worker assignments | `$PROJECT_ROOT/runs/T<NNN>/assignments/<sub>.yaml` |
| Worker handoffs | `$PROJECT_ROOT/runs/T<NNN>/handoffs/<sub>.yaml` |
| Run artifacts (`RUN_DIR`) | `$PROJECT_ROOT/runs/T<NNN>/artifacts/<sub>/<experiment>/<run-id>/` |
| Compute reservations | `$PROJECT_ROOT/runs/compute.yaml` |
| Model weights | Hugging Face cache (`HF_HOME`, default `~/.cache/huggingface`), shared by all worktrees; never under `data/` |

For an experiment node the directory is `$PROJECT_ROOT/runs/E<NNN>/` with the same layout; read `T<NNN>` in `docs/research/contracts.md#experiment-run` as the node ID.

`compute.yaml` is the shared ledger of GPUs and ports. Create it if it is missing. Add your entry before starting a model server, check that it does not overlap with an existing one, and remove it when the server stops:

```yaml
- session: m01-E003        # who holds the reservation
  gpus: [0, 1]
  ports: [8000]
  since: 2026-11-23
  purpose: Qwen3-8B server for E003
```

Worktrees: their location is chosen by whoever creates them (Claude Code, the Codex app, or `git worktree add`). `git worktree list` from any worktree shows all of them.

## Viewing the plan

```bash
make plan
# open http://localhost:8000/docs/work/plan/
```

Browsers block page access to local files under `file://`, so the viewer needs this local server (or VS Code's Live Preview). It loads its libraries from a CDN.
