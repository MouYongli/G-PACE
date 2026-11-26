# Interface Contracts

This file is the single specification of the interfaces between modules and tasks. Workers implement against it without reading each other's code; managers review against it; contract tests in `tests/contracts/` and fixtures in `tests/fixtures/` make it executable.

## How to change a contract

- Each section has one owner. Only the owner (or a PR the owner approves) may change it. Owners are assigned in the Issue that introduces the section; `TBD` means no change is allowed until one is assigned.
- A change PR updates, in the same PR: the section text, its `Version` line, the fixtures, the contract tests, and a list of experiments whose results it invalidates.
- Freeze the sections a task depends on, and push them to the task branch, before dispatching workers (see `.agents/roles/manager.md`).
- Split this file into `docs/contracts/` when JSON Schema files are added, a section grows beyond about 100 lines, or two owners change it concurrently.

Conventions used below: `MUST`, `MUST NOT` and `MAY` are normative. All files are UTF-8 JSON Lines (one JSON object per line) unless stated otherwise.

## Benchmark records

> Replaces the sample-level "Benchmark input" record of v0.1 (task T001). Terms follow plan sections 3.1 and 6.2: a **history** is the unit of memory, a **segment** a dated part of it, a **message** one $h_r$, and a **read task** a question or state request bound to a version.

Owner: T001 manager (`m01-T001`) · Version: 0.2 · Producer: benchmark adapters (`eval/datasets/benchmarks/`) · Consumers: harness, probes, oracles, judging, metrics

An adapter writes, per benchmark, data version and split:

| File | One record per | Visible to systems |
| --- | --- | --- |
| `histories.jsonl` | history ([History](#history)) | yes |
| `messages.jsonl` | message ([Message](#message)) | yes |
| `read_tasks.jsonl` | read of the native schedule ([Read task](#read-task)) | yes |
| `read_tasks.<schedule>.jsonl` | read of an additional schedule, for example `streaming` for LoCoMo (T007) | yes |
| `gold.jsonl` | reference of one task under one annotation ([Gold](#gold)) | no: scoring side only |

Rules shared by all record types in this file:

- IDs are non-empty strings copied from the source, including leading zeros and suffixes; never cast them to numbers. Where the source has no ID, the adapter builds one by the rule on the benchmark card.
- `benchmark` equals the `benchmark` key of `configs/benchmarks/<slug>.yaml`; `split` is a split listed there (`fixture` in `tests/fixtures/`). One file holds one benchmark and one split.
- The fields listed in each table are the only top-level fields. Benchmark-specific fields go into the optional `metadata` object and are documented on the benchmark card.
- Times are ISO 8601 strings with no invented precision (`2023-05-08T13:56:00`, or `2023-05-08` when the source gives only a date; an offset only when the source gives one). The source string is kept in the matching `*_raw` field. Both are `null` when the source has no time.
- Visible records never contain a reference answer, an evidence annotation, a category or stratum label, or any field the card marks as masked (plan 6.8). Those live only in `gold.jsonl`, which reaches a system only through `eval/engines/oracles/` in a labelled upper-bound experiment.
- Write-side gold (HaluMem memory points and update labels; gold claim graphs and per-message invalidation ground truth of `change-seq`) is also scoring side only. Its files are named on the benchmark card and in the T008 design; they are outside these records.

Adapter obligations:

- Fail on duplicate keys, missing required fields, unknown top-level fields and empty strings. The error names the source file, the source line or record index, and the offending key.
- Compare per-split counts of histories, messages and read tasks with the card and the manifest; fail on any mismatch.
- Exclude what the plan excludes (for example LoCoMo images, image captions and human-written summaries) and write the count per exclusion reason to `exclusions.json` next to the records.
- Never write into `$PROJECT_ROOT/data`; write converted output to `RUN_DIR`.

Synthetic fixtures of all six benchmarks are in `tests/fixtures/benchmarks/<slug>/`; the reference checks the contract tests apply to them are in `tests/contracts/records.py`.

## History

Owner: T001 manager (`m01-T001`) · Version: 0.2 · Producer: benchmark adapters · Consumers: harness, probes

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `benchmark`, `split` | string | yes | See [Benchmark records](#benchmark-records). |
| `history_id` | string | yes | Source ID of the unit of memory (plan 6.2); unique within benchmark and split. |
| `subset` | string or `null` | yes | Named subset when one benchmark ships histories of different kinds (MemoryAgentBench `factconsolidation-6k`); `null` otherwise. |
| `n_messages` | integer | yes | $N\ge 1$; equals the number of message records of the history. |
| `segments` | list of objects | yes | Segments in order; `[]` when the benchmark has none. |
| `metadata` | object | no | Visible benchmark-specific fields. |

Segment object: `segment_id` (string, source ID, unique within the history), `first_version` and `last_version` (integers), `timestamp` and `timestamp_raw` (string or `null`). Segments cover versions 1 to $N$ in order, without gaps or overlaps. Every message of a history with segments names its segment, and its version lies in that segment's range; in a history without segments every message has `segment_id: null`.

## Message

Owner: T001 manager (`m01-T001`) · Version: 0.2 · Producer: benchmark adapters · Consumers: harness, probes, oracles

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `benchmark`, `split`, `history_id` | string | yes | `history_id` names an existing history. |
| `version` | integer | yes | Position $r$ of the message in $\mathcal H$; writing it commits version $r$. Within a history the versions are exactly $1,\dots,N$. |
| `message_id` | string | yes | Source message ID; unique within the history. This is the evidence ID that evidence annotations, citations and traces use. |
| `segment_id` | string or `null` | yes | See [History](#history). |
| `speaker` | string or `null` | yes | Source speaker name or label (`Melanie`, `USER`); `null` when the unit has no speaker. |
| `role` | string | yes | `user` (the person the memory serves), `agent` (assistant or system side of a task dialogue), `peer` (one of several equal participants), or `document` (text without a speaker). |
| `text` | string | yes | Non-empty message text after the exclusions of the card. |
| `timestamp`, `timestamp_raw` | string or `null` | yes | The message's own time. When the source dates only segments both are `null` and readers use the segment's time; adapters do not copy segment times down or invent finer ones. |
| `metadata` | object | no | Visible benchmark-specific fields. |

Records are written in version order within a history; readers MUST still sort by `version` and fail on a gap or a duplicate. Evidence spans inside a message (`context/memory/history/spans.py`, T014) refine a `message_id`; they do not replace it.

## Read task

Owner: T001 manager (`m01-T001`) · Version: 0.2 · Producer: benchmark adapters; read-schedule builders (T007 for LoCoMo streaming) · Consumers: harness, judging, metrics

A read task is a question or a state request arriving at version $r$ (plan 3.1). It is the alignment key of predictions.

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `benchmark`, `split`, `history_id` | string | yes | `history_id` names an existing history. |
| `read_id` | string | yes | `<task_id>@<version>`; unique within the file. Predictions align on it. |
| `task_id` | string | yes | ID of the question or state target; links to [Gold](#gold). |
| `version` | integer | yes | Snapshot cut-off, $1\le r\le N$: the read sees exactly the messages with `version` $\le r$. |
| `kind` | string | yes | `question` or `state`. |
| `question` | string or `null` | yes | Non-empty for `question`; `null` for `state`. |
| `state_schema` | string or `null` | yes | For `state`: the slot inventory named on the card (`multiwoz-slots`); `null` for `question`. |
| `asked_at`, `asked_at_raw` | string or `null` | yes | World time at which the question is asked (LongMemEval `question_date`). It is specified separately from `version` (plan 3.1). |
| `metadata` | object | no | Visible benchmark-specific fields. |

Schedules:

- The harness writes messages $1..r$, answers every read task with `version` $r$ on that snapshot, each independently, and only then writes message $r+1$. Answering never writes to the history (plan 6).
- End of history: every read task has `version` $=N$. Per turn: one `state` read at the version of each user turn. Interleaved and streaming: versions set by the schedule.
- A task read at several versions has one reference valid at all of them (LoCoMo streaming asks the same question at $v(q)$ and $N$). A schedule whose reference changes with the version uses one `task_id` per read point (`change-seq`).
- Each read-task file is its own key space; a run reads exactly one of them and records which in its resolved config.

## Gold

Owner: T001 manager (`m01-T001`) · Version: 0.2 · Producer: benchmark adapters; derived-gold builders (T006) · Consumers: oracles, judging, metrics only

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `benchmark`, `split`, `history_id`, `task_id` | string | yes | Same values as the read tasks of this task. |
| `annotation` | string | yes | Annotation the reference comes from: the data version (`2.4`, `2.2`, `2.1` for MultiWOZ) or a derived gold named on the card (`2.4-current-choice`). The key is `(annotation, task_id)`. |
| `reference` | any JSON value or `null` | yes | Answer (string or list) or state (object slot → value). `null` only for splits without public labels. |
| `evidence_ids` | list of strings or `null` | yes | `message_id`s of the annotated evidence; `null` when the benchmark annotates no message evidence for this task. |
| `evidence_segment_ids` | list of strings or `null` | yes | Segment-level evidence (LongMemEval `answer_session_ids`); `null` when none. |
| `evidence_unresolved` | list of strings | yes | Source evidence references that name no message (LoCoMo has 13 such questions; plan 11.1); `[]` when all resolve. |
| `labels` | object | yes | Category and stratum labels (LoCoMo `category`, LongMemEval `question_type`, abstention, change type); `{}` when none. |
| `metadata` | object | no | Other scoring-side fields, such as MultiWOZ dialogue acts. |

Every evidence ID names a message (or segment) of the history, and every evidence message has a version at most the `version` of every read task of this `task_id` in every schedule. A violation is a snapshot mismatch: the schedule places a read before its evidence.

An annotation MAY cover only some tasks (derived gold exists only for turns after an offer). Scoring against it uses the tasks it covers and reports their number.

## Benchmark mapping

Owner: T001 manager (`m01-T001`) · Version: 0.2.1 (T002: HaluMem and MemoryAgentBench rows confirmed on the data)

How the six benchmarks of `docs/research/benchmarks.md` map onto the records. Source field names follow the plan and the public releases; T002 confirms them on the data and records any deviation on the card.

| Slug | `history_id` | Segment | `message_id`; `role` | Times | Read tasks | Gold evidence and labels |
| --- | --- | --- | --- | --- | --- | --- |
| `change-seq` | Sequence ID | Episode | Generator message ID; `user`, `agent` | Generator world time per message | Interleaved `question` reads at generator-scheduled versions; one `task_id` per read point | Witness messages from the event log; change type and the pair ID of "known then" and "seen from now" questions in `labels` |
| `multiwoz` | `dialogue_id` | None | Turn index as a string; `USER` → `user`, `SYSTEM` → `agent` | None | Per turn: one `state` read at each user turn | Cumulative state per annotation `2.4`, `2.2`, `2.1` on the same `task_id`; derived "current choice" gold (T006) as its own annotation; dialogue acts in `metadata` |
| `locomo` | `sample_id` | Session `session_<k>`, dated by `session_<k>_date_time` | `dia_id`; both speakers `peer` | Segment time only | End of history: every question at $N$, `task_id` `<sample_id>:q<index>`; streaming file at $v(q)$ and $N$ (T007) | `evidence` → `evidence_ids`, unresolvable references in `evidence_unresolved`; `category` in `labels` |
| `longmemeval-s` | `question_id` | Haystack session, dated by `haystack_dates` | `<session_id>:<turn index>`; `user`, `agent` | Segment time; `question_date` → `asked_at` | End of history, one question per history; `task_id` = `question_id` | Turns with `has_answer` → `evidence_ids`, `answer_session_ids` → `evidence_segment_ids` (both masked in messages); `question_type` and abstention in `labels` |
| `halumem-medium` | User ID (`uuid`) | Session `session_<k>` (the files have no session ID) | `<session_id>:<turn index>`; `user`, `agent` | Session `start_time`; turn time per message | Session by session: each question at the last version of its session | `evidence_ids: null` (the files cite memory points, not turns; cited memory points in `metadata`); question type in `labels`; memory points and update labels as write-side gold |
| `memoryagentbench` | Context ID `<source>:<k>` (the files have none); `subset` names LongMemEval(S\*), FactConsolidation 6K or 32K | Chunk, one message each | `<chunk_id>`; `document`, `speaker: null` | None; LongMemEval(S\*) `question_dates` → `asked_at` | Chunk by chunk, then several questions at $N$ | `evidence_ids: null`; competency in `labels` |

Per-turn reading (MultiWOZ) and end-of-history reading (LoCoMo) differ only in the `version` of their read tasks; the same harness drives both.

## Prediction

> Replaces the sample-level "Prediction output" record of v0.1 (task T001).

Owner: T001 manager (`m01-T001`) · Version: 0.2 · Producer: harness (`eval/runner/harness/outputs.py`) · Consumers: judging, metrics

One record per read task of the schedule the run used.

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `benchmark`, `split`, `history_id` | string | yes | As in the read task. |
| `read_id` | string | yes | Alignment key. |
| `task_id`, `version` | string, integer | yes | Copied from the read task; checked against it. |
| `output` | string | yes | `answer`, `state`, `unknown` (abstention), or `invalid` (no parsable final output). |
| `prediction` | any JSON value | yes | Parsed answer (string or list) or state (object slot → value); `null` for `unknown` and `invalid`. |
| `cited_ids` | list of strings | yes | `message_id`s the final answer cites (plan 5.6). |
| `context_ids` | list of strings | yes | `message_id`s whose source text is in the working context: the set $R$ of plan 3.1, used for strict evidence recall. Lenient recall uses the provenance in the read trace. |
| `further_retrieval` | boolean | yes | Whether the one permitted further retrieval was used. |
| `raw_output` | string or `null` | yes | Unparsed final output of the answering LLM; `null` only for systems that make no answering call. |
| `metadata` | object | no | Ignored by the evaluator. |

Evaluator obligations:

- Align by `read_id` against the read-task file the run used; accept any line order.
- Abort scoring on duplicate keys, missing keys, extra keys, more than one benchmark or split in a file, or a snapshot mismatch: `history_id`, `task_id` or `version` differs from the read task, a `cited_ids` or `context_ids` entry names a message after `version` or no message at all, or a gold evidence message lies after `version`. The error reports the count per category and up to five example keys each.
- `unknown` is scored by the abstention rule on the card. `invalid` is not missing; it is handled by the invalid-output policy in [Evaluation](#evaluation).

## Cost ledger

Owner: T001 manager (`m01-T001`) · Version: 0.1 · Producer: `llm/records.py` (T004) and the recording endpoint `llm/proxy.py` · Consumers: `eval/analysis/metrics/cost.py` (T030)

Every model call writes one record to `calls.jsonl` of the run that made it: chat and embedding calls, judge calls, and the requests external systems (Mem0, Graphiti) send through the recording endpoint. Retries and failed attempts are records of their own and are counted in full (plan 8.1).

| Field | Type | Rules |
| --- | --- | --- |
| `call_id`, `run_id` | string | `call_id` is unique within the run. |
| `history_id`, `read_id` | string or `null` | The history and the read the call serves; `read_id` is `null` when `trigger` is `write`. |
| `version` | integer or `null` | For a write-triggered call, the version being written (the last message of a segment); for a read-triggered call, the read's version. |
| `call_type` | string | `extract` (writing and entity alignment), `vocabulary`, `render`, `plan`, `repair` (compilation repair), `verify`, `answer`, `summary` (rolling-summary baseline), `external`, `embed`, `judge`. |
| `trigger` | string | `write`, `read` or `evaluation`: the phase that caused the call. |
| `category` | string | `W`, `U`, `A`, `embedding` or `evaluation`, set by the caller (table below). |
| `model` | string | Served model and snapshot. |
| `attempt` | integer | 1 for the first attempt of a logical call. |
| `status` | string | `ok`, `failed` or `invalid_output`. |
| `input_tokens` | integer | Logical input: the whole prompt counted with the model's tokenizer and chat template, including tool and query results inserted into it. |
| `output_tokens` | integer | Generated tokens; 0 for embeddings. |
| `cached_input_tokens` | integer | Input tokens served from the prefix cache, as reported by the server; $0\le$ value $\le$ `input_tokens`. |
| `gpu_seconds` | number or `null` | GPU time of the call under local inference; `null` for remote APIs. |
| `latency_ms` | number | Wall time of the call. |
| `prompt_sha256` | string or `null` | Hash of the prompt template (not of the filled prompt). |

Which tokens are counted when:

| Time | Call types | Category | Notes |
| --- | --- | --- | --- |
| Write: a message or segment is ingested | `extract`, `vocabulary`, eager `render`, `summary`, `external` on ingestion | `W` | Includes the extraction of a partial segment when a read falls inside it (plan 8.4); that call has `trigger: read` and is still `W`. |
| Plan: a read starts | `plan`, `repair` | `U` | A rule template makes no call and costs nothing. |
| Render: a view is materialised | `render` | `W` | At write time and for a lazy rebuild at read time alike (plan 8.2); `trigger` tells them apart. Citation patching makes no call. |
| Read: the context is checked and retrieved | `verify`, `external` on search | `U` | `external` is `W` when `trigger` is `write` and `U` when it is `read`. |
| Read: answering | `answer`, including the second call after the one further retrieval | `A` | A full-history baseline has the serialised history in its answer input, so it is `A`. |
| Any time | `embed` | `embedding` | Reported separately; never part of W, U or A. |
| After the system stage | `judge` | `evaluation` | `trigger: evaluation`. Evaluation overhead, never system cost. |

The three ledgers (plan 8.1) are sums over the records of a category: logical tokens $=\sum(\text{input}+\text{output})$; computed tokens $=\sum(\text{input}-\text{cached}+\text{output})$; GPU seconds $=\sum$ `gpu_seconds`, reported with the number of calls whose value is `null`. In the notation of plan 8.2, $W(\mathcal H)$ sums the `W` records of a history, and $U_i$ and $A_i$ sum the `U` and `A` records with `read_id` $i$. Under per-turn and interleaved reading the write cost charged before read $i$ is the union of the `W` records with `version` in $(r_{i-1}, r_i]$ and the `W` records with `read_id` $i$. Database CPU, memory, latency percentiles and tool-call counts are not ledger entries; components record them in the write and read traces ([Experiment run](#experiment-run)).

## Claim graph

> Terms follow plan sections 3.2 and 5.2. Code: `context/memory/graph/` (entries, change sets, RDF mapping, store, SHACL) and `context/memory/history/` (message log, spans). Vocabulary and shapes: `resources/rdf/`.

Owner: T014 manager (`m01-T014`) · Version: 0.3 · Producer: `context/memory/` (commit called by `pipeline/update/`, T022) · Consumers: update, query compilation (T017), views and staleness (T018, T019), the change-sequence generator and oracles (T015), graph metrics

**Entries.** Each is a frozen data class in `graph/entries.py`; its JSON record has exactly the fields below. Entry IDs are non-empty strings, unique across all kinds within a history (witness sets mix claim and attribution IDs). `version` is the version stamp, an integer $\ge 1$.

| Kind | Fields |
| --- | --- |
| Claim | `claim_id`, `subject` (entity ID), `predicate` (vocabulary name), `object` (`{"entity": id}` or `{"value": lexical, "datatype": d}` with `d` in `string`, `integer`, `boolean`, `date`, `dateTime`, `time`, canonical lexical form), `scope` (string or `null` for the default scope), `valid_time` (`start`, `end`, `expression`), `version` |
| Attribution | `attribution_id`, `claim_id`, `speaker`, `function` (`request`, `offer`, `accept`, `reject`, `confirm`, `inform`, `commit`, `question`), `report_mode` (`own`, `quote`, `hypothetical`), `polarity` (`positive`, `negative`), `certainty` (`certain`, `probable`, `possible`, `underspecified`), `derived` (assistant restatement; not independent support), `message_id` (where the stance was expressed), `version` |
| Evidence link | `evidence_id`, `claim_id`, `message_id`, `span` (`{"start", "end"}` or `null`), `version` |
| Supersession | `supersession_id`, `claim_id`, `kind` (`change`, `correction`), `valid_end` (see below), `replacing_claim_id` (or `null` for a removal), `attribution_id` (the stance that licensed it), `version` (the supersession version $\sigma$) |
| Entity equivalence | `equivalence_id`, `entity_a`, `entity_b`, `version`; not one of the four kinds (plan 5.2) |
| Entity label | `label_id`, `entity` (entity ID), `label` (the surface name the ID was made from; non-empty, no surrounding whitespace), `version`; not one of the four kinds (`graph/entities.py`; since 0.3, see "Entity labels" below) |

- Valid time is $[\texttt{start},\texttt{end})$ in canonical `xsd:date` or `xsd:dateTime` form, both bounds of one datatype; `null` start is unknown and `null` end is open. No date is invented; `expression` keeps the source phrase.
- Spans are $[\texttt{start},\texttt{end})$ over the message text in code points. A unified evidence ID is the `message_id`, or `<message_id>#char=<start>,<end>` for a span (`history/spans.py`); `message_of` maps it back to the message.

**Change set.** One record per committed version, the `changesets.jsonl` record of [Experiment run](#experiment-run): `history_id`, `version`, `entries` (exactly the keys `claims`, `attributions`, `evidence_links`, `supersessions`, each a list of full entry records sorted by ID), `vocabulary_version` (label of `resources/rdf/predicates.yaml` in force, or `null`), `entity_merges` (entity-equivalence records), and, since 0.3, `entity_labels` (entity-label records sorted by ID; the key is present only when the change set has labels, so a change set without labels is stored byte for byte as before 0.3, and a record without the key is valid and has no labels). Every entry in it carries the change set's `version`; one change set labels an entity at most once. Change supersessions of one claim in one change set that state a `valid_end` MUST state comparable ones: all `xsd:date`, all `xsd:dateTime` without a zone, or all `xsd:dateTime` with a zone (`check_change_ends`; an `EntryError` otherwise), so that the earliest of them is defined (see the valid end below). A version that produced nothing MAY be committed as an empty change set. The fixture is `tests/fixtures/graph/worked-example/` (the worked example of `docs/research/change-sequences.md` section 6.5, plus a removal, a hypothetical stance and an entity merge); `tests/fixtures/graph/entity-labels/` adds labels (one at first use, a version without labels, a labels-only version with a merge).

**Store rules** (`graph/store.py`, one store per history):

- Append-only: `commit` adds the triples of one change set in one transaction and never changes or removes a triple; $G_r\subseteq G_{r+1}$. A failed commit writes nothing.
- Versions strictly increase (gaps are allowed for segment extraction). A commit at or below the head is accepted only as a retry of the identical change set (entry order ignored) and is then a no-op; anything else is a `CommitConflict`.
- References name an entry of the right kind in the store or the same change set. A new claim MUST NOT repeat the proposition (s, p, o, scope, valid time) of a currently accepted claim: a repeated mention adds an attribution and an evidence link. A superseded proposition may be stated again as a new claim.
- A replacing claim has the subject, predicate and scope of the claim it replaces; the licensing attribution is on the superseded or the replacing claim. The attribution guard itself and the exclusivity rules are not store rules: they decide whether to supersede (`pipeline/update/guard.py`, T022), so a variant without the guard can still write.
- An entity has at most one label in a history: a second label for it, even with the same text, is a `CommitError` (labels are written once and never change).
- Reads are bound to a cut-off: `state(r)` returns the entries stamped $\le r$ (labels: `state(r).entity_labels()`, `state(r).display_name(e)`); `query(sparql, r)` replaces the placeholder `%r%` by the integer $r$ (plan 5.3). Both are stable under later commits (time-travel stability, plan 3.3).
- Save writes `store.json`, `changesets.jsonl` (source of truth) and `graph.nt`; restore replays the change sets and fails if the graph differs.

**RDF mapping** (`graph/rdf.py`; vocabulary `resources/rdf/core.ttl`, functions `resources/rdf/functions.ttl`). Every entry is a named node `gx:<kind>/<id>` typed `g:Claim`, `g:Attribution`, `g:EvidenceLink`, `g:Supersession`, `g:EntityEquivalence` or `g:EntityLabel` (path `label/`), with `g:knownFrom` = its version stamp. Claims: `rdf:subject`/`rdf:predicate`/`rdf:object` and type `rdf:Statement` under RDF 1.1 standard reification (main configuration, `rdf11`), or `rdf:reifies <<( s p o )>>` under RDF 1.2 (`rdf12`); all other triples are identical in both, and the reified triple is never asserted. Further properties: `g:scope`, `g:validFrom`, `g:validUntil`, `g:validTimeExpression` (claim); `g:about`, `prov:wasAttributedTo`, `g:function` (`gf:` SKOS concepts with ISO 24617-2 notes), `g:reportMode`, `g:polarity`, `g:certainty`, `g:derived`, `prov:wasDerivedFrom` (attribution); `g:supports`, `prov:wasDerivedFrom`, `oa:hasSelector` → `oa:TextPositionSelector` (evidence); `g:supersedes`, `g:kind`, `g:licensedBy`, `g:replacedBy`, `g:validEnd` (supersession); `g:labelOf` (the entity) and `rdfs:label` (an `xsd:string` literal, no language tag) on the label node (entity label). The entity node itself never carries `rdfs:label`: a triple on it could not be filtered by cut-off; labels at cut-off $r$ are `?l g:labelOf ?e ; rdfs:label ?name ; g:knownFrom ?v . FILTER(?v <= %r%)`. "Currently accepted" at cut-off $r$ is `FILTER NOT EXISTS { ?s g:supersedes ?c ; g:knownFrom ?v . FILTER(?v <= %r%) }`; the historical form adds `?s g:kind g:Correction`. The `https://example.org/grace/` namespace is a placeholder until release. The mapping is exact both ways: parsing rejects any triple it would not produce.

**Structural validation** (`graph/shacl.py`, shapes `resources/rdf/shapes.ttl`). Only the claims a change set touches (new claims, claims that receive an entry, replacing claims) are validated, together with the change set's own entries, on the RDF 1.1 serialisation of those claims and all their entries. Shapes require one version stamp per entry, at least one attribution and one evidence link per claim, closed value lists, ordered valid-time and span bounds, no entry older than the entries it names, no valid end on a correction, a licence on the superseded or replacing claim, and exactly one entity and one non-empty `xsd:string` name per entity label. Domain exclusivity rules are not shapes.

**Entity labels** (version 0.3; user decision of 2026-11-26). The writer (T022) makes grammar-safe entity IDs (`[A-Za-z0-9_]+`, collisions suffixed `_2`, `_3`); the label records the surface name an ID was made from, for the planner (T023) and for rendering.

- *Versioning.* A label is an entry stamped with the version of the change set that adds it, so a read at a cut-off before it sees no label and reads at every cut-off are stable. The writer adds it to the change set of the first version whose entries name the entity (subject, entity object, speaker or merged entity), only for IDs that differ from their surface name; generated change sequences carry none.
- *No change.* A label is written once per entity and history and never changes (store rule above). A wrong surface name stays as display data; correcting it is not supported in 0.3.
- *Merges.* An entity equivalence never rewrites a label. `display_name(e)` at cut-off $r$ is the label of $e$; else the label of its class representative at $r$; else the label of the smallest labelled member of its class (by code point); else the ID $e$ (`entities.display_name`).
- *Display data only: not part of any answer or fingerprint.* No compiled query reads labels, so answers, witnesses, evidence and their fingerprints (`QueryResult.fingerprints`) are identical with and without labels, and a label invalidates or marks no view: unlike an entity merge or a vocabulary change (plan 5.2, formalisation A5), it changes no entity identity and no query semantics, so `ViewStore.note_changeset` and the matching strategies ignore it (tests: `tests/contracts/test_entity_labels.py`). A view or prompt that shows labels shows the label at its own cut-off.
- *Compatibility.* Change sets, `changesets.jsonl` files and `graph.nt` snapshots written before 0.3 are valid 0.3 data without labels and need no regeneration (generated change sequences, the E002 and T022 writer runs). Results invalidated by this change: none (no experiment reads labels; E004 and E005 use generated graphs, which have none).

**Supersession semantics** (answers to `docs/research/change-sequences.md` open questions 2 and 6):

- *Valid end (question 2).* A supersession of kind `change` MAY carry `valid_end`, the world time from which the superseded claim no longer holds: stated by the source ("I sold it in March"), or the start of the replacing claim when that is dated. `null` means ended at an unknown time no later than the world time of message $\sigma$. A `correction` never carries one: the claim leaves the past state entirely and the replacing claim carries its own interval. The effective valid end of a claim at cut-off $r$ is its own `end`; else, among the change supersessions of the claim stamped $\le r$ that state a `valid_end`, those with the earliest stamp count, and of them the earliest `valid_end` by value (`entries.effective_change_end`, used by `GraphState.valid_end` and the change matcher; the compiled query implements the same rule). Equal instants in different lexical forms give the same comparisons (the store returns the smallest form). The tie-break between same-stamp events is by value, not by entry ID or IRI, because entry IRIs percent-encode the ID and so order differently from it (version 0.2; before it, the store and the matcher broke ties by ID and the compiled query by IRI, which could disagree, formalisation discrepancy 11). Reason: a claim's interval is fixed when it is written, so the end of a state learned later can only be recorded by a later entry, and the supersession is the entry that says the state ended; being stamped $\sigma$, it keeps reads at $k<\sigma$ stable. Without it the past membership of a multi-valued predicate is undetermined, because no successor claim exists. The matching unit is unchanged (the event still points to one claim), so the proposition of plan 3.4 is unaffected.
- *Guard without a replacing claim (question 6, G2(ii)).* The attribution guard covers it. A supersession with `replacing_claim_id: null` is licensed only by an attribution $a'$ on the superseded claim $c$ itself with report mode `own` and polarity `negative`, whose speaker and communicative function equal those of some earlier attribution on $c$; no exclusivity rule is needed. Reason: plan 5.2 states a denial as a new attribution on the same claim, never a second claim, so a negative own stance is the only way a removal ("I no longer play the violin") can be written; without it a multi-valued predicate could never shrink. The same speaker and function conditions keep what the guard protects: another speaker's denial, a quote or a hypothetical leaves both stances in place and the conflict marked. The kind may be `change` (removal) or `correction` (the multi-valued variant of `m-correct`).

## Evaluation

> Replaces the sample-level v0.1. Scoring is keyed by `read_id` and scored against one gold `annotation` at a time, following the T001 records.

Owner: T004 manager (`m01-T004`; assigned by the user's dispatch of the 2026-11-25 round) · Version: 0.3.1 (aggregation added by decision D002; `verified` and `deviation` defined by the T004 upstream comparison) · Producer: `judge` and `score` stages (`eval/analysis/judging/`, `eval/analysis/metrics/`) · Consumers: reporting (T035, T036)

### Registration

Before any formal comparison every metric is registered in `configs/common/scorers.yaml`; the benchmark card's Evaluation field points there. Per benchmark and metric:

| Key | Rules |
| --- | --- |
| `name`, `direction` | Registered metric name; `higher` or `lower`. |
| `code` | `module:function` of the scorer. Official scorers name `upstream` (`repo`, `file`, `revision`, `verified`). `verified` becomes `true` only when upstream's own code, run at `revision`, and the scorer give identical values (exact equality, not a tolerance) on upstream's published examples where upstream publishes any, and otherwise on development-split and synthetic inputs; a regression test with upstream-produced expected values keeps it so. Where no upstream implements the registered definition, or the two differ by design, `verified` stays `false` and `deviation` states the difference. |
| `annotation` or `annotations` | The gold annotation(s) scored ([Gold](#gold)). One set of predictions is scored against each annotation separately (MultiWOZ 2.4, 2.2, 2.1). |
| `population` | The denominator: all reads of the read-task file, or those whose gold `labels` match `include` (LoCoMo categories 1 to 4). |
| `judge` | For judged metrics, the judge config in `configs/judges/`. |
| `abstention` | The gold label that marks a task as unanswerable. |
| `invalid_policy` | `count_as_wrong` or `exclude_and_report`. |
| `strata` | Gold labels by which the metric is also reported. Stratum labels are used on the scoring side only (plan 6.7). |

### Scoring rules

- Alignment follows the evaluator obligations of [Prediction](#prediction); scoring aborts on any of them, and on an unparsable line or an empty prediction file. Gold is indexed by `(annotation, task_id)`; a read whose task the annotation does not cover is outside that annotation's population, and the covered count is reported as `n_total`.
- Each read gets a value in $[0, 1]$. `answer` and `state` predictions are scored by the registered scorer. `unknown` is correct exactly on tasks the `abstention` label marks, and wrong otherwise; for a state read it is the empty state. `invalid` scores 0 under `count_as_wrong` and leaves the denominator under `exclude_and_report`; it is counted in `n_invalid` either way.
- Judged metrics judge only `answer` predictions; `unknown` and `invalid` are scored by the rules above without a judge call. A judgement whose own output is unparsable (`verdict: invalid`) leaves the denominator and is counted in `n_judge_invalid`.

### Judges

- A judge config (`configs/judges/<judge>.yaml`) pins the prompt by its hash in `configs/common/prompts.yaml`, the parsing rule, decoding (temperature 0) and the judge model snapshot. The snapshot is decision D006: DeepSeek-V4-Flash-0731 (local, pinned revision) as the primary judge, Azure gpt-4.1-mini (version 2025-04-14) for the E001 comparison and the LongMemEval templates.
- The judge is blind: its input is exactly the question, the reference of the scored annotation and the prediction as text (lists joined with `; `). It never receives run, engine or config names, the working context, citations, `raw_output` or `metadata`.
- Judge calls are call records with `call_type: judge`, `trigger: evaluation` ([Cost ledger](#cost-ledger)); each judgement is one `judgements.jsonl` record ([Experiment run](#experiment-run)) naming its judge config. One `judge` run MAY run several judges over the same predictions (LongMemEval: the blind and the official judge); `(read_id, judge)` is unique.
- Judge reruns are new `judge` runs and are reported as their own source of uncertainty (plan 6.9).

### Judge calibration against human labels

Measured on development data only, before the blind judge's numbers are used in a comparison:

1. Draw a sample of judged development reads, stratified by benchmark and by the judge's verdict (size in `configs/judges/blind.yaml`).
2. Two annotators label each read `correct` or `incorrect`, seeing only what the judge sees; disagreements are adjudicated into a third label set.
3. Labels are JSON Lines, one record per read and annotator: `read_id`, `task_id`, `annotation`, `annotator` (`adjudicated` for the merged set), `verdict`.
4. Report, with `eval/analysis/judging/human.py`: Cohen's $\kappa$ and observed agreement of the judge against the adjudicated labels, $\kappa$ between the two annotators, the number of reads, and the number of judge outputs that were `invalid`.

Negative controls (deliberately wrong and vague answers), judge reruns and agreement between the blind and the official judge are calibration of T035.

### `metrics.json`

One JSON object `{"metrics": [...]}`, written exclusively by a `score` run, with one record per benchmark, split, annotation, metric and stratum:

| Field | Type | Rules |
| --- | --- | --- |
| `benchmark`, `split` | string | As in the predictions. |
| `schedule` | string | The read-task file the scored run used (`read_tasks.jsonl`, `read_tasks.streaming.jsonl`). |
| `annotation` | string | Gold annotation scored against. |
| `metric`, `direction` | string | Registered name and direction. |
| `stratum` | string or `null` | `<label>=<value>`; `null` for the whole population. |
| `seed` | integer | Seed of the run that produced the predictions. |
| `value` | number or `null` | Mean over the denominator; `null` exactly when `n_scored` is 0. |
| `n_total` | integer | Reads in the registered population. |
| `n_scored` | integer | Reads that entered the denominator. |
| `n_invalid`, `n_unknown` | integer | `invalid` and `unknown` predictions in the population. |
| `n_judge_invalid` | integer | Reads left out because the judge output was unparsable; 0 for unjudged metrics. |
| `invalid_policy` | string | As registered. |
| `scorer` | string | `<benchmark>/<metric>` in the registry. |
| `evaluator_version` | string | Full code SHA of the `score` run. |

### Reporting rules

- Report every benchmark, split, annotation and seed separately, with counts.
- Multi-seed summaries give the mean, the sample standard deviation and the number of runs.
- No score is averaged or combined across benchmarks ([Aggregation](#aggregation)).

### Aggregation

Decision D002; the machine-readable form is the `aggregation` block and the per-benchmark `cluster_unit` of `configs/common/scorers.yaml`.

- **No cross-benchmark score.** Benchmarks differ in metric, scale and role, and each research question names its own evidence (plan 6.6). Results are reported per benchmark; no overall, normalised or weighted score is computed, in the main text or the supplementary material.
- **Point estimate.** `value` in `metrics.json` is the micro mean over the reads of the population: questions, or turns for MultiWOZ. This follows each benchmark's official convention. Where clusters differ in size (MultiWOZ dialogues, controlled-sequence families), the macro mean of cluster means is reported in the supplementary material as a sensitivity analysis.
- **Strata.** The overall value pools all reads of the population; it is not a mean of stratum values. Each registered stratum is reported separately. A stratum with fewer than 100 reads is descriptive only: it gets counts and an interval, but no test and no claim (plan 6.9).
- **Annotations.** Each annotation is reported separately (MultiWOZ 2.4 main; 2.2 and 2.1 alongside) and never combined.
- **Missing values.** Every registered metric uses `invalid_policy: count_as_wrong`. `unknown` follows the abstention rule. A run that failed leaves its cell empty with the reason; nothing is imputed. `n_total` and `n_scored` are always shown.
- **Uncertainty.** Intervals are 95% percentile intervals from a cluster bootstrap (10,000 resamples) over the `cluster_unit` of the benchmark. For differences between two systems the bootstrap is paired: the same clusters are drawn for both. Tests follow plan 6.9: question-level paired tests with history as a random effect, with per-cluster differences and leave-one-cluster-out as sensitivity analyses. Judge reruns are a separate source of uncertainty and are summarised as mean, sample standard deviation and number of runs.

Required regression tests (`tests/contracts/test_evaluation.py`): empty prediction file, duplicate key, missing key, extra key, mixed splits, shuffled order, unparsable prediction; also snapshot mismatches, both invalid-output policies, the abstention rule and the `metrics.json` record.

## Experiment run

Owner: integration owner · Version: 0.2 (stages and upstream runs, intermediate artefacts and `resources_sha256` added by decision D013)

Every formal run owns one directory, created exclusively (fail if it exists, or use `tempfile.mkdtemp`):

```text
<RUN_DIR>/<experiment>/<run-id>/
  run.json              status and provenance (below)
  resolved-config.yaml  the fully resolved config actually used
  run.log               stdout and stderr
  report.yaml           written with the experiment-report skill
  cache/                library caches for this run only
  calls.jsonl           every model call; see Cost ledger
  predictions.jsonl     see Prediction
  contexts.jsonl        working contexts (below)
  traces/write.jsonl    write traces (below)
  traces/read.jsonl     read traces (below)
  changesets.jsonl      change sets (below)
  snapshot/             engine state per history, with snapshot/manifest.json
  judgements.jsonl      judgements (below)
  metrics.json          see Evaluation
```

A run writes only the files of its stage (table below); the first five entries are written by every run.

`RUN_DIR` is `$PROJECT_ROOT/<runs_root>/T<NNN>/artifacts/<worker>/`, with `runs_root` from `configs/common/paths.yaml`. It lives in the main checkout, outside every worktree, so removing a worktree never removes evidence.

Run ID format: `<experiment>-<UTC timestamp YYYYMMDDTHHMMSSZ>-<4 hex>`, for example `E001-20261121T093000Z-a1b2`.

### Stages and upstream runs

A run is one stage. Each stage reads only the files of the stage before it, which it names as upstream runs by run ID.

| Stage | Upstream | Writes |
| --- | --- | --- |
| `system` | none | `calls.jsonl`, `predictions.jsonl`, `contexts.jsonl`, `traces/`, `changesets.jsonl` |
| `ingest` | none | `calls.jsonl`, `traces/write.jsonl`, `changesets.jsonl`, `snapshot/` |
| `read` | exactly one `ingest` | `calls.jsonl`, `predictions.jsonl`, `contexts.jsonl`, `traces/read.jsonl` |
| `probe` | none, or one `ingest` or `system` | `calls.jsonl`, `traces/`, `changesets.jsonl`, outputs named in the experiment file |
| `judge` | one `system` or `read` | `calls.jsonl`, `judgements.jsonl` |
| `score` | one `system` or `read`, and at most one `judge` of it | `metrics.json` |

- Stages without an upstream run read benchmark records from `$PROJECT_ROOT/data` (through the adapters); `judge` and `score` also read gold.
- Under end-of-history reading, ingestion and reading are separate stages, and one `ingest` run serves several `read` runs (the four budget levels; the read-side ablations D, E and H). A `read` run restores the snapshot into its own directory; under per-turn and interleaved reading writes and reads alternate on one live state and form one `system` run.
- An upstream run MUST be `completed`. A run MUST NOT write, rename or delete anything in an upstream directory. Rescoring and judge reruns are new `score` and `judge` runs with new run IDs; they never rerun a system.

### Intermediate artefacts

All are JSON Lines. A field that does not apply to a system (a baseline has no views) holds an empty list or `null`; it is never omitted.

| File | One record per | Fields |
| --- | --- | --- |
| `contexts.jsonl` | read | `read_id`, `history_id`, `version`, `budget_tokens` (`null` for the full history), `tokens` (counted with the answering model's tokenizer), `text` (the context exactly as sent), `fragments` (list of `fragment_id`, `kind` = `message`, `view`, `claim`, `summary`, `retrieved` or `other`, `evidence_ids`, `tokens`) |
| `traces/write.jsonl` | committed write (message or segment) | `history_id`, `version`, `message_ids`, `call_ids`, `stale_marks` (list of `view_id`, `strategy`, `level` = `answer`, `citation` or `unknown`), `timings_ms` (component → milliseconds) |
| `traces/read.jsonl` | read | `read_id`, `history_id`, `version`, `candidates` (list of `id`, `channel`, `score`), `included_ids` (equal to `context_ids` of the prediction), `provenance` (fragment ID → `message_id`s, for lenient recall), `view_hits`, `staleness_decisions` (list of `view_id`, `strategy`, `decision` = `fresh`, `answer_stale` or `citation_stale`, `action` = `reuse`, `patch` or `rebuild`), `further_retrieval`, `call_ids`, `timings_ms` |
| `changesets.jsonl` | committed version | `history_id`, `version`, `entries` (added entries grouped as `claims`, `attributions`, `evidence_links`, `supersessions`; the entry format is owned by `context/memory/graph/changeset.py`, T014), `vocabulary_version`, `entity_merges` |
| `judgements.jsonl` | judged prediction | `read_id`, `task_id`, `annotation`, `judge` (judge config name), `verdict` (`correct`, `incorrect` or `invalid`), `raw_output`, `call_id` |

`snapshot/manifest.json` is one JSON object, `{"histories": [{"history_id", "version", "files": [{"path", "sha256"}]}]}`: per history, the last committed version and every snapshot file (path relative to `snapshot/`) with its SHA-256. The files themselves are in the engine's own format.

Example records of every artefact are in `tests/fixtures/runs/`.

### `run.json`

| Field | Type | Rules |
| --- | --- | --- |
| `run_id`, `experiment` | string | As above. |
| `stage` | string | One of the stages above. |
| `upstream` | list of objects | One per upstream run: `run_id`, `stage`, resolved absolute `path`, and `run_json_sha256` of its final `run.json`. `[]` when none. |
| `status` | string | `running`, then exactly one of `completed` or `failed`. |
| `code_sha` | string | Full 40-character SHA. |
| `code_dirty` | boolean | MUST be `false` for a `completed` formal run. |
| `config_path`, `config_sha256` | string | Source config and checksum of `resolved-config.yaml`. |
| `resources_sha256` | string | Checksum of `resources/` in the worktree (below). After the configuration lock (D012) a test compares it with the value recorded at the lock. |
| `data` | list of objects | One per benchmark whose records or gold the stage reads: `benchmark`, `version`, `manifest_sha256`, `split`, and the resolved absolute `path`. |
| `project_root` | string | Absolute `PROJECT_ROOT` resolved at run time. |
| `seed` | integer | |
| `command` | string | Exact command line. |
| `environment` | object | `python`, `lock_sha256`, `host`, `device`. |
| `started_at`, `finished_at` | string | ISO 8601 UTC; `finished_at` is `null` while running. |
| `n_records` | integer | Records processed: messages for `ingest`, reads for `system` and `read`, judgements for `judge`, scored reads for `score`, as defined in the experiment file for `probe`. |
| `failure` | string or `null` | Cause when `status` is `failed`. |

`resources_sha256` is computed like `sha256sum`: for every regular file under `resources/`, the line `<SHA-256 of its bytes, lowercase hex>  <path relative to resources/, with />` followed by a newline; the lines sorted by path in UTF-8 byte order and concatenated; the SHA-256 of that text. A missing or empty `resources/` gives the SHA-256 of the empty string. A symbolic link under `resources/` is an error.

### Lifecycle

1. Check that every upstream run is `completed`; then create the directory and write `run.json` with `status: running`.
2. Write all artifacts, then check the record count, metrics and exit code.
3. Only then set `status: completed` (or `failed` with `failure`) and `finished_at`.
4. Retries use a new run ID. Never delete or overwrite an earlier run's evidence.
