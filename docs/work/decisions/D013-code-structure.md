---
id: D013
title: Code structure and dependency rules
created: 2026-11-24
---

# D013 · Code structure and dependency rules

## Context

`src/grace/` holds only the download command and the path resolver. Phase 2 starts several tasks in parallel (T014, T015, T017, T018, T019), each with its own `WRITE_SCOPE`, so the package layout has to be fixed before they are dispatched.

The layout must serve three requirements of the plan:

- **Leakage prevention (section 6.8).** Questions, reference answers and evidence annotations are invisible while writing, for GRACE and for every baseline.
- **Experiments of different shapes (sections 6 and 7).** Some experiments answer questions end to end. Others run on gold graphs, or ask no questions at all: ablation A on gold graphs, the scale experiment, the natural distribution of staleness, graph quality.
- **Cost (section 8).** The write side of LongMemEval-S alone is estimated at 80M to 680M tokens. Four budget levels and the read-side ablations change only the read path. One set of MultiWOZ predictions is scored against three annotation versions, and judge reruns are reported separately.

## Options

**Shape of `eval/`.**

1. One harness package that ingests, asks and scores in one loop.
2. Four groups along the data flow: `datasets`, `engines`, `runner`, `analysis`. The runner separates experiments that call the answering LLM (`harness`) from those that do not (`probes`); `analysis` reads only files.

**Where the interface lives.**

1. In `context/engine.py`, together with `GraceEngine`.
2. In its own file, `context/api.py`, which imports nothing else from `context/`.

**Where the baselines live.**

1. In a top-level package beside `context/`.
2. Under `eval/engines/baselines/`, kept away from gold data by an import rule.

**How a GRACE variant is expressed.**

1. As a class in the baselines package.
2. As a config file that replaces one component of the GRACE assembly.

**A separate package for timing and traces (`telemetry/`).**

1. Yes.
2. No: the trace types live in `context/api.py` and each component times itself.

## Decision

The layout, the dependency rules and the responsibility of each file are specified in `docs/work/plan/structure.md`. The choices behind it:

- **`eval/` has four groups along the data flow** (option 2). A single loop cannot run the gold-graph and no-question experiments, and it ties scoring to inference.
- **A run has stages: system, judging, scoring.** Each stage reads only the files of the stage before it. Under end-of-history reading the system stage splits again into ingestion and reading, and one ingestion snapshot serves several read configurations. Under per-turn and interleaved reading it does not split, because a read changes resident views.
- **The interface is in `context/api.py`** (option 2). The rule "a baseline depends only on the interface" can then be checked as an import rule.
- **Baselines stay under `eval/`** (option 2). `engines/baselines/` does not import `datasets/`; `engines/oracles/` is the only package that hands gold data to a system. A sentinel test covers what import rules cannot.
- **A variant is a config** (option 2). The replaced component lives in `context/` next to the component it replaces, and `engine.py` has no branches for variants. `eval/engines/baselines/` holds only systems that do not use the GRACE assembly.
- **No `telemetry/` package** (option 2). The plan asks only that latency and database time be reported separately.
- **`pipeline/` is split by function, and its packages do not call each other.** The order of steps is written only in `engine.py`. `pipeline/update/` imports only `memory/`, which keeps views away from the writer.
- **`views/staleness/` is its own package.** The eight strategies are the whole subject of ablation A, and the replay probe needs nothing else from `views/`.
- **`resources/` holds prompts, vocabulary, view templates and schemas** at the repository root, read from the current worktree and frozen as a whole at D012.
- **`configs/` gains `common/`, `models/` and `engines/`.** `paths.yaml` moves to `configs/common/`.

Two points were proposed separately and confirmed with the decision:

- **The directory name `configs/engines/`.** It matches the interface name `ContextEngine` and the package `eval/engines/`. The alternative considered was `configs/systems/`.
- **Budget levels under interleaved reading.** Each budget level runs its own pass. Forking the state at every read point would save ingestion cost but needs cheap snapshots; it is not built unless the cost of separate passes proves prohibitive.

## Consequences

- An import-check test and a gold-sentinel test in `tests/contracts/` enforce the rules. Tasks cut their `WRITE_SCOPE` along the packages of `structure.md`.
- `AGENTS.md` and `AGENTS.zh-CN.md` change with this decision: the repository map points to `docs/work/plan/structure.md`, the `src/grace/` row lists the five packages, and four rules join the hard rules (`context/` does not import `eval/`; `eval/engines/baselines/` does not import `eval/datasets/`; every model call goes through `llm/`; `eval/analysis/` reads only files in run directories).
- Moving `paths.yaml` changes the path written in `AGENTS.md`, `AGENTS.zh-CN.md`, `src/grace/paths.py`, `docs/research/contracts.md` and `docs/README.md`; all are updated in the PR that moves it. `src/grace/paths.py` moves to `src/grace/config/paths.py`.
- Three extensions are requested from the owner of the "Experiment run" section of `docs/research/contracts.md`:
  - a run may reference an upstream run by its run ID and read it without writing to it (the precondition for stages);
  - the intermediate artefacts are listed: `calls.jsonl`, working contexts, change sets, write and read traces, judgements;
  - `run.json` records the checksum of `resources/`.
- T008 states how the invalidation ground truth of the controlled sequences is computed. The recommendation is one small function per template family that reads the event log directly and does not use the query compiler. Otherwise the end-to-end reference shares the compiler with the system under test, and a compiler error would be invisible. On gold graphs both routes must agree, which also tests the compiler.
- The owners of T003 and T027 decide whether the fixed slot table is one implementation or two. The phase 1 pilot needs it before GRACE exists; ablation B needs it inside the GRACE assembly, combined with the attribution guard and bitemporality.
- Pure logic such as the compiler, the attribution guard and the staleness strategies needs unit tests. They go to `tests/unit/`, which is listed in the repository map of `AGENTS.md`.
- Baselines and GRACE time themselves, so latency figures may not be measured in exactly the same way. This is accepted, because latency is reported separately and supports no main conclusion.

## Revisit when

- Code outside `eval/` needs to write run directories: move the run-directory code out of `runner/harness/`.
- Latency or database time becomes part of a main claim, or the timing of baselines and GRACE cannot be aligned: introduce a shared timing module.
- Variants force branches into `engine.py`: reconsider how the engine is assembled.
- Any file listed in `structure.md` grows into several concerns: split it into a subpackage inside the same package; this needs no new decision.

## Log

- 2026-11-24: proposed. Registered in `plan.yaml` as a project-wide decision; T002, T003, T004 and T014, the first nodes that add packages under `src/grace/`, depend on it.
- 2026-11-24: accepted by the user, including the directory name `configs/engines/` and separate passes per budget level under interleaved reading.
- 2026-11-24: follow-ups written into the task files: the contract extensions and the import-rule test into T001, layout, the gold-sentinel test and the slot-table question into T003 and T027, the invalidation ground truth into T008 and T015. `tests/unit/` added to the repository map. Not yet assigned: moving `paths.yaml` and `paths.py`.
