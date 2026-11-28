---
id: D007
title: "Phase 1 gate: evidence placement"
created: 2026-11-23
---

# D007 · Phase 1 gate: evidence placement

## Context

The pilot measurements decide where the paper's claims can be supported (plan section 9, phase 1 checkpoint).

## Options

- Few MultiWOZ offer turns (T006): the primary evidence for the attribution-guard claim moves to the controlled sequences.
- Narrow spread of LoCoMo read points (T007): streaming moves to the supplementary material.
- Fragment coverage below one half (T012): lower the expectation for RQ1 on LoCoMo.
- The write budget cannot pay back on paper (T013): claim no token savings on LoCoMo.
- Missed change types are rare in natural dialogue (E002): RQ2 rests on the controlled sequences.

## Also recorded here

Phase 1 also chooses the second annotator (plan sections 9 and 11.4): a person not involved in building the system, who works on fragment coverage (T012), the MultiWOZ derived gold (T006), the sequence audit (T016) and graph quality (T024). The user names this person before the two-annotator part of T012 or T006 starts; the name, and whether the durations of plan section 9.4 match actual staffing, are written into the decision below.

Second annotator, named by the user: a graduate research assistant of the user, not involved in building the system. The name is added here when the annotator starts. Whether the durations of plan section 9.4 match this staffing is still open.

## Decision

Taken by the user on 2026-11-28: no checkpoint option is triggered and the benchmark placement of the plan stands, with these qualifications.

| Option | Evidence | Outcome |
| --- | --- | --- |
| Few MultiWOZ offer turns (T006) | Rule precision 173/200 = 86.5% on development turns; 995 of 1,149 test accept-or-reject turns after discounting; half-width 2.85 points at 70% accuracy (rule: 5) | Not triggered. MultiWOZ stays the primary evidence for the attribution-guard claim, the controlled sequences supporting evidence. The half-width would exceed 5 points only below n = 323, that is a rule precision below 28%. No separate claim about rejections (45 test turns). Whether the score reflects only a projection rule matching the annotation convention is answered by the planned controls (never-write-system-values rule, tagged hybrid retrieval; T028, T027) |
| Narrow spread of LoCoMo read points (T007) | Held-out share with v(q) < N 0.968 (threshold 0.5); median 29.5 distinct read points per history (5); median 579 tokens between adjacent read points (256); thresholds fixed on development data before held-out counting | Not triggered. LoCoMo streaming is in the main text |
| Fragment coverage below one half (T012) | 262/308 = 85.1% (Wilson 95% 80.7-88.6%) | Not triggered. Expectations for RQ1 on LoCoMo are not lowered; the paper states that coverage is an upper bound for the graph channel. The low graph-channel recall seen in the T022 smoke runs (R@20 about 0.1) is an extraction and retrieval question for D009, not a placement question |
| Write budget cannot pay back on paper (T013) | Per-message extraction never pays back; segment-8 and session extraction pay back for c above about 0.06-0.09; measured c 0.13 for warm LoCoMo reads (an upper bound) | Conditionally not triggered. Token savings on LoCoMo are claimed only for batched extraction (segments or sessions) and reported as a curve over c, not as one saving. T013 assumed the writer tokens; when E007 measures them, the break-even point is recomputed, and if the break-even c exceeds the measured c, no token savings are claimed on LoCoMo |
| Missed change types rare in natural dialogue (E002) | The change types citation-based dependencies miss are 99.1% (LoCoMo dev) and 97.3% (LongMemEval-S dev) of answer staleness (rule: below 10%) | Not triggered. RQ2 keeps its natural-dialogue evidence; per-type rates of this rough pass are unreliable and E009 repeats the measurement with the formal writer |

Staffing (also recorded here): the second annotator's planned work is the T006 re-annotation (200 turns), the T012 re-annotation (all 308 questions), the T016 sequence audit and the human review of the T024 merged file (6-10 hours). Deviation accepted by the user: plan 6.7 asks for two independent annotators on the 40 graph-quality segments; T024 instead uses two independent agent annotators followed by one human review of every disagreement and single-annotator claim, and reports agreement between the agents and between the agent merge and the human review. Two independent human annotations (23-34 hours) are not planned.

## Consequences

Fixes the benchmark placement that the lock (D012) freezes.

## Revisit when

A formal run contradicts a pilot number.

## Log

- 2026-11-23: proposed as part of the full project DAG.
- 2026-11-25: the choice of the second annotator is recorded in this decision (user, 2026-11-25); no separate node.
- 2026-11-25: the user named a graduate research assistant as the second annotator; the name is to be added when annotation starts.
- 2026-11-26: T012 first round recorded (in_fragment 262/308 = 85.1%, anonymous annotators, no human kappa; details in the T012 log): the fragment-coverage option is not triggered. User decision: a second group of annotators re-annotates after all other work is finished, with the second annotator labelling all 308 questions; annotators are recorded anonymously and label files are not committed.
- 2026-11-28: T006 first human check recorded (rule precision 173/200 = 86.5% on development turns, one anonymous annotator, no human kappa; details in the T006 log): with n discounted to 995 the half-width is 2.85 points, so the offer-turn option is not triggered. User decision: a second human annotator labels the same turns later and the two label sets are compared; if they differ widely, the analysis is repeated. All nodes this decision depends on are now resolved.
- 2026-11-28: decision taken by the user (see Decision): no option triggered, placement unchanged; LoCoMo token savings conditional on the E007 writer-token recomputation; T024 agent-plus-human-review deviation accepted.
- 2026-11-28: correction recorded by the integration owner (T028 evidence): the scorable paired-correctness items are fewer than the 1,149 accept-or-reject turns used above. On development data there are 492 items with an original constraint (half-width 4.05 points at 70% accuracy; 4.35 after the 86.6% rule-precision discount), so the decision stands. The conflict-only subset (204 items, half-width 6.3) is reported descriptively only. Test counts are not read before the T033 tag.
- 2026-11-28: condition on LoCoMo token savings resolved (user decision of the same day, on the E014 evidence): no token or compute savings are claimed on LoCoMo; the paper reports the cumulative cost curves and break-even points over c only. Evidence: compute-weighted GRACE does not pay back against cached full history at the measured c = 0.130 (conv-26 ends 14% higher; conv-49 crosses at read 154 of 156); in tokens it pays back only with cache credit for its Qwen3-8B calls measured on the Qwen3-32B server; quality is 0.017 F1 below cached full history.
