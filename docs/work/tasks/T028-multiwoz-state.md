---
id: T028
title: MultiWOZ state prediction and baselines
created: 2026-11-23
---

# T028 · MultiWOZ state prediction and baselines

## Goal

Everything specific to MultiWOZ (plan section 6.5): the projection from the claim graph to official slots, scoring of original-constraint retention and of paired correctness with the derived gold of T006, and the baselines: ReacTOD reproduced on Qwen3-8B, deterministic overwrite on official slots, the 'system values are not written' rule, and direct state output by the answering LLM.

## Scope

- In scope:
  - One prediction file is scored against 2.4, 2.2 and 2.1.
  - No look-ahead and no gold-state backfill.
- Out of scope: Any cost argument on MultiWOZ.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Scores of the reproduced ReacTOD are compared with its published 2.1 number and the gap is explained.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` MultiWOZ package.

## Notes (worker `w01-T028`)

Code:

- `src/grace/eval/engines/baselines/multiwoz.py`: slot rows; the projection policies `overwrite`, `user-only` and `guard`; the claim-graph projection `rows_from_graph` (predicate -> slot mapping, domain from the subject); the slot-row extractor (pinned `extract-slots` prompt over the 30 slots plus entity IDs).
- `src/grace/eval/engines/baselines/multiwoz_reactod.py` and `resources/prompts/reactod/`: the ReacTOD reproduction. The module docstring lists every choice the paper leaves open.
- `src/grace/eval/datasets/benchmarks/multiwoz_derived.py`: derived gold `2.4-current-choice` on top of the T006 offer rule: retention items on every post-offer turn and paired items, each with a conflict flag (definitions in the module docstring).
- `src/grace/eval/analysis/metrics/dst.py`: `retained`, `current_choice` (reads the predicted choice), `choice_correct`, `paired_correct`; `paired_correct_conflict` is `paired_correct` over the conflicting constraints only.
- `src/grace/cli/multiwoz.py`: `reactod` (system), `rows` (ingest), `project` (read), `score` (score); tests in `tests/unit/test_multiwoz_state.py`.

The current choice is not an official slot (train IDs). Predictions carry it in `metadata.current_choice`; where that key is missing, the scorer reads the domain's `-name` slot. The Prediction contract says the evaluator ignores `metadata`. A contract note and the scorer-registry entries are proposed in PR #149 but not written, because no user-approved owner of those sections took part (see the Log).

**Metric definitions (s00-super decision, 2026-11-28, PR #149).** These follow the wording of plan 6.5. Paired correctness is defined on turns that accept or reject an offer: an item is correct only if both the original constraint and the current choice are right. Plan 6.5 does not require the original constraint to conflict with the offer. The primary metric `paired_correct` therefore covers every accept/reject domain that has an offered entity and at least one original constraint. `paired_correct_conflict` keeps only the constraints that conflict with the offer; it is a descriptive diagnostic stratum. The same holds for retention: `retained` covers all post-offer items, with the conflict subset reported as stratum `conflict=true`. The first score runs (`…002433Z-8ed1`, `…002837Z-6f69`, `…002935Z-1c7a`, `…003032Z-990f`, `…003127Z-42a1`) used the earlier conflict-only definition and earlier names. They are superseded by the score runs below; no system was rerun.

Development results, 2026-11-28 (1,000 dev dialogues, 7,374 user turns, Qwen3-8B; score runs at `f2b57a2`). The derived gold has 795 offer turns in 602 dialogues. It holds 1,207 retention items (338 conflicting) and 492 paired items: train 198, hotel 114, restaurant 104, attraction 76; 473 accept, 19 reject. Of the paired items, 204 have a conflicting constraint (179 of them train). All values are percentages. The run files give 95% intervals from a dialogue-cluster bootstrap. The primary value matches exactly after normalisation; the lenient value uses the T006 `values_match` and is a sensitivity analysis.

| System (run; score run) | JGA 2.4 | JGA 2.2 | JGA 2.1 | JGA 2.1 lenient | `retained` (n=1,207) | `retained`, conflict=true (n=338) | `choice_correct` (n=492) | **`paired_correct`** (n=492) | `paired_correct`, lenient | `paired_correct_conflict` (n=204) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Direct state output, full history (E001 `full-cached`, 8 shards; `T028-20261128T004313Z-cbfb`) | 9.33 | 9.45 | 9.18 | 13.83 | 54.02 | 50.89 | 32.72 | 12.60 | 32.32 | 0.98 |
| ReacTOD (`T028-20261128T002229Z-888f`; `…004314Z-abf8`) | 23.22 | 24.38 | 24.26 | 28.98 | 74.07 | 85.50 | 12.80 | 8.13 | 17.89 | 2.94 |
| Deterministic overwrite on slot rows (`…002731Z-f427`; `…004314Z-188b`) | 16.90 | 17.51 | 16.73 | 19.72 | 59.90 | 36.69 | 33.33 | 16.67 | 34.15 | 2.94 |
| Never-write-system-values rule on slot rows (`…002744Z-bbe9`; `…004316Z-7d0f`) | 21.36 | 21.54 | 20.90 | 24.76 | 67.77 | 73.37 | 21.34 | 11.99 | 24.39 | 1.96 |
| Guard projection on slot rows (`…002756Z-7ff4`; `…004318Z-cfb3`) | 20.59 | 21.03 | 20.50 | 24.22 | 68.27 | 73.37 | 41.06 | 25.81 | 40.04 | 38.24 |

The slot rows come from ingest run `T028-20261128T002231Z-5bf7`: 14,748 messages, 183 failed extraction calls.

**ReacTOD and its published number.** ReacTOD reports 47.34 JGA on the MultiWOZ 2.1 test set. The reproduction reaches 24.26 exact and 28.98 lenient on 2.1 dev, a gap of about 18 to 23 points. The test-split comparison is open until the T033 tag exists. The gap breaks down from the run evidence as follows (diagnostic computations, not registered metrics):

1. **Label conventions (about 8 points).** The scorer matches exactly and applies no TRADE-style label fixes. ReacTOD's validator enforces the 2.2 enumerations, which differ from the 2.1 labels: `hotel-internet` and `hotel-parking` are `free` in the predictions where 2.1 says `yes` (965 and 762 wrong-value slots), and there are spelling and suffix variants (`french cuisine` / `french`, `worth house hotel` / `worth house`). Lenient matching adds 4.7 points. Mapping `free` to `yes` as well gives 32.49 on 2.1.
2. **Offered names (about 8 points).** 2.1 writes names the system offers and the user takes up; ReacTOD records only what the user says. Missing `hotel-name`, `restaurant-name` and `attraction-name` are the largest missing-slot classes (669, 640, 510). Ignoring the three name slots on top of item 1 gives 40.85.
3. **Turns classified `none`.** 2,145 of 7,374 turns (29%) end in the fallback intent and so make no update. Many of them are acceptances ("yes, book it"), which the paper's design passes to slot resolution through the previous system utterance. 110 turns hit the 6-call cap; 29% of turns had at least one validator correction (paper: 9.3%). Most corrections were `resolve_slots` called before `classify_intent` (1,522) and repeated `classify_intent` calls (776). The prompt wording is a reproduction choice; the paper publishes none.
4. **Split.** Dev against test. Dev JGA is usually close to test JGA for MultiWOZ, but that is not measured here.

The remaining distance, after items 1 and 2 are discounted, is about 6 points (40.85 against 47.34). The prompt and the unpublished normalisation are the likely causes; they are not separated further.

**Sample size.** The primary `paired_correct` has 492 dev items. At 70% accuracy the 95% half-width is 4.05 points; discounted by the human-checked T006 rule precision (86.6%, 426 effective items) it is 4.35 points. Both are below the 5-point threshold of plan 6.5. The conflict-only diagnostic (204 items, 176 after the discount) would give 6.29 and 6.77 points; it is reported descriptively only. Test counts were not computed, because the T033 tag does not exist.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-28: worker session `w01-T028` started on `task/T028-multiwoz-state` from `b7c62c3` (Issue #140, start comment posted). Development data only, because the T033 preregistration tag does not exist.
- 2026-11-28: code committed (`ef02d7b`, `e543f73`, `96270ef`). Formal dev runs: ReacTOD `T028-20261128T002229Z-888f` and slot rows `T028-20261128T002231Z-5bf7` at `e543f73`, the three projections and five score runs at `96270ef`, all `completed` with clean code. Direct state output is scored from the E001 `full-cached` runs (no new model calls). Results and the explanation of the ReacTOD gap are in the Notes above. The published-number comparison is done on dev only; the test comparison stays open.
- 2026-11-28: open: the scorer registry entries for retention and paired correctness (`configs/common/scorers.yaml`, Evaluation owner); the `metadata.current_choice` field (Prediction contract owner); the derived-gold item count (204 paired items on dev) against the 5-point threshold of plan 6.5 (user decision).
- 2026-11-28: s00-super decision on PR #149, following the wording of plan 6.5: the primary `paired_correct` covers every accept/reject domain with an offered entity and at least one original constraint (dev n=492); the conflict-only variant becomes the diagnostic `paired_correct_conflict` (n=204); `retained` covers all post-offer items (n=1,207), with stratum `conflict=true` (n=338). Code `f2b57a2` (after merging `origin/main`). The five score runs were rerun without model calls: `T028-20261128T004313Z-cbfb` (direct state output), `…004314Z-abf8` (ReacTOD), `…004314Z-188b` (overwrite), `…004316Z-7d0f` (never-write), `…004318Z-cfb3` (guard). They supersede the first score runs. Half-width of `paired_correct` at 70%: 4.05 points raw, 4.35 discounted by the 86.6% rule precision.
- 2026-11-28: s00-super asked for the registry entries (`configs/common/scorers.yaml`) and a Prediction-contract note on `metadata.current_choice`, acting as owner of both sections. The edit to `docs/research/contracts.md` was refused by the session's permission check: an agent's message is not the user's written assignment of ownership. The registry edit was withdrawn for the same reason. Both texts are proposed in the PR; they wait for the owners (T004, T001) or a written user decision.
- 2026-11-28: recorded done with a remark by the integration owner (s00-super): PR #149 merged. Decisions of the same day: the primary paired metric follows plan 6.5 (all accept-or-reject items with an original constraint, dev n = 492; the conflict-only variant, n = 204, is a descriptive stratum), scored with the lenient T006 `values_match` rule (exact match as sensitivity). Open: registration of the MultiWOZ metrics in `configs/common/scorers.yaml` and the Prediction-contract note on `metadata.current_choice` (drafts in the PR #149 body) await the user's direct approval; the ReacTOD test-split comparison waits for the T033 tag.
- 2026-11-28: code follow-up (branch `task/T028-lenient-primary`): the score command now computes the primary `retained`, `choice_correct`, `paired_correct` and `paired_correct_conflict` with the T006 `values_match` rule, as registered in `configs/common/scorers.yaml`; exact match after `normalise_state` is reported under the sensitivity keys `retained-exact`, `choice_correct-exact`, `paired_correct-exact` and `paired_correct_conflict-exact` (the former `-lenient` keys are gone; `jga-lenient|2.1` is unchanged). No rescore; earlier score runs carry the old key names.
