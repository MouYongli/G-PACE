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

- [x] Every number traces to a run report: 12 runs (6 system, 6 score), each with `report.yaml`; paired statistics in the two `summary.json` files above.

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

## Results

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

**Rendering** (llm arm, `views/view_events.jsonl` and `calls.jsonl` of the system runs): 1024: 639 units rendered, 13 of 638 checked LLM sentences failed the rendering check and fell back to the template (sentence failure rate 0.020, unit fallback rate 0.020); 602 render calls (all `ok`, ledger W), 247,580 input tokens (232,704 served from the prefix cache) and 30,643 output tokens on the write side, against 0 for the template arm. 512: 14 of 638 failed (0.022); 602 calls, 247,580 input and 30,626 output tokens. Mean context tokens at 1024: template 506, llm 521, raw 972; every view fits at 1024 in both view arms (15 of 15 views in every context); at 512 the mean number of views in context is 14.0 (template) and 13.8 (llm).

**Other observations.** Presupposition questions ("my field of work is still education, isn't it?", 84 reads) score 0 in every arm: Qwen3-8B answers `unknown` (or an invalid `unknown` with citations) although the view states the current value; this is answering-model behaviour under the shared answer prompt, identical across arms, and it bounds every arm's accuracy. Historical questions (190 reads, descriptive, outside the population): template 0.284, llm 0.274, raw 0.274 at 1024. Inspection of the discordant V4 reads shows the mechanism of the LLM arm's loss: the rendered sentence often drops the task the constraint belongs to ("The constraint is arrive by 12:00." against the template's "Requested for train booking A: arrive by 12:00."), leaving the link only in the view title; the rendering check requires the row values, not the binding constants, so such sentences pass.

## Conclusion

On gold graphs of the development families, LLM rendering of the result rows does not help the answering LLM more than template serialisation at equal display budget: it is 2.1 points worse at the primary budget (CI excludes zero at both cluster units) and 1.3 points worse at 512 (CI includes zero), while costing 602 render calls and about 278K tokens on the write side per pass over the 25 sequences. Both view arms beat the raw-text window by 27 to 29 points. This meets the overturn condition of the RQ3 premise as stated in plan 4.2 for the gold-graph setting ("template serialisation is not worse in answer accuracy"): on this evidence rendering, caching and maintaining rendered text are not needed, and the phase 2 gate (D008) should weigh the framing "a staleness criterion plus computing at query time". Limits: one answering and rendering model (Qwen3-8B), one seed, development data, gold graphs with surface entity labels, a scorer not yet registered in `configs/common/scorers.yaml`, and five families as clusters; the rerun on extracted graphs is E010.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-E005` started on `task/E005-ablation-c-gold` from `63f9d4fff7021651c9626af18bdc0a25ce50e557`; Issue #95. Design and config written before the first formal run; CPU pre-checks (view answers against gold, template context sizes) on the development set.
- 2026-11-25: formal runs at `cb52b73` (Qwen3-8B, vLLM 0.34, GPU 3, port 8106): six system runs (template, llm, raw at 1024 and 512) and six score runs, all completed, with reports; comparisons in `E005-summary/budget-1024` and `budget-512`. Result: llm − template −0.021 [−0.024, −0.018] at 1024. Server stopped by PID and the compute.yaml entry removed. No judge run.
