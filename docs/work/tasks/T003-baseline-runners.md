---
id: T003
title: Baseline runners
created: 2026-11-21
---

# T003 · Baseline runners

## Goal

Runnable baselines needed by the pilot: full history with the same answering LLM, text retrieval (BM25, dense, RRF), rolling summary with recent raw text, and the fixed-schema slot table with speaker and communicative-function fields and provenance, all producing predictions and cost-ledger entries under the T001 contracts.

## Scope

- In scope: the four baseline families above on the primary model.
- Out of scope: external memory systems and the remaining baselines of plan section 7.2 (milestone M4).
- Candidate worker subtasks: one per baseline family.
- Layout (decision D013): baselines go to `src/grace/eval/engines/baselines/` and implement the interface of `src/grace/context/api.py`; the first version of the harness goes to `src/grace/eval/runner/harness/`. A baseline imports nothing from `eval/datasets/`.
- Open question, to settle with the manager of T027 before the slot table is written: ablation B combines the fixed slot table with the attribution guard and bitemporality, so that version must use the GRACE assembly, which does not exist in phase 1. Either this task writes a standalone slot table for the pilot and T027 writes a second one inside the GRACE assembly, or one implementation is designed here so that T027 can reuse it. Record the choice in both Logs.

## Acceptance

- [x] Each baseline runs end to end on fixtures and on one development history per benchmark.
- [x] Every run writes `run.json`, predictions and cost-ledger entries that pass the contract tests.
- [x] A test in `tests/contracts/` plants a sentinel string in the gold data of a fixture and asserts that it appears in no input any baseline receives from the harness.

## Deliverables

Baseline modules under `src/grace/eval/engines/baselines/`, the harness under `src/grace/eval/runner/harness/`, and one config per baseline under `configs/engines/`.

## Log

- 2026-11-21: created from plan section 9, phase 1.
- 2026-11-22: "JSON state table" renamed to "relational state table" to match plan v3.
- 2026-11-23: "relational state table" replaced by the fixed-schema slot table, following the revised plan (section 7.2): a relational encoding with the same fields is the same data model as the graph and is not compared.
- 2026-11-24: layout, the gold-sentinel test and the open question about the slot table added from decision D013.
- 2026-11-25: manager session `m01-T003` started on `task/T003-baseline-runners` from `main` at `985d232`; Issue #31. No workers dispatched: the four baseline families were written in the manager worktree.
- 2026-11-25: the `ContextEngine` interface (`src/grace/context/api.py`) landed first in its own PR #35 (head `6264bd4`, merged as `23d14fb`), so that T002 and T014 can use its types.
- 2026-11-25: slot-table question settled (T027 has no manager yet; record it in the T027 Log when it starts): this task writes a standalone pilot slot table, `eval/engines/baselines/slots.py`, with no attribution guard and no bitemporality; T027 writes the slot-table representation for ablation B inside the GRACE assembly (`context/`). Code cannot be shared, because `context/` never imports `eval/` (D013 import rules); what is shared is the frozen slot inventory and function list, which live in config (`configs/engines/slot-table.yaml`) and which T027 should read from the same place.
- 2026-11-25: interpretation of the two rolling-summary variants (plan 7.2): "rewritten after every update" rewrites the whole summary whenever messages leave the recent window; "reused without rewriting" appends a summary block per `block_size` leaving messages and never revises earlier blocks.
- 2026-11-25: interim pieces to replace when their owners land: the calls.jsonl writer (`harness/ledger.py`) by `llm/records.py` (T004); the fake-only backend by `llm/client.py` (T004); placeholder prompts (summary, slot extraction, answer) by `resources/prompts/` through `llm/prompts.py` (T004); the record loader (`harness/inputs.py`, fixture and `dev*` splits only) by `eval/datasets/benchmarks/splits.py` (T002). `context/memory/index/` holds only message chunking, BM25 and exact cosine for the retrieval baselines; T025 owns the package.
- 2026-11-25: acceptance on fixtures: all nine engine configs run end to end on all six fixture benchmarks at full and 24-token budgets, and on the LoCoMo streaming schedule with further retrieval; run.json, predictions and calls.jsonl pass the contract checks; the gold-sentinel test passes with a positive control. Runs on one development history per benchmark are not done: they need T002's converted records and T004's model client (known gap in the task PR).
- 2026-11-25: manager session `m01-T003b` resumed T003 on `task/T003-harness-llm` from `main` at `9fdde49` (the old branch `task/T003-baseline-runners` stays in its own worktree; PR #39 merged). Interim pieces replaced: `harness/ledger.py` removed (calls.jsonl written by `llm/records.CallLedger`); a `ClientModel` sends chat calls through `llm/client.ChatClient` with the pin of `configs/models/qwen3-8b.yaml` (thinking disabled, temperature 0) and embedding calls through a new, strictly additive `llm/embeddings.EmbeddingClient`; the fake backend stays for CI; answer, summary and slot-extraction prompts load from `resources/prompts/` through `llm/prompts` with their registry pins, and the answer output is checked against `resources/schemas/llm/answer.json`; development splits load through `eval/datasets/benchmarks/splits.load_split` (development kind only), directory loading remains for split `fixture` only.
- 2026-11-25: one prompt added to T004's registry: `extract-slots` (call type `extract`, no schema; the engine checks slots and functions against `configs/engines/slot-table.yaml`). `dense` and `rrf` name the embedding model (Qwen3-Embedding-0.6B at its cached revision) and a placeholder query instruction, both to be frozen on development data.
- 2026-11-25: acceptance smoke run on development data (not an experiment: no held-out data, no tuning, no scores reported): all nine engine configs on one development history per benchmark (locomo `conv-26`, longmemeval-s `852ce960`, multiwoz `MUL1003.json`, halumem-medium `91b283d7-7236-3b83-abeb-f0a159564f45`, memoryagentbench `factconsolidation_sh_6k:0`) with Qwen3-8B served by vLLM 0.34.0 on GPU 6 (`--max-model-len 32768`, prefix caching, prompt-token details) and Qwen3-Embedding-0.6B on the same GPU; budget `full` for the two full-history configs and 1024 tokens for the others; code `01e3ba7`; runs under `runs/T003/artifacts/manager/T003/`. change-seq has no data yet and was not run. All runs pass the run.json, calls.jsonl and artefact checks of the contract tests. The first dense and rrf runs on longmemeval-s failed (`T003-20261125T010342Z-f99b`, `T003-20261125T010341Z-b431`): one message of 18,600 tokens exceeded the embedding server's 8,192-token limit; rerun as `T003-20261125T010612Z-b367` and `-048f` after restarting the server at 32,768 tokens.
- 2026-11-25: expected outcome, recorded and not worked around: full-history prompts that exceed Qwen3-8B's 32,768-token window are rejected by the server (HTTP 400, three recorded `failed` attempts) and the read becomes `invalid`: the longmemeval-s read, and 111 of 137 halumem-medium reads. The raw-text engine's `window_tokens` bounds the context only, not context plus answer prompt and output reserve, so its overflow disclosure does not prevent the rejection; whether to subtract the fixed prompt parts is open for the pilot.
- 2026-11-25: partial run: halumem-medium `summary-rewrite` (`T003-20261125T010335Z-d8fb`) rewrites the summary on nearly every write (about 2,650 sequential summary calls) and was stopped by the manager to close the session after 2,235 of 2,658 messages and 114 of 137 reads; its run.json says `failed` with the cause. The other 44 engine x benchmark runs (with the two longmemeval-s reruns) completed. Servers stopped and the `compute.yaml` entry removed.
- 2026-11-25: outcome: 44 of 45 benchmark x engine runs completed (plus the two longmemeval-s dense/rrf reruns). The halumem-medium summary-rewrite run `T003-20261125T010335Z-d8fb` (one summary call per write, about 26 calls per minute) was stopped by the manager after 2,235 of 2,658 messages and 114 of 137 reads to close the session; its run.json is marked `failed` with the reason (partial run). Servers stopped and the compute reservation removed.
- 2026-11-25: closed by the user (`T003: active -> done`) on the evidence of PRs #39 and #61. Known gaps passed on: change-seq had no data at the smoke run (T015 now generates it; E001 runs the baselines on it); the halumem-medium `summary-rewrite` run `T003-20261125T010335Z-d8fb` is partial (stopped, marked `failed`); whether the raw-text engine's `window_tokens` subtracts the fixed prompt parts and output reserve is decided in E001.
- 2026-11-25: finding from T030 (PR #79): in client mode the engine config's `prefix_caching` does not reach the vLLM server, so the full-history development runs of the smoke run were served with prefix caching (LoCoMo conv-26: 3.94M of 3.96M input tokens cached). They are not an uncached measurement; T030 measured both rows separately (runs `T030-20261125T175342Z-756d` cached, `T030-20261125T180458Z-d447` uncached).
- 2026-11-25: the open `window_tokens` question was decided in E001 (PR #90): the raw-text engine gains `prompt_reserve_tokens` (default 0); the full-history, cached full-history and last-k configs set 1024 (output reserve 256 + largest fixed prompt part 592 + 64, rounded up to 128). Recorded here by the integration owner.
- 2026-11-28: slot-table choice confirmed by T027 (recorded by the integration owner): two implementations. The phase 1 pilot table stays in `eval/engines/baselines/slots.py`; the ablation-B table is `context/memory/graph/slots.py` (row key subject plus slot, with report mode, polarity, correction and valid time). Both read the frozen slot inventory and function list from `configs/engines/slot-table.yaml`.
