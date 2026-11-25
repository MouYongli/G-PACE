---
id: T034
title: Optional benchmark and system adapters
created: 2026-11-23
---

# T034 · Optional benchmark and system adapters

## Goal

Adapters for the summary-table benchmarks and the optional external systems (plan sections 6.3 and 7.2).

## Scope

- In scope:
  - Decide how the claim graph projects onto HaluMem's per-session extracted memories before writing its adapter.
  - MemoryAgentBench: LongMemEval(S*) and the 6K and 32K FactConsolidation variants only.
  - Graphiti: publish the adaptation and failure rate; keep a row with its native backbone.
- Out of scope: Redistributing re-annotated HaluMem data (licence CC BY-NC-ND 4.0).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Each adapter loads its development data through the common record contracts.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` adapters; `configs/benchmarks/`.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-T034` started on `task/T034-optional-adapters` from `795cb9e`; Issue #68. This round: benchmark adapters on CPU; Graphiti and Mem0g are planned, not run.
- 2026-11-25: benchmark adapters already complete from T002; no new adapter code written. `halumem.py` and `memoryagentbench.py` under `src/grace/eval/datasets/benchmarks/` are registered in `splits.adapters()` and load their `dev` splits through `splits.load_split`, which verifies the manifest SHA-256 of `configs/benchmarks/` (`halumem-medium` `cb04336` `de45bed8…77920`; `memoryagentbench` `7ea0669` `cb1ecc84…3f682`; both match the store), validates the records against the Benchmark records contract and checks the configured counts: halumem-medium 4 histories, 12,980 messages, 709 reads, 709 gold, 3,190 memory points; memoryagentbench 9 histories (`longmemeval-s-star` ×5, `factconsolidation-{sh,mh}-{6k,32k}` ×1 each), 833 messages, 137 reads, 137 gold, with eventqa, ruler and FactConsolidation 64K/262K excluded and counted. Evidence: `tests/integration/test_benchmark_data.py` (real store), `tests/contracts/test_benchmark_adapters.py` (synthetic fixtures, including the subset filter), `runs/T034/artifacts/dev-load-check.txt`.
- 2026-11-25: decision (manager, for the user to confirm): projection of the claim graph onto HaluMem's per-session extracted memories, used to score extraction and updates against `memory_points.jsonl`. The adapter needs no change; the projection reads only `changesets.jsonl` of a run and lives on the scoring side (`eval/analysis/`), written by the node that first scores HaluMem.
  - Window: the memories extracted from session `session_<k>` are the entries of the change sets with version in (last version of `session_<k-1>`, last version of `session_<k>`]. Scoring is session-scoped, as in HaluMem's own protocol.
  - Memory: one per claim that is new in the window and has at least one attribution with `report_mode: own`, `polarity: positive` and `derived: false`. Claims carried only by quotes, hypotheticals, negative stances or assistant restatements are not memories. A claim that already existed and only gains an attribution in the window is not a new memory; its count is reported beside the scores.
  - Rendering: deterministic template, no LLM call: `<subject label> <predicate label> <object>`, plus the scope and the valid time (`expression`, else the canonical bounds) when present. Labels come from the entity mentions and the predicate vocabulary. The template is fixed on development data before the configuration lock (D012) and is the same for every variant of GRACE.
  - Update: one per supersession in the window; its rendering is that of the replacing claim (or `no longer <old rendering>` for a removal) and its `original_memories` are the renderings of the superseded claim. It is scored against the gold points with `is_update: "True"`. Both supersession kinds count; `kind` is kept for a breakdown.
  - Interference points (`memory_source: interference`) are scored as false memories: a projected memory that the judge matches to one counts against GRACE (HaluMem's false-memory resistance).
  - Matching to gold uses HaluMem's official judge prompts once they are registered in `configs/common/scorers.yaml#halumem-medium` (still `metrics: []`); no hand alignment. `memory_type` is not predicted and serves only as a stratum of the gold.
  - Other systems: Mem0 and Graphiti expose their per-session added memories natively and are scored with the same judge; raw-text, retrieval and summary baselines get QA scores only.
  - Licence (CC BY-NC-ND 4.0): gold points, projections and judge outputs stay in run directories; only aggregate metrics are published; no derived or re-annotated subset is committed or released.
- 2026-11-25: plan for the external systems (recorded, not run this round; they need model calls and services).
  - Mem0g: Mem0 with its graph store enabled. It reuses T029's Mem0 adapter (`eval/engines/baselines/`, owned by `m01-T029`) with only a graph-store configuration added, so it waits until T029 is merged; no separate code before then.
  - Graphiti: `graphiti-core` pinned in its own environment (decision D004), with an embedded graph backend (Kuzu) so that no database server is needed; Neo4j only if the embedded backend fails on the pinned version. Its LLM, embedder and reranker clients are replaced by thin wrappers over `src/grace/llm/`, so that every call is recorded and counted and the backbone is Qwen3-8B through the shared serving environment. Ingestion: one episode per message (`<speaker>: <text>`, `group_id` = history ID, reference time = message timestamp, else the segment time, else the ordinal position with no invented date). Read: Graphiti's hybrid search under the same budget; the facts of the returned edges with their `valid_at` and `invalid_at` are rendered into the context and answered by the same answering LLM and prompt as the other engines.
  - Failure rate, published: per history, the share of episodes whose `add_episode` fails after Graphiti's own retries, and the share of LLM calls whose structured output does not parse. Failed episodes are skipped and counted, never fixed by hand.
  - Rows: Graphiti on Qwen3-8B (main protocol) and a separate row on its native backbone (the OpenAI models that the pinned version defaults to). The native row calls a hosted API and spends money, so it needs the user's approval and budget before it runs.
  - Engine code goes under `eval/engines/baselines/` in a later round (outside this round's write scope). Order: LoCoMo development histories first, then the other benchmarks.
- 2026-11-25: acceptance: item 1 met by the T002 adapters (evidence above); item 2 `make test` (377 tests, OK) and `make lint` (ruff, all checks passed) on `795cb9e`. Graphiti and Mem0g adapters are not written; the node stays open for them.
- 2026-11-25: the user confirmed the HaluMem projection recorded above (decision for the user to confirm, same day).
