---
id: E005
title: Ablation C on gold graphs
created: 2026-11-23
---

# E005 · Ablation C on gold graphs

## Question

Does an LLM-rendered view help the answering LLM more than a template serialisation of the same result rows? This is the premise of RQ3. If the template ties, nothing expensive needs caching and the paper becomes 'a staleness criterion plus computing at query time'.

## Design

Written on 2026-11-25 before the first formal run. Config: `configs/experiments/E005-ablation-c-gold.yaml`; driver: `uv run python -m grace.cli.ablation_c` (subcommands `system`, `score`, `compare`); scorer and statistics: `src/grace/eval/analysis/metrics/changeseq.py`. Plan sections 3.4, 4.2 (RQ3 premise), 5.4 and 7.3 (ablation C).

| Item | Value |
| --- | --- |
| Benchmarks and splits | Controlled change sequences, development families only: the model-rendered development set of run `T015-devmodel-20261125T192037Z` (generator `changeseq-generator-2`, surface renderer Mistral-Small-3.2-24B; 5 families, 25 sequences of 200 messages, densities 1, 3, 10, 30), read through the change-seq adapter with an inline benchmark config (as E001; `configs/benchmarks/change-seq.yaml` is not bound yet). Read schedule: the primary schedule of each sequence (A20d1 at density 10, U10 otherwise), 1,145 questions. No held-out data |
| Gold graph | The stored gold claim graph of each sequence (`graph/`), injected by the driver as the gold-graph oracle (structure.md: "Question answering on gold graphs"). Entity IDs of the generator are replaced by their surface labels before the views see the graph (task `k1` becomes "car rental A", item `car-astra` becomes "Opel Astra"), so that view text and questions name things alike; values, predicates, speakers and companions are unchanged |
| Resident views | The 15 gold bindings of each sequence (`bindings.jsonl`; V1 to V6 mapped to the template families `list`, `current`, `count`, `constraints`, `pending`, `choice`), built with the frozen view code of T018 (`src/grace/context/views/`, `resources/views/`) and `configs/views/default.yaml` with the two gold-graph overrides of the T019 replay: `state_speaker: user`, `choice_predicate: selectedService`. Views are built before the first message and, at the first read of every read version, re-queried and repaired (`ViewStore.maintain`, confirm on: local rebuild, citation patch or cut-off advance). The views' answers equal the generator's gold answers on every question of the population (CPU check before the run: 955 of 955 questions; regression test `tests/integration/test_ablation_c.py`) |
| Systems | Three arms, one changed factor (the source of the view text): (1) **template**, template serialisation of the rows (no LLM call); (2) **llm**, LLM rendering of the same rows with the frozen `render-view` prompt, rendering check and template fallback (`views/render.py`; decoding temperature 0, max 512 tokens, max 16 rows per call); (3) **raw**, reference: the raw-text engine of T003 (`configs/engines/full-history.yaml`) at the same budget, i.e. the newest messages that fit. Ablation C's third source (LLM rewriting from raw text) and the provenance factor are not part of E005 |
| Equal display budget | Every arm's working context is limited to the same token budget (answering model's tokenizer). A view arm's context has one fragment per view (title; each sentence after the message IDs it cites; the read-time scope note), taken in an order fixed per read (sha256 of read ID and view ID, identical for both view arms) while it fits; a view that does not fit is skipped. Budgets from `configs/common/budgets.yaml`: **1024 (primary)**, where every template context fits (CPU pre-count over the 350 read points: 390 to 828 tokens, median 502), so only verbosity can cost an arm content; and 512, where the budget binds for both view arms |
| Answering | The shared harness step (`runner/harness/answer.py`, prompt `answer`), Qwen3-8B (`configs/models/qwen3-8b.yaml`, thinking off, temperature 0, seed 0), output reserve 256 tokens, one further retrieval per read (a view arm returns the same views again). The same model renders views (plan 5.6: every call type is served by the same model by default). vLLM 0.34 on GPU 3, port 8106, `--max-model-len 32768`, explicit KV-cache size, prefix caching on |
| Population | Questions about the state at the read version: types `changed`, `uniform`, `presupposition`, `abstention` (955 of 1,145). Historical questions (`known_then`, `seen_from_now`, 190) ask for the state at an earlier knowledge version or world time, which no resident view family states; they are answered by every arm and reported as a descriptive stratum only |
| Metrics | Answer accuracy by normalised set match (deterministic; the primary change-seq scorer of `docs/research/change-sequences.md` section 9; rule in `eval/analysis/metrics/changeseq.py`): `unknown` is correct exactly on abstention questions, an answer to an abstention question is correct when it names no candidate value, otherwise every gold item must be named and no other candidate value (other values of the same view template in the same sequence, gold or outdated) may be; on presupposition questions rejecting the outdated premise is allowed. Invalid outputs count as wrong (D002). Reported with strata by question type, view template and change type. Rendering-check failure rate of the llm arm: failed LLM sentences / LLM sentences checked, and template-fallback units / units rendered. Write-side rendering cost: render calls (ledger W) with input and output tokens from `calls.jsonl`. Context tokens per arm |
| Statistics (D002) | Micro mean over reads; 95% percentile interval from a cluster bootstrap over scenario families (10,000 resamples, seed 20261125), paired for differences (same clusters drawn for both arms). Primary readout: llm − template at budget 1024. Secondary: template − raw and llm − raw; budget 512. Sensitivity: sequence as the cluster unit, macro mean of cluster differences, leave-one-family-out, discordant counts. With five families the family-level interval is coarse; strata below 100 reads are descriptive only |
| Runs | Per budget: three `system` runs (template, llm, raw), one `score` run each; `compare` (not a run) writes `summary.json` with the checksum of every input `run.json` under `runs/E005/artifacts/manager/E005-summary/`. View runs also write `views/view_events.jsonl` (every maintenance event); score runs write `records/` (the split's records, gold as files), `scores.jsonl` (one value per read) and `metrics.json` |
| Judging | None. The deterministic set match is the primary scorer; the blind judge (secondary) is not run. The set-match metric is not yet registered in `configs/common/scorers.yaml` (change-seq metrics are pending there; owner T004 manager); registration is requested in the E005 PR |
| Frozen before the first run | View code, view templates and `configs/views/default.yaml` (T018), prompts `render-view` and `answer` and their pins, budgets, engine configs, the scorer rule and this design |

## Acceptance

- [x] Every number traces to a run report: 12 runs (6 system, 6 score), each with `report.yaml`; paired statistics in the `summary.json` files of `E005-summary/` (`budget-1024`, `budget-512`, and the per-template and sensitivity files `budget-1024-by-template`, `budget-512-by-template`).
- [x] Rerun with the fixed rendering check (2026-11-26): 12 further runs (6 system, 6 score), each with `report.yaml`; paired statistics in `E005-summary-rerun/` (the same four files).

## Runs

Reports are under `$PROJECT_ROOT/runs/E005/artifacts/manager/E005/<run-id>/report.yaml`; arm and budget in brackets. Every run is at code SHA `cb52b73ed06e34ed74888481e0e776f8751bcb5c` (clean). Paired comparisons (not runs; checksums of every input `run.json` inside): `runs/E005/artifacts/manager/E005-summary/budget-1024/summary.json` and `.../budget-512/summary.json`.

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| `E005-20261125T201943Z-e56e` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T201943Z-e56e/report.yaml` (system, template, 1024) |
| `E005-20261125T201943Z-0e4f` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T201943Z-0e4f/report.yaml` (system, llm, 1024) |
| `E005-20261125T201943Z-64c1` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T201943Z-64c1/report.yaml` (system, raw, 1024) |
| `E005-20261125T201943Z-1949` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T201943Z-1949/report.yaml` (system, template, 512) |
| `E005-20261125T201943Z-bb70` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T201943Z-bb70/report.yaml` (system, llm, 512) |
| `E005-20261125T201943Z-aa89` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T201943Z-aa89/report.yaml` (system, raw, 512) |
| `E005-20261125T202517Z-8003` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T202517Z-8003/report.yaml` (score of e56e) |
| `E005-20261125T202505Z-2471` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T202505Z-2471/report.yaml` (score of 0e4f) |
| `E005-20261125T202509Z-ef0b` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T202509Z-ef0b/report.yaml` (score of 64c1) |
| `E005-20261125T202507Z-2731` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T202507Z-2731/report.yaml` (score of 1949) |
| `E005-20261125T202514Z-b173` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T202514Z-b173/report.yaml` (score of bb70) |
| `E005-20261125T202512Z-4535` | 2026-11-25 | completed | `cb52b73` | `runs/E005/artifacts/manager/E005/E005-20261125T202512Z-4535/report.yaml` (score of aa89) |

**Rerun with the fixed rendering check** (2026-11-26, session `m01-E005b`). System runs at code SHA `0753fc20cfd3c98f2e60d3711b25ad6aef30dcff` (clean), score runs at `67a21f8bad0e5e57ef373591680f88e1fe877dad` (clean; differs from `0753fc2` only by the documentation commit of the E005 and T018 logs). Qwen3-8B on vLLM 0.34, GPU 0, port 8106, same server arguments as the original runs. Paired comparisons: `runs/E005/artifacts/manager/E005-summary-rerun/budget-1024`, `budget-512`, `budget-1024-by-template`, `budget-512-by-template` (`summary.json`, checksums of every input `run.json` inside).

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| `E005-20261126T024149Z-fa65` | 2026-11-26 | completed | `0753fc2` | `runs/E005/artifacts/manager/E005/E005-20261126T024149Z-fa65/report.yaml` (system, template, 1024) |
| `E005-20261126T024149Z-4287` | 2026-11-26 | completed | `0753fc2` | `runs/E005/artifacts/manager/E005/E005-20261126T024149Z-4287/report.yaml` (system, llm, 1024) |
| `E005-20261126T024149Z-57a9` | 2026-11-26 | completed | `0753fc2` | `runs/E005/artifacts/manager/E005/E005-20261126T024149Z-57a9/report.yaml` (system, raw, 1024) |
| `E005-20261126T024149Z-56b1` | 2026-11-26 | completed | `0753fc2` | `runs/E005/artifacts/manager/E005/E005-20261126T024149Z-56b1/report.yaml` (system, template, 512) |
| `E005-20261126T024149Z-ea79` | 2026-11-26 | completed | `0753fc2` | `runs/E005/artifacts/manager/E005/E005-20261126T024149Z-ea79/report.yaml` (system, llm, 512) |
| `E005-20261126T024149Z-0d2d` | 2026-11-26 | completed | `0753fc2` | `runs/E005/artifacts/manager/E005/E005-20261126T024149Z-0d2d/report.yaml` (system, raw, 512) |
| `E005-20261126T024731Z-ed75` | 2026-11-26 | completed | `67a21f8` | `runs/E005/artifacts/manager/E005/E005-20261126T024731Z-ed75/report.yaml` (score of fa65) |
| `E005-20261126T024731Z-e0c5` | 2026-11-26 | completed | `67a21f8` | `runs/E005/artifacts/manager/E005/E005-20261126T024731Z-e0c5/report.yaml` (score of 4287) |
| `E005-20261126T024731Z-384a` | 2026-11-26 | completed | `67a21f8` | `runs/E005/artifacts/manager/E005/E005-20261126T024731Z-384a/report.yaml` (score of 57a9) |
| `E005-20261126T024731Z-5e8f` | 2026-11-26 | completed | `67a21f8` | `runs/E005/artifacts/manager/E005/E005-20261126T024731Z-5e8f/report.yaml` (score of 56b1) |
| `E005-20261126T024731Z-92b6` | 2026-11-26 | completed | `67a21f8` | `runs/E005/artifacts/manager/E005/E005-20261126T024731Z-92b6/report.yaml` (score of ea79) |
| `E005-20261126T024731Z-88f7` | 2026-11-26 | completed | `67a21f8` | `runs/E005/artifacts/manager/E005/E005-20261126T024731Z-88f7/report.yaml` (score of 0d2d) |

## Results

### First runs (2026-11-25, rendering check without the binding subject)

From completed runs only (code `cb52b73`). Population: 955 questions about the state at the read version, 25 sequences, 5 families; set match; intervals are 95% cluster-bootstrap percentile intervals over families (10,000 resamples, seed 20261125), paired for differences; the sequence-level interval is the sensitivity analysis.

**Answer accuracy** (`metrics.json` of the score runs; invalid outputs count as wrong):

| Budget | Template | LLM rendering | Raw window | Score runs (template, llm, raw) |
| --- | --- | --- | --- | --- |
| 1024 (primary) | 0.903 [0.892, 0.911] (invalid 15) | 0.882 [0.869, 0.890] (invalid 18) | 0.614 [0.599, 0.629] (invalid 0) | `8003`, `2471`, `ef0b` |
| 512 | 0.876 [0.863, 0.889] (invalid 15) | 0.864 [0.849, 0.879] (invalid 15) | 0.585 [0.569, 0.599] (invalid 0) | `2731`, `b173`, `4535` |

**Paired differences** (`summary.json`):

| Budget | Pair | Difference | 95% CI (family) | 95% CI (sequence) | Discordant (first only / second only) |
| --- | --- | --- | --- | --- | --- |
| 1024 | llm − template | −0.021 | [−0.024, −0.018] | [−0.030, −0.011] | 2 / 22 |
| 1024 | template − raw | +0.289 | [+0.278, +0.305] | [+0.258, +0.317] | 282 / 6 |
| 1024 | llm − raw | +0.268 | [+0.258, +0.284] | [+0.237, +0.298] | 270 / 14 |
| 512 | llm − template | −0.013 | [−0.024, +0.001] | [−0.026, +0.002] | 15 / 27 |
| 512 | template − raw | +0.291 | [+0.265, +0.318] | [+0.260, +0.322] | 289 / 11 |
| 512 | llm − raw | +0.279 | [+0.253, +0.304] | [+0.252, +0.306] | 278 / 12 |

At 1024 the llm − template difference is negative in every family (−0.016 to −0.027) and in every leave-one-family-out estimate (−0.020 to −0.022). By question type (1024, llm − template): changed −0.055 (199 reads), uniform −0.018 (501), abstention 0.000 (171), presupposition 0.000 (84, descriptive). By template the LLM arm loses mainly on the constraints view V4 (0.845 against 0.974, 155 reads).

**By view template** (llm vs template, paired; same score runs; family-cluster bootstrap; `E005-summary/budget-1024-by-template/summary.json` and `budget-512-by-template/summary.json`, written by `compare` at code `95552384` from the score runs above; templates with fewer than 100 reads are descriptive only):

| Budget | Template family | Reads | Template | LLM | llm − template | 95% CI (family) | Discordant (llm only / template only) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1024 | V1 list | 128 | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 0 / 0 |
| 1024 | V2 current | 179 | 0.514 | 0.520 | +0.006 | [−0.017, +0.032] | 2 / 1 |
| 1024 | V3 count | 107 | 1.000 | 0.991 | −0.009 | [−0.029, 0.000] | 0 / 1 |
| 1024 | V4 constraints | 155 | 0.974 | 0.845 | −0.129 | [−0.169, −0.098] | 0 / 20 |
| 1024 | V5 pending | 205 | 0.990 | 0.990 | 0.000 | [0.000, 0.000] | 0 / 0 |
| 1024 | V6 choice | 181 | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 0 / 0 |
| 512 | V1 list | 128 | 0.914 | 0.992 | +0.078 | [+0.050, +0.102] | 10 / 0 |
| 512 | V2 current | 179 | 0.492 | 0.497 | +0.006 | [0.000, +0.018] | 2 / 1 |
| 512 | V3 count | 107 | 0.963 | 0.963 | 0.000 | [−0.028, +0.028] | 2 / 2 |
| 512 | V4 constraints | 155 | 0.955 | 0.819 | −0.135 | [−0.193, −0.090] | 0 / 21 |
| 512 | V5 pending | 205 | 0.980 | 0.971 | −0.010 | [−0.020, 0.000] | 1 / 3 |
| 512 | V6 choice | 181 | 0.994 | 0.994 | 0.000 | [0.000, 0.000] | 0 / 0 |

**Descriptive sensitivity analysis: excluding V4** (post hoc, not preregistered; named `sensitivity_excluding_V4` in the same summary files; 800 reads): at 1024 template 0.889, llm 0.889, llm − template 0.000 [−0.005, +0.006] (discordant 2 / 2); at 512 template 0.861, llm 0.873, llm − template +0.011 [+0.001, +0.020] (15 / 6). The V2 rows are low in both arms because of the presupposition questions (see below), not because of the view content.

**Rendering** (llm arm, `views/view_events.jsonl` and `calls.jsonl` of the system runs): 1024: 639 units rendered, 13 of 638 checked LLM sentences failed the rendering check and fell back to the template (sentence failure rate 0.020, unit fallback rate 0.020); 602 render calls (all `ok`, ledger W), 247,580 input tokens (232,704 served from the prefix cache) and 30,643 output tokens on the write side, against 0 for the template arm. 512: 14 of 638 failed (0.022); 602 calls, 247,580 input and 30,626 output tokens. Mean context tokens at 1024: template 506, llm 521, raw 972; every view fits at 1024 in both view arms (15 of 15 views in every context); at 512 the mean number of views in context is 14.0 (template) and 13.8 (llm).

**Other observations.** Presupposition questions ("my field of work is still education, isn't it?", 84 reads) score 0 in every arm: Qwen3-8B answers `unknown` (or an invalid `unknown` with citations) although the view states the current value; this is answering-model behaviour under the shared answer prompt, identical across arms, and it bounds every arm's accuracy. Historical questions (190 reads, descriptive, outside the population): template 0.284, llm 0.274, raw 0.274 at 1024. Inspection of the discordant V4 reads shows the mechanism of the LLM arm's loss: the rendered sentence often drops the task the constraint belongs to ("The constraint is arrive by 12:00." against the template's "Requested for train booking A: arrive by 12:00."), leaving the link only in the view title; the rendering check requires the row values, not the binding constants, so such sentences pass.

### Rerun with the fixed rendering check (2026-11-26)

From completed runs only (system runs at `0753fc2`, score runs at `67a21f8`; Runs table above). Same population, scorer (now registered as `change-seq` `set-match`), statistics and design; the only change is that every LLM sentence must name its binding's subject (Log, 2026-11-26). All three arms were rerun on one server so that the pairs share code and serving.

**Reproducibility of the unchanged arms.** The template contexts are byte-identical to the first runs at both budgets; template and raw predictions differ in 1 to 5 of 1,145 reads (serving nondeterminism on another GPU), and their accuracies are unchanged to three decimals (template 0.903 / 0.876, raw 0.614 / 0.585).

**Answer accuracy** (score runs; invalid outputs count as wrong):

| Budget | Template | LLM rendering | Raw window | Score runs (template, llm, raw) |
| --- | --- | --- | --- | --- |
| 1024 (primary) | 0.903 [0.893, 0.911] (invalid 15) | 0.887 [0.869, 0.903] (invalid 16) | 0.614 [0.599, 0.629] (invalid 0) | `ed75`, `e0c5`, `384a` |
| 512 | 0.876 [0.863, 0.889] (invalid 15) | 0.871 [0.852, 0.890] (invalid 13) | 0.585 [0.569, 0.599] (invalid 0) | `5e8f`, `92b6`, `88f7` |

**Before and after** (llm − template, paired; `E005-summary` against `E005-summary-rerun`):

| Budget | Readout | First runs | Rerun |
| --- | --- | --- | --- |
| 1024 | overall, 95% CI (family) | −0.021 [−0.024, −0.018] | −0.016 [−0.024, −0.007] |
| 1024 | overall, 95% CI (sequence) | [−0.030, −0.011] | [−0.026, −0.004] |
| 1024 | discordant (llm only / template only) | 2 / 22 | 4 / 19 |
| 1024 | V4 constraints (155 reads): llm vs template | 0.845 vs 0.974, −0.129 [−0.169, −0.098], 0 / 20 | 0.884 vs 0.974, −0.090 [−0.168, −0.031], 1 / 15 |
| 1024 | excluding V4 (800 reads, post hoc, descriptive) | 0.000 [−0.005, +0.006] | −0.001 [−0.009, +0.009] |
| 512 | overall, 95% CI (family) | −0.013 [−0.024, +0.001] | −0.005 [−0.021, +0.009] |
| 512 | discordant | 15 / 27 | 17 / 22 |
| 512 | V4 constraints | −0.135 [−0.193, −0.090], 0 / 21 | −0.097 [−0.176, −0.025], 1 / 16 |
| 512 | excluding V4 (post hoc, descriptive) | +0.011 [+0.001, +0.020] | +0.013 [+0.001, +0.024] |

At 1024 the overall difference is negative in every family (−0.032 to −0.005) and in every leave-one-family-out estimate (−0.018 to −0.012). By question type at 1024: changed −0.045 (199 reads), uniform −0.010 (501), abstention −0.006 (171), presupposition 0.000 (84, descriptive). The other families at 1024 (llm − template): V1 0.000, V2 +0.011, V3 −0.009, V5 −0.010, V6 0.000; at 512 V1 is again +0.078 [+0.050, +0.102] (10 / 0), the one family where rendering helps, at the budget that binds (`budget-*-by-template/summary.json`). Template − raw is unchanged (+0.289 at 1024, +0.291 at 512); llm − raw is +0.273 [+0.260, +0.295] at 1024 and +0.286 [+0.257, +0.315] at 512.

**Rendering** (llm arm, `views/view_events.jsonl` and `calls.jsonl`). Rendering-check failures rise as expected: at 1024, 50 of 638 checked LLM sentences failed (0.078, first runs 0.020) and 50 of 639 units fell back to the template (0.078, first runs 0.020); at 512, 53 of 638 (0.083, first runs 0.022). By family at 1024: constraints 16 of 81 (0.198, first runs 0), current 15 of 106 (0.142, 0), pending 4 of 33 (0.121, 0), count 13 of 223 (0.058, unchanged), choice 1 of 26, list 1 of 169. Render calls and tokens are unchanged, since a fallback adds no call: 602 calls (all `ok`, ledger W), 247,580 input tokens (234,688 from the prefix cache) and 30,633 output tokens at 1024; 602 calls, 247,580 and 30,621 at 512. Mean context tokens at 1024: template 506, llm 522, raw 972; all 15 views fit in every view context.

**Remaining V4 loss.** In each of the 15 V4 reads still lost at 1024 the accepted LLM sentences of the relevant constraints view name their task and their values (for example "The constraint for hotel booking A is check in day with value Monday." against the template's "Requested for hotel booking A: check in day Monday."). The answering model then answers `unknown` (5 reads), names the constraint or the view instead of the value ("check in day", "pickup station", "constraints requested for flight booking A"; 6), or names another or an outdated constraint value (4). V4 by family at 1024 (llm − template, first runs → rerun): train travel −0.143 → 0.000 (where the dropped-task sentences such as "The constraint is arrive by 12:00." came from), car rental −0.121 → −0.030, apartment search −0.081 → −0.081, flight travel −0.118 → −0.118, hotel stay −0.217 → −0.261 (23 to 37 reads per family, descriptive). The rest of the V4 deficit therefore comes from how the frozen `render-view` prompt makes Qwen3-8B phrase a constraint row, not from a gap in the check. The first runs' statement that the whole V4 deficit was due to the check gap is corrected by this rerun: the gap explains about 4 of the 13 points.

## Conclusion

As measured, on gold graphs of the development families, with the rendering check fixed, LLM rendering of the result rows did not help the answering LLM more than template serialisation at equal display budget. At the primary budget 1024 it was 1.6 points worse (CI [−0.024, −0.007] over families, [−0.026, −0.004] over sequences, both excluding zero); at 512 the difference was −0.5 points (CI [−0.021, +0.009]). The write-side cost was the same as before: 602 render calls and about 278K tokens per pass over the 25 sequences, against none for the template. Both view arms beat the raw-text window by 27 to 29 points.

The fix did what it was meant to do. Sentences that drop their task now fall back to the template: the check failure and fallback rate rose from 2% to 8%, mostly on constraints, current and pending. The V4 deficit fell from −12.9 to −9.0 points at 1024, but it did not go away. The remaining loss is attributable to the LLM's phrasing of constraint rows under the frozen prompt, which the answering model misreads. That is a property of LLM rendering as specified, not a defect of the check. Outside V4 the arms tie at 1024 (−0.001 [−0.009, +0.009]); at 512 rendering is slightly ahead (+0.013 [+0.001, +0.024], mainly V1 because more fits in the budget). Both figures come from a post hoc, descriptive analysis.

On this evidence the overturn condition of the RQ3 premise (plan 4.2, "template serialisation is not worse in answer accuracy") **is established for E005's scope**. Template serialisation was not worse than LLM rendering at either budget; it was better at the primary budget, and the defect that the first runs' caveat pointed to has been removed. The scope matters, and nothing beyond it is claimed. The evidence covers one model rendering and answering (Qwen3-8B), the frozen `render-view` prompt, one seed, development data and gold graphs with surface labels, with five families as clusters. A different rendering prompt, a stronger renderer or extracted graphs (E010) could still change the comparison. The 512 result and the exclusion analysis show that rendering is not uniformly worse: the effect depends on the family and the budget. For D008 the evidence is: on gold graphs, LLM rendering adds write-side cost and no accuracy at the primary budget, and loses accuracy on constraint views.

Limits: the scope above; presupposition questions score 0 in every arm (answering-model behaviour under the shared prompt); historical questions are descriptive only (1024: template 0.284, llm 0.268, raw 0.274); the rerun used GPU 0 instead of GPU 3 (same server arguments; unchanged arms reproduce); the exclusion and phrasing analyses are post hoc.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-E005` started on `task/E005-ablation-c-gold` from `63f9d4fff7021651c9626af18bdc0a25ce50e557`; Issue #95. Design and config written before the first formal run; CPU pre-checks (view answers against gold, template context sizes) on the development set.
- 2026-11-25: formal runs at `cb52b73` (Qwen3-8B, vLLM 0.34, GPU 3, port 8106): six system runs (template, llm, raw at 1024 and 512) and six score runs, all completed, with reports; comparisons in `E005-summary/budget-1024` and `budget-512`. Result: llm − template −0.021 [−0.024, −0.018] at 1024. Server stopped by PID and the compute.yaml entry removed. No judge run.
- 2026-11-25: amendment requested by the integration owner (PR #97): the Conclusion overstated the result. Added the per-template table and a descriptive sensitivity analysis excluding V4, both computed by `compare` (code `95552384`, new option `--exclude-template`) from the existing score runs, without new model runs; Conclusion rewritten: the main deficit is attributable to the rendering-check gap (binding constants not required), so the RQ3 overturn condition is not established until the check is fixed and E005 rerun. E005 stays `active`.
- 2026-11-26: user decisions after the first runs: (1) fix T018's rendering check and rerun E005; (2) register the change-seq set-match scorer in `configs/common/scorers.yaml`. Manager session `m01-E005b` on `task/E005-render-check` from `3143ab337cf080b3511698d5b01e5f2361f4d961`.
- 2026-11-26: design change, recorded before the rerun (deliberate and user-approved, before the configuration lock D012, not a deviation from a locked design): the rendering check of the llm arm (`views/render.py`, frozen T018 code) now also requires the binding's subject (the task of V4 to V6, the entity of V1 to V3) in every LLM sentence, matched like the row values (normalised substring); the predicate and title stay allowed but not required. Everything else of the design is unchanged: config `configs/experiments/E005-ablation-c-gold.yaml` byte-identical (sha256 `5b3dc672…`; its comment "not yet registered" is now stale), prompts, templates, view config, population, budgets, arms, seed, models. All six system runs are repeated at the new code so that the paired comparison uses one code SHA and one server; the serving GPU is 0 instead of 3 (GPU 3 was occupied by another user's process), same vLLM 0.34 arguments. CPU replay on the original llm-arm contexts (1,056 distinct sentences): 53 lack their subject (constraints 15 of 81, current 34 of 244, pending 4 of 33), the expected order of new check failures.
- 2026-11-26: scorer registered: `change-seq` `set-match` (population: the four state question types) and `set-match-historical` (descriptive), code `grace.eval.analysis.metrics.changeseq:set_match`, annotation `generator`, rule unchanged.
- 2026-11-26: rerun at `0753fc2` (system runs) and `67a21f8` (score runs; the two differ only in documentation), Qwen3-8B on vLLM 0.34, GPU 0, port 8106: six system and six score runs, all completed, each with a report; comparisons in `E005-summary-rerun/`. Result: llm − template −0.016 [−0.024, −0.007] at 1024 (first runs −0.021) and −0.005 [−0.021, +0.009] at 512. Check failure and fallback rate 0.078 (first runs 0.020); render calls and tokens unchanged. V4 deficit −0.090 (first runs −0.129). The template and raw arms reproduce the first runs. Conclusion rewritten: the RQ3 overturn condition is established within E005's scope. The remaining V4 loss comes from how the LLM phrases constraint rows, not from the check, which corrects the attribution made after the first runs. Server stopped by PID; compute.yaml entry removed. No judge run.
