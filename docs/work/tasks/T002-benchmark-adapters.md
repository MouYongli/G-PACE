---
id: T002
title: Benchmark adapters
created: 2026-11-21
---

# T002 · Benchmark adapters

## Goal

Adapters that turn each benchmark's development histories into the T001 records, with counts checked against the manifests, so phase 1 pilot measurements can run on all benchmarks.

## Scope

- In scope: adapters and manifests for LoCoMo, LongMemEval S, MultiWOZ 2.4/2.2, HaluMem-Medium, MemoryAgentBench; the generator skeleton for the controlled change sequences.
- Out of scope: held-out splits beyond what phase 1 needs; conditional benchmarks (STALE, Memora).
- Candidate worker subtasks: one per benchmark.

## Acceptance

- [ ] Each adapter passes the contract tests and reproduces the counts in `docs/research/benchmarks.md`.
- [ ] Development/held-out split lists are written to configs and match the plan.
- [ ] Excluded inputs (for example LoCoMo images and human summaries) are excluded and counted.

## Deliverables

`src/gpace/` adapters, `configs/benchmarks/<slug>.yaml`, filled sections in `docs/research/benchmarks.md`.

## Log

- 2026-11-21: created from plan section 9, phase 1.
