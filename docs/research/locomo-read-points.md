# LoCoMo Evidence-Anchored Read Points

Report of task T007 (`docs/work/tasks/T007-locomo-read-points.md`) for the streaming protocol of plan section 6.5. Everything here is model-free: no LLM is called; the counts come from the evidence annotation, session boundaries and message texts.

## Definition

- Each category 1–4 question $q$ is read at $v(q)$, the last version of the session that holds the latest turn of its annotated evidence, and again at $N$ (plan 6.5). Versions are those of the T002 adapter: messages $1..N$ in source order, one segment per `session_<k>`.
- **Excluded from streaming** (no read point): questions whose evidence is missing or contains a reference that names no turn (adapter `evidence_status` `missing` or `unresolved`). A partly resolvable list counts as unresolved, because completeness of the evidence is what makes the gold valid at $v(q)$.
- **Reported separately**: questions on the independent audit's evidence-error list (`WRONG_CITATION` in `dial481/locomo-audit` @ `9493fb4`, shipped under `data/locomo/3eb6f2c/audit/`). They keep a read point from the annotated evidence; the audit's corrected evidence gives a second value, $v_{audit}$, for comparison. Exclusion takes precedence when a question is on both lists.
- **Label only**: the audit's 99 answer errors (`HALLUCINATION`, `TEMPORAL_ERROR`, `ATTRIBUTION_ERROR`, `AMBIGUOUS`, `INCOMPLETE`) do not affect $v(q)$; they are carried as a label so that results can be reported on all questions and on the 1,441 remaining (plan 6.5).
- **Read points of a history**: the distinct $v(q)$ of its streaming questions, plus $N$. The writes between adjacent read points $r_i < r_{i+1}$ are the messages with version in $(r_i, r_{i+1}]$.
- **Token counter**: the pinned Qwen3-8B tokenizer (`configs/models/qwen3-8b.yaml`, `Qwen/Qwen3-8B@b968826d9c46dd6066d109eabc6255188de91218`, files checked against their SHA-256 by `grace.llm.tokens`), `count_text` on the message text only: no speaker name, chat template or special tokens. Image fields are not part of the text (adapter).
- Quantiles interpolate linearly between order statistics (`statistics.quantiles`, method `inclusive`).

## Runs

| Stage | Run directory (`$PROJECT_ROOT/runs/T007/artifacts/`) | Code SHA | Scope |
| --- | --- | --- | --- |
| dev | `read-points-dev-20261125T005427Z` | `9b6f0453ab801e928afcb5624201a8c8ee599b1f` | conv-26, conv-49 |
| all | `read-points-all-20261125T005549Z` | `d77ab6344eb6c3ccf7e1d229be209efad8a64ee1` | all 10 histories |

Data: `locomo` version `3eb6f2c`, manifest `c68369667248276b0b7b314d6cf566a877386471ac49f94dada7c9f1ca588ae7`, `locomo10.json` `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`; every manifest file was verified by `splits.load_split`, which also checked the split counts of the config. Commands: `scripts/locomo_read_points.sh dev` and `scripts/locomo_read_points.sh all --held-out-annotation-only`. Each run directory holds `run.json` (command, SHA, clean tree, checksums, token-counter pin), `read_points.jsonl` (one row per question), `histories.json`, `summary.json`, `exclusions.json`, `read_tasks.streaming.jsonl` (the `streaming` schedule of contracts.md: each question with a read point at $v(q)$ and $N$) and `read_points.yaml`, which is committed as `configs/benchmarks/read-points/locomo.yaml`. The all stage also writes `threshold_evaluation.json`. Rerunning the dev stage inside the all stage reproduced every dev number.

Held-out access: the all stage reads the eight held-out histories through `load_split` with the preregistration guard overridden, only behind the flag `--held-out-annotation-only`. No system, model or score touches them; only evidence IDs, session boundaries and text lengths are counted. This was requested by the integration owner for T007; see the open question at the end.

## Order of work

1. Dev stage run and inspected (commit `9b6f045`).
2. Promotion threshold written into `configs/benchmarks/read-points/locomo.yaml` and the task Log, committed as `d77ab63` and pushed to `origin` before any held-out statistic was computed. The CLI refuses the all stage unless that file is committed and unchanged, and records the commit that introduced the threshold.
3. All stage run at `d77ab63`.

## Exclusions

| List | Dev | Held-out | All | Questions |
| --- | ---: | ---: | ---: | --- |
| Evidence missing (excluded) | 2 | 2 | 4 | conv-26:q30, conv-26:q46, conv-50:q39, conv-50:q42 |
| Evidence unresolved (excluded) | 4 | 5 | 9 | conv-26:q37 (`D8:6; D9:17`), conv-49:q31, q38, q46 (space-separated lists), conv-42:q58 (`D10:19`), conv-42:q88 (`D`), conv-43:q18 (`D:11:26`), conv-47:q38 (`D4:36`), conv-50:q69 (`D30:05`) |
| Audit `WRONG_CITATION` (reported separately) | 13 | 40 | 53 | listed in `exclusions.json` and the config |
| Audit `WRONG_CITATION` also excluded above | 1 | 3 | 4 | conv-26:q37, conv-42:q88, conv-47:q38, conv-50:q69 |
| Audit answer error (label only) | 29 | 70 | 99 | 98 have a read point; conv-42:q58 is excluded |

The 13 excluded questions are the 13 of the benchmark card (dev 6, held-out 7). The audit lists 57 evidence errors; 4 of them are among the 13, leaving 53 reported separately. For 4 of the 53 the corrected evidence moves the read point: later for conv-26:q4 (18 → 232), conv-48:q78 (50 → 663) and conv-48:q155 (451 → 565), earlier for conv-44:q8 (50 → 24). At the annotated $v(q)$ the first three would be asked before the turn the audit says supports the answer, which is the reason to report this group apart.

## Development histories (threshold basis)

| History | $N$ | Sessions | Tokens | Streaming questions | $v(q)<N$ | Distinct read points | Tokens between adjacent reads (min / median / max) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| conv-26 | 419 | 19 | 13,065 | 138 | 134 | 19 | 450 / 653 / 1,047 |
| conv-49 | 509 | 25 | 14,600 | 151 | 146 | 25 | 405 / 585 / 823 |

- 308 questions: 289 streaming, 13 reported separately, 6 excluded.
- Share of streaming questions with $v(q)<N$: 0.969 (280 of 289); by category 1: 0.952, 2: 0.971, 3: 0.952, 4: 0.978.
- $v(q)/N$: p10 0.11, p25 0.24, median 0.51, p75 0.81, p90 0.96; roughly uniform over deciles, with 50 of 289 in the last decile.
- Every session end of both histories is a read point, so adjacent reads are exactly one session apart: median 19.5 messages and 613.5 tokens (42 gaps, min 405). About 96% of all messages are written after the first read point.

## Promotion threshold

Fixed from the development histories and committed in `d77ab63` before held-out statistics existed. Streaming is reported in the main text if all three hold on the held-out streaming questions; otherwise it moves to the supplementary material.

| Criterion | Threshold | Dev value |
| --- | ---: | ---: |
| Pooled share of questions with $v(q)<N$ | ≥ 0.5 | 0.969 |
| Median distinct read points per history ($N$ included) | ≥ 5 | 22 |
| Median tokens written between adjacent read points | ≥ 256 | 613.5 |

Rationale: the values follow from what the protocol needs, not from the dev values, which pass with a wide margin. (1) "A substantial share" in plan 6.5 is read as a majority; below one half, most streaming reads coincide with the end-of-history reads. (2) Staleness strategies differ in cost only when a view is read, invalidated by later writes and read again; four or more read points before $N$ give each view several such cycles. (3) "Real writes" between reads means at least as many new tokens as the smallest answer memory budget (256, `configs/common/budgets.yaml`), so the new material cannot simply be passed through in context. Since $v(q)$ is always a session end, adjacent reads are at least one whole session apart, and criterion 3 guards against very short sessions.

## All histories

Computed after the threshold commit.

| History | Split | $N$ | Sessions | Tokens | Streaming questions | $v(q)<N$ | Distinct read points | Tokens between adjacent reads (min / median / max) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| conv-26 | dev | 419 | 19 | 13,065 | 138 | 134 | 19 | 450 / 653 / 1,047 |
| conv-49 | dev | 509 | 25 | 14,600 | 151 | 146 | 25 | 405 / 585 / 823 |
| conv-30 | held-out | 369 | 19 | 10,171 | 78 | 76 | 19 | 318 / 497 / 884 |
| conv-41 | held-out | 663 | 32 | 20,071 | 145 | 143 | 31 | 436 / 606 / 1,247 |
| conv-42 | held-out | 629 | 29 | 16,616 | 190 | 184 | 29 | 261 / 571 / 1,100 |
| conv-43 | held-out | 680 | 29 | 19,454 | 173 | 169 | 29 | 330 / 625 / 1,167 |
| conv-44 | held-out | 675 | 28 | 18,826 | 120 | 110 | 27 | 399 / 695 / 1,067 |
| conv-47 | held-out | 689 | 31 | 18,446 | 143 | 139 | 30 | 368 / 587 / 954 |
| conv-48 | held-out | 681 | 30 | 16,651 | 185 | 183 | 30 | 295 / 506 / 1,222 |
| conv-50 | held-out | 568 | 30 | 18,551 | 151 | 143 | 30 | 322 / 590 / 1,168 |

Per-history medians in this table use the middle element of the sorted gaps; the pooled quantiles below interpolate.

| Statistic | Held-out (8 histories) | All (10) |
| --- | ---: | ---: |
| Questions / streaming / separate / excluded | 1,232 / 1,185 / 40 / 7 | 1,540 / 1,474 / 53 / 13 |
| Share of streaming questions with $v(q)<N$ | 0.968 (1,147) | 0.968 (1,427) |
| By category 1 / 2 / 3 / 4 | 0.974 / 0.959 / 0.955 / 0.971 | 0.969 / 0.961 / 0.955 / 0.972 |
| $v(q)/N$ p10 / p25 / median / p75 / p90 | 0.13 / 0.31 / 0.58 / 0.80 / 0.94 | 0.12 / 0.29 / 0.57 / 0.80 / 0.95 |
| Distinct read points per history, median (min–max) | 29.5 (19–31) | 29 (19–31) |
| Gaps between adjacent read points | 217 | 259 |
| Messages per gap, median (min–max) | 20 (10–47) | 20 (10–47) |
| Tokens per gap, p10 / median / p90 (min–max) | 422 / 579 / 914 (261–1,247) | 428 / 587 / 896 (261–1,247) |
| Gaps spanning 2 sessions | 3 | 3 |
| Share of messages written after the first read point, median | 0.966 | 0.965 |

Threshold on held-out: share 0.968 ≥ 0.5, median read points 29.5 ≥ 5, median gap 579 tokens ≥ 256. **All three hold: by the preregistered rule, evidence-anchored streaming qualifies for the main text** (`threshold_evaluation.json`).

## Notes and limits

- Nearly every session end is a read point (only 3 of 259 gaps span two sessions), so streaming on LoCoMo amounts to reading after every session. Reads are spread evenly in time; there is no clustering at the end.
- The protocol inherits the limitation stated in plan 6.5: questions are asked only once their evidence is complete, so it measures false-positive staleness and reuse, not true staleness.
- Validity of the gold at $v(q)$ rests on evidence completeness. The audit checked whether cited evidence supports the answer, not whether every needed turn is cited; multi-hop questions whose citation omits an earlier or later supporting turn are not detectable here. The consistency check between $v(q)$ and $N$ (plan 6.5) will surface some of them.
- Questions answerable only from an image caption are not flagged yet (open on the benchmark card); they are inside the streaming set.
- Whitespace-token counts are available with `--tokens whitespace` but were not used.

## Open question

The all stage reads held-out annotations before the preregistration tag of T033, behind an explicit flag and without any system run. AGENTS.md forbids running held-out data before that tag; this was interpreted as forbidding system runs and scores, not annotation statistics, on the instruction of the integration owner. If the user reads the rule more strictly, the held-out tables above and the held-out part of the config should be withdrawn and recomputed after the tag; the threshold commit is unaffected.
