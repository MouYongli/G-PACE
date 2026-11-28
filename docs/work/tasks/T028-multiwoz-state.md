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
- `src/grace/eval/datasets/benchmarks/multiwoz_derived.py`: derived gold `2.4-current-choice` on top of the T006 offer rule: retention items, paired items and broad paired items (definitions in the module docstring).
- `src/grace/eval/analysis/metrics/dst.py`: `retained`, `current_choice`, `choice_correct`, `paired_correct`.
- `src/grace/cli/multiwoz.py`: `reactod` (system), `rows` (ingest), `project` (read), `score` (score); tests in `tests/unit/test_multiwoz_state.py`.

The current choice is not an official slot (train IDs). Predictions carry it in `metadata.current_choice`; where that key is missing, the scorer reads the domain's `-name` slot. The Prediction contract says the evaluator ignores `metadata`. This needs a decision by the contract owner (see the PR).

Development results, 2026-11-28 (1,000 dev dialogues, 7,374 user turns, Qwen3-8B). The derived gold has 338 retention items on 328 turns, 204 paired items (179 train) and 492 broad paired items. Values are percentages with 95% dialogue-cluster bootstrap intervals in the run files.

| System (run) | JGA 2.4 | JGA 2.2 | JGA 2.1 | JGA 2.1 lenient | Retention | Paired (lenient) | Paired broad (lenient) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Direct state output, full history (E001 `full-cached`, 8 shards; score `T028-20261128T002433Z-8ed1`) | 9.33 | 9.45 | 9.18 | 13.83 | 50.89 | 1.96 | 32.32 |
| ReacTOD (`T028-20261128T002229Z-888f`; score `…002837Z-6f69`) | 23.22 | 24.38 | 24.26 | 28.98 | 85.50 | 3.43 | 17.89 |
| Deterministic overwrite on slot rows (`…002731Z-f427`; score `…002935Z-1c7a`) | 16.90 | 17.51 | 16.73 | 19.72 | 36.69 | 3.43 | 34.15 |
| Never-write-system-values rule on slot rows (`…002744Z-bbe9`; score `…003032Z-990f`) | 21.36 | 21.54 | 20.90 | 24.76 | 73.37 | 2.45 | 24.39 |
| Guard projection on slot rows (`…002756Z-7ff4`; score `…003127Z-42a1`) | 20.59 | 21.03 | 20.50 | 24.22 | 73.37 | 42.16 | 40.04 |

The slot rows come from ingest run `T028-20261128T002231Z-5bf7`: 14,748 messages, 183 failed extraction calls.

**ReacTOD and its published number.** ReacTOD reports 47.34 JGA on the MultiWOZ 2.1 test set. The reproduction reaches 24.26 exact and 28.98 lenient on 2.1 dev, a gap of about 18 to 23 points. The test-split comparison is open until the T033 tag exists. The gap breaks down from the run evidence as follows (diagnostic computations, not registered metrics):

1. **Label conventions (about 8 points).** The scorer matches exactly and applies no TRADE-style label fixes. ReacTOD's validator enforces the 2.2 enumerations, which differ from the 2.1 labels: `hotel-internet` and `hotel-parking` are `free` in the predictions where 2.1 says `yes` (965 and 762 wrong-value slots), and there are spelling and suffix variants (`french cuisine` / `french`, `worth house hotel` / `worth house`). Lenient matching adds 4.7 points. Mapping `free` to `yes` as well gives 32.49 on 2.1.
2. **Offered names (about 8 points).** 2.1 writes names the system offers and the user takes up; ReacTOD records only what the user says. Missing `hotel-name`, `restaurant-name` and `attraction-name` are the largest missing-slot classes (669, 640, 510). Ignoring the three name slots on top of item 1 gives 40.85.
3. **Turns classified `none`.** 2,145 of 7,374 turns (29%) end in the fallback intent and so make no update. Many of them are acceptances ("yes, book it"), which the paper's design passes to slot resolution through the previous system utterance. 110 turns hit the 6-call cap; 29% of turns had at least one validator correction (paper: 9.3%). Most corrections were `resolve_slots` called before `classify_intent` (1,522) and repeated `classify_intent` calls (776). The prompt wording is a reproduction choice; the paper publishes none.
4. **Split.** Dev against test. Dev JGA is usually close to test JGA for MultiWOZ, but that is not measured here.

The remaining distance, after items 1 and 2 are discounted, is about 6 points (40.85 against 47.34). The prompt and the unpublished normalisation are the likely causes; they are not separated further.

**Derived gold and sample size (serious).** On dev, a paired item needs an original constraint that conflicts with the offer. Only 204 accept/reject domain items qualify, 179 of them train, against 1,149 accept-or-reject test turns in the T006 census. At 70% accuracy, 204 items give a 95% half-width of about 6.3 points, above the 5-point threshold of plan 6.5. If the test split is similar, MultiWOZ paired correctness would become supporting evidence (D007 option) unless the broad variant (492 items, half-width about 4.0 points) is chosen. That choice belongs to the user, not to this task.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-28: worker session `w01-T028` started on `task/T028-multiwoz-state` from `b7c62c3` (Issue #140, start comment posted). Development data only, because the T033 preregistration tag does not exist.
- 2026-11-28: code committed (`ef02d7b`, `e543f73`, `96270ef`). Formal dev runs: ReacTOD `T028-20261128T002229Z-888f` and slot rows `T028-20261128T002231Z-5bf7` at `e543f73`, the three projections and five score runs at `96270ef`, all `completed` with clean code. Direct state output is scored from the E001 `full-cached` runs (no new model calls). Results and the explanation of the ReacTOD gap are in the Notes above. The published-number comparison is done on dev only; the test comparison stays open.
- 2026-11-28: open: the scorer registry entries for retention and paired correctness (`configs/common/scorers.yaml`, Evaluation owner); the `metadata.current_choice` field (Prediction contract owner); the derived-gold item count (204 paired items on dev) against the 5-point threshold of plan 6.5 (user decision).
