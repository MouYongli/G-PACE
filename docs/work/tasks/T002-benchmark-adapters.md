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
