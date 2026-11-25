---
id: D002
title: Evaluation aggregation
created: 2026-11-21
---

# D002 · Evaluation aggregation

## Context

Six benchmarks are evaluated: the controlled change sequences, MultiWOZ, LoCoMo, LongMemEval-S, HaluMem-Medium and MemoryAgentBench. Their metrics are JGA and slot F1, token-F1, judged accuracy and normalised set match. Their roles differ: core, adverse setting, targeted diagnostic or optional (plan 6.3). Each research question names its own primary evidence (plan 6.6).

The current plan and contracts already fix three things:

- Plan 6.7: each benchmark keeps its native metrics and also reports a unified blind-judge accuracy.
- Plan 6.9: question-level paired tests with history as a random effect, the clustering unit per benchmark, small subsets descriptive only, and uncertainty reported by source.
- The Evaluation contract: every metric is registered in `configs/common/scorers.yaml`, and multi-seed runs are summarised as mean, standard deviation and number of runs.

Six things were open:

1. Whether there is a score across benchmarks.
2. Whether the point estimate is a micro or a macro mean.
3. How the overall value relates to the strata.
4. How several annotations are reported.
5. How missing values are handled.
6. How intervals are computed.

## Options

| Question | Options | Considerations |
| --- | --- | --- |
| 1. Cross-benchmark score | A: none, report per benchmark. B: none in the main text, plus a preregistered summary in the supplementary material, such as equal-weight relative change against the full-history baseline or win/tie/loss counts under the margins. C: a weighted overall score in the main text | Under B and C the result depends on the weights. Under C no claim of the paper rests on the score. A matches the plan, where each research question has its own evidence |
| 2. Point estimate | Micro mean over reads; macro mean of cluster means | Micro follows each benchmark's official convention, so results compare with the literature. The two barely differ on LoCoMo (about 150 questions per history) and LongMemEval (one question per history). They do differ on MultiWOZ dialogues and on controlled-sequence families |
| 3. Overall versus strata | Pool all reads; mean of strata | Pooling matches the official metrics. A mean of strata gives small strata the weight of large ones |
| 4. Annotations | Separate; combined | The MultiWOZ annotations differ in convention, so combining them would hide the agreement-with-convention effect (plan 6.5) |
| 5. Missing values | `invalid` counted as wrong or excluded; failed runs imputed or left empty | Excluding invalid outputs rewards a system that fails to answer. Imputation invents results |
| 6. Intervals | Cluster bootstrap; per-question normal intervals | Questions within a history are correlated. Plan 6.9 names the clustering units |

## Decision

Taken by the user: option A for question 1, and the recommended options for questions 2 to 6.

- **No cross-benchmark score**, in the main text or the supplementary material. Results are reported per benchmark.
- **Point estimate:** the micro mean over the reads of the population (questions, or turns for MultiWOZ). The macro mean of cluster means is a supplementary sensitivity analysis where clusters differ in size.
- **Strata:** the overall value pools all reads. Strata are reported separately. A stratum with fewer than 100 reads is descriptive only (plan 6.9: 96, about 62 and 30).
- **Annotations:** reported separately and never combined. MultiWOZ 2.4 is the main annotation; 2.2 and 2.1 are reported alongside.
- **Missing values:**
  - `invalid` is counted as wrong for every registered metric (`count_as_wrong`);
  - `unknown` follows each benchmark's abstention rule;
  - a failed run leaves its cell empty with the reason, and nothing is imputed;
  - denominators are always shown.
- **Uncertainty:** 95% percentile cluster-bootstrap intervals (10,000 resamples) over the clustering unit of plan 6.9, paired for differences between systems. Tests follow plan 6.9. Judge reruns are reported as mean, sample standard deviation and number of runs.

## Consequences

- `docs/research/contracts.md`, Evaluation section v0.3, gains an "Aggregation" subsection.
- `configs/common/scorers.yaml` gains an `aggregation` block and a `cluster_unit` per benchmark. `tests/contracts/test_aggregation.py` checks them.
- Reporting code (T035, T036) implements the cluster bootstrap and the macro sensitivity analysis.
- The preregistration (T033) copies these rules.

## Revisit when

- The benchmark set or a registered metric changes.
- A reviewer or venue requires a single summary score. It would then be added as a supplementary, preregistered summary (option B), never in place of the per-benchmark results.

## Log

- 2026-11-21: proposed (needs project confirmation).
- 2026-11-25: rewritten against the revised plan (sections 6.3, 6.6, 6.7 and 6.9) and the Evaluation contract v0.2. Six questions and their options were summarised. The user chose option A and the recommended rules, with invalid outputs counted as wrong.
