# MultiWOZ offer-turn census (T006)

Task: `docs/work/tasks/T006-multiwoz-offer-turns.md`. Plan: section 6.5 (MultiWOZ) and section 9, phase 1.

This census is a deterministic, model-free count of annotations. It runs no model. It reads the dialogue acts and dialogue states of MultiWOZ 2.1, 2.2 and 2.4. On the test set it writes no utterance text.

## Evidence

| Split | Run ID | Code SHA | Command |
| --- | --- | --- | --- |
| test (`held-out`) | `T006-20261125T010248Z-25f5` | `8780c2f4139ed0a950bce8328fde5e98a4430467` | `scripts/multiwoz-offer-census.sh --split held-out --allow-held-out-annotations` |
| validation (`dev`) | `T006-20261125T010238Z-7565` | `8780c2f4139ed0a950bce8328fde5e98a4430467` | `scripts/multiwoz-offer-census.sh --split dev` |

- Run directories: `$PROJECT_ROOT/runs/T006/artifacts/census/<run-id>/`. Each holds `run.json`, `resolved-config.yaml`, `run.log`, `census.json`, `turns.jsonl`, `act_files.json` and `report.yaml`.
- Both runs are `completed` with `code_dirty: false`.
- The runs verified the manifests named in `configs/benchmarks/multiwoz.yaml`: 2.4 `78ca9c26…fc35`, 2.2 `7916a2aa…d49c`, 2.1 `553f662f…3d17`.
- The split sizes match the config: test has 1,000 dialogues and 7,372 user turns; dev has 1,000 dialogues and 7,374 user turns.
- Two earlier runs at `e771234` (`T006-20261125T010134Z-8d26` on test, `T006-20261125T010124Z-cd8a` on dev) have identical counts. Only the dev check sample changed afterwards: utterance tabs now stay out of the TSV.
- Runs under `runs/T006/artifacts/scratch/` were made with uncommitted code during development and are not evidence.
- Code:
  - rule and census: `src/grace/eval/datasets/benchmarks/multiwoz_offers.py`
  - entry point: `src/grace/cli/data/multiwoz_offers.py`
  - Bash wrapper: `scripts/multiwoz-offer-census.sh`
  - tests: `tests/unit/test_multiwoz_offers.py`

### Held-out access

The task file names the test set. The census does not use `load_split`, which refuses held-out splits until the T033 preregistration tag exists. It reads the annotation files directly, and only after the explicit flag `--allow-held-out-annotations`; `run.json` records that flag. Held-out outputs contain IDs, acts, slot values and counts, never utterance text. The manual check uses development turns only (see below).

## Identification rule

The rule is stated in full in the module docstring. In short:

- **Offer.** A system turn offers something in domain `d` when its acts include any of:
  - `d-Recommend`, `d-Select` or `d-OfferBook`;
  - `Booking-Inform`, assigned to the active domain;
  - a `d-Inform` naming an entity (`name`, or train `trainid`) that neither speaker has named before.

  The offered values are the slot–value pairs of those acts.
- **Response** of the next user turn, read from its acts:
  - `reject`: the user informs a value for an offered slot that matches no offered value (`dontcare` does not count as a rejection).
  - `accept`, explicit: the user repeats an offered value, or gives booking details in `d`.
  - `accept`, implicit: the user requests an attribute of a proposed entity, or the booking reference.
  - `none`: anything else.
- **Act source.** 2.4 keeps system acts only. Its `dialogue_acts.json` equals the 2.1 system acts on 7,175 of the 7,372 test system turns after normalisation. The 2.1 acts are therefore the primary act source for 2.1 and 2.4. The 2.2 acts are a second act source, reported as a sensitivity check.
- **State comparison.** Per version, an offered slot (one of the 30 evaluated slots) is `offered`, `other` or `unset` after the user turn. It is `new` when it was not `offered` after the previous user turn. Values are compared leniently (`values_match`: articles, punctuation, plural and spacing variants, times, token coverage, near-identical spellings). Exact string agreement is reported as well.

## Which version files keep dialogue acts

These are test-split counts (`act_files.json`). Dev counts are similar.

| File | User turns with acts | System turns with acts |
| --- | --- | --- |
| 2.4 `data.json` (`dialog_act`) | 0 | 0 |
| 2.4 `dialogue_acts.json` | 0 (system turns only) | 7,291 / 7,372 |
| 2.1 `data.json` (`dialog_act`) | 6,701 / 7,372 | 7,293 / 7,372 |
| 2.2 `dialog_acts.json` | 7,258 / 7,372 | 7,355 / 7,372 |
| 2.2 dialogues (`frames[].actions`) | 0 | 0 |

User-side acts exist only in 2.1 and 2.2. The derived "current choice" gold must therefore read user acts from 2.1 or 2.2, even when scoring against 2.4.

## Counts (test set)

**Offer turns.** With 2.1 acts, 2,022 user turns (in 910 dialogues) follow a system offer. Responses:

- 1,104 accept: 644 explicit, 460 implicit;
- 45 reject;
- 873 none.

That gives **1,149 accept-or-reject turns** in 784 dialogues. With 2.2 acts the figures are 2,052 offer turns, 1,218 accept, 49 reject and 1,267 accept-or-reject turns.

| Domain (2.1 acts) | Offers | Accept | Reject | None |
| --- | --- | --- | --- | --- |
| attraction | 407 | 226 | 7 | 174 |
| hotel | 559 | 260 | 20 | 279 |
| restaurant | 516 | 320 | 11 | 185 |
| train | 546 | 298 | 7 | 241 |
| taxi | 0 | 0 | 0 | 0 |

- A turn with offers in two domains is counted once in each domain.
- Taxi has no offers: taxi turns carry no Recommend, Select or OfferBook acts and no entity name.
- Per-slot counts, and the offer kinds (recommend 430, select 253, offerbook 375, booking-inform 557, inform-entity 977), are in `census.json` under `by_slot` and `offer_kinds`.

## Does "2.2 writes system-offered values into the state, 2.4 does not" hold?

**No, not in general.** The comparison covers offered (turn, slot) pairs whose offered value newly enters the 2.2 or the 2.4 state after the user turn (test, 2.1 acts, 932 pairs):

| | Pairs | Share |
| --- | --- | --- |
| Offered value in both 2.2 and 2.4 | 611 | 65.6% |
| Only in 2.2 (2.4 unset 98, other 50) | 148 | 15.9% |
| Only in 2.4 (2.2 unset 165, other 8) | 173 | 18.6% |

- In most cases both versions write the offered value.
- Where they differ, 2.4 holds the offered value about as often as 2.2 does: slightly more often on the test set, and clearly more often on dev (247 against 94).
- The same holds on accepted turns alone: 491 both, 85 only 2.2, 117 only 2.4.
- The plan's sentence should therefore not enter the paper as a general fact. A defensible wording: "2.2 and 2.4 disagree on the offered slot in about a fifth of accept/reject offer turns, in both directions."

**Disagreement share.** Of the 963 accept-or-reject test turns that have at least one offered slot among the 30 evaluated slots, 2.2 and 2.4 disagree on an offered slot's value in:

- **209 turns (21.7%)** under the lenient match;
- 253 turns (26.3%) under exact string match.

By domain (lenient): attraction 28.1%, hotel 24.3%, restaurant 18.3%, train 17.0%. On dev the share is 25.5% lenient and 30.2% exact.

## Precision of the rule (manual check)

**Status: checked by the agent session `m01-T006`, pending human confirmation.** The precision below is not human-verified. Human confirmation is done by the second annotator the user names under decision D007 (`docs/work/decisions/D007-gate-evidence-placement.md`, "Also recorded here"), before the two-annotator part of T006 starts.

- **Sample.** 60 identified dev turns, drawn by seeded stratification (seed 6): 30 labelled accept, 30 labelled reject. The sample comes from the development split so that no test utterance is read. The rule is the same on both splits.
- **Criterion.** A label is correct when the system turn makes an offer the user can take up, and the user's turn takes it up (accept) or turns it down (reject). When a turn declines part of an offer, an `accept` label counts as incorrect.
- **Result.** 28/30 accept labels and 28/30 reject labels are correct: 56/60 = **93.3%**. Accept dominates the counts (96% of accept-or-reject turns), so the prevalence-weighted precision is also 93.3%.
- **Errors.**
  - Two booking offers that the user declined while asking about the entity were labelled accept.
  - One offer to "look for a different kind" that the user accepted by naming a type was labelled reject.
  - One act-annotation slip (`bookday=6`) was labelled reject.
- **Files.**
  - `docs/research/multiwoz-offer-turns-check.tsv` (tracked): turn ID, label, offer kinds, verdict and note; no utterance text.
  - `$PROJECT_ROOT/runs/T006/artifacts/manual-check/check_sample_verdicts.tsv`: the same rows with the three-turn context, offered values and act evidence, for a human to re-check.
- **Not done here.** Plan 6.5 asks for two annotators on 200 turns with Cohen's κ for the derivation rule. This check covers 60 turns by one (agent) checker and gives no κ. That part waits for the D007 annotator.

## Interval width and recommendation (plan 6.5)

- **Rule.** At 70% accuracy, the 95% interval half-width is $1.96\sqrt{0.21/n}$. Plan 6.5 moves the primary evidence to the controlled sequences when the half-width exceeds 5 points, that is when $n < 323$.
- **Primary count.** With $n = 1{,}149$ test accept-or-reject turns (2.1 acts), the half-width is **2.65 points**. With 2.2 acts ($n = 1{,}267$) it is 2.52 points.
- **Conservative variants:**

  | Variant | n | Half-width (points) |
  | --- | --- | --- |
  | Discounted by the measured precision | 1,072 | 2.74 |
  | One item per dialogue | 784 | 3.21 |
  | Accept turns only | 1,104 | 2.70 |
  | **Reject turns only** | **45** | **13.4** |

- **Recommendation.** MultiWOZ offer turns **remain the primary evidence** for the attribution-guard claim of RQ1 (`census.json` still says "role claim", the wording at run time) on accept-or-reject turns taken together. Every variant stays below 5 points except the reject-only slice. Rejections are too rare (45 test turns) to support any separate claim about rejection; that slice should be reported descriptively, with the controlled sequences carrying the rejection cases.

## Limitations

- Rejections are found only through a counter-value. A plain "no" without a new value is classed `none`. The reject count is therefore a lower bound.
- Turns without acts cannot be classified. In 2.1, 79 of 7,372 test system turns (1.1%) and 671 user turns (9.1%) carry no acts.
- Lenient matching can merge distinct values that share tokens. Exact-match figures are given for the 2.2/2.4 comparison.
- Implicit acceptance (asking about the proposed entity) is the weakest part of the rule. Both errors among the accept labels come from it. The derived-gold rule of plan 6.5 may want to require explicit acceptance; that gives 644 test turns and a half-width of 3.5 points.

## Requested MultiWOZ card fields

The requested fields for `docs/research/benchmarks.md#multiwoz` go to the data owner in the T006 PR, not into the card directly.
