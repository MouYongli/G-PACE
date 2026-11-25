---
id: T030
title: Cost ledgers and amortisation tooling
created: 2026-11-23
---

# T030 · Cost ledgers and amortisation tooling

## Goal

The cost side of plan section 8: per-call records aggregated into three ledgers (logical tokens, tokens actually computed after prefix caching, GPU seconds), plus the scripts that draw quality-versus-token curves, cumulative-token curves over reads, M* over the cache ratio and cost per successful task.

## Scope

- In scope:
  - Failed attempts are counted.
  - Embedding tokens, database CPU, latency and tool calls are listed separately; judge calls are evaluation overhead.
- Out of scope: Running experiments.
- Candidate worker subtasks and write scopes: none; the manager wrote the code in its own worktree.

## Acceptance

- [x] Ledger totals reconcile with per-call logs on a fixture run.
- [x] The cached full-history row is measured, not estimated.
- [x] `make test` and `make lint` pass.

## Deliverables

`src/grace/` cost package and CLI.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-T030` started on `task/T030-cost-ledgers` from `main` at `795cb9e`; Issue #66. No workers dispatched.
- 2026-11-25: layout. `eval/analysis/metrics/cost/` is a package (`ledger.py`, `amortisation.py`, `plots.py`) rather than the single `cost.py` of `structure.md`; it imports only `grace.llm.records` and reads run-directory files. Entry points: `grace.cli.cost.report` (ledger, amortise, payback, quality, success) and `grace.cli.cost.measure` (a `system` run with wall-clock GPU seconds per call). Figures and CSVs are written only into a new directory under the runs root. `llm/records.py`, the harness and `contracts.md` are unchanged.
- 2026-11-25: accounting choices. A record's cost at cache ratio c is `input - (1 - c) * cached + output` (c = 1 logical, c = 0 computed), so pricing the records of a full-history run made with prefix caching gives the cached row measured at every c; M*(c) = ceil(W(c) / (f(c) - a(c))) with f the mean warm read of the cached full history and a the mean U + A of the system. The plan 8.2 formula is reported beside it. GPU seconds are undefined (null) for a set of calls when any call has none. Two measured cache ratios: tokens (share of the reusable history not served from the cache) and GPU seconds (warm cached read over the same read uncached; an upper bound, as question prefill and decoding are included).
- 2026-11-25: finding. T003's `full-history` (uncached) development runs were served with prefix caching on (LoCoMo conv-26: 3.94M of 3.96M input tokens cached), because in client mode the engine's `prefix_caching` flag does not reach the server; they are not an uncached measurement. The T030 runs use separate servers with caching on and off.
- 2026-11-25: measured runs (Qwen3-8B, vLLM, GPU 5, development data): LoCoMo dev cached `T030-20261125T175342Z-756d` and uncached `T030-20261125T180458Z-d447`; MultiWOZ dev, first 20 dialogues, cached `T030-20261125T180034Z-e698` and uncached `T030-20261125T181021Z-74c8`. `T030-20261125T175712Z-92f9` was started by mistake on all 1,000 MultiWOZ dev dialogues, stopped, and finalised as failed; not evidence. LoCoMo cached full-history row: 8,929,441 logical, 87,713 computed tokens, 126.9 GPU s for 308 reads (uncached: 8,957,954 / 8,957,954 / 273.5 GPU s); token cache ratio 0.000, GPU cache ratio 0.385 (upper bound, 279 paired reads). Reports under `runs/T030/artifacts/manager/reports/final/`.
- 2026-11-25: acceptance. Fixture reconciliation: `tests/analysis/test_cost.py` (`FixtureRunTest` runs three engines on the LoCoMo fixture under both schedules and compares the ledgers and per-read charges with sums over calls.jsonl; also checks the contract fixture's hand-computed totals and a randomised comparison with the contract test's reference). `make test` (406 tests) and `make lint` pass. Quality-against-tokens and cost-per-success are implemented and tested on fixtures only: no `score` or `judge` run exists yet.
