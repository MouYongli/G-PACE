# Sequence Audit Annotation Guideline

This guideline is for task T016 (plan section 6.4, "Validity"): two annotators judge, message by message, whether the rendered text of the controlled change sequences says what the event log says. The protocol is fixed in `docs/research/change-sequences.md` section 8; this file is its working guide. The adjudicated mismatch rate is the label-noise estimate of the controlled sequences (plan section 6.9). Only development families are audited before the T033 preregistration tag; reading held-out text in the audit is allowed by design section 8 but is not part of this round.

Files (all under `docs/research/annotations/sequence-audit/`):

| File | Content |
| --- | --- |
| `sample.json` | The sample record: seed, dataset run, manifest checksum, chosen sequences, windows and questions |
| `sheet.csv` | The blank annotation sheet: one row per message or question, readable events next to the text, empty annotator columns (section 7) |
| `labels-<annotator>.csv` | One label file per annotator (section 7) |
| `labels-agent-m01-T016.csv` | A first-pass pre-annotation by the manager agent of T016. It is **not a human annotator** and is never one of the two annotators of plan 6.4 |

Code: `src/grace/eval/analysis/annotation/sequence_sheet.py` (sample and sheet) and `src/grace/eval/analysis/annotation/sequence.py` (label files, mismatch rates, kappa). Entry point: `uv run python -m grace.cli.annotate.sequence` (section 8).

## 1. Sample

The sample is drawn from the model-rendered development dataset `T015-devmodel-20261125T192037Z` (generator `changeseq-generator-2`, renderer Mistral Small 3.2 24B at a pinned snapshot; `docs/work/tasks/T015-change-sequence-generator.md`). The draw is a pure function of that dataset and the seed string `T016-audit-v1`; every seeded choice orders candidates by the SHA-256 of `T016-audit-v1:<purpose>:<key>`. The builder checks every file against the dataset's `MANIFEST.sha256` and refuses any sequence whose split is not `development`.

- **Sequences.** Per development family, 5 sequences, stratified over revision density (one per density level in seeded order, then the rest). The dataset holds exactly 5 per family (densities 1, 3, 10, 10 and 30), so every development sequence is in the sample.
- **Windows.** Per sequence one audit window of 30 consecutive messages after the setup episode (seeded start). The 10 preceding messages are shown as read-only context (`part = context`) and take no label.
- **Questions.** At most 5 questions of the sequence's primary schedule (`A20d1` for density 10, `U10` otherwise) whose read version lies inside the window, chosen in seeded order; both members of a known-then / seen-from-now pair are always taken together.
- **Pilot.** Two calibration windows (`part = pilot`) in sequences of two different families, placed so that they and their context do not overlap the audit window or its context. Pilot labels are discussed during calibration and never counted.

Result: 5 families × 5 windows = 25 audit windows, 750 audit messages and 121 audit questions, plus 2 pilot windows (60 messages, 7 questions) and 270 context messages.

## 2. What is judged

For each message: **does the text express exactly the events of that message, no more and no less?** Judge against the `events` and `cue` columns of the same row, with the earlier messages of the window as context. Do not judge whether the dialogue world is plausible (section 5, T9), and do not use knowledge of later messages.

For each question: **is the gold answer right for the question as worded, given the text the system will have read up to the read version?**

## 3. Reading the sheet

| Column | Content |
| --- | --- |
| `item_id` | `<sequence_id>:<message_id>` or `<sequence_id>:<question_id>` |
| `kind`, `part`, `window` | `message` or `question`; `context`, `pilot` or `audit`; the window ID |
| `family`, `sequence_id`, `density` | Scenario family, sequence, revision density level |
| `version`, `episode`, `date`, `speaker` | Message version (for a question: its read version), episode, episode date, speaker |
| `text` | The rendered message, or the question text |
| `events` | The message's events in readable form (below); `(none)` for fillers |
| `cue` | The macro (name, intended change type, focus binding), the values the text must mention, the old values it may mention, and the required discourse signal |
| `skeleton` | The dialogue skeleton of the message (for a question: its type) |
| `gold` | Questions only: type, template and binding, gold answer, expected abstention, outdated values, premise flag, pair, world time, knowledge version and anchor message, and the evidence messages quoted in full |
| `annotator`, `label`, `subclass`, `note` | Filled by the annotator (section 7) |

Event notation, one event per `||`:

- `NEW c8 (user, worksIn, journalism) valid from 2026-03-04 [user: inform, own, positive]`: a new claim with its proposition, valid time if any, and the speaker's stance (communicative function, report mode, polarity).
- `ON c4 (Anouk, worksIn, catering) [assistant: inform, own, positive, restatement]`: a stance on an existing claim; `restatement` marks an assistant restatement (`derived`).
- `SUPERSEDE c2 (user, worksIn, education) as change, replaced by c8`: the claim is no longer current, by a real change or by a correction; `no replacement` marks a removal.

Report modes: `own` (the speaker asserts it), `quote` (the speaker reports what someone else said), `hypothetical` ("what if"). Functions: `inform`, `confirm`, `request` (a constraint of a booking), `offer` (the assistant proposes an item), `accept`, `reject`. Catalogue items appear by their ID (for example `apt-am-anger-3`); the `cue` gives their surface name.

## 4. Labels

**Messages.** Exactly one `label` per message (design section 8):

| Label | Meaning | Optional `subclass` |
| --- | --- | --- |
| `agree` | The text expresses the events and nothing else about the family's state | |
| `missing` | An event is not expressed: a claim, a stance, or a supersession is absent or too vague to recover | `partial` (some events of the message are expressed, others are not) |
| `extra` | The text expresses a state proposition that is not in the events: additional or contradicting content, state content in a filler, or a later event announced early | `filler-state`, `contradiction`, `foreshadowing` |
| `wrong-value` | The proposition is expressed with a different value, entity or item, or with an alias that does not identify the value | `alias` |
| `wrong-attribution` | Speaker, communicative function, report mode or polarity differs (for example an offer rendered as a booking, a hypothetical rendered as a statement) | `speaker`, `function`, `report-mode`, `polarity` |
| `wrong-time` | The valid time is wrong, a change is rendered as a correction or the reverse, or a change or correction lacks the discourse signal that the cue requires | `valid-time`, `swapped-kind`, `missing-signal` |
| `unnatural` | Meaning right, English unacceptable (for example a reply that responds to nothing). Reported, not counted as a mismatch | |

The five labels from `missing` to `wrong-time` are mismatches; `agree` and `unnatural` are not. The kinds of mismatch named in the T016 assignment map onto these labels as follows: missing event → `missing`; extra or contradicting content → `extra` (`contradiction` when it contradicts the state); wrong value or alias → `wrong-value` (`alias`); missing discourse signal for a correction or change → `wrong-time` (`missing-signal`); foreshadowing → `extra` (`foreshadowing`). The subclass is optional; it helps the T015 fix but does not enter kappa.

**Precedence.** If several labels apply, take the first in the order `missing`, `wrong-value`, `wrong-attribution`, `wrong-time`, `extra`, `unnatural`, and name the others in `note`.

**Questions.** Exactly one `label` per question:

| Label | Meaning |
| --- | --- |
| `agree` | The gold answer is right for the question as worded, given the text up to the read version |
| `gold-wrong` | The text supports a different answer (or no answer where gold has one, or the reverse) |
| `ambiguous` | The question or the text it depends on admits more than one reading, and the gold picks one of them |
| `anchor-unidentifiable` | A known-then question names an anchor event (an offer, a booking) that does not identify one earlier message uniquely |

## 5. Tie rules

- **T1. Paraphrase is fine.** The text need not repeat the template sentence. "I'm in architecture" expresses `(user, worksIn, architecture)`. Required values must be recognisable; a listed alias counts as the value.
- **T2. Mentions.** A stance on an existing claim (`ON`) is expressed by restating the proposition. Discourse fillers such as "Oh, and", "As I mentioned", "Yep" or "By the way" do not change the label. `confirm` and `inform` on an existing claim are not distinguished: a plain restatement agrees with either.
- **T3. "Actually" and similar markers.** A correction marker ("actually", "my mistake", "I meant") on a message whose events contain no supersession is `extra` / `contradiction` only when it implies that a current value is wrong or replaced (for example "Actually, I'm vegan" right after "I follow a pescatarian diet", when both stay current). When the stated value is already the current one, it is `agree`.
- **T4. Past-dated statements.** A past interval must keep the meaning of the predicate: "I lived in Bremen from 2012 to 2016" expresses `livesIn`; "I was in Bremen from 2 to 4 June" describes a stay, not a residence, and is `missing` (the `livesIn` claim is not expressed). The same holds for `homeAirport` ("I was at Cologne Bonn Airport from 4 to 6 February", or "I flew out of X from 14 to 15 May" for a one-day interval). Dates without a year are fine when the episode date makes the year clear.
- **T5. Changes and corrections.** A change must signal that the state changed ("now", "moved", "switched", "no longer", "used to"). A correction must signal that an earlier statement was wrong ("my mistake", "I got that wrong", "I meant"). A correction rendered as a change or the reverse is `wrong-time` / `swapped-kind`; no signal at all is `wrong-time` / `missing-signal`. Naming the old value is allowed (`may mention`) but not required.
- **T6. Non-endorsing frames.** Quotes ("A friend says …") and hypotheticals ("What if …") must keep the frame. A quote or hypothetical rendered as the speaker's own assertion is `wrong-attribution` / `report-mode`.
- **T7. Offers, acceptances and rejections.** An offer must propose the item for the named booking and state its catalogue value (time); an offer worded as if already booked is `wrong-attribution` / `function`. An acceptance must accept the named item; a rejection must reject it.
- **T8. Fillers.** A filler must express no proposition about a predicate of the family. Small talk that reacts to the topic without stating or asking about state ("That's quite the career change!") is `agree`. A filler that states or asks about family state ("How long has she been working there?", "I've been practising my Spanish") is `extra` / `filler-state`. A filler that responds to nothing ("You're right" with nothing to agree with) is `unnatural`.
- **T9. The world is not audited.** Overlapping intervals, a two-day job or several moves within a month come from the generator's world model, not from the renderer. If the text matches the events, the label is `agree`; record the oddity in `note`.
- **T10. Questions depend on their evidence.** A question whose gold answer rests on a message that does not express its event (for example a past-dated stay under T4) is `ambiguous` (or `gold-wrong` if the text clearly supports another answer). A known-then question whose anchor event occurred more than once is `anchor-unidentifiable`.

## 6. Worked examples

Examples 1 to 3 are taken from development messages outside the audit and pilot windows; examples 4 to 10 are constructed for this guide.

| # | Text | Events (and cue) | Label |
| --- | --- | --- | --- |
| 1 | "I used to work in education, but now I'm in journalism." (`apartment-search-rho10-L200-000:m0023`) | `NEW (user, worksIn, journalism)`, `SUPERSEDE (user, worksIn, education) as change`; must signal a change | `agree`: change signalled by "used to … now" |
| 2 | "I was in Nuremberg from 13 November 2025 until 16 November 2025." (`car-rental-rho3-L200-000:m0045`) | `NEW (user, livesIn, Nuremberg) valid 2025-11-13 to 2025-11-16` | `missing`: a three-day stay; residence is not expressed (T4) |
| 3 | "Oh, I got that wrong again! Yuki actually flies out of Berlin Airport now, not Stuttgart." (`flight-travel-rho10-L200-001:m0028`) | `NEW (Yuki, homeAirport, Berlin Airport)`, `SUPERSEDE (…, Stuttgart Airport) as change`; must signal a change | `wrong-time` / `swapped-kind`: "I got that wrong" marks a correction (T5) |
| 4 | "I work in architecture." | `NEW (user, worksIn, architecture)`, `SUPERSEDE (user, worksIn, journalism) as correction`; must signal an earlier statement was wrong | `wrong-time` / `missing-signal` |
| 5 | "I live in Bremen now." | `NEW (user, livesIn, Bremen) [user: inform, hypothetical, positive]` | `wrong-attribution` / `report-mode`: the hypothetical frame is lost (T6) |
| 6 | "I've booked the Opel Astra for you, pickup at 12:05." | `NEW (k1, selectedService, car-astra) [assistant: offer]`, `NEW (car-astra, pickupTime, 12:05)` | `wrong-attribution` / `function`: an offer rendered as a booking (T7) |
| 7 | "I've been practising my Spanish a lot lately." (train travel, filler) | `(none)`; filler | `extra` / `filler-state`: states `speaksLanguage` (T8) |
| 8 | "I'm thinking of moving to Cologne soon." (train travel; the move to Cologne comes 20 messages later) | `(none)`; filler | `extra` / `foreshadowing` |
| 9 | Question at read version 92: "Where does Jonas live?", gold `Bremen`, evidence "Jonas was in Bremen from 1 to 3 March." | | `ambiguous`: the evidence describes a stay (T10) |
| 10 | Question: "When you offered me EC 175 for the train booking A, …?", where EC 175 was offered twice for booking A before the read version | | `anchor-unidentifiable` |

## 7. Workflow, files and agreement

**Label files.** Copy `sheet.csv` to `labels-<annotator>.csv` and fill `annotator`, `label`, `subclass` and `note` on every `pilot` and `audit` row; keep `annotator` the same on every row and leave `context` rows empty (a label there is an error). Rows with an empty label are skipped; the reader ignores the other columns, so the file can stay a full copy of the sheet. A name beginning with `agent-` marks a model or agent pre-annotation; the name `adjudicated` marks the adjudicated labels. An annotation page under `web/human-reviewer/` may be added by its owner; it must export the same four annotator columns keyed by `item_id`.

**Annotators.** Design section 8 names one author and one person not involved in building the system, chosen in phase 1. Their names are not assumed here and no placeholder second label set is made; the integration owner asks the user and records the choice. The agent pre-annotation is neither annotator. Both annotators label all 750 audit messages and 121 audit questions, independently: neither sees the other's labels or the agent pre-annotation before finishing.

**Calibration.** Both annotators read this guide, label the two pilot windows, and discuss their pilot disagreements before starting the audit windows. Changes to this guide after calibration are recorded in the T016 log with the date.

**Statistics** (design section 8), all on the `audit` part, per family and overall: Cohen's kappa on the binary label (any mismatch vs `agree` or `unnatural`) and on the full label set; raw disagreement rate; mismatch prevalence; positive and negative specific agreement (mismatches are rare, which depresses kappa at high raw agreement); 95 % intervals from a bootstrap over windows (2,000 draws, seed 20261125). For questions: kappa and disagreement over the four question labels.

**Adjudication.** Disagreements are resolved by discussion and recorded as `labels-adjudicated.csv` (`annotator = adjudicated`). The adjudicated label is final.

**Decision rule** (design section 8). A family is flagged when its adjudicated mismatch rate exceeds 5 % of audited messages, or when the same mismatch occurs three or more times in it. "The same mismatch" is operationalised here as the same label on the same dialogue skeleton (for example `missing` on `past`), because the skeleton, its lexicon and the rendering prompt are what a T015 fix changes. A flagged family is fixed in T015 and re-audited with fresh windows, or excluded with the reason recorded in the T016 log.

## 8. Commands

```bash
uv run python -m grace.cli.annotate.sequence sheet                    # redraw sample.json and sheet.csv from the T015 dataset run
uv run python -m grace.cli.annotate.sequence mismatch docs/research/annotations/sequence-audit/labels-<annotator>.csv --json "$PROJECT_ROOT/runs/T016/artifacts/<run>/mismatch.json"
uv run python -m grace.cli.annotate.sequence agreement labels-<a>.csv labels-<b>.csv --json "$PROJECT_ROOT/runs/T016/artifacts/<run>/agreement.json"
```

`sheet` reads the dataset from `$PROJECT_ROOT/runs/T015/artifacts/T015-devmodel-20261125T192037Z/dataset` unless `--dataset` is given; an integration test checks that the committed sheet and record are reproduced byte for byte. `mismatch` reports one label file (mismatch rate per family with Wilson and window-bootstrap intervals, label counts, repeats per skeleton, flagged families, question labels). `agreement` reports two label files and marks the result as not human agreement when either is an agent pre-annotation.
