# Graph-quality annotation guideline (T024)

This guideline defines the human reference for the quality of extracted claim graphs (plan section 6.7, memory layer). Annotators list **every claim** in a sampled segment of a development history. E006 (graph quality) compares the writer's output with this list to measure claim precision, recall and F1, attribution accuracy and time accuracy.

The second part of T024 is correcting the writer's extraction of the two LoCoMo development histories, conv-26 and conv-49. It starts once E007 fixes the writer prompt (user decision of 2026-11-28) and is not covered here.

## 1. Sample

`docs/research/annotations/graph-quality/sample.json` lists the segments by ID. `src/grace/eval/datasets/benchmarks/graph_quality_sample.py` draws them from the development records with seed `T024-segments-v1`; the module docstring states the procedure.

| Benchmark | Segments | Messages | Words | Unit |
| --- | --- | --- | --- | --- |
| LoCoMo dev (conv-26, conv-49) | 16, 8 per history | 289 | about 7,200 | One session: the whole session if it has at most 24 messages, otherwise 20 consecutive messages |
| LongMemEval-S dev | 24, allocated over question types | 289 | about 51,000, of which 45,000 from the assistant | One haystack session: 12 evidence sessions (the window holds an evidence message) and 12 filler sessions |

**Deviation from plan 6.7.** The plan specifies segments of about 20 messages. LongMemEval-S haystack sessions have 8 to 14 messages, and each has about 2,100 words, four times a 20-message LoCoMo segment. LongMemEval-S segments are therefore whole sessions, and the sample has 578 messages instead of about 800.

Each segment comes with the 6 messages before it as **context**. Read context messages but do not annotate them.

## 2. What counts as a claim

A claim is one proposition worth remembering about a participant or about the things in their life. Ask: *would this still be worth knowing about the person in a month?*

Include:

- Facts about the participants and the people, pets, places, things and events in their lives: identity, family and relationships, possessions, home and location, work and studies, health, hobbies and activities, preferences and opinions, plans and goals, events they took part in, and the tasks they pursue together.
- For a concrete task (a booking, a purchase, a trip, a project of the user), the requirements a speaker states, the specific options a speaker offers, and whether an option is accepted or rejected.
- Statements that a fact no longer holds, or never held (section 4).

Exclude:

- General knowledge, explanations, advice, instructions, recipes, and the content of texts, code or stories written on request. This covers most assistant messages in LongMemEval-S.
- Generic lists of suggestions that answer a request ("here are ten tips", "some books you may like"). Exception: when the user takes up or turns down a specific item, record that item as a claim at the user's message, with function `accept` or `reject`.
- The conversation itself: greetings, goodbyes, thanks, compliments, encouragement, sympathy, reactions ("wow, that's cool"), questions that assert nothing, and feelings about the chat.

One claim is one proposition. Split conjunctions: "I have two kids, Mia and Leo" gives `hasChild Mia` and `hasChild Leo`. Facts that hold together and need no separate retrieval stay together: write `object: "2"` for "two kids" only when no names are given.

## 3. Fields of a claim

| Field | Rule |
| --- | --- |
| `message_id` | The message that states the claim. When a claim spans messages, use the message that completes it. |
| `subject` | The entity the claim is about, which is not always the speaker. For LoCoMo, use the speaker names (`Caroline`, `Melanie`). For LongMemEval-S, use `user` and `assistant`. Write "I" and "my" as the speaker and "you" as the other participant. Give an entity known only by its role a name built from its owner: `Caroline's mom`, `user's dog`. Spell the same entity the same way throughout the segment. A task is an entity too: `user's train booking`. |
| `predicate` | A short lowerCamelCase relation that says what the claim is: `livesIn`, `worksAt`, `hasChild`, `attended`, `visited`, `adopted`, `startedLearning`, `plansToVisit`, `likes`, `owns`. Prefer an existing common predicate; make up a specific one only when none fits. Never use catch-all predicates (`said`, `mentioned`, `talkedAbout`, `experienced`, `hasExperience`, `hasFeeling`, `felt`, `hasPlan`). The subject has the relation to the object: `Sam hasChild Mia` means Mia is Sam's child. |
| `object` | A short canonical value of one to five words: a name, a noun phrase, a number, a date or a time. Never a clause. If the content cannot be written as subject, specific relation and short object, leave it out. |
| `object_type` | `entity` for a person, place, organisation, pet, item, option or task that other claims may describe; otherwise `string`, `integer`, `boolean`, `date` (YYYY-MM-DD), `dateTime` or `time` (HH:MM:SS). |
| `speaker` | Who expresses the stance: the speaker of `message_id` as written in the segment. |
| `function` | `inform` (states it as true), `request` (asks for it or states it as a requirement of a task), `offer` (proposes it as an option), `accept`, `reject`, `confirm` (agrees with something already said), `commit` (promises to do it), `question` (asks whether it holds). |
| `report_mode` | `own` (in the speaker's own voice), `quote` (reports what someone else said or wants: "my sister says she moved to Rome"), `hypothetical` (conditions, wishes, suppositions: "if I moved to Rome"). |
| `polarity` | `negative` when the speaker says it does not hold; otherwise `positive`. |
| `certainty` | `certain`, `probable` ("I think", "probably"), `possible` ("maybe", "might") or `underspecified`. |
| `derived` | `true` when the speaker only restates what the other participant said (typically the assistant echoing the user). |
| `correction` | `true` when the claim corrects a value that was wrong all along ("sorry, I meant 21:15, not 20:15"). |
| `time_expression` | The phrase that places the claim in time ("last Sunday", "since college", "next month"), copied from the message; `null` when there is none. |
| `valid_from`, `valid_until` | When the claim holds in the world, as YYYY-MM-DD, only when the message states the date or it follows from the message date ("yesterday" said on 2023-05-08 gives 2023-05-07; for an event, the day it happened). Otherwise `null`. Never guess a date. |
| `quote` | The shortest exact span of the message text that states the claim, copied character for character. |

## 4. Stances on claims already annotated in the segment

Use a stance record, not a new claim, when a later message in the same segment:

- states the same claim again (`function: inform` or `confirm`; `derived: true` when the assistant only echoes it);
- accepts, rejects or asks about an offered option (`accept`, `reject`, `question`);
- says the claim no longer holds (`function: inform`, `polarity: negative`, `ends: change`, with `valid_until` if stated), or that it was wrong all along (`ends: correction`). End only a claim the message names: the quote contains the thing that ended.

When a single-valued fact changes to a new value ("I moved to Munich"), write the new claim; do not also end the old one. When the earlier claim is only in the context messages, write the claim at the segment message with that message's function.

## 5. Entity alignment

When a message shows that two names denote the same entity ("Mel" is Melanie), add a `same_as` record.

## 6. File format

One JSON Lines file per annotator, `labels-<annotator>.jsonl`, with one record per line. Every record has `segment` (the segment key from `sample.json`), `annotator` and `kind`.

```json
{"segment": "locomo:conv-26:session_4:59-76", "annotator": "A", "kind": "claim", "id": "c1", "message_id": "D4:3", "subject": "Caroline", "predicate": "attended", "object": "LGBTQ support group", "object_type": "entity", "speaker": "Caroline", "function": "inform", "report_mode": "own", "polarity": "positive", "certainty": "certain", "derived": false, "correction": false, "time_expression": "yesterday", "valid_from": "2023-06-08", "valid_until": null, "quote": "I went to a LGBTQ support group yesterday"}
{"segment": "locomo:conv-26:session_4:59-76", "annotator": "A", "kind": "stance", "message_id": "D4:9", "claim": "c1", "speaker": "Caroline", "function": "inform", "polarity": "positive", "derived": false, "ends": null, "valid_until": null, "quote": "the support group"}
{"segment": "locomo:conv-26:session_4:59-76", "annotator": "A", "kind": "same_as", "message_id": "D4:2", "name": "Mel", "same_as": "Melanie"}
{"segment": "locomo:conv-26:session_4:59-76", "annotator": "A", "kind": "segment_done", "minutes": 18, "note": ""}
```

- Claim `id` values are unique within a segment (`c1`, `c2`, ...). A stance's `claim` names one of them.
- Every segment ends with exactly one `segment_done` record, also when it has no claims. A segment without one counts as not annotated. `minutes` is the time spent (`null` for an agent).
- `python -m grace.cli.annotate.graph_quality validate <file>` checks a file against the sample. It checks that every message is in its segment, every quote occurs verbatim in its message, enumerations are closed, and stances name a claim.

## 7. Procedure and agreement

1. Two annotators label every segment independently. Neither sees the other's labels or any writer output.
2. `agreement A B` matches claims one to one within a segment. A pair matches at the **anchor level** when it has the same message, the same subject and the same object after normalisation: case, articles, possessive `'s`, punctuation, and token containment for multi-word names. It matches at the **strict level** when the normalised predicate is also equal. The command reports claim-level agreement as Dice $2m/(n_A+n_B)$ at both levels, and attribute agreement (function, polarity, report mode, certainty, time) on matched pairs. Results are given per benchmark.
3. `merge A B` writes one merged file: matched pairs (`agreement: both`, with a list of fields where they differ) and unmatched claims (`a_only`, `b_only`). Reviewers resolve every `a_only`, `b_only` and differing field. The resolved file is the reference for E006.

**Agent pre-annotation (user decision of 2026-11-28).** The first round uses two independent Claude agent annotators (`agent-A`, `agent-B`) that follow this guideline. They see only this guideline and the segments, not the writer's prompt output, the T022 runs or each other's labels. Their agreement is agreement between models, not human agreement. A human review of the merged file follows; human agreement and the final reference come from that review.

## 8. Effort

Estimated person-hours for a human annotator working from scratch:

| Step | Estimate |
| --- | --- |
| LoCoMo, 16 segments (289 messages, about 7,200 words, about 0.5 to 1 claim per message) | 4 to 6 h |
| LongMemEval-S, 24 segments (289 messages, about 51,000 words, mostly assistant text without claims) | 6 to 9 h |
| One annotator, all 40 segments | 10 to 15 h |
| Two annotators plus merge and adjudication | 23 to 34 h |
| Reviewing an agent-merged file instead (checking every disagreement, spot-checking agreed claims) | 6 to 10 h |
| Correcting the extraction of conv-26 and conv-49 (928 messages; 474 to 957 claims in the T022 smoke runs) | 8 to 12 h |

Plan 9.4 estimates 60 to 80 person-hours for all manual annotation, more than half of it for this task. If hours overrun, reduce the number of segments first (plan 10), starting with LongMemEval-S filler sessions.
