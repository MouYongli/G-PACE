---
id: E006
title: Graph quality
created: 2026-11-23
---

# E006 · Graph quality

## Question

How good is the extracted graph itself: claim precision, recall and F1, attribution and time fields, and how often a restatement counts as independent evidence? Serves all three research questions as the error source of the graph channel.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Annotated segments from T024; controlled sequences with gold graphs |
| Systems and baselines | Primary writer at the main configuration |
| Metrics | Claim precision, recall, F1; shape conformance and retries; whether the cited span entails the claim; attribution and time accuracy; answer coverage upper bound |
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E006-graph-quality.yaml` |

## Acceptance

- [ ] Every number traces to a run report.

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| E006-20261128T001447Z-0046 | 2026-11-28 | completed (provisional; probe: segment-wise extraction, Qwen3-8B T022 writer) | `aaee362e54ca141efa3bb685e42cbf4fb0ebef65` | `runs/E006/artifacts/w01-E006/E006/E006-20261128T001447Z-0046/report.yaml` |
| E006-20261128T002555Z-50c6 | 2026-11-28 | completed (predicate-matcher check) | `f2b69d7b6de65607820c2b22afaa3a7db5192e52` | `runs/E006/artifacts/w01-E006/E006/E006-20261128T002555Z-50c6/report.yaml` |
| E006-20261128T002604Z-514e | 2026-11-28 | completed (provisional; score of E006-20261128T001447Z-0046) | `f2b69d7b6de65607820c2b22afaa3a7db5192e52` | `runs/E006/artifacts/w01-E006/E006/E006-20261128T002604Z-514e/report.yaml` |
| E006-20261128T002611Z-896e | 2026-11-28 | completed (comparison; score of T022-20261126T214758Z-613e, LoCoMo segments) | `f2b69d7b6de65607820c2b22afaa3a7db5192e52` | `runs/E006/artifacts/w01-E006/E006/E006-20261128T002611Z-896e/report.yaml` |

## Results

Provisional only: the writer is the T022 configuration (Qwen3-8B), not the main configuration E007 will fix, and the gold is two agent annotators pending human review. Precision and recall are bounds (lower–upper): precision against core units (both agents) to all units, recall against all units to core units. Loose = same message, subject and object (T024 normalisation) and an equivalent predicate (lexical, then the Qwen3-8B judge). Scorer code `f2b69d7`.

| Run | Benchmark | Writer claims | Gold core / all | Level | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E006-20261128T002604Z-514e (segment-wise) | all | 611 | 426 / 675 | anchor | 0.311–0.365 | 0.330–0.446 | 0.320–0.402 |
| | | | | loose | 0.160–0.182 | 0.164–0.230 | 0.162–0.203 |
| | | | | strict | 0.048–0.052 | 0.047–0.068 | 0.047–0.059 |
| | LoCoMo | 343 | 182 / 262 | loose | 0.140–0.163 | 0.214–0.264 | 0.169–0.202 |
| | LongMemEval-S | 268 | 244 / 413 | loose | 0.187–0.205 | 0.133–0.205 | 0.155–0.205 |
| E006-20261128T002611Z-896e (T022 full-history run) | LoCoMo | 428 | 182 / 262 | anchor | 0.173–0.206 | 0.336–0.407 | 0.228–0.273 |
| | | | | loose | 0.068–0.077 | 0.126–0.159 | 0.088–0.104 |

Other measures of run E006-20261128T002604Z-514e (all segments): the cited span anchors in the message text for 523 of 611 claims (0.856); the Qwen3-8B judge finds the span entails the claim for 0.828 of 523 (0.941 of 101 loose-matched, 0.801 of 422 unmatched; 0 invalid); on loose matches with core units the fields agree for function 0.897 (n 97), certainty 0.891 (92), speaker 0.969 (98), polarity, report mode and derived 1.0, time expression 0.837 (92) but 0.444 of the 27 where the gold sets one, and the writer sets `valid_from` on none (gold sets it on 12). Catch-all predicates are 8 of 611 claims (precision 0.375); 152 distinct predicates. Entity labels: 2 of 507 are first-person (`my fam`, `my dad`), 34 (0.067) have a content word that is not in the segment or context text (mostly abstract nouns typed as entities); on loose matches the writer's subject equals the gold name in 0.937 (n 111) and an entity object in 0.743 (n 105). Ending-evidence check: 10 ending stances dropped on units with segment messages and no gold ending stance exists in the 40 segments, so the false-drop rate is 0 of 10 by construction and the check's recall cannot be measured on this sample. The full-history run (896e) has 44 `felt` claims (10% catch-all, precision 0) against 1.3% in the segment-wise run, and its span entailment rate is 0.655 (n 377).

## Conclusion

Pending.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-26: design inputs from the T022 writer smoke runs (PR #126, #129; runs under `runs/T022/artifacts/manager/T022/`), recorded by the integration owner on user decisions: measure both missed and spurious extraction against gold or human labels (writer scale trades precision for coverage: Qwen3-32B wrote 474 claims and left 45/136 units empty, Qwen3-8B wrote 957 with more noise); report quality per predicate, including catch-all predicates (no program-side blacklist is applied); measure the false-drop rate of the writer's evidence check on ended stances; separate writer errors from planner (T023) and fragment-selection errors in graph-channel misses (graph-channel R@20 was about 0.1 with either writer on LoCoMo dev); note that neither writer fills `valid_from`.
- 2026-11-27: design input recorded by the integration owner (user decision, T014 log of the same date): entity labels are immutable, so E006 also checks whether the writer's first-mention labels are correct surface names; a material error rate reopens the question of label correction.
- 2026-11-28: worker session `w01-E006` started on `task/E006-graph-quality` from `b7c62c3`; Issue #142. Scope of this round: the scorer and a provisional run; the formal run waits for the main writer configuration that E007 fixes.
- 2026-11-28: scorer `src/grace/eval/analysis/metrics/graph.py` (files only; reuses the T024 matching and normalisation of `eval/analysis/annotation/graph_quality.py`) and CLI `python -m grace.cli.graph_quality score <writer-run-dir>`, which takes any writer run directory with `updates.jsonl` and `graphs/<id>/` (a segment graph per sampled segment, or a graph per history as written by `grace.cli.writer_smoke`), writes a new `score` run with `metrics.json`, `claims.jsonl`, `gold.jsonl`, `judgements.jsonl` and `calls.jsonl`, and accepts `--experiment E007 --run-parent <dir>` for E007 arms. Gold: two label files give core units (claims both agents found, paired with the T024 matcher, identical to the merged review file) and uncertain units (one agent); precision and recall are reported as bounds (precision vs core to vs all units, recall vs all to vs core units). One label file (the human-reviewed reference) makes every claim core and the bounds coincide, without code change (`--gold FILE` or `scoring.gold`).
- 2026-11-28: predicate matching decision (run `E006-20261128T002555Z-50c6`). Three matchers were checked on 212 agent-agent predicate pairs: the 132 anchor pairs whose normalised predicates differ, and 80 seeded cross pairs (one pair's subject, object and quote with another pair's predicate), labelled same/different by the worker agent (`docs/research/annotations/graph-quality/predicate-check-reference.jsonl`; 130 same, 82 different; an agent's labels, not human). Normalised equality: accuracy 0.387 (accepts none of the differing pairs). Lexical (shared content stem after light words): accuracy 0.703, precision of SAME 0.986, recall 0.523. Lexical then the Qwen3-8B judge (`resources/prompts/predicate-judge`, through `grace.llm`, shared server): accuracy 0.882, precision 0.965, recall 0.838, 0 invalid. Chosen: lexical then judge as the `loose` level; `strict` (T024 strict) and `anchor` (no predicate condition) are reported with it as lower and upper references. The judge is conservative (it rejects, for example, wants/requires for a stated need), and the prompt examples were written after looking at these pairs, so the check is in-sample for the prompt. vLLM at temperature 0 is not bit-reproducible under batching (a dry run gave 0.887).
- 2026-11-28: deviation from a full-history reading (plan 6.7 does not fix how the writer sees a sampled segment): the provisional extraction writes each T024 segment on its own, with a fresh graph, its 6 context messages first (extracted, not scored) and the segment after (`eval/runner/probes/extract.py`, `segment_mode: context+segment`). Reason: cost; the LongMemEval-S segments sit in haystacks of about 50 sessions, and writing every prefix would cost the whole development histories for 578 scored messages; the segment-wise run made 132 calls. Effect measured on LoCoMo by scoring the T022 full-history Qwen3-8B run (same prompt, schema and writer config): loose precision 0.068–0.077 and recall 0.126–0.159 against 0.140–0.163 and 0.214–0.264 segment-wise; the full-history graph carries 10% catch-all claims (44 `felt`) against 1.3%. The segment-wise reading therefore overstates a full-history writer's graph quality; the formal E006 run should use full-history extraction at least for LoCoMo (both development histories are already written by any writer run) and decide for LongMemEval-S.
- 2026-11-28: provisional runs (not the formal E006 result): extraction `E006-20261128T001447Z-0046` (Qwen3-8B, T022 writer config, 40 segments, 132 calls, all schema-valid); score `E006-20261128T002604Z-514e`; comparison score `E006-20261128T002611Z-896e` of `T022-20261126T214758Z-613e`. Numbers in Results. Findings for the writer prompt round (E007): many conversational claims that the guideline excludes (`asks`, `askedAbout`, `contacted`, `expressedGratitude`, `feels`); speaker-as-subject claims where the gold describes an entity (`Caroline hasOrigin Sweden` for the necklace); `valid_from` never filled; 88 of 611 quotes do not anchor in the message text.
- 2026-11-28: not measurable or not done in this round: (1) the false-drop rate of the ending-evidence check: no gold ending stance exists in the 40 T024 segments (both agents), so all 10 drops on segment units are true drops by construction and the check's recall needs sequences with real endings (the controlled sequences); (2) the controlled sequences with gold graphs are not scored yet; (3) the separation of writer errors from planner (T023) and fragment-selection errors in graph-channel misses is not done (needs the retrieval traces of a T025-style run on the formal writer graph); (4) the answer-coverage upper bound. Contract note for the integration owner: a `score` run whose upstream is a `probe` run (writer-only extraction) is not in the stage table of contracts.md (Experiment run).
