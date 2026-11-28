---
id: E010
title: Ablation C on extracted graphs
created: 2026-11-23
---

# E010 · Ablation C on extracted graphs

## Question

With extracted graphs, which source of view content serves the answering LLM best, and how often do standing views serve a read at all? Serves RQ3 and RQ2. A low hit rate means maintenance conclusions rest on the controlled sequences alone.

## Design

Written on 2026-11-28 before the first formal run (worker session `w01-E010`, Issue #170). Config: `configs/experiments/E010-ablation-c-extracted.yaml`; driver: `uv run python -m grace.cli.ablation_c_extracted` (subcommands `read`, `system`, `score`, `compare`); LoCoMo scoring with `grace.cli.locomo_score`. Plan sections 4.2 (RQ3 premise), 5.4 and 7.3 (ablation C).

| Item | Value |
| --- | --- |
| Benchmarks and splits | (1) LoCoMo development histories (conv-26, conv-49; 308 end-of-history reads), read from the snapshot of the shared ingest run of the main configuration `E006-20261128T082608Z-21cb` (writer Qwen3-32B, session units). (2) Controlled sequences: the model-rendered development set of `T015-devmodel-20261125T192037Z` (inline benchmark config as E005), one sequence per family at density 10 (`*-rho10-L200-000`, primary schedule A20d1): 5 sequences, 334 reads, per-turn reading as `system` runs with the main configuration's writer. No held-out data |
| Systems | GRACE's main configuration with one component replaced: the view slot is a read-time content source (`src/grace/context/views/readtime.py`, registry name `read-time-views`). It presents the plan's query answers, from a resident-equivalent view hit or a temporary view, by one of three sources: **template** (template serialisation: the family's sentence pattern on a hit, `name = value` otherwise; no model call), **llm** (LLM rendering of the same rows: frozen `render-view` prompt, rendering check with the binding subject, template fallback), **rewrite** (LLM rewriting from raw text: new `rewrite-view` prompt; the model sees the view title and the raw text of the messages the rows cite, never the rows, and labels each sentence with its source messages; sources outside the given messages are dropped and counted, a chunk that keeps no sentence falls back to the template). Each with source annotation (state lines prefixed by their message IDs, main configuration) and without (`configs/assembly/no-state-citations.yaml`, `state_citations: false`; selection costs follow the shown lines). Reference: **raw**, the raw-text engine `configs/engines/full-history.yaml` (newest messages that fit). Further LoCoMo reference row: the main configuration's read run on the same snapshot (`E006-20261128T083248Z-24b4`, E006), scored here |
| Why read-time sources | Resident views maintained at write time with LLM rendering would change the write side, so each such arm would need its own 32B ingest (stages.py write-side rule). A resident view of a binding holds, at the read version, the rows of its bound query; the read-time source evaluates the same query at the same version and applies the same hit rule (`engine.Views.hit`: the plan's query text equals the binding's bound query, the binding reaches the instantiation threshold), so hits and content equal those of a resident store that is maintained exactly (read-time re-query). What the read-time arms do not measure is the staleness of cached rendered text; rendering is paid per read |
| Equal display budget | 1024 tokens (answering model's tokenizer), the primary level of E005 and the level of the E013 LoCoMo reference. Every arm uses the same evidence-driven assembly; only the state lines differ |
| Answering | The shared harness step (prompt `answer`), Qwen3-8B, thinking off, temperature 0, seed 0; planner, rendering and rewriting on the same Qwen3-8B server (plan 5.6); embeddings Qwen3-Embedding-0.6B. Shared servers of s00-super (8252, 8251, 8253) |
| Metrics | Answer accuracy (LoCoMo registered token F1, categories 1-4, invalid as 0; change-seq set match on the four state question types as E005, historical types descriptive). Correctness after rebuild: change-seq accuracy on `changed` questions (a read-time view is rebuilt at every read). Rendering-check failures (failed LLM sentences / checked; fallback units / units). Wrong citations (rewrite sources outside the given messages / sources named; answer citations of messages not in the working context / answer citations). Rendering cost (render calls, input and output tokens; ledger W, trigger `read`). View hit rate (plan 5.4: reads with a view hit shown in the context; reads served entirely by views) and, per presentation, why there was no hit: the nearest binding (its subject and predicate occur in the plan's query) and how its bound query differs (`variable_names` only, also `attribution`, or `other`). Share of reads with any presented state line in the context |
| Statistics (D002) | Micro means; 95% percentile intervals from a cluster bootstrap (10,000 resamples, seed 20261128) over LoCoMo conversations (2) and change-seq families (5), paired for differences; read-level intervals beside them as sensitivity (the cluster intervals are coarse with 2 and 5 clusters). Primary readout: llm-src − template-src. Secondary: rewrite-src against template-src and llm-src, each source with − without annotation, template-src − raw. Descriptive stratum: reads where either arm showed a presented state line (the only reads where the source can matter) |
| Runs | LoCoMo: six `read` runs (one per view arm) and one `system` run (raw), each scored by `locomo_score`, plus a score run of the E006 reference read. Change-seq: seven `system` runs, each scored by `score`. `compare` (not a run) writes `summary.json` per benchmark with the checksum of every input `run.json`. View runs also write `views/presentations.jsonl` |
| Noise | On LoCoMo the arms share one snapshot; rerun noise of a full read is about 0.003 F1 (E013). On the controlled sequences the 32B writer runs once per arm and output varies between runs at temperature 0 (server batching); reported as the agreement of the arms' change sets |
| Judging | None (no local judge yet; T035) |
| Frozen before the first run | Read-time view code, `rewrite-view` prompt and schema, arm configs, budget, population, scorer and this design |

## Acceptance

- [ ] Every number traces to a run report.

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |

## Results

Not run.

## Conclusion

Pending.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-28: worker session `w01-E010` (Issue #170) on `task/E010-ablation-c-extracted` from `bc8fdc5`. Design and config written before the first formal run; smoke read run on conv-26 (llm-src, dirty code, not formal) showed 0 view hits in 124 presentations, 86 of them with a near binding.
