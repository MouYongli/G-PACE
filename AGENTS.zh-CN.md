# G-PACE Agent 指南（中文译本）

> 本文件是 `AGENTS.md` 的中文译本，仅供人阅读，不会被任何工具自动加载。内容以英文版为准。修改 `AGENTS.md` 的 PR 必须同步修改本文件（CI 会检查两者的标题结构是否一致）。

G-PACE 是一个研究项目。研究问题、假设和设计见 `docs/research/plan.md`；里程碑、任务及其状态见 `docs/work/plan/plan.yaml`。Codex 直接加载 `AGENTS.md`，Claude Code 通过 `CLAUDE.md` 加载。本文件保持精简：只做索引并列出硬性规则，细节放在它指向的文件中。

## 语言

- 仓库内所有文件都用英文：代码、注释、文档、配置、commit message、PR 和 Issue 文本。
- 例外：`AGENTS.zh-CN.md` 是本文件的中文译本，以英文文件为准。修改 `AGENTS.md` 的 PR 必须在同一个 PR 中更新 `AGENTS.zh-CN.md`（CI 检查标题结构是否一致）。
- 与用户对话使用中文。

## 会话身份

每个会话都从一份任务书开始，任务书须声明 `ROLE`、`SESSION_ID`、`TASK`、`WORKDIR` 和 `BRANCH`。

| ROLE | 行动前阅读 | 任务书来源 |
| --- | --- | --- |
| `manager` | `.agents/roles/manager.md` | skill `start-manager` |
| `worker` | `.agents/roles/worker.md` | skill `assign-worker` |
| `reviewer` | `.agents/roles/reviewer.md` | 指定 SHA 的审查请求 |

角色缺失时保持只读，直到发起者以书面形式明确角色和归属。

## 仓库与 worktree

一个仓库，多个 worktree。主 checkout 始终在 `main` 分支，是人的工作区，agent 不在其中改代码。每个 manager 在一个 worktree 中工作，分支为从 `main` 切出的 `task/T<NNN>-<slug>`；每个 worker 在一个 worktree 中工作，分支为从其 task 分支切出的 `worker/T<NNN>-<sub>`。同一分支只能被一个 worktree 检出，由此保证每个分支只有一个写入者。worktree 放在哪里无关紧要，可以由 Claude Code、Codex app 或 `git worktree add` 创建。命名规范和查找路径见 `docs/README.md`。

## 项目根目录与路径

`PROJECT_ROOT` 指主 checkout，所有 worktree 共享。shell 状态不会在工具调用之间保留，所以在每条需要它的命令中现场计算：

```bash
PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")}"
```

- 已导出的 `PROJECT_ROOT` 环境变量优先；否则取共享 `.git` 目录的上一级。解析路径的代码采用相同顺序。
- `configs/paths.yaml` 是共享目录（`data_root`、`runs_root`）的唯一来源，路径相对于 `PROJECT_ROOT`。
- `$PROJECT_ROOT/data` 存放只读 benchmark 数据，`$PROJECT_ROOT/runs` 存放所有 `RUN_DIR`。两者都被 git 忽略，只存在于主 checkout，因此删除 worktree 不会删除数据或证据。
- 被追踪的文件中不得写绝对路径。解析后的绝对路径记录在 `run.json` 中。

## 启动检查

先运行以下命令，并与任务书核对；不一致时停止。

```bash
pwd -P
git rev-parse --show-toplevel
git branch --show-current
git status --short
PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")}"; echo "$PROJECT_ROOT"
test -d "$PROJECT_ROOT/data" && test ! -w "$PROJECT_ROOT/data" && echo "data: present, read-only"
test -w "$PROJECT_ROOT/runs" && echo "runs: writable"
```

保留已有的未提交修改，未经询问不得 reset 或丢弃。

## 仓库地图

| 路径 | 用途 | 写入者 |
| --- | --- | --- |
| `AGENTS.md`、`AGENTS.zh-CN.md`、`CLAUDE.md` | Agent 入口文件 | 集成负责人 |
| `.agents/roles/` | 各角色的会话规程（Codex 与 Claude Code 共用） | 集成负责人 |
| `.agents/skills/` | 可复用流程及表单模板（`SKILL.md` 格式） | 集成负责人 |
| `.claude/` | 仅 Claude Code 使用：`settings.json`、`agents/`；`skills` 是指向 `.agents/skills` 的软链接 | 集成负责人 |
| `docs/README.md` | 命名规范、文件格式、查找路径 | 集成负责人 |
| `docs/research/plan.md` | 研究计划（英文，为准）；`plan.zh-CN.v1.md` 是临时源文件，之后删除 | 计划负责人 |
| `docs/research/benchmarks.md`、`literature.md` | Benchmark 登记表与说明；文献笔记 | 数据负责人；任务负责人 |
| `docs/research/contracts.md` | 测量与数据交换规则，每节一个 owner | 该节 owner |
| `docs/work/plan/` | `plan.yaml`（项目 DAG：里程碑、节点、状态、日期）、`README.md`（schema、检查点）、`index.html`（可视化） | 集成负责人 |
| `docs/work/tasks/`、`experiments/`、`decisions/` | 每个任务 `T<NNN>`、实验 `E<NNN>`、决策 `D<NNN>` 一个文件 | 任务 manager；实验执行者；决策 owner |
| `configs/` | `paths.yaml`、benchmark 与实验配置 | 任务负责人 |
| `src/gpace/` | Python 包 | 任务负责人，限 `WRITE_SCOPE` 内 |
| `tests/` | `contracts/`（接口测试）、`integration/`、`docs/`、`fixtures/`（合成数据） | 任务负责人 |
| `paper/` | 论文稿件与图表脚本 | 论文负责人 |
| `data/`、`runs/` | 仅在主 checkout，git 忽略；见"项目根目录与路径" | 数据维护者 / 运行负责人 |

## 常用命令

```bash
make setup                                              # 创建 .venv 并安装包及测试依赖（uv sync；Python >= 3.10）
make test                                               # 全部测试
make test-contracts                                     # 仅契约测试
make lint                                               # lint（ruff）
uv run python <script>                                  # 其他命令都在该环境中运行；不要直接调用 python3 或 pip
git worktree list                                       # 列出所有 worktree 及其分支
```

## 硬性规则

必须：

- 任一可写 worktree 同一时间只有一个写入者。只读审查须指定 SHA。
- 只从 `$PROJECT_ROOT/data` 读取共享输入，并校验 `configs/benchmarks/` 中写明的版本和 manifest 校验值。
- 缓存、索引、预测、日志和 checkpoint 只写入 `$PROJECT_ROOT/runs` 下自己独占的 `RUN_DIR`（见 `docs/research/contracts.md#experiment-run`）。
- 正式运行前提交所有可能影响结果的修改，并记录完整 SHA、解析后的配置、数据校验值、split、seed、命令和计算资源。
- 失败、部分结果和跳过的检查要如实报告，并附实际输出。

禁止：

- 写入 `$PROJECT_ROOT/data`，或在主 checkout 中改代码。
- 在被追踪的文件中写绝对路径。
- 修改不归自己负责的 `docs/research/contracts.md` 小节。应把需求交给 owner，同时继续独立部分。
- 报告无法关联到真实运行证据的分数。合成 fixtures 仅用于 CI。
- 推送到 `main`、对共享分支 force-push，或合并自己的 PR。
- 非本轮集成负责人修改 `docs/work/plan/plan.yaml` 或 `docs/work/*/README.md` 中的索引表。
- 在任务、实验或决策文件中写状态或日期；这些只记录在 `plan.yaml` 中。

## 计划、状态与验收

- 项目以 DAG 规划：里程碑 `M<N>`（对应计划第 9 节的每个阶段，各有一个检查条件）包含任务 `T<NNN>`、实验 `E<NNN>` 和决策 `D<NNN>`。`docs/work/plan/plan.yaml` 是结构、状态和日期的唯一来源；schema 和检查点见 `docs/work/plan/README.md`。
- 集成负责人通过向 `main` 提 PR 更新 `plan.yaml`。其他人在 PR 或交接单中报告状态变化（例如 `T003: active -> review`）。
- 每个任务、实验和决策文件都有 YAML front matter（`id`、`title`、`created`）和按日期记录的 `## Log`；有进展时追加日志。
- GitHub Issue 用于讨论和关联 PR；每个任务的 Issue 编号记录在 `plan.yaml` 中。验收在 PR 中完成（`.github/pull_request_template.md`）。
- 跨任务的接口变更须先与相关契约小节的 owner 协调。
- 分支、审查、合并顺序和恢复见 `.agents/roles/manager.md`。

## Skills

| Skill | 使用时机 |
| --- | --- |
| `start-manager` | 为某个 Issue 启动或恢复 manager 会话 |
| `assign-worker` | manager 创建 worker 分支及其任务书 |
| `worker-handoff` | worker 将 PR 和证据交回 manager |
| `experiment-report` | 任何正式运行结束时（无论完成还是失败）；填写实验文件的 Runs 和 Results |

## 编码约定

- Python >= 3.10，优先用标准库；向 `pyproject.toml` 添加依赖须在 PR 中说明理由。
- 代码放在 `src/gpace/`；测试使用 `unittest`；用 `ruff` 做 lint。
- 共享路径通过 `PROJECT_ROOT` 和 `configs/paths.yaml` 解析；路径不存在时明确报错。

## 需要停下来询问的情况

- 启动检查结果与任务书不一致。
- 所需修改超出 `WRITE_SCOPE`，或涉及不归自己负责的契约小节。
- 数据版本、manifest 校验值或样本数与配置不符。
- 结果与假设或先前运行相矛盾，且无法从证据中解释原因。
- 操作不可逆或对外可见（删除运行记录、改写历史、发布）。
