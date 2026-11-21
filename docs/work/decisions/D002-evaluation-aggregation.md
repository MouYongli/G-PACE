---
id: D002
title: Evaluation aggregation
created: 2026-11-21
---

# D002 · Evaluation aggregation

## Context

The three benchmarks may use metrics with different meanings and scales. A single average across them can be hard to interpret.

## Decision

The main table lists, per benchmark, the official metric, the number of samples and the number of runs. If an overall score is needed, first record the normalization method, weights and missing-value handling, and have the evaluation owner confirm it before baseline experiments start.

## Consequences

Any change updates `docs/research/contracts.md#evaluation` and the experiment configs before affected experiments are run again.

## Revisit when

The final benchmark set or metrics are fixed.

## Log

- 2026-11-21: proposed (needs project confirmation).
