# A Graph Memory–Enhanced Context Engine for LLM Agents

Nov 20, 2026 · @Yongli

## 1. Overview

English title: A Graph Memory–Enhanced Context Engine for LLM Agents (tentative)

This plan builds and evaluates a three-layer system: graph memory maintains the history, the context engine organizes evidence for the current task, and a downstream LLM generates the answer. The question to answer is whether, at equal answer quality, it can be cheaper than rereading the full history or repeatedly rewriting summaries, while keeping every answer traceable to the original messages.

| Layer | Responsibility | Research focus of this plan at this layer |
| --- | --- | --- |
| Graph memory | Stores the raw-text log, extracts messages into claims carrying evidence, a speech-act role, a valid time and a knowledge time, and revises them as new messages arrive | The role decides which old claim may be superseded; the claim model is based on standard vocabularies |
| Context engine | Parses the current task into graph queries and text retrieval, verifies scope and time, assembles a cited working context within a token budget, and maintains reusable views | Assembly driven by evidence requirements; view staleness determined by query-level dependencies |
| Downstream LLM | Reads only the working context and answers the question or outputs the state; reports unknown when evidence is insufficient | Under the same reader, compares quality and end-to-end cost against full history, summaries, retrieval and other memory systems |

The evaluation covers three kinds of read tasks: long-conversation question answering, turn-level state tracking in task-oriented dialogue, and agent memory tasks with incrementally fed input.

In a long conversation, the compressed content handed to the model to read comes from earlier messages. New messages revise facts, add set members, and accept or reject a proposal. Afterwards the old compressed content may be wrong, and the system does not know it. Existing practice picks one of three options: reread the full history every time, fully rewrite the summary every time, or keep using the old summary. The first two are expensive; the third gives wrong answers.

The context engine defines such compressed content as views: each view is defined by a graph query, rendered by an LLM into text with per-sentence evidence, and records the query patterns and version it depends on. After a new message is written, the system uses the dependencies to decide which views are stale, rebuilds only the stale parts, and falls back to the raw text when the decision is unreliable.

There are three core claims, each paired with results that would refute it (see Section 4):

- **Staleness detection requires query-level dependencies.** Recording only "which claims a view used" misses new matches: a set gains a member, an empty result becomes non-empty, a count or latest state changes, while none of the existing claims has changed.
- **The speech-act role decides which old claim may be superseded.** A system proposal should not overwrite a user request; a restatement should not count as independent evidence.
- **At matched quality, maintaining views is cheaper in the regime where "revisions are frequent and the same history is read many times".** Outside this regime, full history or query-time resolution is more suitable, and the plan reports the regions where it does not dominate.

The plan also accepts negative results. If re-executing the query at read time detects staleness equally accurately, the conclusion narrows to "exact freshness checks are cheap; the bottleneck is extraction".

## 2. Background and related work

Provenance traceability, bitemporality, role distinction and cascading invalidation along dependency edges all have precedents; the gap this plan identifies is "view staleness triggered by new matches" and its evaluation with a cost ledger.

Most of the 2026 preprints in the tables below have been read only at the abstract level, and some are not peer-reviewed. Before writing "system X does not do Y", the full text must be read.

### 2.1 Closest work and how this plan differs

| Direction | What the closest work already does | How this plan differs |
| --- | --- | --- |
| Temporal graph memory | Zep/Graphiti: edges carry two timelines and are traceable to episodes; on conflict, new facts invalidate old edges | Whether supersession is allowed is decided by role; the invalidated object is a derived view, not just a single edge |
| Append-only storage with query-time resolution | APEX-MEM: an entity-centric property graph, with facts attached to dated events and conflicts handled at read time | Persists views and maintains their freshness; compares cumulative cost with "no caching, resolve at every query" |
| Programmatic state memory | ProgMem: compiles dialogue events into state-update programs and verifies evidence; evaluated with Qwen3-4B/8B/14B on the 1,540 questions of LoCoMo | Query-level dependencies and view rebuilding; evidence recall and cost comparison |
| Invalidation and repair of derived memory | PACMI: a provenance graph with typed dependency edges, four validity states, and cascading invalidation. MemoRepair: retracts affected derivatives and selectively rebuilds. MemTX and Kumiho also track dependencies | These works track "which records a view used". This plan tracks "which not-yet-seen records would change a view", and meters tokens on natural dialogue with full recomputation as the reference |
| Query cache invalidation | The SPARQL query cache of Martin, Unbehauen and Auer (2010): selective invalidation by the graph patterns of cached queries. Incremunica: incremental maintenance of SPARQL results | What is cached is an LLM-rendered reading view with evidence and a bitemporal scope; the rebuild cost is LLM tokens, which must be traded off against accuracy |
| RDF dialogue memory | Leolani/GRaSP: claims, mentions, per-speaker attribution (polarity, certainty). An and Gentile: RDF plus PROV-O, with the LLM writing SPARQL directly | Update handling, a typed intermediate representation, empty results with scope statements, and evidence sets returned at construction time |
| Role distinction | TripPy's system-inform memory; ParsingDST's separate User/System tables | Uses the role as a guard condition for "which old claim may be superseded" |
| Dynamic vocabulary | EDC, AutoSchemaKG, DIAL-KG: relation canonicalization, schema induction and incremental evolution, all document-oriented | Tests, on dialogue and with small models, whether constrained local extension is worthwhile |
| Cost evaluation | Pollertlam and Kornsuwannawit: break-even analysis with cache discounts. Unified evaluation studies: per-question amortization of construction and query tokens | Quality-matched comparison, cost per correct answer including failed attempts, and maintenance cost under updates |

### 2.2 Known adverse evidence

These results determine what the evaluation must guard against, and the plan does not avoid them. Scores from different papers are not directly comparable because backbone models and judging methods differ.

- **The full-history baseline is strong.** In Mem0's own table, GPT-4o-mini reading the full text reaches an LLM-judged accuracy of 72.90 on LoCoMo, higher than the 68.44 of its graph variant.
- **Graph structure yields little gain at small scale.** With the same extractor, Llama-3.1-8B on LongMemEval-S reaches QA accuracy of 0.614 with flat memory versus 0.620 with graph memory (Does Memory Need Graphs?).
- **LLMs writing SPARQL directly is unreliable.** The system of An and Gentile scores far below the same paper's full-context baseline on LongMemEval, and the authors list NL-to-SPARQL as the main bottleneck. This supports this plan's use of a restricted intermediate representation with deterministic compilation.
- **Structured writing is a weakness of small models.** In one comparative study, Nemori's format error rate rises from 17.91% with gpt-4o-mini to 30.38% with Qwen-2.5-3B. HaluMem reports that most systems miss more than half of the updates they should make.
- **Re-querying at read time may be sufficient.** Since a view is defined by a deterministic query, re-executing it at read time and comparing result fingerprints costs no LLM tokens. GroundedCache already performs a similar read-time recheck in the retrieval setting. The plan includes it as an experimental arm; see Section 7.3.

### 2.3 Theoretical foundations

View maintenance and dependency tracking cite the survey by Gupta and Mumick, DBSP, Doyle's truth maintenance system, and Adapton. "Which views are worth persisting" cites the view selection work of Agrawal et al. Evidence sets for query answers belong to how-provenance and cite SPARQLprov.

## 3. Task definition and notation

The input is a dialogue history arriving over time; at any moment the system must be able to answer a question or output a state using the memory visible at that time, and give the original messages it relied on.

$$
\mathcal H=\langle h_1,\dots,h_N\rangle,\qquad
\mathcal M_r=\mathrm{Write}(\mathcal M_{r-1},h_r),\qquad
(g,R)=\mathrm{Read}(\mathcal M_r,q)
$$

| Notation | Meaning | Role in the experiments |
| --- | --- | --- |
| $h_t$ | The $t$-th message, with speaker, original ID and available time metadata | Unit of the raw-text log; evidence is aligned by original message ID |
| $\mathcal H$ | The complete history; $L(\mathcal H)$ is its token count after serialization | The full-history baseline and the memory systems receive the same information |
| $\mathcal M_r$ | Memory after reading message $r$: raw-text log, text index, claim graph, a set of views | Each message commits one version; a read sees only the specified version |
| $q$ | A read task arriving at version $r$: one QA question or one state request | The reference answer $a$ and annotated evidence $e$ are held by the evaluator |
| $g$, $R$ | The answer output by the system; the set of evidence message IDs actually presented to the reader | Answer quality and evidence quality are scored separately |
| $W$, $U$, $A$ | LLM tokens for writing, intermediate read steps, and final answering, respectively | Cost ledger; see Section 8 |

The world time of a question and the snapshot cutoff version are specified separately. "What was known then" and "what it was then, looking back from now" are two different reads.

### 3.1 Two running examples

**A multi-valued predicate should not be overwritten by the "latest value".** In LoCoMo's conv-26, Melanie mentions playing the violin at D2:5 (2023-05-25) and playing the clarinet at D15:26 (2023-08-28). A test question asks which instruments she plays, and the reference answer counts both. The writer produces two `playsInstrument` claims with provenance; when the second is written, the first is entirely unchanged, yet the view "instruments Melanie plays" is already stale. Keeping only the latest edge, or listening only to claims already used, both lead to incomplete answers.

**A proposal should not overwrite a request.** In MultiWOZ's SNG0296.json, at turn 0 the user requires arrival by 20:45 at the latest; at turn 5 the system proposes TR7143 (departs 19:48, arrives 20:38); at turn 6 the user accepts and asks for a booking reference. After turn 5 the view should read "candidate TR7143, awaiting confirmation"; after turn 6 the "current selection" view needs rebuilding, while the "original arrival requirement" remains 20:45. The official annotations of the two versions differ here: MultiWOZ 2.2 changes `train-arriveby` to 20:38, while 2.4 keeps 20:45 throughout.

## 4. Contributions and research questions

The contributions are organized by the three layers; the novelty is concentrated in the context engine layer and the evaluation methodology, while most elements of the graph memory layer are a justified combination of existing practices.

### 4.1 Contributions

1. **Graph memory: a claim and evidence model based on standard vocabularies.** Claims are not asserted by default; only the "currently accepted state" enters the derived graph. Communicative function (request, proposal, acceptance, confirmation, inform) and reported-speech attribution are separated into two axes. The role is used as a guard condition for supersession rules.
2. **Context engine: a verifiable path from task to working context.** It has three parts: a deterministic compiler from a typed intermediate representation to SPARQL fragments, which returns evidence sets at construction time and annotates the evidence scope for empty results and counts; budgeted assembly of original sentences and fact cards driven by evidence requirements; and view staleness detection derived from query patterns, covering new matches, empty results, counts and latest states.
3. **Evaluation: quality-matched end-to-end cost and layered diagnostics.** It includes cache-adjusted break-even curves, cost per correct answer including failed attempts, a staleness detection evaluation stratified by change type with full recomputation as the reference, a comparison between gold-graph and extracted-graph conditions, and a direct evaluation of the extracted graph itself.

Provenance links, bitemporality, separating requests from proposals, and local repair are written up as "adopted existing practices" and are not claimed as novel on their own.

### 4.2 Research questions and falsification conditions

| Research question | Testable hypothesis | Results that would refute or narrow the claim |
| --- | --- | --- |
| RQ1 (overall): At equal task quality, can the three-layer system reduce end-to-end cost? | When the same history is read many times, has revisions, and the context budget is tight, the write cost is amortized, and the cache-adjusted cumulative cost is lower than full history and "no caching, resolve at query time" | Only the reader prompt gets shorter, and the advantage disappears once writing, compilation, validation and failed retries are counted; or the break-even number of reads exceeds the actual number of reads in the benchmarks |
| RQ2 (graph memory): What do roles and graph structure each contribute? | Roles prevent proposals from overwriting requests and prevent restatements from being treated as independent evidence; the graph outperforms a role-annotated JSON table on the connection, counting and point-in-time query slices | A role-annotated JSON table ties on these slices. In that case only the effect of roles is reported, and the graph is demoted to an implementation choice |
| RQ3 (context engine: assembly): Does assembly driven by evidence requirements beat fixed truncation? | Under the same token budget, requirement-coverage selection increases the full evidence hit rate and lowers the unsupported answer rate | An equal-budget BM25 plus dense fusion top-k achieves the same effect |
| RQ4 (context engine: view freshness): How fine-grained must the dependencies for staleness detection be, and at what cost? | Tracking only used claim IDs misses new matches, empty-to-non-empty transitions and count changes; detection derived from query patterns agrees with full recomputation, with less over-marking as dirty than predicate-level invalidation | These change types are extremely rare in natural dialogue; or read-time re-querying with fingerprints is equally accurate on all strata and not more expensive. In that case the conclusion narrows to "exact freshness checks are cheap; the listening pattern is just one implementation" |
| RQ5 (vocabulary): When is dynamic vocabulary extension worthwhile? | On unseen relation expressions and domain word-sense ambiguity, constrained local extension improves predicate alignment and query correctness | A frozen vocabulary plus alias retrieval is equally effective and cheaper; or schema bloat offsets the gains |

## 5. System design

The system has three layers: writes pass only through the graph memory layer, reads traverse the three layers top-down, and layers exchange data only through interfaces carrying version numbers and evidence IDs.

New messages are written only to graph memory; for each read, the context engine fetches claims and evidence from graph memory, assembles them into a cited working context, and hands it to the downstream LLM.

### 5.1 Components and data flow

| Layer | Component | Input and persistent state | Output |
| --- | --- | --- | --- |
| Graph memory | Message log | Original messages, speaker, message ID, receipt sequence number, available timestamps | Append-only writes; each message commits one version; retries are idempotent |
| Graph memory | Text index | Each message and its spans | BM25 suits entity names, numbers and identifiers; the dense index suits coreference and paraphrase |
| Graph memory | Claim graph | Entities, events, claims, attributions, evidence spans | Indexed by entity, predicate, event, validity period and version; only the currently accepted state is asserted |
| Context engine | Query planning and compilation | Current task, relevant vocabulary fragments, time and provenance requirements | Typed intermediate representation, SPARQL, matched claims and evidence sets |
| Context engine | View store | Query, rendered text, claims used, dependency patterns, cutoff version | Reusable messages with evidence; staleness markers |
| Context engine | Retrieval and assembly | Three-way candidates, existing views, token budget | Working context: task, recent raw text, verified state, evidence spans, open items, with per-item accounting |
| Downstream LLM | Reader and controller | Working context, output contract | An answer, a state, one supplementary retrieval request, or "unknown" |

Write path:

1. The raw text is appended to the log, and BM25 and dense indexes are built.
2. The writer extracts claim patches with span anchors.
3. A program performs structural validation and, according to role and exclusivity rules, decides whether to append, supersede, or keep in parallel.
4. The graph transaction commits and produces a change set.
5. Views affected by the change set are marked, and a new version is published.

Read path:

1. The task is parsed into an intermediate representation, listing required variables or evidence requirements.
2. Graph queries and text retrieval are executed, first binding the history identifier and the readable version.
3. Existing views are checked for usability; if stale, they are rebuilt or the system falls back to the raw text.
4. The working context is assembled within the budget.
5. The reader answers, and the evidence IDs used and the actual token usage are recorded.

When a graph write fails, reads may use the committed text index and explicitly mark the coverage; after the write is retried from the log, the new version is published atomically. While indexing is not yet complete, "not found" must not be treated as "does not exist".

### 5.2 Graph memory layer

The graph memory layer is append-only and never deletes: raw text is kept forever, supersession of a claim is expressed as closing its valid interval and knowledge version, and the state at any past moment can be read back.

**Objects a message can produce**

- **Episode** keeps the raw text. Each mention points to an entity, and each piece of evidence points to a specific span, speaker and claim.
- **Claim** is a proposition: event or subject, predicate, object, scope, valid time or interval, and ingestion and invalidation versions. When two messages state the same thing, they are merged into one claim node that keeps both pieces of evidence. Message retries do not increase the number of sources.
- **Attribution** connects a speaker with a claim and carries communicative function, polarity and certainty. When two speakers take opposite stances on the same proposition, each has its own attribution node; a denial does not create a second claim, and a change of stance is a new attribution rather than an overwrite.
- **Temporal expressions** are distinguished into three kinds: the order of messages, the world time reported by the source, and the reference time required by the question. When there is no natural date, only the order is kept and no absolute date is fabricated; for "last week", the original phrase and any available temporal anchor are stored.

**Roles have two axes.** The communicative-function axis takes the values request, proposal, acceptance, rejection, confirmation, inform, commitment and question, corresponding to the dialogue act inventory of ISO 24617-2. The reported-speech attribution axis takes the values own statement, quoting others, and hypothetical. The two axes are annotated separately: a sentence "he said he wants to book the Saturday train" is both an inform and a quoted request of someone else.

**Vocabulary mapping** (specific property names come from background knowledge and must be checked against each specification before implementation)

| Model element | Adopted vocabulary or practice | Notes |
| --- | --- | --- |
| Claim node | RDF 1.2 reifier (`rdf:reifies`), with an equivalent serialization in RDF 1.1 standard reification | The referenced triple is not asserted by default, which exactly expresses requests, proposals, quotations and hypotheticals. RDF 1.2 is not yet a W3C Recommendation and engine support is uneven, so the fallback is kept |
| Attribution and stance | GRaSP-style attribution nodes, with `prov:wasAttributedTo` pointing to the speaker | Polarity and certainty attach to the attribution, not to the claim |
| Communicative function | ISO 24617-2 communicative functions, built as a SKOS concept scheme | No official RDF version was found, so a concept scheme must be built and its correspondence documented |
| Task state | schema.org Action and reservation status; user constraints (e.g. "arrive by 20:45 at the latest") use local properties | A proposal is a pending reservation that becomes confirmed after acceptance; constraints always belong to the request |
| Provenance | PROV-O, including the model and prompt version used for extraction | Assistant restatements are marked as derived sources and do not count as independent support |
| Span anchors | NIF or Web Annotation selectors | Evidence points to a character range within a message |
| Valid time | OWL-Time; intervals are left-closed, right-open | Without dates, the message sequence number serves as the ordinal position |
| Knowledge time | PROV generation and invalidation times, mapped to version numbers | There is no W3C standard vocabulary for bitemporality; this is the plan's own mapping, and reads follow the version-materialization description from RDF archiving |
| Structural validation | SHACL shapes, validating only the claims touched by the current patch | Distinguishes domain/range inference, structural constraints and domain exclusivity rules |

**Change types and update operations**

| Message type | Handling on the graph | Read effect |
| --- | --- | --- |
| Reconfirmation of the same fact | Evidence is appended to the same claim; assistant restatements are marked as derived sources | Retrievable by source; restatements do not add independent support |
| Genuine state change | For the same subject, role and scope with an exclusivity rule, the old valid interval is closed and a new claim is added | Both the current and earlier states can be queried |
| Late correction | A correction is appended, recording the revised target and the past interval it applies to; the old knowledge snapshot remains readable | "What was known yesterday at the time" and "looking back at yesterday today" can differ |
| Request, proposal, acceptance | Separate attributions are created, and only the corresponding task state is advanced; a proposal does not close the request's constraints | Can answer both "what was originally required" and "what was finally chosen" |
| Coexisting multiple values | Without an exclusivity rule, parallel claims are kept | Reasonable answers are not deleted by "the latest sentence wins" |
| Contradictory evidence of unclear origin | Attributions of both sides are kept and the conflict is marked | Returns the conflict or reports unknown |

**Vocabulary: a stable core plus local extensions.** The core defines only basic concepts such as Person, Entity, Event, Request, Offer, Confirmation, Claim, Evidence and Time; it is frozen during development and shared globally. An alias table maps "arrive by" and "no later than" to the same constraint predicate. Only when a candidate predicate has no mapping or keeps producing type conflicts does the vocabulary-maintenance role propose an alias, a new predicate or a split; proposals are validated by a program before being committed, and a new predicate is first used provisionally within the current history. When the version changes, old definitions are kept, affected queries are recompiled, and all calls are billed as usual. An old value may be closed automatically only when the scope is the same and an exclusivity condition genuinely holds.

### 5.3 Context engine layer

The output of the context engine is a working context with stable citations; it guarantees that every fact in it can be traced back to the original messages, and it reports how many tokens were spent assembling it.

**Intermediate representation and compilation.** Query planning generates only an intermediate representation in a restricted grammar, e.g. `SELECT site WHERE deployment(service=Atlas, env=prod) AT(valid=d, known=r)`. A deterministic compiler turns it into parameterized SPARQL basic graph patterns, restricted aggregation and version filters. The grammar covers five kinds of operations: filtering, one- to three-hop joins, distinct counting, latest confirmed state, and provenance expansion. Tasks that rule templates can cover do not invoke an LLM; when parsing or type checking fails, the system falls back to text retrieval.

The query below asks for "the accepted train and its arrival time" on the version at the 6th message. It is written in RDF 1.1 standard reification; `ex:` is an illustrative local prefix, and `ex:knownFrom` and `ex:supersededAt` represent the generation and invalidation times mapped to version numbers.

```sparql
PREFIX ex:   <https://example.org/dialogue/>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?train ?arrives ?confirmation ?offer WHERE {
  ?c rdf:subject ex:request1 ; rdf:predicate ex:acceptedService ;
     rdf:object ?train ; ex:knownFrom ?r1 ; prov:wasDerivedFrom ?confirmation .
  ?a rdf:subject ?train ; rdf:predicate ex:scheduledArrival ;
     rdf:object ?arrives ; ex:knownFrom ?r2 ; prov:wasDerivedFrom ?offer .
  FILTER(?r1 <= 6 && ?r2 <= 6)
  FILTER NOT EXISTS { ?c ex:supersededAt ?s1 . FILTER(?s1 <= 6) }
  FILTER NOT EXISTS { ?a ex:supersededAt ?s2 . FILTER(?s2 <= 6) }
}
```

One answer to this conjunctive query depends on two messages at once: the user's confirmation and the system's proposal. The compiler projects both sources when constructing the query, so every answer carries its own evidence set. Counts are returned as "counted within the current observation scope", and empty results always state their evidence scope; exhaustive statements are supported only when source coverage is sufficient. The paper needs to state the SPARQL fragment the intermediate representation corresponds to, what it cannot express, and the proportion of each benchmark's questions that fall outside the fragment.

**Views.** A view is a five-tuple: the intermediate representation with its bound parameters, rendered text with per-sentence evidence, the claims used, the dependency patterns, and the cutoff version. If a summary sentence mixes several facts, each item carries its own evidence; summaries that cannot be reliably aligned serve only as recall cues. Views created at write time persist with the history; views created at answer time are discarded at the end of the question.

**Why dependencies must include query patterns.** When "which services Lina is responsible for" is cached, there is only Atlas, and the claims used contain a single edge. Later, "Lina also maintains Boreal" is added; the original edge is unchanged, yet the answer set has changed. So the view must also listen to the pattern `(Lina, maintains, ?service)`. Empty results, counts and top-ranked results are analogous: all depend on claims that may match in the future.

**Six strategies for staleness detection.** The system implements detection as a replaceable module, and the evaluation compares all six:

| Strategy | Approach | Expected weakness |
| --- | --- | --- |
| Never invalidate | A view is reused indefinitely once built | May answer wrongly after any update |
| Full rebuild every turn | All views are rebuilt after every new message | Correct but most expensive; serves as the equivalence reference |
| Used claim IDs only | Invalidate when a used claim is modified or retracted | Misses new matches, empty-to-non-empty transitions and count changes |
| Predicate-level | Invalidate on any write to a relevant predicate | Over-marks as dirty and rebuilds too much |
| Query-pattern dependencies | At write time, match the change set against each view's dependency patterns | Exact only for query grammars from which dependencies can be reliably extracted; other queries fall back to predicate-level |
| Read-time re-query with fingerprint | Re-execute the query at read time and rebuild only if the result fingerprint changed | Every read pays for a database query; not worthwhile when many views are resident |

The last two both wait until the next read to rebuild. Under this lazy strategy, both spend theoretically the same LLM tokens; the difference lies only in database computation and write-time overhead. This is exactly what RQ4 measures empirically. When detection is unreliable, the engine falls back to raw-text retrieval.

**Retrieval routing.** The engine first chooses channels using structural signals: identifiers favor BM25, paraphrases favor dense retrieval, and relational joins, timing, counting and corrections favor the graph; when confidence is insufficient, the hybrid channel is used. Routing rules, weights and thresholds are tuned only on the development set and compared against "always all three channels" and learned routing.

**Assembly driven by evidence requirements.** The engine first reserves the current task and necessary instructions, sets aside a window for the output, and then selects memory fragments by token:

1. List the required variables for this answer, e.g. "deadline, accepted train, the train's arrival time".
2. Map the candidates from BM25, dense and graph paths to unified evidence IDs and rank them initially with RRF; first filter by knowledge version, valid time, scope and role, then check which variables each candidate can support.
3. Within the budget, select greedily by "additional requirement coverage divided by additional tokens". One original sentence may cover several items; both ends of a two-hop path must be selected together.
4. If variables remain uncovered, expand one summary into raw text, or issue one additional restricted graph query. When the budget is exhausted, keep "unknown" or a partial answer, counted as a failure or abstention.
5. Serialize into a fixed layout: task, recent raw text, verified state, evidence spans, open items, output contract. Each fragment carries a stable citation.

The same set of facts can be presented as raw text, source spans, structured fact cards, or a local state summary. For "the train and its arrival time" versus "who confirmed it", the engine should return different working contexts.

### 5.4 Downstream LLM and role division

The downstream LLM sees only the working context and has no direct access to the graph or the log; this lets the same reader be applied unchanged to all baselines, so what is compared is the context itself.

The reader has four legal outputs: answer, output state, request one more retrieval, and report unknown. In offline evaluation, reporting unknown counts as missing or abstention, and follow-up questions or fabricated tool results do not count as success. Every final answer records all evidence IDs used.

LLM calls in the system switch templates by role and are, by default, served by the same model:

| Role | Layer | When called | Input and authorized output |
| --- | --- | --- | --- |
| Writing and entity alignment | Graph memory | Each message that requires extraction; structured tool events go through deterministic mapping | Current message, local context, candidate entities and predicates; outputs claim patches with span anchors |
| Vocabulary maintenance | Graph memory | A candidate predicate has no suitable mapping, persistent type conflicts occur, or mixed predicate usage causes validation failures | Candidate definitions, positive and negative examples, old versions; outputs proposals for aliases, new predicates or splits, committed after program validation |
| Query planning | Context engine | Rule templates cannot cover the current task | Question, relevant vocabulary fragments, time and provenance requirements; outputs a typed intermediate representation, variables to fill, and fallback channels |
| Verification and view rendering | Context engine | Program validation encounters ambiguity, or query results need to be rendered into a view | Query results, original sentences, budget; outputs a supported, conflicting or unknown judgment and text with per-sentence evidence |
| Reader | Downstream LLM | Every read | Working context and output contract; outputs an answer or state |

**How prompts are assembled.** Role instructions and the output JSON schema are fixed. At call time the following are concatenated as needed: the current vocabulary version, definitions related to the current entities and predicates, at most two validated examples, one relevant failure counterexample, and the remaining budget. For example, if "latest arrival" was once mistakenly written as "actual arrival", this counterexample can be reused in later writes within the same history.

**Constraints.** At test time, only program validation and raw-text support from the current history prefix are allowed; correcting prompts using the evaluator or answers is not allowed. At most one vocabulary proposal per message, and at most one compilation repair and one supplementary retrieval per read; the specific limits are frozen on the development set. All calls, retries and rereads are billed.

## 6. Evaluation protocol

All six benchmarks share the same system, each keeps its native read timing and answer target, and results are reported separately; each history gets its own store, questions are answered independently on the snapshot of the specified version, and writes are not shared across questions.

### 6.1 Benchmarks and terminology mapping

Datasets name the same layered structure differently; this plan uniformly calls the unit of memory a "history". LoCoMo's conversation refers to an entire independent history, roughly what some agent benchmarks and papers call a complete session; yet LoCoMo and LongMemEval also call the dated segments inside a history sessions. The mapping is given only here.

| Benchmark | One history (memory unit) | Segment within a history | Single message |
| --- | --- | --- | --- |
| LoCoMo | conversation (`sample_id`) | session (dated) | turn (`dia_id`) |
| LongMemEval | The chat history attached to each `question_id` | session (an independent timestamped conversation) | turn |
| MultiWOZ | dialogue (`dialogue_id`) | none | turn |
| HaluMem | All sessions of each user | session | turn |
| MemoryAgentBench | One context | chunk (fed chunk by chunk) | no uniform unit |

### 6.2 Benchmarks and read modes

| Benchmark | Store construction and reads | Primary metrics | Main questions served |
| --- | --- | --- | --- |
| Controlled change sequences (self-built) | Natural English dialogues with a program event log as ground truth, covering six change types; readable after every message | Precision and recall of staleness detection, answer agreement with full recomputation, rebuild tokens | RQ4 |
| MultiWOZ 2.4 (main) and 2.2 (auxiliary) | Each dialogue is initialized independently and written incrementally message by message; each user turn sees only the prefix at that time and predicts the cumulative state | Accuracy on turns that accept a proposal, original-constraint recovery rate, stale-value misuse rate; overall JGA and slot F1 as references | RQ2, RQ4 |
| LoCoMo | One store per history, independent QA on the final snapshot; about 150 questions per history | token-F1 and calibrated blind-judged accuracy; evidence recall; curve of cumulative tokens versus number of reads | RQ1, RQ3 |
| LongMemEval S (cleaned version) | One question per history; ingest all sessions, keep `question_date`, mask `has_answer` and `answer_session_ids` | Accuracy from the official GPT-4o per-question-type judge; session-level and turn-level evidence recall | Adverse setting for RQ1, RQ3 |
| HaluMem-Medium | Ingest segment by segment; score extraction and updates against gold memory points and update labels | Operation-level accuracy of extraction and updates, QA accuracy | RQ2, RQ4, graph quality |
| MemoryAgentBench | Context fed chunk by chunk; after everything is fed, answer several questions about the same context; includes the fact-conflict task FactConsolidation | Accuracy per capability dimension; curve of cumulative tokens versus number of reads | RQ1, RQ4 |

Key points for each benchmark:

- **Controlled change sequences.** The six change types are: modifying or retracting a cited claim, new match, empty to non-empty, count or ranking change, late correction, and irrelevant update. They also include "alternatives proposed but not confirmed" and paired "known then / looking back now" questions. The program event log provides ground truth, semantics are spot-checked by two annotators, and splits are made by template family. High scores on synthetic data do not replace results on natural benchmarks. The survey found no dialogue memory benchmark with explicit bitemporal questions, so this part must be self-built.
- **MultiWOZ.** The test set has 1,000 dialogues and 7,372 user turns. The predictor projects the internal graph onto the official slots, and the same projection is provided to all systems with structured internal state. The state in 2.4 mainly reflects what the user said, consistent with the design "requests are not overwritten by proposals", so it serves as the main evaluation; 2.2 writes system-proposed values into the state and is used to show how the projection rules depend on annotation conventions. Later turns are not read, and gold states are not backfilled.
- **LoCoMo.** The public file contains 10 histories and 1,986 questions. Following the official evaluation code, category 1 is multi-hop (282 questions), 2 is temporal (321), 3 is open-domain (96), 4 is single-hop (841), and 5 is adversarial (446). The main evaluation uses categories 1 to 4, 1,540 questions in total; conv-26 and conv-49 serve as the development set (308 questions), and the other 8 are held out (1,232 questions). If category 5 is evaluated for abstention, it is reported separately with an explanation of the self-defined judging method. Inputs uniformly exclude images, image captions and human-written summaries; questions whose answers appear only in image captions are reported separately.
- **Gold-label quality of LoCoMo.** An independent audit claims that 99 of the 1,540 questions have wrong answers, and another 57 have wrong evidence annotations. The audit is not peer-reviewed, but its per-question list is public. The plan spot-checks that list and reports both all 1,540 questions and the 1,441 questions remaining after removing the 99.
- **LongMemEval S.** 500 questions, each with its own history of about 115k tokens. Stratified by question type and abstention label, about 20% is used for development and 80% held out, and the actual lists are published. Each history has only one question, which is the least favorable setting for amortizing write cost, and the plan reports this truthfully. The histories exceed the native window of the main model, so the full-history baseline is handled by a second, long-context reader.
- **HaluMem-Medium.** 20 users, each with about 70 sessions and about 160k tokens. It provides per-segment gold memory points, update labels and links to replaced memories, so the write path can be scored separately from QA. The license is CC BY-NC-ND 4.0, so re-annotated subsets cannot be released.
- **MemoryAgentBench.** Context lengths range from 100k to 1.44M tokens, fed incrementally with multiple questions per context, which suits drawing break-even curves; it also takes the evaluation beyond two-party dialogue, matching the "agents" in the title. Its fact-conflict task consists of synthetic counterfactual edits, and results are reported separately.
- **Conditional additions.** STALE and Memora directly test the use of stale memory. Whether their data has been released and under what license is not yet confirmed; once confirmed usable, they will be added, replacing the generic "current value after update" part of the controlled sequences.

### 6.3 Metrics

Metrics are computed separately for each of the three layers, so that "was it stored correctly", "was it provided correctly" and "was it answered correctly" can be attributed separately.

$$
\mathrm{Acc}=\frac{1}{|I|}\sum_{i\in I}J(q_i,g_i,a_i),\qquad
\mathrm{Recall}_i=\frac{|R_i\cap e_i|}{|e_i|},\qquad
\mathrm{Full}_i=\mathbf 1[e_i\subseteq R_i]
$$

| Layer | Metrics | Notes |
| --- | --- | --- |
| Graph memory (stored state) | Claim precision, recall and F1; structural validation conformance rate and number of retries; whether the cited span entails the claim; accuracy of role and time fields; proportion of restatements treated as independent evidence; answer coverage upper bound | Computed on sampled annotations and HaluMem gold memory points; MultiWOZ ships with dialogue act annotations, so roles can be checked directly |
| Context engine (context presented to the reader) | Evidence recall and full hit; precision and recall of staleness detection; agreement of views with full recomputation; proportion of stale content entering the prompt; parse failure rate and rate of fallback to text retrieval | Retrieval candidates and the evidence actually presented to the reader are counted separately |
| Downstream LLM (final answer) | Accuracy Acc ($J$ is a preregistered binary semantic judgment); token-F1; JGA and slot F1; unsupported answer rate; stale-value misuse rate; abstention correctness | Each benchmark keeps its native metrics, plus a unified blind-judged accuracy |

**Evidence recall is reported under two definitions.** The strict definition counts a hit only when the original sentence enters the prompt; the lenient definition credits derived items via provenance links. One audit shows that this choice changes ranking metrics for the vast majority of queries and flips system rankings, so both are reported, together with how each baseline's evidence set is extracted. Annotated evidence may list only one set of usable sources, so alternative sources are manually verified on a pre-drawn sample to avoid misjudgment.

**Judge calibration.** The blind judge fixes the model snapshot and prompt, and adds "deliberately wrong vague answers" as negative controls. The same LoCoMo audit reports that the commonly used gpt-4o-mini judge accepts 62.81% of such answers. All systems use the same fixed answering prompt, because the answering prompt alone can shift the same reader's accuracy by about 10 points.

**Stratified reporting.** Results are stratified by token-length quantile of the history, revision frequency, actual number of reads per history, and number of segments covered by annotated evidence, and regions where the system does not dominate are reported explicitly. Stratification labels are used only on the scoring side.

### 6.4 Leakage prevention and validation

Questions, reference answers and evidence annotations are invisible at write time. Other rules:

- All baselines share the same dates and visible information; for any experiment that artificially shortens the input history, the results table states the visible range and the selection criteria.
- Temporary views, compilation repairs and generated answers from answer time are discarded at the end of the question and not appended to the history.
- Two question orders are compared on a sample with fixed decoding, checking that index versions and per-question input evidence are consistent.
- Perfect extracted graphs, perfect intermediate representations and gold evidence appear only in clearly labeled error upper-bound experiments.
- Roles, time filters, raw-text citations and execution results of intermediate representations are checked on a manually annotated subset.
- Splits, exclusion reasons and per-category counts are frozen and published.

### 6.5 Statistical analysis

The main analysis uses question-level paired tests plus a model with history as a random effect, with per-cluster differences and leave-one-cluster-out as sensitivity analyses.

- **LoCoMo has only 8 held-out clusters.** A two-sided sign test needs all 8 histories to agree in direction to reach p ≈ 0.008; with 7 in the same direction, p ≈ 0.07. Even treating the 1,232 questions as independent samples, the half-width of the 95% interval is about 1.7 to 2.2 points at accuracies between 80% and 90%. Therefore no 1-percentage-point non-inferiority is claimed on LoCoMo.
- **Criterion for matched quality.** Non-inferiority margins are preregistered during development according to each benchmark's sample size; when the data cannot support them, only confidence intervals of paired differences are reported and no equivalence is claimed. Statistical power comes mainly from LongMemEval, HaluMem and MultiWOZ.
- **Small subsets are descriptive only.** LoCoMo's open-domain has only 96 questions; LongMemEval's single-session preference and abstention questions have 30 each, leaving about 24 held out after splitting.
- **Uncertainty is reported by source.** Repeated judge runs, answering prompt, reader, sampling error and label noise are given separately, not only the first.
- **Clustering units.** LoCoMo by conversation, LongMemEval by evaluation instance with checks for highly overlapping histories, MultiWOZ by dialogue, HaluMem by user, and MemoryAgentBench by context.

## 7. Models, baselines and ablations

All comparisons fix the same reader, the same answering prompt and the same set of context budgets; the only thing that varies is "how the context given to the reader was produced".

### 7.1 Model configuration

| Setting | Choice | Rationale and caveats |
| --- | --- | --- |
| Main model | Qwen3-8B, serving as writer, planner, renderer and reader; thinking disabled, chat template and tokenizer frozen | Same backbone as ProgMem and ReacTOD, which eases comparison. Native context of 32,768 tokens |
| Decoding | Temperature 0 | The model card recommends T=0.7 for non-thinking mode; choosing 0 is a deliberate deviation for reproducibility, with sensitivity under the recommended setting reported separately |
| Second, long-context reader | An open-weight model that can hold the full LongMemEval S history, candidate Qwen3.8-27B | Handles the full-history baseline on long histories and rechecks the effect of model scale. The candidate's license and context length are checked against the model card before adoption |
| Recheck with a contemporary small model | A newer open-weight model of the same size class as the main model | Qwen3 was released in April 2025, and several generations of open-weight models have followed; the main conclusions need to be replicated on a newer model |
| Writer scale | On a preregistered stratified subset, replace both the writer and the reader with a large model | Estimates the write bottleneck; only scale effects within the same model family are claimed |
| Embeddings | Qwen3-Embedding-0.6B; the query instruction string is frozen and published | BM25 uses the same tokenization and chunking; for shorter histories, cosine similarity is computed exactly without an approximate index |
| Reranking | No cross-encoder in the main configuration | Avoids misattributing reranking gains to the graph; reranking is a separate comparison group, turned on for all methods simultaneously |
| Compute and judging | Local 8×B200 processing multiple independent histories in parallel; external APIs are used only for independent blind judging and disagreement rechecks | APIs take part in no graph-update decision |

Score expectations are calibrated to the small-model range. With 7–8B backbones, training-free systems reach token-F1 of roughly 25 to 38 on LoCoMo (PVLDB unified reproduction; ProgMem), which is not the same yardstick as the 85 to 94 obtained with frontier models plus LLM judging.

### 7.2 Baselines

| Category | Baseline | Explanation to rule out |
| --- | --- | --- |
| Text | Full history with the same reader; last-k; truncation to the same budget | A shorter complete raw text may already be optimal. When the full text exceeds the window, the proportion is disclosed rather than silently truncated |
| Text | BM25, dense, and their RRF fusion; rolling summary plus recent raw text | Strong text recall or compression alone explains the gains |
| Text | RAG tuned with the LongMemEval recipe: turn-level storage, facts merged into index keys, time-aware query expansion, Chain-of-Note reading | The contribution of reader-side techniques. These techniques are given to the other comparisons as well |
| Text | Raw-text search agent: reads the log using only grep, search and open | Letta reports that such an agent with gpt-4o-mini scores 74.0% on LoCoMo (LLM-judged, vendor report) |
| Structured comparison | A role-annotated JSON state table with the same fields, including provenance and allowing equivalent joins; exact key-value or slot cache | Structured fields or caching alone suffice; if reliability is equal, implementation complexity and execution cost are compared |
| Structured comparison | A fixed-schema temporal graph using the same three-way index and reader | Whether a dynamic vocabulary and views are needed |
| Structured comparison | A same-backbone "append-only, resolve conflicts at query time, no caching" system | Whether persisted views are necessary. This is the most suitable opponent on the cost question |
| External systems | Mem0 and Mem0g; LightMem; a hierarchical system usable with 7B models (e.g. MemOS) | Common references in recent comparison tables; LightMem is the reference for write-token efficiency |
| External systems | Graphiti, with the adaptation and failure rate published, plus a separate row with its native backbone | Its small-model performance is contradictory in the literature: Zep's LoCoMo token-F1 is 33.82 in one reproduction (Qwen2.5-7B) and 13.82 in ProgMem's table (Qwen3-8B) |
| MultiWOZ-specific | ReacTOD; deterministic overwrite updates based on official slots; the same reader directly outputting the cumulative state | ReacTOD reports 47.34 JGA (with a validation loop) and 39.29 (single pass) zero-shot with Qwen3-8B on MultiWOZ 2.1 |
| MultiWOZ-specific | Supervised D3ST, listed separately | Additional training is disclosed and not merged into the training-free ranking |
| Paper reference only | APEX-MEM, ProgMem | No code was found for either. When quoting scores, backbone and metric are noted, and they are not treated as same-protocol results; if code is released later, they are rerun with the same backbone |

### 7.3 Ablations

| ID | Only factor changed | Most informative readout | Corresponding question |
| --- | --- | --- | --- |
| A | The six staleness detection strategies (Section 5.3), stratified by the six change types; run once each on the gold graph and the extracted graph | Detection precision and recall, answer agreement with full rebuild, rebuild tokens, database time; how much of the gain the extracted graph retains relative to the gold graph | RQ4 |
| B | With or without roles × JSON table or graph | Accuracy on turns that accept a proposal, original-constraint recovery rate; differences on the connection, counting and point-in-time query slices | RQ2 |
| C | Graph recall on/off × role and time verification on/off over the same candidates | Path evidence recall versus stale-value misuse; prevents attributing verification gains to retrieval | RQ2 |
| D | Fixed top-k or RRF truncation versus assembly driven by evidence requirements; expandable pointers versus summaries only | Full evidence hit rate, unsupported answer rate, final prompt and total tokens | RQ3 |
| E | Raw-text window, rolling summary without provenance, views with provenance; display budget controlled | Quality at equal budget, write cost of compression, wrong citations | RQ1, RQ3 |
| F | Remove BM25 and dense recall separately; total candidates and returned tokens fixed | Unique contribution of each channel: identifiers, numbers and long-tail entities versus natural-language paraphrase | RQ3 |
| G | Rule routing, always all three channels, learned routing | Quality and cost per read | RQ1, RQ3 |
| H | Last-value overwrite without roles, roles with single time, roles with bitemporality | MultiWOZ confirmation turns, original-constraint recovery, paired accuracy on controlled late corrections | RQ2, RQ4 |
| I | Frozen vocabulary, frozen plus aliases, local vocabulary evolution; additionally, dynamic examples and counterexamples disabled under the same schema; compared with the EDC pipeline and a DIAL-KG-style incremental strategy | Predicate linking accuracy on unseen expressions, schema bloat rate, prompt cost; separates the contributions of vocabulary and prompts | RQ5 |
| J | Single structured call, fixed role routing, conditionally triggered roles; total call budget matched | Trigger precision, end-to-end cost, parse failure and recovery rate; rules out gains from mere multiple sampling | RQ1 |
| K | Writer scale: main model versus large model | Changes in graph quality metrics and downstream quality | Feasibility |

All ablations control samples and budgets and report interactions between components. In order of execution, A, B and E come first, because they determine whether the core claims hold.

## 8. Cost accounting

Main results use the cache-adjusted accounting, and cost differences are interpreted only on quality-matched pairs.

### 8.1 Accounting rules

- Input and output tokens are recorded per call, covering extraction, validation, vocabulary, planning, rendering, retries and answering. Failed attempts are counted as well.
- When tool or query results enter the next prompt, they are counted in that call's input.
- Each method reports three ledgers: logical tokens, tokens actually computed after prefix-cache reuse, and GPU seconds.
- Embedding encoding tokens, database CPU, memory, p50 and p95 latency, and number of tool calls are listed separately.
- Blind-judging calls are listed separately as evaluation overhead and are not counted in system cost.
- Equal token counts from different models are not interpreted as equal prices.
- All methods use the same cache-friendly prompt layout: stable content first, question-dependent content last.
- The reader's memory-fragment budget takes four levels: 256, 512, 1,024 tokens and the actual full history; system instructions, the current question and output reservation are fixed, and the real total input is published separately.

### 8.2 Formulas

Fix one history and $M$ independent questions. The cost of the full-history baseline under no-cache and cache accounting, and the cost of this system:

$$
T_{\mathrm{full}}=M\,H+\sum_{i=1}^{M}\bigl[L(q_i)+L(g_i)\bigr],\qquad
T_{\mathrm{full}}^{\mathrm{cache}}=H+c\,(M-1)\,H+\sum_{i=1}^{M}\bigl[L(q_i)+L(g_i)\bigr]
$$

$$
T_{\mathrm{sys}}=W(\mathcal H)+\sum_{i=1}^{M}\bigl(U_i+A_i\bigr),\qquad
M^{*}=\left\lceil \frac{W}{\Delta}\right\rceil
$$

$H$ is the token count of the serialized history; $c$ is the ratio of cache-hit input to full price, using the measured compute ratio for local inference and the billing ratio for APIs. $W$ is the LLM tokens used for extraction, graph construction, vocabulary and view maintenance in one complete ingestion; $U_i$ is planning, verification and repair for question $i$; $A_i$ is the input and output of the final answer. $\Delta$ is the number of tokens per question by which the cache-adjusted full history exceeds this system; when $\Delta$ is non-positive there is no break-even point. For tasks with per-turn reads (MultiWOZ), $W$ is replaced by the sum of the incremental write cost per turn, and the full-history baseline is computed on the actual prefix length at each turn.

### 8.3 Results to report

- **Quality versus total tokens curves.** Compare accuracy at equal budget; compare average tokens at similar quality.
- **Break-even curves.** On the same snapshot, draw different numbers of independent questions with fixed seeds, reuse the same write, plot cumulative tokens against number of reads, and report the intersection at which the quality threshold is reached. The opponents are full history with prefix caching, query-time resolution without caching, and the raw-text search agent.
- **Cost per successful task.** Total cost including failures divided by the number of successes, with the success rate attached; undefined if there are no successes.
- **Maintenance cost versus revision density.** Vary revision frequency on the controlled sequences and report rebuild tokens for each staleness detection strategy.
- **Before/after caching comparison.** The same set of results is reported once under each accounting, showing how sensitive the conclusions are to the caching assumption.

### 8.4 Design constraints implied by the accounting

The two items below are rough estimates from figures in the literature, not measurements, used to set the order of magnitude of the write budget.

- **LoCoMo.** About 150 questions per history, about 20k to 25k tokens to read the full text per question; without caching, the full-history side totals about 3M to 4M input tokens. If cache-hit input is counted at 10%, this amounts to only 300k to 400k. So the writer's budget per history should be kept on the order of 100k tokens.
- **LongMemEval.** Each history has only one question, so a method whose write cost exceeds about 115k tokens cannot break even on tokens. What must be compared here is quality and reader window usage; the plan does not claim end-to-end token savings on this benchmark.

"Counting writes" and "break-even number of questions" have published precedents, citing Pollertlam and Kornsuwannawit, the unified evaluation study, and MERIT with per-operation billing. This plan's increment is limited to four items: quality-matched comparison, cost per successful task including failed attempts, maintenance cost under updates, and before/after caching comparison on open small models. Write costs reported by other papers are not directly quoted for comparison, because the accounting for the same system can differ by an order of magnitude across papers; all baselines are re-measured under the same accounting.

## 9. Implementation phases and scope of conclusions

Implementation has seven phases, each ending with a checkpoint; when a checkpoint fails, the corresponding claim is narrowed instead of adding more components.

| Phase | Work | Output | Checkpoint: what to do if the following occurs |
| --- | --- | --- | --- |
| 1. Pilot measurement | Run full history, text retrieval, rolling summary and the JSON state table on each benchmark's development histories; fix English prompts, counters, budgets and the judge | Distribution of history lengths, cost of completing tasks with the full text, measured cache ratio, natural update density (how often an already-rendered view is read again after an invalidating update) | Natural update density is very low: state that view maintenance targets high-revision workloads, and base RQ4 mainly on MultiWOZ, HaluMem and the controlled sequences |
| 2. Core mechanism on the gold graph | Implement the claim model and validation shapes, the intermediate representation compiler, views and the six staleness detection strategies; compare full rebuild and local rebuild turn by turn on the gold graph given by program logs or annotations | Gold-graph results of ablation A; new matches, empty to non-empty, confirmations not overwriting original constraints, and late corrections must be handled correctly | Query-pattern dependencies do not beat used-claims-only on the new-match stratum, or read-time re-query is equivalent across the board: RQ4 narrows to "freshness checks are cheap" |
| 3. End-to-end extraction and planning | Turn on the writer and query planning; count extraction errors, planning errors and compilation failures separately | Graph quality table; extracted-graph results of ablation A; ablation K | Most of the gain disappears with the extracted graph: the conclusion changes to "the bottleneck is extraction and key alignment", reporting how much a large writer recovers |
| 4. Context assembly and baselines | Implement retrieval routing and assembly driven by evidence requirements; integrate all baselines; get the three ledgers working | Ablations B to H; quality versus token curves on the development set | The role-annotated JSON table ties with the graph: report only on which joins or scopes the graph adds value |
| 5. Vocabulary evolution | When the frozen vocabulary genuinely has naming conflicts, add the conditionally triggered vocabulary role | Ablations I and J | Frozen vocabulary plus aliases is equally effective: the main configuration switches to the frozen vocabulary, and the dynamic vocabulary is reported as a negative result |
| 6. Lock-in and formal evaluation | Freeze configuration, splits, judging rules and budgets, and preregister non-inferiority margins; run the held-out sets of the six benchmarks and all baselines | Three tables: formal benchmarks, controlled probes, manual audit; break-even curves | No further tuning after lock-in; every deviation from the preregistration is disclosed item by item |
| 7. Rechecks | Second long-context reader, contemporary small model, recommended decoding settings, reranking on/off | Whether the primary conclusions and key failure modes hold under other configurations | The conclusions hold only on the main model: limit the scope of applicability truthfully |

### 9.1 Scope of conclusions

- If only the reader input is reduced while end-to-end tokens increase, the conclusion narrows to "improved window utilization".
- If the role-annotated JSON state table matches the graph, report only on which joins or scopes the graph adds value.
- If bitemporality yields gains only on synthetic data, claim only that the system can handle the mechanism.
- If the full text is generally optimal for short histories, present "when to enable graph memory" as an empirical result; similar findings have already been reported, so this serves only as corroborating evidence.
- All performance improvements, absolute run times and API costs remain to be measured; the plan does not presuppose any values.

## 10. Risks and mitigations

The biggest risk is the extraction quality of the small-model writer, which would simultaneously drag down graph memory and every conclusion that depends on it.

| Risk | Evidence or symptom | Mitigation |
| --- | --- | --- |
| Unreliable writer extraction | Small models have high format error rates in structured writing; most systems miss many of the updates they should make | Output constrained by JSON schema and structurally validated; keep the raw-text path on failure; graph quality in its own table; gold graph and extracted graph reported separately; use a large writer to estimate the upper bound |
| Query planning errors | Systems in which the LLM writes SPARQL directly fail on entity binding, silent empty results and missing aggregation | Generate only a restricted intermediate representation; type checking; empty results state their evidence scope; on failure, fall back to text retrieval and count it in the fallback rate |
| The full-history baseline wins | Short histories fit in the window, and reading the full text is often the strongest row | Stratify by history length and number of reads; explicitly report regions where the system does not dominate; state conclusions as conditions of applicability rather than general superiority |
| No gain from the graph over flat structures | At small scale, flat memory and graph memory have nearly identical accuracy | 2×2 design of role and representation; look for the graph's value only on the connection, counting and point-in-time query slices |
| Too few changes in natural dialogue | LoCoMo has no knowledge-update questions | Measure natural update density first; RQ4 relies mainly on MultiWOZ, HaluMem, MemoryAgentBench and the controlled sequences |
| Benchmark label noise and lenient judges | LoCoMo gold labels contain errors; commonly used judges accept vague wrong answers | Report under both definitions; judge negative controls; fixed answering prompt; uncertainty reported by source |
| External baselines run too weakly | Graphiti's scores with small models vary widely in the literature | Publish adaptation, versions and failure rates; keep a row with the native backbone; separate native tables from same-backbone tables |
| Mispositioning of the closest work | Several 2026 preprints have been read only at the abstract level | Before writing the paper, read the full texts of PACMI, MemoRepair, MemTX, Kumiho, ProgMem and APEX-MEM, and check whether code is public |
| Standards not yet stable | RDF 1.2 and SPARQL 1.2 are not yet W3C Recommendations, and engine support is uneven | Define the model once, providing both RDF 1.2 and RDF 1.1 serializations; queries are executable under RDF 1.1 |
| Data license restrictions | LoCoMo is CC BY-NC 4.0; HaluMem prohibits derivatives | Release only split lists, scripts and pointers to annotation differences; do not redistribute re-annotated data |

## 11. Reproducibility and sources

All data statistics cited in this plan can be recomputed from the original files; the hashes below correspond to the verified statistics or the original example files.

### 11.1 Data files and counts

| Original file | SHA-256 | License |
| --- | --- | --- |
| LoCoMo `locomo10.json` | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` | CC BY-NC 4.0 |
| LongMemEval `longmemeval_oracle.json` | `821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c` | Repository is MIT |
| MultiWOZ 2.2 `test/dialogues_001.json` | `d6f43876cf130fdb2dfa8f96bc056b0995354137f02122e004925d01264ed386` | Repository is MIT; license of the data itself to be verified |
| MultiWOZ 2.2 `test/dialogues_002.json` | `89af95d8f596a448e733d59b31be78f1dd1632eddd99d5cb298a3fcb1ac9d185` | Same as above |

- **LoCoMo counts.** Build a `dia_id` dictionary per `sample_id`. All 1,986 questions can be verified as 446 (category 5) plus 1,201 (evidence within the same segment) plus 326 (evidence across segments) plus 13 (evidence missing or not fully resolvable). The latter 13 questions are kept in answer evaluation and removed from the denominator of evidence metrics.
- **LongMemEval.** The main experiments use `longmemeval_s_cleaned.json`; its hash, split lists and the per-`question_id` history overlap audit are published with the formal run manifest.
- **HaluMem and MemoryAgentBench.** HaluMem is CC BY-NC-ND 4.0; MemoryAgentBench's data is CC BY 4.0 according to its paper. File hashes for both are registered at first download.

### 11.2 Materials released with the paper

- The claim model's vocabulary, validation shapes and examples of both serializations.
- The intermediate representation grammar, the compiler and all query templates.
- Prompts, output schemas and frozen decoding settings for each role.
- Split lists, exclusion reasons and per-category counts.
- Per-call records of the token ledger and aggregation scripts.
- The generator, event logs and spot-check records of the controlled change sequences.
- Versions, adaptation patches and failure rates of the external baselines.

### 11.3 References

Entries marked "abstract" have been read only at the abstract level; entries marked "preprint" are not peer-reviewed.

**Memory systems and closest work**

- Zep: A Temporal Knowledge Graph Architecture for Agent Memory. arXiv 2501.13956 · Graphiti
- APEX-MEM: Agentic Semi-Structured Memory with Temporal Reasoning for Long-Term Conversational AI. ACL 2026
- ProgMem: Programmatic Belief-State Memory for Long-Horizon Conversational Agents. Findings of IJCNLP-AACL 2026
- Mem0 and Mem0g. arXiv 2504.19413
- LightMem. arXiv 2510.18866
- PACMI (preprint). arXiv 2610.05732
- MemoRepair (preprint, abstract). arXiv 2605.07242
- MemTX (preprint, abstract). arXiv 2607.23929
- Kumiho (preprint, abstract). arXiv 2603.17244
- GroundedCache (preprint, abstract). arXiv 2605.27494
- Does Memory Need Graphs? (preprint). arXiv 2601.01280
- Anatomy of Agentic Memory (preprint). arXiv 2602.19320
- Unified reproduction study of memory systems. arXiv 2604.01707
- Letta, Benchmarking AI Agent Memory (vendor blog). letta.com

**RDF dialogue memory, querying and standards**

- Vossen et al., Leolani. arXiv 1806.01526
- An and Gentile, RDF-based dialogue memory. CEUR Vol-4210
- Martin, Unbehauen and Auer, SPARQL query caching (2010, full text not read). Springer
- Incremunica. Paper
- SPARQLprov. PVLDB 2021
- BEAR: query types for RDF archiving. Project page
- W3C, SPARQL 1.1 Query Language. Recommendation
- W3C, PROV-O: The PROV Ontology. Recommendation
- W3C, Shapes Constraint Language (SHACL). Recommendation
- W3C, RDF 1.2 Concepts and Abstract Syntax (not yet a W3C Recommendation). TR

**View maintenance and dependency tracking**

- Gupta and Mumick, survey of materialized view maintenance (1995). dblp
- DBSP. PVLDB 2023
- Doyle, A Truth Maintenance System (1979). MIT
- Adapton. PLDI 2014
- Agrawal, Chaudhuri and Narasayya, Automated Selection of Materialized Views and Indexes for SQL Databases. VLDB 2000

**Vocabulary and knowledge graph construction**

- Extract, Define, Canonicalize. EMNLP 2024
- AutoSchemaKG. ACL 2026
- DIAL-KG (preprint). arXiv 2603.20059

**Dialogue state tracking**

- TripPy. arXiv 2005.02877
- ParsingDST. arXiv 2310.10520
- ReacTOD (preprint). arXiv 2605.19077
- Description-Driven Task-Oriented Dialog Modeling (D3ST). arXiv 2201.08904

**Benchmarks and evaluation methodology**

- Evaluating Very Long-Term Conversational Memory of LLM Agents (LoCoMo). ACL 2024 · Data
- Independent audit of LoCoMo (not peer-reviewed). GitHub
- LongMemEval. ICLR 2025 · Code · Data
- MultiWOZ 2.2. Paper · Data
- MultiWOZ 2.4. Paper · Data
- HaluMem. arXiv 2511.03506 · Data description
- MemoryAgentBench. arXiv 2507.05257
- STALE (preprint, abstract). arXiv 2605.06527
- Memora. Findings of ACL 2026
- Same Ranking, Different Winner: an audit of what evidence scoring counts. Findings of EMNLP 2026
- Pollertlam and Kornsuwannawit, break-even analysis with cache discounts (preprint). arXiv 2603.04814
- Unified evaluation study of memory methods. IJCNLP-AACL 2026
- MERIT (preprint, abstract). arXiv 2609.05441

**Models**

- Qwen3-8B. Model card
- Qwen3-Embedding-0.6B. Model card
