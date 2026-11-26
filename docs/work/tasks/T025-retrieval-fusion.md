---
id: T025
title: Retrieval channels, routing and fusion
created: 2026-11-23
---

# T025 · Retrieval channels, routing and fusion

## Goal

The retrieval side of plan section 5.5: BM25, dense and graph candidates mapped to one evidence ID space, rule-based routing with an always-three-channels fallback, and RRF fusion with weighted fusion as an alternative.

## Scope

- In scope:
  - Each channel can be switched off with the total number of candidates held fixed.
  - Routing rules, weights and thresholds are tuned on development data only.
- Out of scope: Selecting what goes into the prompt (T026).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Evidence recall of each channel is reported on the development set.
- [ ] Channel switches are covered by tests.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` retrieval package.

## Design

- **Package** `src/grace/context/pipeline/retrieval/`: `candidates.py` (candidate types; unified evidence ID = `message_id`, spans `#char=` mapped to their message), `text.py` (BM25 and dense channels over `memory/index/`; the query embedding goes through a caller-supplied `embed_query` wired to `grace.llm.embeddings`), `graph.py` (graph channel: evidence of a query result passed in by the engine, newest message first, score 1.0), `route.py` (rule-based routing), `fuse.py` (RRF, weighted min-max fusion), `retrieve.py` (`RetrievalConfig`, `Retriever`). Imports only `context/api.py` and `memory/index/`.
- **Channel switches.** `RetrievalConfig.channels` lists the enabled channels; `without(channel)` switches one off. `total` (fused candidates) is independent of the channel set; each channel contributes `depth >= total`, and `backfill` fills the list from the other enabled channels when the routed ones run dry. The graph channel is available for a read only when the planner compiled a query.
- **Routing.** Signal families on the request text: identifier (letter-digit tokens, `#` references, quoted phrases, e-mail, URL) -> BM25; time, count, correction, relation cues -> graph; no identifier -> dense (paraphrase). Fewer than `min_confidence` (1) structural signals -> all available channels; a route of the graph alone is widened to all available channels.
- **Fusion.** RRF (`k = 60`, weights 1) is the main configuration; weighted fusion normalises each channel's scores to [0, 1] (min-max) and sums them with per-channel weights.
- **Embedding model.** Qwen3-Embedding-0.6B (plan 7.1, revision pinned in `configs/retrieval/default.yaml`), served by vLLM from `envs/serve` on GPU, reached over the OpenAI-compatible `/embeddings` API through `grace.llm.embeddings.EmbeddingClient` (recorded in `calls.jsonl`). No new Python dependency: BM25 is the existing pure-Python index.
- **Probe.** `grace.cli.retrieval_recall` (stage `probe`), `eval/runner/probes/retrieval_recall.py`, recall from run files by `eval/analysis/metrics/retrieval.py`; config `configs/experiments/T025-retrieval-recall.yaml`. Recall@K is |gold ∩ top-K| / |gold| at message granularity; reads without resolvable gold evidence are not scored.

## Runs

| Run ID | Status | Code SHA | Data | Note |
| --- | --- | --- | --- | --- |
| `T025-20261126T155956Z-6787` | completed | `1fbe56a24b131b3566ad54fa097934ed2d83ac09` | LoCoMo dev | Smoke run, LoCoMo only; not used for reported numbers |
| `T025-20261126T160007Z-79ab` | completed | `1fbe56a24b131b3566ad54fa097934ed2d83ac09` | LoCoMo dev, LongMemEval-S dev, change-seq dev (T015 model-rendered) | Formal run; report `runs/T025/artifacts/manager/T025/T025-20261126T160007Z-79ab/report.yaml` |

## Results (development data only)

All numbers from `recall.json` of run `T025-20261126T160007Z-79ab` at code `1fbe56a24b131b3566ad54fa097934ed2d83ac09`. R@K: mean evidence recall at K fused candidates (total fixed at K for every condition); full@20: share of reads with all gold evidence in the top 20. Change-seq planner routes: {'fallback': 40, 'llm': 795, 'rule': 310}; fallbacks {'anchor': 36, 'type': 4}; graph available for 1105 of 1145 reads.

**locomo dev** (text channels only; graph pending (no extracted graph before T022); scored 302 of 308 reads)

| Condition | R@5 | R@10 | R@20 | R@50 | full@20 |
| --- | --- | --- | --- | --- | --- |
| bm25 | 0.428 | 0.498 | 0.565 | 0.663 | 0.507 |
| dense | 0.536 | 0.623 | 0.699 | 0.821 | 0.616 |
| graph | pending | pending | pending | pending | pending |
| rrf-all | 0.548 | 0.629 | 0.733 | 0.838 | 0.649 |
| rrf-routed | 0.550 | 0.611 | 0.714 | 0.830 | 0.629 |
| weighted-all | 0.550 | 0.632 | 0.728 | 0.845 | 0.639 |
| weighted-routed | 0.554 | 0.610 | 0.716 | 0.835 | 0.626 |
| rrf-no-bm25 | 0.536 | 0.623 | 0.699 | 0.821 | 0.616 |
| rrf-no-dense | 0.428 | 0.498 | 0.565 | 0.663 | 0.507 |
| rrf-no-graph | 0.548 | 0.629 | 0.733 | 0.838 | 0.649 |

**longmemeval-s dev** (text channels only; graph pending (no extracted graph before T022); scored 95 of 98 reads)

| Condition | R@5 | R@10 | R@20 | R@50 | full@20 |
| --- | --- | --- | --- | --- | --- |
| bm25 | 0.645 | 0.796 | 0.875 | 0.929 | 0.800 |
| dense | 0.803 | 0.940 | 0.970 | 0.983 | 0.947 |
| graph | pending | pending | pending | pending | pending |
| rrf-all | 0.749 | 0.911 | 0.981 | 0.988 | 0.968 |
| rrf-routed | 0.767 | 0.940 | 0.970 | 0.983 | 0.947 |
| weighted-all | 0.787 | 0.930 | 0.978 | 0.991 | 0.958 |
| weighted-routed | 0.778 | 0.935 | 0.970 | 0.983 | 0.947 |
| rrf-no-bm25 | 0.803 | 0.940 | 0.970 | 0.983 | 0.947 |
| rrf-no-dense | 0.645 | 0.796 | 0.875 | 0.929 | 0.800 |
| rrf-no-graph | 0.749 | 0.911 | 0.981 | 0.988 | 0.968 |

**change-seq dev** (graph channel on the stored gold graph with the T023 planner (Qwen3-8B); a perfect-writer upper bound; scored 679 of 1145 reads)

| Condition | R@5 | R@10 | R@20 | R@50 | full@20 |
| --- | --- | --- | --- | --- | --- |
| bm25 | 0.371 | 0.529 | 0.697 | 0.851 | 0.627 |
| dense | 0.644 | 0.851 | 0.947 | 0.987 | 0.912 |
| graph | 0.841 | 0.878 | 0.882 | 0.882 | 0.882 |
| rrf-all | 0.793 | 0.931 | 0.972 | 0.998 | 0.962 |
| rrf-routed | 0.840 | 0.948 | 0.979 | 0.997 | 0.974 |
| weighted-all | 0.832 | 0.947 | 0.977 | 0.996 | 0.971 |
| weighted-routed | 0.866 | 0.954 | 0.979 | 0.997 | 0.974 |
| rrf-no-bm25 | 0.858 | 0.950 | 0.979 | 0.997 | 0.974 |
| rrf-no-dense | 0.779 | 0.887 | 0.938 | 0.960 | 0.929 |
| rrf-no-graph | 0.506 | 0.751 | 0.911 | 0.988 | 0.859 |

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-26: manager session m01-T025 started on `task/T025-retrieval` (base `9db00d1`); Issue #122. No workers: the manager wrote the code.
- 2026-11-26: retrieval package, configs and recall probe committed at `1fbe56a`; `make test` (738 tests, 3 skipped) and `make lint` pass.
- 2026-11-26: formal run `T025-20261126T160007Z-79ab` (GPU 3, Qwen3-Embedding-0.6B on port 8251, Qwen3-8B planner on port 8252; reservation removed after the servers stopped). Routing rules were written before the run and not tuned on it.
- 2026-11-26: user decision (recorded by `m01-T022b`): routing rules and fusion weights are not tuned now. One tuning pass on development data happens after graph-channel recall on extracted graphs exists, before D012 (configuration lock).
- 2026-11-26: graph channel on extracted graphs (T022 follow-up `m01-T022b`). `retrieval_recall` accepts experiment T022 and `graph: extracted` (the claim graphs of a completed, clean, unlimited T022 writer run, named as upstream); the planner sees a per-question fragment of the graph's vocabulary (`ExtractedGraph.fragment`: 30 predicates and 30 entities by word overlap with the question; this probe's selection, not a GRACE design decision). Run `T022-20261126T185026Z-5205` (code `5319e8a`, config `configs/experiments/T022-writer-smoke-recall.yaml`, upstream writer run `T022-20261126T184442Z-2a64`, Qwen3-8B planner and Qwen3-Embedding-0.6B on GPU 0; report `runs/T022/artifacts/manager/T022/T022-20261126T185026Z-5205/report.yaml`). LoCoMo dev, 302 of 308 reads scored; text-channel numbers equal those of `T025-20261126T160007Z-79ab`. Graph channel alone R@5 0.039, R@10 0.067, R@20 0.085, R@50 0.101 (full@20 0.063); rrf-all R@5 0.546, R@10 0.632, R@20 0.740, R@50 0.841 against rrf-no-graph 0.548, 0.629, 0.733, 0.838. The planner compiled a query for 161 reads (91 with a non-empty answer); of 147 fallbacks, 114 are IR parse failures, mostly entity IDs with spaces or apostrophes that the writer produced and the IR grammar cannot express. A smoke number on a poor writer graph (see the T022 log), not a measurement of the graph channel's value.
