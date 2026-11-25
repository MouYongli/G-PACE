# Fragment Coverage Annotation Guideline

This guideline is for task T012 (plan section 6.5, "Fragment coverage"). Annotators label each of the 308 LoCoMo development questions (histories conv-26 and conv-49, categories 1 to 4): can the question be expressed in the query fragment of plan section 3.3, and if not, why not? The share of questions inside the fragment is an upper bound on the accuracy of the graph channel. If that share is below one half, expectations for RQ1 on LoCoMo are lowered (plan section 9). Held-out histories are never annotated.

Files (all under `docs/research/annotations/fragment-coverage/`):

| File | Content |
| --- | --- |
| `sheet.csv` | The blank annotation sheet: one row per question, with empty annotator columns (section 7) |
| `labels-<annotator>.csv` | One label file per annotator (section 7) |
| `labels-agent-m01-T012.csv` | A first-pass pre-annotation by the manager agent of T012. It is **not a human annotator** and is never one of the two annotators of plan 6.5 |

Code: `src/grace/eval/datasets/benchmarks/locomo_annotation.py` (sheet, overlap choice) and `src/grace/eval/analysis/annotation/fragment.py` (label files, coverage, kappa). Entry point: `scripts/annotation/fragment-coverage.sh`. The sheet copies question text and evidence turns from LoCoMo (`snap-research/locomo` @ `3eb6f2c`, CC BY-NC 4.0; see `docs/research/benchmarks.md#locomo`).

## 1. What is being judged

The label states whether the question is **expressible** in the fragment. It does not say whether a real system would answer it correctly. Judge each question under an *ideal writer* that has the following properties:

- **A1. Text only.** The writer reads the dialogue text and the session dates. Image captions are not input (plan 6.5). The sheet shows the caption of an evidence turn only so that you can see when an answer exists only in an image.
- **A2. Perfect extraction of what is stated.** Every proposition the text states or directly names becomes a claim, with the right speaker, communicative function and evidence link. That includes reasons, feelings and opinions stated as such ("I chose them 'cause they help LGBTQ+ folks"). Nothing the text only implies is extracted. Entities are resolved across turns ("that book you recommended" is the same book).
- **A3. Vocabulary at the granularity of the question.** For each relation or type the question asks about, there is one predicate, or one type claim that a join can use, provided the text states it or directly names it (`playsInstrument`, `doesActivity`, `(event, type, LGBTQ event)`). You may not assume a predicate whose members can only be found by judging relevance ("changes during her transition").
- **A4. Write-time time normalisation.** The writer resolves every time expression against the date of the session it occurs in and stores the result as the claim's valid time, keeping the phrase in `expression` (`docs/research/contracts.md`, Claim graph). For example, "yesterday" in a session dated 8 May 2023 becomes 7 May 2023, "last year" becomes 2022, and "seven years now" becomes a start in 2016. This is tie rule T1.
- **A5. Built-ins.** Every current-state query carries the "currently accepted" negation and every answer carries its provenance (plan 3.3). Neither counts as an operation you list.

## 2. The fragment (plan section 3.3)

Its atom is a **claim pattern** `(s, p, o, ω)[u, f]`. The subject, predicate, object and scope are constants or variables. The optional attribution constraint `[u, f]` requires a stance of speaker `u` with communicative function `f` (request, offer, accept, reject, confirm, inform, commit or question) on the claim. The fragment allows six operations:

| Operation | What it allows | LoCoMo example (development set) | Listed as |
| --- | --- | --- | --- |
| Filters | Comparisons with constants and with valid times carried by claims | conv-26:q31 "When did Melanie go camping in June?": camping pattern, valid time in June 2023 | `filter` |
| Joins | Up to three claim patterns sharing variables | conv-26:q11 "Where did Caroline move from 4 years ago?": `(Caroline, movedFrom, ?c)` and `(Caroline, homeCountry, ?c)` give Sweden | `join` |
| Negation | `NOT EXISTS` over one claim pattern that shares variables with the positive part, not nested | None among the 308 questions in the pre-annotation. Constructed example: "Which hobbies has Sam considered but not taken up?" is `(Sam, considersHobby, ?h)` with `NOT EXISTS (Sam, practises, ?h)` | `negation` |
| Distinct counting | `COUNT(DISTINCT …)` over matches | conv-26:q40 "How many times has Melanie gone to the beach in 2023?" (count with a filter); conv-49:q3 "How many Prius has Evan owned?" | `count` |
| Latest confirmed state | Maximum by version or valid time | conv-49:q0 "What kind of car does Evan drive?"; conv-26:q97 "What workshop did Caroline attend recently?" | `latest` |
| Provenance expansion | Projecting the claims and evidence an answer relies on | Every in-fragment answer, for example conv-26:q60 "What instruments does Melanie play?" cites D2:5 and D15:26 (plan 3.5) | never listed |

Attribution constraints are part of the claim pattern, not a separate operation. Examples: conv-49:q90 "What new suggestion did Evan give to Sam …?" is `(Sam, swapFor, ?x)[Evan, offer]`, and conv-49:q91 "What did Sam agree to try …?" matches the same claims with `[Sam, accept]`.

Outside the fragment are:

- union over predicates the vocabulary would keep apart;
- more than three claim patterns;
- property paths (chains of unbounded length);
- any aggregation other than a distinct count and the latest selection, such as sum, average, ranking or "every third";
- arithmetic on values or dates;
- comparisons with the time of reading ("in the last week", "how long ago" counted from now).

A question with relative time can be compiled into an absolute interval at read time, as a temporary query (plan 3.3). It is in the fragment only if that interval is anchored to a date carried by a claim or a session, never to the read time.

## 3. Labels

Each question gets exactly one `label`.

| Label | Meaning | Examples |
| --- | --- | --- |
| `in_fragment` | Under section 1, a fragment query returns the gold answer (or the answer the question asks for; see T6) | conv-26:q60, conv-26:q11, conv-49:q3 |
| `open_reasoning` | The answer needs inference, judgement, prediction, a counterfactual, a summary across heterogeneous statements, or a count or attribute that is implied but never stated | conv-26:q14 (counterfactual), conv-26:q75 (number of children inferred), conv-26:q65 ("changes during her transition") |
| `date_arithmetic` | The answer needs arithmetic on dates or durations at read time: a difference between two events, a frequency computed from intervals, or an offset from the time of reading | conv-49:q39 (months between two check-ups), conv-49:q70 (dating time before the wedding), conv-49:q43 (check-up frequency) |
| `common_sense` | Exactly one background fact about the world, not stated in the dialogue, would turn the question into a fragment query if it were added as a claim | conv-26:q22 (Dr. Seuss books are classic children's books), conv-49:q57 (Lake Tahoe is in California), conv-49:q71 (late December is the Christmas season) |
| `other` | Any other reason. `other_reason` is required and must be one of the codes below | conv-26:q110, conv-49:q24 |

Codes for `other_reason`:

- `image_only`: the whole answer is only in image captions (A1). If only part of the answer is in captions, use T5 and the `partial_image` flag instead.
- `annotation_error`: the question itself presupposes something the dialogue does not contain, so no query over the dialogue can address it. Examples are an invented book title (conv-26:q26) and an event attributed to the wrong speaker (conv-49:q24).
- `beyond_fragment`: the question is well formed and grounded in the text, but needs one of the excluded constructs of section 2 (union, more than three patterns, a path, sum or average, ranking) and none of the other classes applies.

For `in_fragment`, also fill:

- `operations`: the operations used beyond a single claim pattern, separated by `;`, chosen from `filter`, `join`, `negation`, `count` and `latest`. Leave it empty for a single claim pattern with projection.
- `flags` (optional, section 6).

## 4. Decision procedure

Work through the steps in order and stop at the first that applies.

1. Read the question, the gold answer, the evidence text with its session dates, the evidence image caption and the audit columns. If the evidence is missing or wrong, look up the turn in the history. The record files of the development split can be written with `uv run python -m grace.eval.datasets.benchmarks.splits locomo dev --out "$PROJECT_ROOT/runs/<node>/…"`.
2. If the question presupposes an entity or event that is not in the dialogue, label `other` / `annotation_error`.
3. If the whole answer is only in image captions, label `other` / `image_only`.
4. Try to write the query under section 1: at most three claim patterns, the six operations, filters only against constants and claim valid times. If you can, and its answer is what the question asks for, label `in_fragment` and list the operations.
5. Otherwise name what is missing. If the answer needs arithmetic on dates or durations at read time, label `date_arithmetic`.
6. If adding one background fact as a claim would make step 4 succeed, label `common_sense`.
7. If the answer needs inference, judgement, prediction or a summary, label `open_reasoning`.
8. Otherwise label `other` / `beyond_fragment`, and say in the rationale which construct is missing.

If several reasons apply, the earliest step wins. That makes the order of steps 5 to 8 the precedence rule: date arithmetic, then common sense, then open reasoning, then other. Write a one-sentence `rationale` for every label that names the claim pattern or the missing piece.

## 5. Tie rules

- **T1. Relative time is resolved at write time.** A time expression that is resolved against the date of its own session belongs to the writer (A4), so the question stays in the fragment. Set the flag `relative_time` (section 6). Examples: conv-26:q0 ("yesterday" gives 7 May 2023) and conv-26:q68 ("seven years now" gives since 2016).
- **T2. "When" asks for a valid time.** A question that asks when one event happened is answered by projecting that event's valid time, at whatever granularity the gold answer uses: day, "the week before 9 June 2023", month or year. It is `in_fragment`. A time restriction in the question ("in June", "in 2023", "on 13 October") is a `filter`.
- **T3. Differences are arithmetic.** If the answer is a duration or offset between two events, or between an event and the time of reading, label `date_arithmetic`. T4 is the exception.
- **T4. A stated duration is a value.** A duration or frequency that one message states verbatim as a property ("married for 5 years", "known these friends for 4 years", "once or twice a year", "ten years ago") is a claim value or time expression. A question that asks for it is `in_fragment`.
- **T5. Partly in an image.** If part of the answer is in the text and part only in captions, label by the query shape and set the flag `partial_image`.
- **T6. Wrong gold, sound question.** If the gold answer is wrong or incomplete (see the audit columns) but the question is grounded in the dialogue, label the question as asked against the dialogue text. The gold answer only shows what the question means. Use `annotation_error` only when the question itself cannot be grounded (step 2).
- **T7. Hedged questions.** "Likely", "would" and "might" questions (mostly category 3) are `open_reasoning`, unless the answer is stated directly (then `in_fragment`) or exactly one world fact is missing (then `common_sense`).
- **T8. Variable predicates and subjects.** A pattern may leave the predicate or the subject as a variable. For example, "how does Evan describe the woman" can be `(woman, ?p, ?o)[Evan, inform]`, and "health scares of Sam and Evan" can bind the subject to either speaker. Such a question stays in the fragment when it is one pattern. A list of facts that would need several unrelated patterns is `open_reasoning` (if relevance must be judged) or `other` / `beyond_fragment`.

## 6. Flags

Flags mark in-fragment questions whose label depends on a contestable assumption, so that coverage can be reported under the strict reading as well. Separate several flags with `;`.

| Flag | Set when |
| --- | --- |
| `relative_time` | The label relies on T1 (write-time resolution of a relative time expression) |
| `partial_image` | The label relies on T5 (part of the answer is only in an image) |

`coverage` reports the counts of each flag and the coverage when flagged questions count as outside the fragment.

## 7. Workflow, files and agreement

**Sheet columns.** `question_id` (`<history>:q<index>`, the index in the source `qa` list, as in the adapter), `history_id`, `category`, `category_name`, `overlap` (`yes` or `no`), `question`, `gold_answer`, `evidence_ids`, `evidence_text` (each turn as `[id | session date | speaker] text`, separated by ` || `), `evidence_status`, `evidence_image_caption`, `audit_error_type` and `audit_correct_answer` (the independent audit, plan 6.5; not peer reviewed). The annotator fills `annotator`, `label`, `operations`, `other_reason`, `flags` and `rationale`.

**Label files.** Copy `sheet.csv` to `labels-<annotator>.csv`, fill the six annotator columns, and keep `annotator` the same on every row. The browser page `web/human-reviewer/t012.html` does this and exports the file (see `web/human-reviewer/README.md`). Rows with an empty label are skipped. The reader ignores the other columns, so the file can stay a full copy of the sheet. A name beginning with `agent-` marks a model pre-annotation.

**Two annotators (plan 6.5).** The two-annotator part and the kappa wait until the user names the second annotator under decision D007 (`docs/work/decisions/D007-gate-evidence-placement.md`, section "Also recorded here"). That person is not involved in building the system, and the name is recorded in D007. No placeholder second label set is made in the meantime. The agent pre-annotation is neither annotator. Annotator A labels all 308 questions; A's labels give the coverage figure. Annotator B, the second annotator named under D007, labels the 100 questions with `overlap = yes`. Both work blind: neither sees the other's labels or the agent pre-annotation before finishing. Kappa is computed on the overlap only. Disagreements are then discussed, and any change A makes after adjudication is recorded in the T012 log with the before and after counts. Coverage is reported from A's labels, before and after adjudication.

**Overlap choice.** The 100 overlap questions are fixed when the sheet is written (`select_overlap`). The sample is stratified by history and category, with largest-remainder allocation of `100 · n_stratum / 308`. Inside each stratum, questions are ordered by the SHA-256 of `T012-overlap-v1:<question_id>` and the first ones are taken. The resulting strata are conv-26: 10 / 12 / 4 / 23 and conv-49: 12 / 11 / 4 / 24 for categories 1 / 2 / 3 / 4. Rewriting the sheet reproduces the same set, and an integration test checks that the committed sheet is reproduced byte for byte.

**Commands.**

```bash
scripts/annotation/fragment-coverage.sh sheet                         # rewrite sheet.csv from $PROJECT_ROOT/data (dev split only)
scripts/annotation/fragment-coverage.sh coverage docs/research/annotations/fragment-coverage/labels-A.csv --json "$PROJECT_ROOT/runs/T012/artifacts/coverage-A.json"
scripts/annotation/fragment-coverage.sh agreement docs/research/annotations/fragment-coverage/labels-A.csv docs/research/annotations/fragment-coverage/labels-B.csv
```

`agreement` reports Cohen's kappa over the five classes and over in versus out, the observed agreement, the confusion matrix, the questions that disagree, and any overlap questions a file leaves unlabelled. It marks the result as not human agreement when either file is an agent pre-annotation.
