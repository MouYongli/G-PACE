---
id: T002
title: Benchmark adapters
created: 2026-11-21
---

# T002 · Benchmark adapters

## Goal

Adapters that turn each benchmark's development histories into the T001 records, with counts checked against the manifests, so phase 1 pilot measurements can run on all benchmarks.

## Scope

- In scope: adapters for LoCoMo, LongMemEval S, MultiWOZ 2.4/2.2/2.1, HaluMem-Medium, MemoryAgentBench (LongMemEval(S\*) and FactConsolidation at 6K and 32K); the generator skeleton for the controlled change sequences, following the design of T008.
- Out of scope: held-out splits beyond what phase 1 needs; benchmarks not evaluated (BEAM, Memora, STALE).
- Candidate worker subtasks: one per benchmark.

## Acceptance

- [ ] Each adapter passes the contract tests and reproduces the counts in `docs/research/benchmarks.md`.
- [ ] Development/held-out split lists are written to configs and match the plan.
- [ ] Excluded inputs (for example LoCoMo images and human summaries) are excluded and counted.

## Deliverables

`src/grace/` adapters, `configs/benchmarks/<slug>.yaml`, filled sections in `docs/research/benchmarks.md`.

## Log

- 2026-11-21: created from plan section 9, phase 1.
- 2026-11-22: scope aligned with plan v3 (MultiWOZ 2.1 added, MemoryAgentBench subsets, BEAM/Memora/STALE not evaluated); T006 and T007 need only the MultiWOZ and LoCoMo parts.
- 2026-11-22: downloads and manifests are provided by T010 (`scripts/data/`, `configs/data/sources.yaml`); this task binds the downloaded versions in `configs/benchmarks/` and writes the adapters.
- 2026-11-25: manager session `m01-T002` started on `task/T002-benchmark-adapters` from `985d232`; Issue #34. No workers dispatched; the manager wrote the adapters itself. All seven manifests match `configs/data/sources.yaml`.
- 2026-11-25: adapters for LoCoMo, LongMemEval S, MultiWOZ 2.4/2.2/2.1, HaluMem-Medium and MemoryAgentBench, `splits.load_split` with the held-out guard (tag `preregistration`, provisional until T033), split lists and counts in `configs/benchmarks/`, cards filled. Counts match plan 6.5 and 11.1 (LoCoMo 308/1,232 and 13 incomplete-evidence questions; MultiWOZ test 1,000/7,372; LongMemEval 500 with KU 78, TR 133, MS 133; HaluMem 20 users, 14,948 memory points, 3,467 questions; MemoryAgentBench LongMemEval(S*) 5 × 60). Development splits converted to `runs/T002/artifacts/records/<slug>/dev/`.
- 2026-11-25: mapping rows of HaluMem (evidence cites memory points, so `evidence_ids: null`) and MemoryAgentBench (context IDs built; `question_dates` → `asked_at`) corrected in `contracts.md`, with the HaluMem fixture. Deferred: the change-sequence generator skeleton (`eval/datasets/changeseq/`).
