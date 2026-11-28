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
| Benchmarks and splits | (1) LoCoMo development histories (conv-26, conv-49; 308 end-of-history reads), read from the snapshot of the shared ingest run of the main configuration `E006-20261128T082608Z-21cb` (writer Qwen3-32B, session units). (2) Controlled sequences: the model-rendered development set of `T015-devmodel-20261125T192037Z` (inline benchmark config as E005), one sequence per family at density 10 (`*-rho10-L200-000`, primary schedule A20d1): 5 sequences, 338 reads, per-turn reading as `system` runs with the main configuration's writer. No held-out data |
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

- [x] Every number traces to a run report: 23 formal runs (6 read, 8 system, 9 score; plus a score run of the E006 reference read), each with `report.yaml`; paired statistics in `runs/E010/artifacts/w01-E010/E010-summary/locomo-1024/summary.json` and `.../change-seq-1024/summary.json` (checksums of every input `run.json` inside).

## Runs

Reports are under `$PROJECT_ROOT/runs/E010/artifacts/w01-E010/E010/<run-id>/report.yaml`; arm and benchmark in brackets. Qwen3-8B (8252), Qwen3-32B writer (8253) and Qwen3-Embedding-0.6B (8251) shared servers of s00-super. Code `d42c721` for the change-seq system runs and the LoCoMo template-src read; `91640c6` for the other LoCoMo runs (differs from `d42c721` only in `compare`, which no run executes); score runs at `91640c6`.

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| `E010-20261128T092533Z-8465` | 2026-11-28 | completed | `d42c721` | read, template-src, LoCoMo |
| `E010-20261128T092929Z-c38e` | 2026-11-28 | failed | `d42c721` (dirty) | read, template-nosrc, LoCoMo: started with uncommitted code, not formal |
| `E010-20261128T093207Z-c406` | 2026-11-28 | failed | `d42c721` (dirty) | read, llm-src, LoCoMo: started with uncommitted code, killed, not formal |
| `E010-20261128T093322Z-6b75` | 2026-11-28 | completed | `91640c6` | read, template-nosrc, LoCoMo |
| `E010-20261128T093601Z-3fea` | 2026-11-28 | completed | `91640c6` | read, llm-src, LoCoMo |
| `E010-20261128T093925Z-07cc` | 2026-11-28 | completed | `91640c6` | read, llm-nosrc, LoCoMo |
| `E010-20261128T094246Z-4c16` | 2026-11-28 | completed | `91640c6` | read, rewrite-src, LoCoMo |
| `E010-20261128T094548Z-5bb1` | 2026-11-28 | completed | `91640c6` | read, rewrite-nosrc, LoCoMo |
| `E010-20261128T094900Z-428b` | 2026-11-28 | completed | `91640c6` | system, raw, LoCoMo |
| `E010-20261128T092535Z-0b6e` | 2026-11-28 | completed | `d42c721` | system, template-src, change-seq |
| `E010-20261128T092535Z-c1cd` | 2026-11-28 | completed | `d42c721` | system, template-nosrc, change-seq |
| `E010-20261128T092535Z-404a` | 2026-11-28 | completed | `d42c721` | system, llm-src, change-seq |
| `E010-20261128T092535Z-841f` | 2026-11-28 | completed | `d42c721` | system, llm-nosrc, change-seq |
| `E010-20261128T092535Z-c5c9` | 2026-11-28 | completed | `d42c721` | system, rewrite-src, change-seq |
| `E010-20261128T092535Z-a1fa` | 2026-11-28 | completed | `d42c721` | system, rewrite-nosrc, change-seq |
| `E010-20261128T092535Z-c20e` | 2026-11-28 | completed | `d42c721` | system, raw, change-seq |
| `E010-20261128T093335Z-9a60` | 2026-11-28 | completed | `91640c6` | score of 8465 |
| `E010-20261128T095007Z-8e25` | 2026-11-28 | completed | `91640c6` | score of 6b75 |
| `E010-20261128T095008Z-a5dc` | 2026-11-28 | completed | `91640c6` | score of 3fea |
| `E010-20261128T095008Z-44ac` | 2026-11-28 | completed | `91640c6` | score of 07cc |
| `E010-20261128T095009Z-9af8` | 2026-11-28 | completed | `91640c6` | score of 4c16 |
| `E010-20261128T095010Z-07b9` | 2026-11-28 | completed | `91640c6` | score of 5bb1 |
| `E010-20261128T095010Z-f1e7` | 2026-11-28 | completed | `91640c6` | score of 428b |
| `E010-20261128T092540Z-4b40` | 2026-11-28 | completed | `91640c6` | score of the E006 reference read `E006-20261128T083248Z-24b4` (main configuration, code `bd232a9`) |
| `E010-20261128T094246Z-9309` | 2026-11-28 | completed | `91640c6` | score of 0b6e |
| `E010-20261128T094258Z-3a12` | 2026-11-28 | completed | `91640c6` | score of c1cd |
| `E010-20261128T094249Z-5c7b` | 2026-11-28 | completed | `91640c6` | score of 404a |
| `E010-20261128T094252Z-07d0` | 2026-11-28 | completed | `91640c6` | score of 841f |
| `E010-20261128T094301Z-34de` | 2026-11-28 | completed | `91640c6` | score of c5c9 |
| `E010-20261128T094255Z-0e19` | 2026-11-28 | completed | `91640c6` | score of a1fa |
| `E010-20261128T093336Z-eca0` | 2026-11-28 | completed | `91640c6` | score of c20e |

## Results

From completed runs only; budget 1024; numbers from the score runs' `metrics.json` and the two `summary.json` files. Intervals: 95% percentile bootstrap, 10,000 resamples, seed 20261128. With two LoCoMo conversations the conversation-cluster interval is degenerate, so the read-level interval is the one to read; on change-seq the family-cluster interval (5 families) is primary.

**Answer accuracy.** No invalid outputs except 1 (LoCoMo llm-src) and 0 elsewhere.

| Arm | LoCoMo F1 (308 reads) [read CI] | change-seq set match (262 reads) [family CI] | change-seq `changed` (60) | change-seq historical (76, descriptive) |
| --- | --- | --- | --- | --- |
| template-src | 0.338 [0.294, 0.383] | 0.584 [0.525, 0.630] | 0.417 | 0.724 |
| template-nosrc | 0.348 [0.304, 0.392] | 0.576 [0.523, 0.621] | 0.367 | 0.684 |
| llm-src | 0.335 [0.291, 0.380] | 0.595 [0.531, 0.640] | 0.450 | 0.618 |
| llm-nosrc | 0.344 [0.300, 0.389] | 0.573 [0.510, 0.626] | 0.383 | 0.671 |
| rewrite-src | 0.349 [0.305, 0.394] | 0.603 [0.527, 0.664] | 0.467 | 0.724 |
| rewrite-nosrc | 0.356 [0.311, 0.401] | 0.595 [0.533, 0.641] | 0.433 | 0.697 |
| raw (newest messages; LoCoMo: see note) | 0.014 [0.006, 0.025] | 0.603 [0.577, 0.629] | 0.450 | 0.211 |
| main configuration (E006 read, reference) | 0.342 [0.298, 0.387] | n/a | n/a | n/a |

**Paired differences** (a − b; discordant reads a only / b only):

| Pair | LoCoMo, read CI | change-seq, family CI | change-seq, read CI |
| --- | --- | --- | --- |
| llm-src − template-src (primary) | −0.004 [−0.020, +0.012], 17 / 12 | +0.011 [−0.007, +0.028], 8 / 5 | [−0.015, +0.038] |
| rewrite-src − template-src | +0.011 [−0.005, +0.026], 25 / 11 | +0.019 [−0.004, +0.049], 14 / 9 | [−0.015, +0.053] |
| rewrite-src − llm-src | +0.014 [−0.005, +0.034], 24 / 18 | +0.008 [−0.024, +0.038], 10 / 8 | [−0.023, +0.038] |
| template-src − template-nosrc | −0.009 [−0.021, +0.001], 10 / 14 | +0.008 [0.000, +0.015], 6 / 4 | [−0.015, +0.031] |
| llm-src − llm-nosrc | −0.009 [−0.019, −0.000], 7 / 12 | +0.023 [−0.019, +0.061], 11 / 5 | [−0.008, +0.053] |
| rewrite-src − rewrite-nosrc | −0.007 [−0.019, +0.005], 11 / 10 | +0.008 [−0.012, +0.027], 7 / 5 | [−0.019, +0.034] |
| template-src − raw | not a result on LoCoMo (see note); +0.324 [+0.279, +0.369], 156 / 7 | −0.019 [−0.082, +0.030], 23 / 28 | [−0.073, +0.034] |

**Note on the LoCoMo raw arm (diagnosis of 2026-11-28, requested by s00-super).** The 0.014 F1 is a real effect of how the arm is defined, not a defect. Run files of `E010-20261128T094900Z-428b`: every read is at the end of the history (versions 419 and 509), and each context is the newest messages that fit 1,024 tokens (about 1,006 tokens; for conv-26, D18:23 to D19:15 out of 419 messages). All gold evidence messages are inside that window for only 5 of the 302 reads that have evidence. On those 5 reads the arm answers 4 and scores F1 0.257. On the other 297 it answers `unknown` 269 times and scores F1 0.008. Outputs are 274 `unknown`, 34 `answer` and 0 invalid, so parsing and the answer prompt behave correctly. The arm is the E005 reference, a recency window (`full-history.yaml` truncated to the budget, newest first). It is neither raw-text retrieval (rrf, 0.347) nor the unbounded full history (0.359). At end-of-history reading it holds almost no evidence. template-src − raw on LoCoMo therefore measures recency against retrieval plus graph, not views against raw text, and is not stated as a result of E010. On the controlled sequences the window is informative, because reads are interleaved and recent: raw 0.603. The E014 near-zero rows for last-k are plausibly the same recency effect; the summary-rewrite and slot-table rows were not diagnosed here.

The content source can only matter on reads whose context holds a presented state line: 77 to 82 of 308 LoCoMo reads and 198 to 202 of 338 change-seq reads. Within that stratum (descriptive) LoCoMo llm-src − template-src is −0.016 (80 reads) and rewrite-src − template-src +0.044 (81); change-seq +0.011 (175) and +0.023 (176).

**View hit rate: 0 on both benchmarks, in every arm** (0 of 308 LoCoMo reads, 0 of 338 change-seq reads; hence also 0 reads served entirely by views). Why (presentations of the template-src runs; the other arms agree within a few reads): the hit rule compares the plan's query text with the binding's bound query text. On change-seq 304 of 337 presentations were view-eligible; 209 of them had a binding whose bound query differs from the plan's query **only in variable names** (e.g. the planner's `SELECT ?q ?v WHERE { (users_apartment_viewing_A, ?q, ?v) [user, request] }` against the `constraints` binding's `SELECT ?constraint ?value ...`; families pending 63, list 49, constraints 44, count 35, current 18), 4 also in attribution constraints, 86 in more (an `AS ?c` alias, a missing exclusivity filter, a different subject), 5 had no near binding. With variable names ignored, 183 of 338 change-seq reads (54%) would have been hits. On LoCoMo 245 of 249 presentations were eligible: 54 differ only in variable names, 33 also in the attribution (the planner names the speaker, `[Caroline, inform]`, where the families use `[_, inform]`), 101 in more (typically subject and object swapped, `(LGBTQ_support_group, visited, ?t)` against `(Caroline, visited, ?value)`), 57 had no near binding; 54 reads (18%) would hit with variable names ignored, 84 (27%) with attribution ignored too. 169 of 249 LoCoMo presentations and 138 of 337 change-seq presentations had empty results.

**Rendering check, wrong citations, cost** (`views/presentations.jsonl`, `calls.jsonl`):

| Arm | Benchmark | Check: failed / checked LLM sentences | Fallback units / units | Rewrite sources outside the given messages | Answer citations outside the context | Render calls (invalid output) | Render input / output tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| llm-src | LoCoMo | 12 / 376 (0.032) | 120 / 561 (0.214) | n/a | 1 / 555 | 94 (6) | 46,505 / 16,891 |
| llm-nosrc | LoCoMo | 15 / 345 (0.043) | 143 / 538 (0.266) | n/a | 8 / 542 | 95 (7) | 46,348 / 16,331 |
| rewrite-src | LoCoMo | n/a | 78 / 512 (0.152) | 1 / 436 | 3 / 534 | 91 (7) | 65,170 / 14,230 |
| rewrite-nosrc | LoCoMo | n/a | 46 / 505 (0.091) | 5 / 478 | 1 / 530 | 92 (5) | 65,207 / 13,979 |
| llm-src | change-seq | 36 / 356 (0.101) | 36 / 376 (0.096) | n/a | 0 / 493 | 201 (0) | 84,907 / 14,070 |
| llm-nosrc | change-seq | 32 / 344 (0.093) | 32 / 362 (0.088) | n/a | 0 / 667 | 203 (0) | 85,264 / 13,587 |
| rewrite-src | change-seq | n/a | 7 / 360 (0.019) | 1 / 728 | 0 / 474 | 202 (1) | 96,916 / 17,798 |
| rewrite-nosrc | change-seq | n/a | 9 / 359 (0.025) | 1 / 716 | 0 / 543 | 200 (1) | 95,848 / 17,207 |

Template arms make no render call. On LoCoMo most fallbacks come from render calls whose output the schema rejected (6 to 7 of about 94 calls, each failing a whole chunk of up to 16 rows), not from the sentence check. The rewrite arms stated every value of 166 of 512 (LoCoMo) and 267 of 360 (change-seq) rendered units somewhere in their sentences (descriptive). Template, llm and rewrite contexts use the budget alike (LoCoMo mean 1,000 to 1,002 tokens; change-seq 668 to 692).

**Writer noise on change-seq.** Against template-src, 92% to 95% of the committed change sets of the other view arms are identical (1,000 per run).

## Conclusion

As measured on development data at budget 1024, with extracted graphs and the main configuration's planner, the view content source made no measurable difference to the answering LLM. On LoCoMo, LLM rendering − template was −0.004 F1 [−0.020, +0.012], and on the controlled sequences +0.011 [−0.007, +0.028]. LLM rewriting from raw text was nominally best on both benchmarks (+0.011 and +0.019 against the template), but every interval includes zero. Source annotation did not help either: removing the message IDs from the state lines changed accuracy by less than one point in each source, with signs that differ between benchmarks. The LLM sources cost about 0.3 render calls per LoCoMo read (about 205 tokens per read for llm, 260 for rewrite) and 0.6 per change-seq read (about 290 and 340 tokens), against none for the template. This is consistent with E005's conclusion on gold graphs: template serialisation is not worse.

Why the source barely matters here: standing views never served a read (hit rate 0 on both benchmarks), and the state lines that the sources rewrite are ad hoc query answers. They reach the context on only a quarter (LoCoMo) to three fifths (change-seq) of the reads, and about half of the presented queries return no rows. On the controlled sequences the extracted-graph views no longer beat the raw-text window (template − raw −0.019 [−0.082, +0.030]; E005 on gold graphs: +0.289). On LoCoMo the raw arm is a recency window that holds the gold evidence for only 5 of 302 reads at end of history (note under Results), so template-src − raw is not a comparison of views with raw text and is not stated as a result.

The zero hit rate is largely an artefact of the hit rule, not a lack of views. On the controlled sequences, for 54% of reads the planner wrote a family's query with other variable names. A hit test modulo variable renaming would have matched them. On LoCoMo the corresponding figure is 18%, or 27% when the speaker in the attribution is also ignored. On this evidence the maintenance conclusions cannot yet rest on natural data. The hit rule is a design decision outside E010 and is listed under open items. Limits: one seed, one budget, development data; 5 of 25 controlled sequences; writer output differs between the change-seq arms in 5 to 8% of change sets; no judge; LoCoMo has only two conversations.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-28: worker session `w01-E010` (Issue #170) on `task/E010-ablation-c-extracted` from `bc8fdc5`. Design and config written before the first formal run; smoke read run on conv-26 (llm-src, dirty code, not formal) showed 0 view hits in 124 presentations, 86 of them with a near binding.
- 2026-11-28: formal runs at `d42c721`/`91640c6`: 6 LoCoMo read runs and 1 LoCoMo system run (raw), 7 change-seq system runs, 9 score runs and a score run of the E006 reference read, all completed, each with a report; two LoCoMo read runs (`c38e`, `c406`) failed as not formal (started with uncommitted code by mistake) and were rerun. Comparisons in `E010-summary/locomo-1024` and `E010-summary/change-seq-1024`. Result: no measurable difference between the content sources or with and without source annotation; view hit rate 0 on both benchmarks, mainly because the hit rule compares query text (54% of change-seq reads would hit modulo variable names). No judge run; shared servers not touched.
- 2026-11-28: after the runs, the read count in a comment of the E010 config corrected from 334 to 338 (5 sequences: 69, 71, 65, 66, 67 reads); nothing else in the config changed.
- 2026-11-28: diagnosis of the LoCoMo raw arm (F1 0.014), requested by s00-super: a real effect of the recency window at end-of-history reading (all gold evidence in the window for 5 of 302 reads; no parsing or prompt defect). The LoCoMo template-src − raw comparison is marked as not a result.
- 2026-11-28: recorded done with a remark by the integration owner (s00-super): PR #177 merged. Remark: budget 1,024 only and 5 of 25 controlled sequences; the view hit rule (exact query text) is an open design question put to the user; the LoCoMo raw-window arm is a recency window and not a comparator.
