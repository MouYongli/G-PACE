# Tasks

A task is a unit of work owned by one manager session and delivered by one task PR into `main`. It may contain several worker subtasks. Status, owner, dates and dependencies live in `../plan/plan.yaml`; this folder holds the content.

The integration owner adds a row here when a task is created. The task's manager keeps its `## Log` up to date on the task branch.

## Index

| ID | Title | Description |
| --- | --- | --- |
| [T001](T001-record-contracts.md) | Record contracts | History, message and question records plus the token-cost ledger |
| [T002](T002-benchmark-adapters.md) | Benchmark adapters | Adapters for the development histories of all benchmarks |
| [T003](T003-baseline-runners.md) | Baseline runners | Full history, text retrieval, rolling summary and fixed-schema slot table |
| [T004](T004-prompts-counters-judges.md) | Prompts, counters, judges | Frozen English prompts, token counters, budgets and judges |
| [T005](T005-plan-v3.md) | Research plan | Self-contained plan with evaluation organised by read protocols |
| [T006](T006-multiwoz-offer-turns.md) | MultiWOZ offer-turn census | Counts of offer-acceptance and rejection turns; 2.2 versus 2.4 convention |
| [T007](T007-locomo-read-points.md) | LoCoMo evidence-anchored read points | Spread of $v(q)$ for the LoCoMo streaming protocol |
| [T008](T008-change-sequence-design.md) | Controlled change-sequence generator design | Design of the RQ2 primary benchmark |
| [T009](T009-env-setup.md) | Python and inference environment | Python 3.12, research and vLLM serving environments (D004) |
| [T010](T010-data-download.md) | Benchmark download scripts | Pinned downloads of the five benchmarks with verified manifests |
| [T011](T011-novelty-check.md) | Novelty check of claim-pattern dependencies | Phase 0: whether the dependency granularity and two-level staleness are already covered |
| [T012](T012-fragment-coverage.md) | Fragment coverage annotation | Share of LoCoMo development questions expressible in the query fragment |
| [T013](T013-write-budget.md) | Write-budget estimate and break-even curves | Paper estimate of writer tokens per extraction granularity against cached full history |
| [T014](T014-claim-model.md) | Claim model and bitemporal store | Vocabulary, SHACL shapes, two serialisations and the append-only versioned graph store |
| [T015](T015-change-sequence-generator.md) | Controlled change-sequence generator | Generator of dialogues with event logs, gold graphs and per-message invalidation truth |
| [T016](T016-sequence-audit.md) | Sequence audit | Two annotators check generated dialogues against their event logs |
| [T017](T017-query-compiler.md) | Query IR and compiler | Typed intermediate representation compiled deterministically to the SPARQL fragment |
| [T018](T018-views-rendering.md) | Views and rendering | Standing views with template serialisation, LLM rendering, row binding and partial rebuild |
| [T019](T019-staleness-strategies.md) | Staleness strategies | Dependency-pattern extraction and the eight interchangeable staleness strategies |
| [T020](T020-formalisation.md) | Final formalisation and proof | Definitions, proposition, exactness conditions and the complete proof |
| [T021](T021-preprint.md) | Preprint | Preprint with the formalisation and the gold-graph results |
| [T022](T022-writer.md) | Writer: extraction and graph update | LLM extraction of claim patches, validation, role-guarded supersession, entity alignment |
| [T023](T023-query-planner.md) | Query planner | From a task to the IR by rule templates, with an LLM planner and text fallback |
| [T024](T024-graph-quality-annotation.md) | Graph-quality annotation | Gold claims for sampled segments and corrected extraction for two LoCoMo histories |
| [T025](T025-retrieval-fusion.md) | Retrieval channels, routing and fusion | Lexical, dense and graph candidates mapped to evidence IDs, routed and fused with RRF |
| [T026](T026-context-assembly.md) | Evidence-demand assembly | Greedy selection of evidence by required variables within a token budget |
| [T027](T027-structured-baselines.md) | Structured and tagged baselines | Slot table, query-time resolution, template variant and tagged hybrid retrieval |
| [T028](T028-multiwoz-state.md) | MultiWOZ state prediction and baselines | Slot projection, derived-gold scoring and the MultiWOZ-specific baselines |
| [T029](T029-mem0-adapter.md) | Mem0 adapter | Mem0 under the common protocol, reader and cost ledger |
| [T030](T030-cost-ledgers.md) | Cost ledgers and amortisation tooling | Three ledgers per method and the scripts for amortisation curves and break-even reads |
| [T031](T031-locomo-streaming.md) | LoCoMo streaming harness | Interleaved reads and writes at the evidence-anchored read points |
| [T032](T032-vocabulary-role.md) | Vocabulary maintenance role | Condition-triggered proposals of aliases, new predicates and splits (optional) |
| [T033](T033-preregistration.md) | Preregistration | Protocol file committed, tagged and registered with a third-party timestamp |
| [T034](T034-optional-adapters.md) | Optional benchmark and system adapters | Adapters for HaluMem-Medium, MemoryAgentBench, Mem0g and Graphiti (optional) |
| [T035](T035-audit-calibration.md) | Audit, judge calibration and uncertainty | Human audit of formal results, judge calibration and the uncertainty breakdown |
| [T036](T036-paper.md) | Paper and submission | The 15-page paper, supplementary material and released artefacts; end node of the plan |


## Template

```markdown
---
id: T<NNN>
title: <title>
created: <YYYY-MM-DD>
---

# T<NNN> · <title>

## Goal

One paragraph: what exists when this task is done, and which plan section or research question it serves.

## Scope

- In scope:
- Out of scope:
- Candidate worker subtasks and write scopes:

## Acceptance

- [ ] Verifiable criterion, with the test or run report that will show it.

## Deliverables

Code paths, contract sections, configs, experiment IDs.

## Log

- <YYYY-MM-DD>: created.
```
