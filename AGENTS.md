# G-PACE Agent Guide

G-PACE is a research project. The research question, hypotheses and design live in `docs/research/plan.md`; milestones, tasks and their status live in `docs/work/plan/plan.yaml`. This file is loaded automatically by Codex (directly) and Claude Code (through `CLAUDE.md`). Keep it short: it is an index plus hard rules; details belong in the files it points to.

## Language

- Write every repository file in English: code, comments, docs, configs, commit messages, PR and Issue text.
- Exception: `AGENTS.zh-CN.md` is the Chinese translation of this file. The English file is canonical. Any PR that changes `AGENTS.md` updates `AGENTS.zh-CN.md` in the same PR (CI checks that the heading structure matches).
- Converse with the user in Chinese.

## Session identity

Every session starts from an assignment that declares `ROLE`, `SESSION_ID`, `TASK`, `WORKDIR` and `BRANCH`.

| ROLE | Read before acting | Assignment form |
| --- | --- | --- |
| `manager` | `.agents/roles/manager.md` | skill `start-manager` |
| `worker` | `.agents/roles/worker.md` | skill `assign-worker` |
| `reviewer` | `.agents/roles/reviewer.md` | review request naming a SHA |

If the role is missing, stay read-only until the initiator states the role and ownership in writing.

## Repository and worktrees

One repository, many worktrees. The main checkout stays on `main` and is the human's workspace; agents do not edit code there. Each manager works in a worktree on `task/T<NNN>-<slug>` cut from `main`; each worker works in a worktree on `worker/T<NNN>-<sub>` cut from its task branch. A branch can be checked out in only one worktree, which enforces one writer per branch. Worktree location does not matter: it may be created by Claude Code, the Codex app or `git worktree add`. Naming conventions and lookup paths: `docs/README.md`.

## Project root and paths

`PROJECT_ROOT` is the main checkout, shared by all worktrees. Shell state does not persist between tool calls, so compute it inside every command that needs it:

```bash
PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")}"
```

- An exported `PROJECT_ROOT` environment variable takes precedence; otherwise it is the parent of the shared `.git` directory. Code that resolves paths uses the same order.
- `configs/paths.yaml` is the only source of shared directories (`data_root`, `runs_root`), written relative to `PROJECT_ROOT`.
- `$PROJECT_ROOT/data` holds the read-only benchmark store and `$PROJECT_ROOT/runs` holds every `RUN_DIR`. Both are git-ignored and exist only in the main checkout, so removing a worktree never removes data or evidence.
- Never write absolute paths into tracked files. Record resolved absolute paths in `run.json` instead.

## Startup checks

Run these first and compare the output with the assignment. Stop if they disagree.

```bash
pwd -P
git rev-parse --show-toplevel
git branch --show-current
git status --short
PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")}"; echo "$PROJECT_ROOT"
test -d "$PROJECT_ROOT/data" && test ! -w "$PROJECT_ROOT/data" && echo "data: present, read-only"
test -w "$PROJECT_ROOT/runs" && echo "runs: writable"
```

Preserve any existing uncommitted changes; never reset or discard them without asking.

## Repository map

| Path | Purpose | Who writes |
| --- | --- | --- |
| `AGENTS.md`, `AGENTS.zh-CN.md`, `CLAUDE.md` | Agent entry points | Integration owner |
| `.agents/roles/` | Session rules per role (shared by Codex and Claude Code) | Integration owner |
| `.agents/skills/` | Reusable procedures and form templates (`SKILL.md` format) | Integration owner |
| `.claude/` | Claude Code only: `settings.json`, `agents/`; `skills` is a symlink to `.agents/skills` | Integration owner |
| `docs/README.md` | Naming conventions, file shapes, lookup paths | Integration owner |
| `docs/research/plan.md` | Research plan (English, canonical); `plan.zh-CN.v1.md` is a temporary source to be deleted | Plan owner |
| `docs/research/benchmarks.md`, `literature.md` | Benchmark registry and cards; literature notes | Data owner; task owners |
| `docs/research/contracts.md` | How things are measured and exchanged; one owner per section | Section owner |
| `docs/work/plan/` | `plan.yaml` (project DAG: milestones, nodes, status, dates), `README.md` (schema, checkpoints), `index.html` (viewer) | Integration owner |
| `docs/work/tasks/`, `experiments/`, `decisions/` | One file per task `T<NNN>`, experiment `E<NNN>`, decision `D<NNN>` | Task manager; experiment runner; decision owner |
| `configs/` | `paths.yaml`, benchmark and experiment configs | Task owners |
| `src/gpace/` | Python package | Task owners within `WRITE_SCOPE` |
| `tests/` | `contracts/` (interface tests), `integration/`, `docs/`, `fixtures/` (synthetic data) | Task owners |
| `paper/` | Manuscript and figure scripts | Paper owner |
| `data/`, `runs/` | Main checkout only, git-ignored; see "Project root and paths" | Data maintainer / run owners |

## Commands

```bash
make setup                                              # create .venv and install the package with test deps (uv sync; Python >= 3.10)
make test                                               # all tests
make test-contracts                                     # contract tests only
make lint                                               # lint (ruff)
uv run python <script>                                  # run anything else inside the environment; do not call python3 or pip directly
git worktree list                                       # all worktrees and their branches
```

## Hard rules

MUST:

- Keep one writer per writable worktree at any time. Read-only reviews pin an explicit SHA.
- Read shared inputs only from `$PROJECT_ROOT/data`. Verify the version and manifest checksum named in `configs/benchmarks/`.
- Write caches, indexes, predictions, logs and checkpoints only to your exclusive `RUN_DIR` under `$PROJECT_ROOT/runs` (see `docs/research/contracts.md#experiment-run`).
- Commit every change that can affect a result before a formal run, and record the full SHA, resolved config, data checksums, split, seed, command and compute resources.
- Report failures, partial results and skipped checks as such, with the actual output.

MUST NOT:

- Write to `$PROJECT_ROOT/data`, or edit code in the main checkout.
- Put absolute paths in tracked files.
- Edit a `docs/research/contracts.md` section you do not own. Send the request to the owner and continue with independent work.
- Report a score that does not link to real run evidence. Synthetic fixtures are for CI only.
- Push to `main`, force-push a shared branch, or merge your own PR.
- Edit `docs/work/plan/plan.yaml` or the index tables in `docs/work/*/README.md` unless you are the integration owner of the current round.
- Write status or dates into task, experiment or decision files; they live only in `plan.yaml`.

## Planning, status and acceptance

- The project is planned as a DAG: milestones `M<N>` (one per phase of plan section 9, each with a gate) contain tasks `T<NNN>`, experiments `E<NNN>` and decisions `D<NNN>`. `docs/work/plan/plan.yaml` is the single source of structure, status and dates; schema and checkpoints are in `docs/work/plan/README.md`.
- The integration owner updates `plan.yaml` through PRs to `main`. Everyone else reports status changes (for example `T003: active -> review`) in their PR or handoff.
- Each task, experiment and decision file has YAML front matter (`id`, `title`, `created`) and a dated `## Log`; append to the log when something happens.
- GitHub Issues are for discussion and linking PRs; each task records its Issue number in `plan.yaml`. Acceptance happens in PRs (`.github/pull_request_template.md`).
- Cross-task interface changes go through the owner of the affected contract section first.
- Branching, review, merge order and recovery are in `.agents/roles/manager.md`.

## Skills

| Skill | Use when |
| --- | --- |
| `start-manager` | Starting or resuming a manager session for an Issue |
| `assign-worker` | A manager creates a worker branch and its assignment |
| `worker-handoff` | A worker hands a PR and evidence back to its manager |
| `experiment-report` | Any formal run finishes (completed or failed); fills the experiment file's Runs and Results |

## Coding conventions

- Python >= 3.10, standard library first; add dependencies to `pyproject.toml` only with a reason in the PR.
- Code lives in `src/gpace/`; tests use `unittest`; lint with `ruff`.
- Resolve shared paths through `PROJECT_ROOT` and `configs/paths.yaml`; fail loudly when a path is missing.

## Stop and ask when

- The startup checks disagree with the assignment.
- A required change falls outside `WRITE_SCOPE` or touches a contract section you do not own.
- Data version, manifest checksum or sample counts do not match the config.
- A result contradicts the hypothesis or an earlier run, and you cannot explain why from the evidence.
- An action is irreversible or outward-facing (deleting runs, rewriting history, publishing).
