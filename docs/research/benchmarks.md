# Benchmarks

Registry and cards for every benchmark in `docs/research/plan.md` (sections 6.3 to 6.5). Download sources are pinned in `configs/data/sources.yaml` and fetched with `scripts/data/` (see the Benchmarks section of `README.md`). Each benchmark has one section here; its slug is shared by `configs/benchmarks/<slug>.yaml`, `tests/fixtures/benchmarks/<slug>/` and `$PROJECT_ROOT/data/<slug>/<version>/`. Split this file into a folder when a card grows beyond about 100 lines.

## Registry

| Slug | Benchmark | Tier | Read protocol | Role in the plan | Status |
| --- | --- | --- | --- | --- | --- |
| `change-seq` | Controlled change sequences (built here; design in T008) | Main text (core) | Interleaved | RQ2 primary (per-message staleness ground truth); RQ3 maintenance surface | to build |
| `multiwoz` | MultiWOZ 2.4 (main); 2.2 and 2.1 score the same predictions | Main text (core) | Per turn | RQ1 primary for roles (turns after an offer, T006); natural over-marking, no cost claims | verified |
| `locomo` | LoCoMo, categories 1 to 4 | Main text (core) | End of history; evidence-anchored streaming (T007) | RQ1 slices; RQ2 false positives under streaming; RQ3 amortisation | verified |
| `longmemeval-s` | LongMemEval S (cleaned); main text uses the knowledge-update, temporal-reasoning and multi-session strata | Main text | End of history, one question per history | RQ1 and RQ3 adverse setting | verified |
| `halumem-medium` | HaluMem-Medium | Summary table (optional) | Session by session | Graph quality (write path); RQ2 support | verified |
| `memoryagentbench` | MemoryAgentBench: LongMemEval(S\*) and FactConsolidation at 6K and 32K | Summary table (optional) | Chunk by chunk, several questions per context | RQ3 multi-read; RQ2 support | verified |
| `beam`, `memora`, `stale` | BEAM, Memora, STALE | Not evaluated | — | Related work only; may enter the supplementary material after the lock if budget remains | not evaluated |

Status values: `to check` (availability or license unknown), `to bind` / `to build`, `bound` (data, manifest and config in place), `verified` (adapter reproduces the counts below), `not evaluated` (considered and left out of the evaluation; no card is kept).

## Card template

Each benchmark section uses these fields. The data owner fills them when binding the data; counts must be reproduced by the adapter before the status becomes `verified`.

| Field | What to record |
| --- | --- |
| Source and license | Official name, citation, download source, release or revision, license and its publishing limits |
| Units | History unit, segment and message, mapped to the records in `contracts.md` |
| Splits and counts | Files, counts per split, development / held-out lists used by the plan |
| Reading protocol | When the system ingests and when it answers; what is masked |
| Evaluation | Official scorer and version, metric direction, denominator, invalid-output policy |
| Known issues | Label errors, overlaps, exclusions (for example images), deviations from the official protocol |
| Manifest | Relative path, size and SHA-256 of every source file; recorded in the config |

## change-seq

Pending. See plan section 6.4 and the generator design (T008).

## multiwoz

Card filled by T002 (acting as data owner this round). Counts are reproduced by the adapter (`src/grace/eval/datasets/benchmarks/`) through `splits.load_split`; development counts are checked at every load, held-out counts were counted once by the same adapter code and are checked when a held-out split is loaded after the T033 preregistration tag.

| Field | Value |
| --- | --- |
| Source and license | MultiWOZ 2.4 (`smartyfh/MultiWOZ2.4` @ `6807c1d`), 2.2 and 2.1 (`budzianowski/multiwoz` @ `fe0c8e6`); repository licence MIT, licence of the data itself to be checked (plan 11.1). Versions `2.4`, `2.2`, `2.1` in `data/multiwoz/` |
| Units | History = dialogue (`dialogue_id` with its `.json` suffix, as in the list files); no segments; message = turn, `message_id` = turn index (0-based string); `USER` → `user`, `SYSTEM` → `agent`, `speaker` keeps the label. Visible text is the 2.4 text (identical to 2.1 on every development turn; 2.2 edits 2,090 development utterances) |
| Splits and counts | `dev` = official validation list (`MULTIWOZ2.4/valListFile.json`; same list in 2.1, same 1,000 IDs in 2.2 `dev/`): 1,000 histories, 14,748 messages, 7,374 state reads, 22,122 gold (3 annotations). `held-out` = official test list: 1,000 histories, 14,744 messages, 7,372 state reads (plan 6.5: 1,000 dialogues, 7,372 user turns), 22,116 gold. The plan names no MultiWOZ development set; the validation set is the T002 proposal |
| Reading protocol | Per turn: one `state` read (`state_schema` `multiwoz-slots`) at the version of each user turn, task `<dialogue_id>:<turn index>`; later turns and gold states are never visible |
| Evaluation | `configs/common/scorers.yaml#multiwoz` (T004): JGA and slot F1 against annotations `2.4`, `2.2`, `2.1` on the same `task_id`s |
| Gold | Cumulative state after the user turn, slot → string over the 30 slots of attraction, hotel, restaurant, taxi and train, named as in 2.2 (`hotel-bookday`, `train-leaveat`). 2.4/2.1: from the metadata of the following system turn; `""`, `not mentioned`, `none` mean unset; `dontcare` is kept. 2.2: union of the frames' `slot_values`; where 2.2 lists several values the first is the reference and all are in `metadata.alternatives`. `metadata.dialogue_acts` holds the acts of the user turn and the preceding system turn per annotation (2.4 `dialogue_acts.json` has system acts only and is byte-identical to 2.1 `system_acts.json`) |
| Known issues | Excluded and counted (`exclusions.json`): the user `goal` (1 per dialogue); slot values outside the inventory (dev: 15 `hospital-department`). No label-variant normalisation (T004 open item). Derived "current choice" gold is T006 |
| Manifest | 2.4 `MANIFEST.sha256` `78ca9c26…fc35`: `MULTIWOZ2.4/data.json` (276,572,745 B, `3555f1c3…f8751`), `dialogue_acts.json` (24,349,109 B, `54d02ef4…20c6f`), `valListFile.json` (`8e19240b…7c8327d80`), `testListFile.json` (`56fff5bf…3fec9`). 2.2 `7916a2aa…d49c`: `dev/dialogues_00{1,2}.json` (`e7ddb563…`, `ede6a2c1…`), `test/dialogues_00{1,2}.json` (`d6f43876…`, `89af95d8…`), `dialog_acts.json` (`328f3921…`). 2.1 `553f662f…3d17`: `MultiWOZ_2.1/data.json` (374,423,663 B, `8be37ba1…7851c`). Full lists in each `MANIFEST.sha256`; checksums in `configs/benchmarks/multiwoz.yaml` |

## locomo

Card filled by T002 (acting as data owner this round). Counts are reproduced by the adapter (`src/grace/eval/datasets/benchmarks/`) through `splits.load_split`; development counts are checked at every load, held-out counts were counted once by the same adapter code and are checked when a held-out split is loaded after the T033 preregistration tag.

| Field | Value |
| --- | --- |
| Source and license | LoCoMo `snap-research/locomo` @ `3eb6f2c`, `locomo10.json`; CC BY-NC 4.0. Independent audit `dial481/locomo-audit` @ `9493fb4` under `audit/` (not peer reviewed; not yet used by the adapter) |
| Units | History = `sample_id`; segment = `session_<k>`, dated by `session_<k>_date_time` (`1:56 pm on 8 May, 2023` → `2023-05-08T13:56`); message = turn, `message_id` = `dia_id`, both speakers `peer`, message time `null` |
| Splits and counts | 10 histories, 5,882 turns, 1,986 questions (category 1: 282, 2: 321, 3: 96, 4: 841, 5: 446). `dev` = conv-26, conv-49 (plan 6.5): 2 histories, 928 messages, 308 reads. `held-out` = the other 8: 4,954 messages, 1,232 reads |
| Reading protocol | End of history: every category 1–4 question at $N$, task `<sample_id>:q<index in the source qa list>`. Streaming at $v(q)$ and $N$ is T007 |
| Evaluation | `configs/common/scorers.yaml#locomo` (T004); gold `annotation` `3eb6f2c`; `category` in `labels` |
| Known issues | Excluded and counted: category 5 (dev 87, held-out 359); image fields `img_url`, `blip_caption`, `query`, `re-download` removed from the turn, text kept (dev 208 turns, held-out 1,018); `event_summary`, `session_summary`, `observation` (1 each per history); 16 `session_<k>_date_time` keys of conv-26 without a session. Evidence: 13 category 1–4 questions (dev 6, held-out 7) have missing or unresolvable evidence (plan 11.1): unresolvable strings such as `D8:6; D9:17` stay verbatim in `evidence_unresolved`, empty evidence gives `evidence_ids: []`; `metadata.evidence_status` is `complete`, `unresolved` or `missing`. Integer answers (6 in dev) are written as strings. Questions answerable only from an image caption are not yet flagged (open) |
| Manifest | `MANIFEST.sha256` `c6836966…88ae7`; `locomo10.json` 2,805,274 B, `79fa87e9…98ff4` (plan 11.1) |

## longmemeval-s

Card filled by T002 (acting as data owner this round). Counts are reproduced by the adapter (`src/grace/eval/datasets/benchmarks/`) through `splits.load_split`; development counts are checked at every load, held-out counts were counted once by the same adapter code and are checked when a held-out split is loaded after the T033 preregistration tag.

| Field | Value |
| --- | --- |
| Source and license | `xiaowu0162/longmemeval-cleaned` @ `98d7416` (Hugging Face), `longmemeval_s_cleaned.json`; MIT. `longmemeval_oracle.json` is downloaded but not used |
| Units | History = the haystack of one `question_id`; segment = haystack session in file order, ID `haystack_session_ids[i]`, dated by `haystack_dates[i]` (`2023/05/20 (Sat) 02:21` → `2023-05-20T02:21`); message = turn, `<segment_id>:<turn index>`, `user` → `user`, `assistant` → `agent` |
| Splits and counts | 500 histories, 246,750 turns. Types: multi-session 133, temporal-reasoning 133, knowledge-update 78, single-session-user 70, single-session-assistant 56, single-session-preference 30; abstention (`_abs`) 30. Split stratified by type × abstention, 20 % dev (rule in the config): `dev` 98 histories, 48,781 messages, 98 reads (KU 15, TR 26, MS 26, SSU 14, SSA 11, SSP 6; abstention 5); `held-out` 402 histories, 197,957 messages, 402 reads (KU 63, TR 107, MS 107, SSU 56, SSA 45, SSP 24; abstention 25) |
| Reading protocol | End of history, one question per history; `question_date` → `asked_at`; `has_answer` and `answer_session_ids` masked |
| Evaluation | `configs/common/scorers.yaml#longmemeval-s` (T004); `question_type` and `abstention` in `labels`; evidence: `has_answer` turns → `evidence_ids`, `answer_session_ids` → `evidence_segment_ids`. Gold `annotation` is the data version `98d7416` (the scorer registry names `cleaned`; to be aligned) |
| Known issues | 13 histories repeat a session ID (identical copy at another date, never an answer session): the n-th occurrence becomes `<session_id>#<n>` (dev 7, held-out 6). 12 turns with empty text are excluded and counted (dev 1, held-out 11; none has `has_answer`). Haystack dates are not chronological in 211 histories (3,167 adjacent inversions) and 1,475 sessions are dated after their `question_date`; versions follow the file order (`session_order: source`), see decisions in the T002 PR |
| Manifest | `MANIFEST.sha256` `235a008a…f547d`; `longmemeval_s_cleaned.json` 277,383,467 B, `d6f21ea9…3c442`; `longmemeval_oracle.json` 15,388,478 B, `821a2034…620c` |

## halumem-medium

Card filled by T002 (acting as data owner this round). Counts are reproduced by the adapter (`src/grace/eval/datasets/benchmarks/`) through `splits.load_split`; development counts are checked at every load, held-out counts were counted once by the same adapter code and are checked when a held-out split is loaded after the T033 preregistration tag.

| Field | Value |
| --- | --- |
| Source and license | `IAAR-Shanghai/HaluMem` @ `cb04336` (Hugging Face), `HaluMem-Medium.jsonl`; CC BY-NC-ND 4.0 (no derived subsets may be published) |
| Units | History = user (`uuid`); segment = session `session_<k>` (1-based; the source has no session IDs), dated by `start_time`; message = dialogue turn `session_<k>:<turn index>`, `user` → `user`, `assistant` → `agent`, with the turn `timestamp` (`Sep 19, 2025, 08:32:00` → `2025-09-19T08:32:00`) |
| Splits and counts | 20 users, 1,387 sessions (896 with questions), 60,146 turns, 14,948 memory points (3,122 with `is_update` and `original_memories`, so the updated memories are included in the 14,948), 3,467 questions (Memory Boundary 828, Memory Conflict 769, Basic Fact Recall 746, Generalization & Application 746, Multi-hop Inference 198, Dynamic Update 180). Plan fixes no split; T002 proposes 4 dev users (20 %, rule in the config): 12,980 messages, 709 reads, 3,190 memory points; `held-out` 16 users: 47,166 messages, 2,758 reads, 11,758 memory points |
| Reading protocol | Session by session; each question at the last version of its session, task `<uuid>:session_<k>:q<j>` |
| Evaluation | `configs/common/scorers.yaml#halumem-medium` (pending in T004). `question_type`, `difficulty` in `labels`. Question evidence cites memory points, not turns: `evidence_ids: null`, cited points in gold `metadata.evidence_memory_points`. Write-side gold: `memory_points.jsonl` (scoring side only; one row per memory point with `segment_id`) |
| Known issues | Excluded and counted: `persona_info` and `token_cost` (1 each per user). No empty turns |
| Manifest | `MANIFEST.sha256` `de45bed8…77920`; `HaluMem-Medium.jsonl` 33,511,525 B, `486fbc13…634e7` |

## memoryagentbench

Card filled by T002 (acting as data owner this round). Counts are reproduced by the adapter (`src/grace/eval/datasets/benchmarks/`) through `splits.load_split`; development counts are checked at every load, held-out counts were counted once by the same adapter code and are checked when a held-out split is loaded after the T033 preregistration tag.

| Field | Value |
| --- | --- |
| Source and license | `ai-hyz/MemoryAgentBench` @ `7ea0669` (Hugging Face), `Accurate_Retrieval` and `Conflict_Resolution` parquet files; MIT (data card; to be checked against the paper, plan 11.1) |
| Units | History = one context row, `<source>:<k>` (the source has no context IDs). Subsets of the plan only: `longmemeval-s-star` (source `longmemeval_s*`, 5 contexts × 60 questions = 300), `factconsolidation-{sh,mh}-{6k,32k}` (1 context × 100 questions each; sh and mh share the context). Chunk = message = segment `chunk_<k>`, `document`, `speaker: null`, no time. LongMemEval(S\*): one chunk per haystack session (header `Chat Time: …` plus `<role>: <content>` lines, as in the source context string). FactConsolidation: `facts_per_chunk` = 20 numbered facts per chunk (6K: 455 facts, 32K: 2,310) |
| Splits and counts | Split by task (T002 proposal): a LongMemEval(S\*) question is dev iff its LongMemEval `question_id` is in `longmemeval-s` dev (so no longmemeval-s held-out question is read in development); 20 % of each FactConsolidation context's questions (rule in the config). `dev` 9 histories, 833 messages, 137 reads (57 + 4 × 20); `held-out` 9 histories, 833 messages, 563 reads. Contexts appear in both splits with disjoint questions |
| Reading protocol | Chunk by chunk, then all questions of the split at $N$; task `<history_id>:<qa_pair_id>`; LongMemEval(S\*) `question_dates` → `asked_at` |
| Evaluation | `configs/common/scorers.yaml#memoryagentbench` (pending in T004). Reference = list of accepted answers; `competency` (`accurate_retrieval`, `conflict_resolution`), `question_type` and `abstention` (LongMemEval(S\*)) in `labels`; `evidence_ids: null` |
| Known issues | Excluded and counted: other sources (eventqa ×15, ruler ×2, FactConsolidation 64K/262K ×4); the FactConsolidation header line. Chunking deviates from the official token-based chunking (no tokenizer pinned); chunk size is a decision for the user |
| Manifest | `MANIFEST.sha256` `cb1ecc84…3f682`; `Accurate_Retrieval-00000-of-00001.parquet` 20,024,386 B, `56c3cd80…655c1`; `Conflict_Resolution-00000-of-00001.parquet` 1,491,588 B, `24d5c3f0…ff45` |
