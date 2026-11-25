# GRACE: A Graph Memory–Enhanced Context Engine with Query-Defined Views over Bitemporal RDF for LLM Agents

Nov 23, 2026 · @Yongli

## 1. Overview

GRACE stands for **GR**aph memory–enh**A**nced **C**ontext **E**ngine.

In LLM agent systems, the conversation history is cumulative, but the state it describes keeps changing: later messages may revise, invalidate, or supersede earlier information. This plan studies one problem: when is the context derived from that history and handed to the LLM still valid, when must it be rebuilt, and is maintaining a graph for this purpose worth its cost? The method adds a structured graph channel on top of hybrid lexical and dense retrieval, and maintains reusable derived context as query-defined views.

The plan is written to meet the review criteria for research papers at peer-reviewed Semantic Web conferences: relevance to the Semantic Web, novelty, rigour, design and execution of the evaluation, and reproducibility. It also assumes their format, a self-contained main text of 15 LNCS pages. It is not tied to a particular submission deadline. Section 9.3 marks out a minimal publishable core. The part of the core that is complete at the end of phase 2 is released as a preprint, and work outside the core is done as capacity allows.

### 1.1 Context is a scarce resource

An agent's conversation history grows without bound, while the context window available at each step is limited. Larger windows help only in part: compute and cost per call grow with input length; models use long inputs unevenly, and accuracy drops when the relevant information sits in the middle of the input; and the effective context length is often far shorter than the nominal one. Passing the whole history to the LLM at every step is therefore expensive and not guaranteed to be the most accurate option.

### 1.2 Existing approaches and their limitations

Existing systems reduce the input to the LLM in three ways.

| Approach | What it does | How it fails when the conversation state keeps changing |
| --- | --- | --- |
| Compression | Condenses the history, or its older part, into a shorter text: rolling or recursive summaries, hierarchical paging, automatic compaction built into agent frameworks, token-level prompt compression | A summary does not record which part of the history each of its sentences depends on. When a new message revises a fact the summary relies on, the summary becomes wrong and the system cannot tell; the only safe remedy is a full rewrite. Compression is also lossy: details it drops cannot be recovered from the summary |
| Retrieval | Keeps the history in an external store and, at each step, retrieves a few passages, typically by fusing BM25 and dense rankings | A system offer and a user request are close both lexically and semantically, and ranking cannot tell which of them sets the current constraint. Questions about sets, counts, the latest state or the state at a past time require combining scattered evidence, and a ranked list of passages does not guarantee that all of it is retrieved |
| Structured memory | Extracts facts into memory entries, state tables or graphs and queries them when a question arrives | Most systems invalidate an old fact only when a new fact conflicts with it directly, and do not track whether content derived from those facts is still correct. A new statement often overwrites an old one regardless of who made it and whether it is the kind of statement that should change the state |

These failure modes highlight three fundamental limitations: derived context goes stale without any signal; attribution is lost; and scattered evidence is not brought together.

### 1.3 Method in brief

The method has two parts.

| Part | Content | Research focus |
| --- | --- | --- |
| Graph channel | An append-only, bitemporal RDF claim graph. Claims are extracted from messages and are not asserted by default. Each claim carries a valid time and a knowledge version, and is linked to its evidence spans and to attributions that record the speaker and the communicative function. A task is translated, through a typed intermediate representation, into a query in a restricted SPARQL fragment, and the results are fused with lexical and dense candidates | Whether the speaker and the communicative function of a statement should determine which earlier claims it may supersede; on which question types the graph channel improves accuracy |
| Query-defined views | Each view is defined by a query. The query result is turned into text with evidence cited for every sentence, by template serialisation or LLM rendering, and the view records its cut-off version. After each new message is committed, the system uses the defining queries to decide which views are stale. At the next read, sentences whose answers changed are regenerated, and a program patches the citations of sentences whose evidence alone changed. When staleness detection fails, the engine falls back to raw text | The definition and detection of staleness; whether LLM rendering is needed instead of template serialisation; when maintaining views is cheaper than recomputing at every read |

GRACE is a context engine for LLM agents. A full agent has further modules, such as a control loop and tools (connected, for example, through MCP); this plan sets them aside and studies only how the context is built from the conversation history.

GRACE has two layers. The memory layer stores the raw history with its text indexes, the claim graph and the views. The pipeline layer runs the write path, which updates the memory after each message, and the read path, which assembles the working context for the current task. GRACE sends the working context to an LLM through an API, and the LLM generates the answer from this context alone. The LLM may be a hosted proprietary model or a self-hosted open-weight model, such as OpenAI's GPT models or Qwen; the experiments use open-weight models (section 7.1). The layers describe the architecture (section 5); the research questions follow the two parts above and cost.

### 1.4 Two goals and three claims

GRACE pursues two goals at once. The first is to match or improve on the task accuracy of the full-history, compression and hybrid-retrieval baselines. The second is to reduce end-to-end token cost, counting every LLM call, failed attempts included, on the write side (extraction, vocabulary maintenance, view rendering) and on the read side (planning, verification, answering).

**Illustrative example (fictional).** Six messages are ingested, and two questions follow.

| Version | Speaker | Message |
| --- | --- | --- |
| 1 | User | I live in Munich. |
| 2 | User | Please book me a train to Berlin on Saturday, arriving by 18:00 at the latest. |
| 3 | Assistant | ICE 947 leaves at 12:10 and arrives at 17:25. Shall I book it? |
| 4 | User | Yes, that one. |
| 5 | User | By the way, I moved to Cologne on 1 November and forgot to mention it. |
| 6 | User | I live in Cologne now, so on Saturday I leave from there. |

Write side, paid while the six messages are ingested:

| LLM call | When | Tokens |
| --- | --- | --- |
| Extraction | Once per message, six calls | 6 × 400 = 2,400 |
| Extraction, failed attempt | The output for message 3 violates the JSON schema and is redone | 400 |
| Vocabulary maintenance | "Leave from" in message 6 has no predicate, and a new one is proposed | 300 |
| View rendering | Three resident views: original constraints, current choice, current residence | 3 × 150 = 450 |
| Total, $W$ | | 3,550 |

Structural validation, SPARQL queries and citation patches are run by programs and cost no LLM tokens.

Read side, paid per question:

| Question | Planning | Verification | Answering | Total |
| --- | --- | --- | --- | --- |
| "When does the train I chose arrive?" | 0 (covered by a rule template) | 0 | 250 | 250 |
| "Does that train meet my original requirement?" | 300 | 200 | 300 | 800 |

End to end, with $U_i$ the planning and verification tokens and $A_i$ the answering tokens of question $i$ (section 8.2):

$$
T_{\mathrm{sys}} = W + \sum_i (U_i + A_i) = 3{,}550 + 250 + 800 = 4{,}600
$$

Most of this is paid on the write side before any question arrives, which is why a comparison that counts only the answering prompt is misleading. On a dialogue this short GRACE loses: the full history is about a hundred tokens, and giving it to the LLM for both questions costs a few hundred. Write cost is recovered only on long histories that are read many times (section 8.2).

There are three core claims, each paired with results that would overturn or narrow it (section 4):

- **The gains of the graph channel are concentrated on specific question types.** Added to hybrid retrieval, it improves accuracy on attribution-sensitive state tracking, aggregation, multi-hop joins and point-in-time queries, and ties with hybrid retrieval alone on single-passage lookup. The plan does not claim that a graph beats a relational table with the same fields: the two encode the same information and differ only in the engine. RDF serves here as a standards-based representation, and its expected value lies in open predicates, standard vocabularies and interoperability.
- **Staleness is determined by the defining query.** A dependency that records only the claims a view used detects the supersession of those claims but misses three kinds of change: a new claim that matches the query, a write that supersedes nothing but matches a negated condition (an acceptance, for example), and a change in the members of an aggregate. Matching each write against the claim patterns of the defining query (section 3.3), including those inside negation and aggregation, misses none of them, at the price of marking some views that are not stale.
- **At matched quality, maintained views are cheaper in end-to-end tokens in the regime where the history contains revisions, is read many times and the context budget is tight.** Outside that regime, giving the LLM the full history, or resolving conflicts at query time without stored views, is the better choice, and the plan reports the regions where GRACE does not win. The claim rests on a premise: the answering LLM answers more accurately from an LLM-rendered view than from a template serialisation of the query result. If the premise fails, there is no expensive artefact worth caching and the claim does not hold.

The plan also allows for negative results and prepares for two of them in advance. First, the answering LLM answers as accurately from template-serialised fact cards as from LLM-rendered views: every read then simply re-runs the query, and the paper becomes one about "a staleness criterion plus computing at query time", with no claim that maintained views are cheaper. Second, read-time re-query, which re-runs the defining query at every read and is exact with respect to the claim graph, costs no more than matching at write time: the conclusion narrows to "exact staleness checks are cheap; the bottleneck is extraction and rendering". Figures reported in recent preprints make the second outcome likely.

## 2. Background and related work

Provenance links, bitemporality, distinguishing statements by speaker and communicative function, cascading invalidation along dependency edges, and cache invalidation by triple pattern all have precedents. Two 2026 preprints have also treated derived memory as views over evolving data. The gap this plan addresses is therefore narrow: a definition of staleness at two levels, answers and citations, for which phase 0 found only partial precedent (section 4.1); a formalisation, on an append-only bitemporal RDF graph, of an invalidation condition derived from the defining query; and an evaluation on natural dialogue with a complete token ledger. The granularity of that condition is not part of the gap: it is finer than refreshing everything derived from a changed source, but the pattern-matching rule behind it comes from SPARQL query caching. The novelty check in phase 0 (section 9) found no dependency key of this granularity in the agent-memory literature, and the plan claims no novelty for it (sections 3.4 and 4.1).

Most of the 2026 work cited here exists only as preprints that have not been peer reviewed. Section 11.3 records how closely each entry was read: in full, at abstract level, or not yet. An entry without a mark was not read specifically for this plan, and its original text is read before any specific result from it is cited. At least five related preprints appeared in the two months before this plan was written, so the literature search must be repeated before the paper is finalised. In phase 0, Martin et al. (2010) and the appendices of MemShift were read in full, and two dedicated searches were run: one on the incremental maintenance of provenance and lineage, and one on materialised views maintained by LLMs. The item-by-item comparison and the search records are in `docs/research/literature.md`.

### 2.1 Closest work and how this plan differs

| Direction | What the closest work already does | How this plan differs |
| --- | --- | --- |
| Temporal graph memory | Zep/Graphiti: edges carry two timelines and trace back to episodes; an LLM judges conflicts and invalidates old edges; community summaries are updated when nodes are added and corrected by periodic full refresh | The speaker and the communicative function of a statement decide whether it may supersede an earlier claim; what is invalidated is a derived view, under an explicit staleness criterion |
| Append-only storage with query-time resolution | APEX-MEM: an entity-centred property graph with facts attached to dated events; conflicts are resolved at read time, with no caching | Views are stored and kept fresh; "no cache, resolve at every query" is treated as the most direct competitor on cost |
| Programmatic state memory | ProgMem: compiles dialogue events into state-update programs and validates evidence; evaluated with Qwen3-4B/8B/14B on the 1,540 LoCoMo questions | This plan adds query-defined views and their rebuilding, and comparisons of evidence recall and cost |
| Cascading invalidation of derived memory | PACMI: dependency edges come from annotation; only the replacement of a single value in the same slot triggers invalidation, and a new member of a set does not. MemoRepair: the only events are deletion, correction and migration; there is no insertion. MemTX: rolls back along a derivation graph and states that it covers only recorded sources. Kumiho: impact analysis along dependency edges, invoked explicitly by the agent. Tether (Dependency-Tethered Memory): a verified conclusion records the versions of the objects it relies on, and the LLM writer records them only when the relation is inside its context window. At every read, a reachability pass over the whole store, without an LLM call, withdraws a conclusion whose support has failed or has a higher version on record; there is no mechanism for changes to sets and counts. Edge recall falls to 0.84 and 0.66 when the relation is stated in a separate session before or after the verdict, respectively, and storing the withdrawals at write time was less safe than recomputing them at read time, because later writers read the stored values. StateMem: state units carry typed `derived_from` and `coupled_with` links recorded by an LLM at ingestion; a deterministic rechecker propagates only from units whose status has just changed and flags their dependents for recheck, so a new unit that supersedes nothing triggers no recheck. StateGraph: states carry derived-from and depends-on edges that an LLM proposes and verifies. Invalidation starts from direct revision, which matches an incoming state to existing states by canonical slot or functional key, and only new status changes propagate further, along strict edges. A new state that matches no existing slot, such as a new member of a set, therefore triggers nothing; there is no mechanism for counts or aggregates | In all of these the dependency points to records or versions the derived object has already consumed. In this plan the dependency is the set of claim patterns of the defining query, which also catches new records that the view never consumed |
| Diagnoses of derived memory as views | MemShift: finds that citation-based dependency keys miss 16.9% of changed items after a source revision and 32.4% after a redefinition, and traces the cause to the phantom problem of predicate locks; coarse source keys miss nothing but invalidate more than 99% of unchanged items; it also evaluates definition-scope keys, gold keys and a "do not store, compute at query time" arm. MemDerive: a benchmark that expresses derived state as views over database tables, with Datalog gold including aggregation and minimal why-provenance witnesses; memory systems refresh 82.4% of explicit changes and only 41.1% of implicit ones | Both use template-synthesised data and neither uses RDF or SPARQL. MemShift's definition-scope key is a fingerprint of the records a definition ranges over: the range is hand-coded per definition, has no per-entity constants, ignores aggregates and thresholds, changes with any field revision of an in-range record, and is recomputed at maintenance checkpoints. The claim-pattern dependency is derived from the query by the compiler and matched against each write, with constants, attribution constraints and local filters, including patterns inside negation and aggregation. With constants and local filters it is finer than the scope key, but not more sound: both catch records that enter a view's range. It follows the pattern-matching principle of Martin et al. (next row), lifted from single triple patterns to claim patterns (one reified star with an attribution constraint). The principle is not claimed as new, and the lift is an implementation detail. The difference lies in the formalisation on an append-only bitemporal RDF graph, two-level staleness and the evaluation on natural dialogue with noisy extracted graphs |
| Query cache invalidation | Martin, Unbehauen and Auer's SPARQL query cache (2010): a cached result is invalidated when an inserted or deleted triple matches any of the query's triple patterns, and application objects rendered from cached results are invalidated with them; a proposition proved by structural induction shows the rule sound for AND, OPTIONAL, UNION and FILTER, so it already covers a non-monotone operator. Williams and Weaver (2011): HTTP cache validation by the last update time of an index, close to predicate level. Incremunica: incremental maintenance of SPARQL results, already supporting FILTER NOT EXISTS, MINUS, GROUP BY and ORDER BY | This plan adopts the pattern-matching invalidation rule and its compositional soundness argument and claims neither as new. What is cached is a text view with evidence cited for every sentence and a bitemporal scope; staleness has two levels, answers and citations; only a staleness decision is needed, not an incremental result, because the expensive step is LLM re-rendering. Martin et al. state no exactness conditions and do not cover NOT EXISTS, counting, latest-state selection or version-bounded reads |
| Read-time re-validation | GroundedCache: re-retrieves at read time and checks whether the overlap of chunk hashes exceeds a threshold. Dynamic data citation (RDA recommendation, revised 2025): timestamped queries are re-executed against the current data, and a checksum of the result set decides whether the result changed | GroundedCache compares the top-k results of vector retrieval, and dynamic data citation fingerprints only the result set. This plan compares exact fingerprints of the answers, witnesses and evidence of deterministic queries |
| LLM-computed views in databases | Enzyme (incremental view maintenance at Databricks) falls back to full recomputation for AI functions; Motion treats prompts as views under weak consistency; semantic-operator systems (LOTUS, Palimpzest, DocETL and others) optimise the cost of each query and do not handle base-data updates | This plan decides the staleness of LLM-rendered views from their defining query and confirms it by fingerprints before re-rendering |
| RDF dialogue memory | Leolani/GRaSP: claims, mentions and per-speaker attribution (polarity, certainty). An and Gentile: RDF plus PROV-O, with SPARQL written directly by an LLM | This plan adds update handling, a typed intermediate representation, empty results annotated with their evidence scope, and evidence sets returned by construction |
| Speaker and communicative function | TripPy's system-inform memory; ParsingDST's separate User/System tables. MemIR names "source-role collapse"; one study reports a fact-contamination rate of 0.543 between same-named speakers when sessions share a store. StateGraph's extractor records the claimant and a claim mode (direct, reported, assumption, intent, advice), which is close to this plan's reported-speech axis, but it has no communicative function such as offer or acceptance | Existing evidence supports only the point that it matters who made a statement. That the communicative function should guard which earlier claim may be superseded has to be shown by this plan itself |
| Dynamic vocabularies | EDC, AutoSchemaKG, DIAL-KG: relation canonicalisation, schema induction and incremental evolution, all on documents | This plan tests, on dialogue and with a small model, whether a constrained local extension of the vocabulary is worth its cost |
| Cost evaluation | Pollertlam and Kornsuwannawit: payback analysis with cache discounts. A unified evaluation study: build and query tokens amortised per question. APEX-MEM, ProgMem, LightMem, MemTX, MemShift, MemDerive and Tether all report write-side tokens; Tether also gives a break-even against verifying everything. StateGraph reports only the total tokens of all calls per case; StateMem reports only the number of encoder calls | Write-side cost is commonly reported. This plan adds: quality-matched comparisons, cost per correct answer including failed attempts, maintenance cost under updates, and a before-and-after-caching comparison on small open-weight models |
| Controlled revision benchmarks | StateMemBench's anti-update probes (synthetic event programs, 322 graded probes); StateGraph's StateChangeBench (50 author-constructed cases stratified by cascade depth, one new observation per case, gold status per state); the controlled revision generator of Deng et al.; STALE's premise-resistance probes | None of them has bitemporal paired questions or per-message view-invalidation ground truth |

### 2.2 Known adverse evidence

The results below determine what the evaluation must guard against; the plan does not sidestep them. Scores from different papers are obtained with different backbone models and judges and are not directly comparable.

- **Full history is a strong baseline.** In Mem0's own table, GPT-4o-mini given the full history reaches an LLM-judged accuracy of 72.90 on LoCoMo, above the 68.44 of Mem0's graph variant (the latter figure is to be re-checked).
- **Graph structure gains little at small scale.** With the same extractor, Llama-3.1-8B on LongMemEval-S scores 0.614 with flat memory and 0.620 with graph memory (Does Memory Need Graphs?).
- **LLMs writing SPARQL directly are unreliable.** An and Gentile's system reaches 11% to 15.6% accuracy, while the full-context baseline in the same paper scores 0.326 on LongMemEval-S; the authors name NL-to-SPARQL as the main bottleneck. This supports the use of a restricted intermediate representation with deterministic compilation.
- **Small models are weak at structured writing.** In one comparison, Nemori's format-error rate rises from 17.91% with gpt-4o-mini to 30.38% with Qwen-2.5-3B. HaluMem reports that most systems miss more than half of the updates they should make.
- **Computing at read time may be enough.** MemShift's query-time view arm costs only 246 extra answering tokens per query and 56.7K write-side tokens per world, against 319.7K ingestion plus 1.3M maintenance for stored approaches. In this plan, views are defined by deterministic queries; re-running them at read time and comparing fingerprints costs no LLM tokens. The plan makes this a first-class arm and the exact reference of ablation A (section 7.3).
- **Coarse invalidation is not necessarily worse.** In Tether's experiments a global flush, which withdraws every passing verdict recorded before the latest failure, is as safe as Tether's exact edges at one or more hops, at about 0.2 more verification calls per candidate; flushing only objects that share a fact with the failed one catches one hop and misses the rest. The data are synthetic and the failures arrive late and together, which the authors note favours the flush.
- **The benefit of detection is capped by repair ability.** MemShift reports that small open-weight writers correctly re-derive at most 25% of changed items, against at least 91% for exact recomputation. In this plan, view content comes from deterministic queries and the LLM only renders it. Ablation C tests this design choice separately, and also tests template serialisation, which uses no LLM rendering at all.
- **Reference scores for small models are unstable.** Two preprints report 50.83 and 71.10 LLM-judged accuracy for Qwen3-8B answering from the full LoCoMo history (the second figure was read only at abstract level and is to be re-checked). Answer prompts and judges must therefore be fixed and disclosed, and baseline numbers from other papers are not used for comparison.

### 2.3 Theoretical foundations

- **Irrelevant updates and query–update independence.** Blakeley, Coburn and Larson give necessary and sufficient conditions for irrelevant updates to select–project–join views and note that "an update that is not irrelevant does not necessarily affect the derived relation". Levy and Sagiv show that independence is undecidable in general, use query reachability as a sufficient condition, and point out that the condition of Blakeley et al. applies only to conjunctive queries without repeated predicates. Any basic graph pattern with two or more triple patterns is a self-join over the triple table, so exactness does not carry over to RDF unchanged.
- **Incremental view maintenance.** Gupta and Mumick survey the field; Motik et al. give maintenance algorithms with correctness theorems for Datalog materialisations with stratified negation; DBSP gives a general incrementalisation method; Incremunica implements incremental evaluation of non-monotonic operators in a SPARQL engine.
- **Monotonicity.** Well-designed SPARQL patterns are weakly monotone, and semantic weak monotonicity is undecidable (Arenas and Ugarte). The query fragment of this plan contains negation, counting and latest-state selection and is not in the weakly monotone fragment, so a conservative syntactic check is used.
- **Provenance.** Witnesses in this plan follow why-provenance, that is, the set of minimal witnesses. The semiring framework for how-provenance and its extensions to non-monotone queries (spm-semiring, SPARQLprov) and to aggregation (semimodules) serve as background. SPARQLprov does not cover aggregate functions. Maintaining provenance under updates is also established: ORCHESTRA maintains provenance relations with their own deltas, and absorption provenance propagates a change of provenance without a change of the tuple as its own event. Neither treats such a change as a level of staleness of a derived artefact.
- **Versioned RDF.** BEAR classifies queries into version materialisation, delta materialisation and version queries. In that vocabulary a read at a cut-off version is a version-materialisation query and the staleness decision is a Boolean delta-materialisation query. Bitemporal RDF has models such as BiTRDF and Bi-VAKs, but no standard vocabulary.
- **Dependency tracking and view selection.** Doyle's truth maintenance system and Adapton for dependency tracking; the view-selection work of Agrawal et al. for the question of which views are worth storing.

## 3. Problem formalisation

This section gives the notation, the definition of staleness, one observation and one proposition. In the main text of the paper it takes about one page; the full proofs, the list of fragment assumptions and the refinements of the decision strategies go to the supplementary material.

### 3.1 History, versions and reads

The input is a conversation history that arrives message by message. At any moment the system must be able to answer a question or output a state using the memory visible at that moment, and to cite the original messages it relied on.

$$
\mathcal H=\langle h_1,\dots,h_N\rangle,\qquad
\mathcal M_r=\mathrm{Write}(\mathcal M_{r-1},h_r),\qquad
(g,R)=\mathrm{Read}(\mathcal M_r,q)
$$

| Symbol | Meaning | Use in the experiments |
| --- | --- | --- |
| $h_t$ | The $t$-th message, with speaker, original ID and any available time metadata | Unit of the raw log; evidence is aligned by original message ID |
| $\mathcal H$ | The full history; $L(\mathcal H)$ is its serialised token count | Full-history baselines and memory systems receive the same information |
| $\mathcal M_r$ | Memory after message $r$ is written: raw log, text indexes, claim graph $G_r$, views | Each message commits one version; a read sees only its stated version |
| $q$ | A read task arriving at version $r$: one question or one state request | Reference answer $a$ and annotated evidence $e$ are held by the evaluator |
| $g$, $R$ | The answer the LLM produces from the working context; the set of evidence message IDs actually included in that context | Answer quality and evidence quality are scored separately |
| $W$, $U$, $A$ | LLM tokens for the write side, for planning, verification and repair on the read side, and for answering | Cost ledger, section 8 |

A question's world time and its snapshot cut-off version are specified separately. "What was known then" and "what was the case then, as known now" are two different reads.

A **read point** is a pair (version, read task). Section 6.1 explains why the placement of read points decides which of the plan's research claims a benchmark can test.

### 3.2 Claim graph and bitemporality

At the abstract level the claim graph contains four kinds of entries, each with a version stamp.

- **Claim** $c=(s,p,o,\omega,\tau,\kappa)$: subject, predicate, object, scope, valid time or interval, knowledge version $\kappa(c)$. The knowledge version is the version number of the message that first produced it. A claim is the proposition itself and does not record who stated it.
- **Attribution** $a=(u,c,f,\rho,\pi,\gamma,\kappa)$: one stance of speaker $u$ towards claim $c$, with communicative function $f$ (request, offer, accept, reject, confirm, inform, commit or question; section 5.2), report mode $\rho$, polarity $\pi$, certainty $\gamma$ and knowledge version.
- **Evidence link** $(c,m,\kappa)$: claim $c$ is supported by message span $m$, visible from version $\kappa$ on.
- **Supersession event** $(c,\sigma,\eta)$: from version $\sigma$ on, claim $c$ is no longer the currently accepted state. The kind $\eta$ is *change* or *correction*. A change says that the world changed: $c$ held until then and remains part of the past state. A correction says that $c$ was mistaken: from $\sigma$ on it is excluded from the past state as well.

The graph is append-only: $G_r\subseteq G_{r+1}$. The entries added at version $r+1$ are of these four kinds only, and all carry the stamp $r+1$. Hence every version stamp in $G_{r_0}$ is at most $r_0$, and every version stamp in $G_r\setminus G_{r_0}$ is greater than $r_0$.

When a proposition is mentioned again, no new claim is created; only an attribution and an evidence link are added. An offer by one party and its acceptance by the other are two attributions on the same claim.

**Attribution guard.** A new claim $c'$, introduced with attribution $a'$, supersedes an existing claim $c$ only if all of the following hold: $c$ and $c'$ have the same subject, predicate and scope, and the predicate has an exclusivity rule; some attribution on $c$ has the same speaker and the same communicative function as $a'$; and the report mode of $a'$ is own statement. Otherwise both claims are kept. In particular, conflicting statements by different speakers are both kept and the conflict is marked.

**Assumption on vocabulary and entity identity.** The results of this section assume that the vocabulary (predicates, aliases, exclusivity rules) and entity identities do not change between a view's cut-off version and the read version. When the vocabulary version changes or two entities are merged, queries are recompiled and the matching of claim patterns changes with them; such a change is not one of the four kinds of entries. The system handles it in the most conservative way: every view of that history is invalidated (section 5.2). The number of such events and the rebuild cost they cause are reported separately.

Valid time $\tau$ says when a fact holds in the world; knowledge and supersession versions say when the system knew it. The two time dimensions are independent.

### 3.3 Query fragment

Views and reads use the same restricted query fragment. Its atom is a **claim pattern** $(s,p,o,\omega)[u,f]$. The first four positions match a claim and are constants or variables. The attribution constraint in brackets is optional and requires an attribution on that claim with speaker $u$ and communicative function $f$. A pattern with an attribution constraint can be matched by a new claim, and also by a new attribution on an existing claim.

The fragment allows six kinds of operation:

- filters (comparisons with constants and valid times);
- joins over up to three claim patterns;
- negation: NOT EXISTS over one claim pattern that shares variables with the positive part, without nesting;
- distinct counting;
- selection of the latest confirmed state (the maximum by version or valid time);
- provenance expansion (projecting the claims and evidence an answer relies on).

"Currently accepted" is a built-in negation: the claim matches and there is no supersession event with version at most the cut-off. Current-state queries carry it. Historical queries carry a weaker form that excludes only claims superseded by a correction, so a claim superseded by a change stays visible as past state. General negation serves queries such as "candidates offered and not yet accepted": the positive part is a pattern with an offer attribution, and the negated part is a pattern on the same claim with an accept or reject attribution.

The fragment excludes property paths, uses a fixed default graph and assumes simple entailment. Filters compare only with constants and with the valid time carried by a claim; comparison with the time of reading (such as "in the last week") is not allowed, because such a view would go stale without any write. A task with relative time is converted to an absolute interval at compile time and runs only as a temporary query while answering; it is not stored as a view.

A query is parameterised by its cut-off version, written $Q[r]$: it sees only entries with version stamp at most $r$. A read at version $r$ evaluates $Q[r]$ on $G_r$.

**Time-travel stability.** For any $r\ge r_0$, $Q[r_0]$ has the same result on $G_r$ as on $G_{r_0}$, because entries appended later carry version stamps greater than $r_0$ and are filtered out by the parameter. A read at a past version therefore never goes stale; staleness can occur only for reads whose cut-off moves forward over time. This also relies on the assumption on vocabulary and entity identity in section 3.2.

### 3.4 Views and staleness

A **view** has six components: a query template $Q$ with its bound parameters, a cut-off version $r_0$, text with evidence cited for every sentence, the claims and attributions used (witnesses), the evidence cited, and the dependency patterns.

**Answers, witnesses and evidence.** $\mathrm{ans}(Q[r],G_r)$ is the answer set. The witness $\mathrm{wit}$ of each answer is defined by these conventions:

- The positive join part uses why-provenance: all minimal witnesses that make the answer hold. Each minimal witness is a set of claims and of the attributions that satisfy attribution constraints; an answer can have several minimal witnesses.
- Negated conditions have no witnesses; an answer's witnesses come only from the positive part.
- The witness of a distinct count is the union of the witnesses of the counted members.
- The witness of a latest-state selection is the witness of the selected answer.

$\mathrm{ev}$ is the union of the evidence links, visible at the cut-off version, of the claims in the witnesses.

**Definition (two-level staleness).** At version $r\ge r_0$, a view with cut-off version $r_0$ is

- **answer-stale** if and only if $\mathrm{ans}(Q[r],G_r)\neq\mathrm{ans}(Q[r_0],G_{r_0})$;
- **citation-stale** if and only if the answers are unchanged and $(\mathrm{wit},\mathrm{ev})(Q[r],G_r)\neq(\mathrm{wit},\mathrm{ev})(Q[r_0],G_{r_0})$.

There are two levels because the repair costs differ. When a view is answer-stale its text must be regenerated. When it is citation-stale the content is unchanged and only the sentence-level citations are incomplete. The most common case is a fact being mentioned again: the set of claims is unchanged and one evidence link is added, and natural dialogue contains many such repetitions. Every sentence of the text is bound to result rows (section 5.4), so citation staleness is repaired by a program that patches the citations, without an LLM call.

The scope note attached to empty results and counts ("within the scope observed up to version $r$") is not part of the view content. A program generates it at read time from the current version and it does not enter the staleness definition; otherwise every write would make such views stale.

**Observation (witnesses alone are not enough).** A policy that invalidates a view only when a claim it used is superseded does catch the supersession of a used claim, because the supersession event points to exactly the claims the view used. It misses three kinds of change:

- A new match: the view "which services Lina is responsible for" has one answer, Atlas; the new claim "Lina maintains Boreal" is written, the old claim is untouched, and the answer set gains a member.
- A write that supersedes nothing but matches a negated condition: the view "candidate trains offered and not yet accepted" has answer TR7143; the user's acceptance of TR7143 is a new attribution on that claim. It supersedes nothing, but it matches the negated condition and the answer disappears.
- A change in aggregate members: the view "number of instruments mentioned" is 1; a new instrument claim arrives and the count becomes 2.

The first case has been measured (MemShift). The last two can be caught by a stronger citation-based policy that, besides the used claims, also watches the claim patterns inside negation and aggregation. That stronger policy still misses new matches of views without aggregation. The evaluation includes it as a separate arm (section 5.4), so that the citation-based baselines are compared in their strongest form.

More generally, in an append-only graph every change is an insertion. A citation-based dependency sees only the insertions that point at entries the view has already consumed (supersession events). It does not see insertions that fall inside the scope of a negation or an aggregate, such as an acceptance or a new member. Invalidation caused by insertions outside the consumed entries is therefore the normal case on such a store, not an edge case.

**Proposition (soundness).** Let $\Delta=G_r\setminus G_{r_0}$, and let the vocabulary and entity identities be unchanged between $r_0$ and $r$. If in $\Delta$

- no new claim or new attribution matches any claim pattern of $Q$ (including patterns inside negated conditions and aggregations), and
- no supersession event points to a claim that matches a claim pattern of $Q$,

then the view is not answer-stale at version $r$ and its witnesses are unchanged. If in addition no evidence link in $\Delta$ points to a claim that matches a positive pattern of $Q$, the view is not citation-stale either.

Proof sketch: structural induction over the query algebra. Under these conditions every claim pattern has the same matches on $G_r$ and $G_{r_0}$; $Q[r]$ and $Q[r_0]$ differ only in the version bound, and since every version stamp in $G_{r_0}$ is at most $r_0$, both bounds accept the same entries. The proposition is an instance of query–update independence and extends Proposition 1 of Martin et al. (2010), which proves the same invariance for one inserted or deleted triple over AND, OPTIONAL, UNION and FILTER by the same compositional argument. The extension covers NOT EXISTS, distinct counting, latest-state selection, reads bounded by a cut-off version, claim patterns with attribution constraints as the matching unit, and the witnesses and evidence of a view. Each step is routine; the main text gives a short proof and says that it is routine.

**Matching unit (implementation note).** Under RDF 1.1 standard reification a claim is encoded as a group of triples (one each for subject, predicate, object and knowledge version). If matching were done per triple pattern, every new claim would carry a knowledge-version triple matching the same pattern in every query, and the decision would degenerate to "every write invalidates". Matching is therefore done on claim patterns (one reified star). With RDF 1.2 triple terms the subject, predicate and object of a claim form one term, but the knowledge version is still a separate triple on the reifier, so matching is done on claim patterns there as well. This is an implementation note, not a contribution.

**Exactness and limits.**

- The decision is exact, meaning a view is marked if and only if its answers or witnesses change, when all of the following hold: the query has one positive claim pattern, possibly with local filters; it contains the "currently accepted" negation; it has no selection operator and no aggregation; no matching new claim in $\Delta$ is superseded again within $\Delta$; and the claim a supersession event points to was not already superseded at $r_0$.
- Outside these conditions the decision over-approximates. Three examples: with latest-state selection, a new matching claim with an earlier valid time changes neither answers nor witnesses; a historical query excludes only corrected claims, so a supersession event of kind change does not alter its result; an already superseded claim is superseded again.
- Joins over-approximate: a new claim matches one pattern but has no join partner. Patterns inside negated conditions also over-approximate: the matching entry may not correspond to any current answer.
- Exact instance-level decision is equivalent to incremental evaluation or re-evaluation; re-querying at read time with fingerprints of answers, witnesses and evidence is the exact reference. Exact static decision is undecidable in general.

**Ladder of decision strategies.** Predicate level ⊇ claim-pattern level ⊇ claim pattern with local filters ⊇ read-time re-query. No rung produces false negatives; further down the ladder there is less over-marking and each check costs more. The false-positive rate of each rung on dialogue workloads is measured experimentally. The two citation-based strategies (used claims only; used claims plus negation and aggregation patterns) can miss staleness and are not on the ladder.

**Not claimed.** A new invalidation algorithm; the first soundness result for SPARQL cache invalidation; complexity results; an incremental maintenance algorithm; "provenance-based invalidation is incorrect in general" (for monotone queries it is correct under deletion). Claim-pattern granularity is not claimed as new: it follows the pattern-matching principle of Martin et al., lifted from single triple patterns to claim patterns, and the lift is an implementation detail (see the matching-unit note above). Phase 0 found no dependency key in the agent-memory literature at this granularity; the closest sound key, MemShift's definition-scope key, applies a definition's condition and window but has no per-entity constants, fires on any field revision of an in-range record and is recomputed at checkpoints, so it is coarser than claim patterns with constants and local filters (section 2.1).

### 3.5 Three running examples

**A multi-valued predicate must not be overwritten by the "latest value" (new answer).** In LoCoMo conv-26, Melanie mentions playing the violin at D2:5 (2023-05-25) and the clarinet at D15:26 (2023-08-28). The test question asks which instruments she plays; the reference answer counts both. The writer produces two `playsInstrument` claims with provenance; when the second is written the first is unchanged, yet the view "instruments Melanie plays" is already stale. Keeping only the latest edge, or watching only the claims already used, misses an answer. If Melanie later mentions the violin again, the set of claims is unchanged and one evidence link is added: the view is only citation-stale, and a program patches the citation.

**An offer must not overwrite a request (attribution).** In MultiWOZ SNG0296.json, at turn 0 the user asks to arrive by 20:45 at the latest; at turn 5 the system offers TR7143 (departs 19:48, arrives 20:38); at turn 6 the user accepts and asks for a reference number. The "original arrival requirement" is always 20:45; the "current choice" becomes TR7143 only after turn 6. The MultiWOZ 2.2 annotation records `train-arriveby` as 20:38 here, while 2.4 keeps 20:45; whether the two versions follow this convention in general for values offered by the system is checked on the data in phase 1 (section 6.5).

**An acceptance makes a candidate disappear (non-monotone).** In the same dialogue, after turn 5 the view "candidates offered and not yet accepted" has answer TR7143. The acceptance at turn 6 is a new attribution (user, accept) on the claim introduced by the offer at turn 5; no claim is modified or superseded. Yet it empties that view and changes the view "current choice" from empty to TR7143. Both views must be rebuilt although none of the claims they used was superseded.

## 4. Contributions and research questions

The novelty lies in two-level staleness for views and its formalisation, the controlled evaluation of the graph channel, and the cost evaluation; most elements of the claim model are a reasoned combination of existing practice.

### 4.1 Contributions

1. **Claim and evidence model.** An append-only, bitemporal RDF claim graph based on standard vocabularies. Claims are not asserted by default; only the currently accepted state is asserted. Attributions record the communicative function (one of the eight values of section 5.2, such as request, offer and accept) and the report mode as two separate axes, and both serve as guards in the supersession rules. The guard is the one element of the model that this plan has to validate itself (RQ1). RDF acts as a standards-based representation (PROV-O, SHACL, OWL-Time, RDF 1.2 reifiers); the plan does not claim that it beats a relational table with the same fields.
2. **Query-defined views and their staleness criterion.** Staleness at two levels, answers and citations, where citation staleness needs no LLM; the three kinds of change that citation-based dependencies miss, with the observation that in an append-only graph all three are insertions outside the entries a view has consumed; a soundness proposition that extends the triple-pattern rule of Martin et al. to negation, counting, latest-state selection and witnesses, with exactness conditions covering four kinds of writes (claims, attributions, evidence, supersession); a comparison of eight decision strategies on dialogue workloads, including two arms that have not been evaluated in the agent-memory invalidation literature retrieved so far (LLM-free read-time re-query with fingerprints, and push filtering with read-time confirmation); and a measurement of how often each kind of staleness occurs in natural dialogue.
3. **A verifiable path from task to working context.** A deterministic compiler from a typed intermediate representation to a SPARQL fragment that projects evidence sets by construction and annotates empty results and counts with their evidence scope; fusion of graph results with lexical and dense candidates; assembly of source sentences and fact cards within a budget, driven by evidence requirements.
4. **Quality-matched end-to-end cost and layered diagnosis.** A comparison of three sources of view content (template serialisation, LLM rendering, LLM rewriting), which decides whether cached views are needed at all; cache-adjusted payback curves and a maintenance-cost surface over revision density and read count; cost per correct answer including failed attempts; a staleness-detection evaluation stratified by change type, with decision misses and extraction-induced misses counted separately; a comparison between gold and extracted graphs; and a direct evaluation of the extracted graph itself.

Provenance links, bitemporality, separating requests from offers, the pattern-matching cache-invalidation rule with its soundness argument and the pattern-matching principle behind claim-pattern dependencies (Martin et al.), and local repair are presented as adopted practice and are not claimed as novel. Phase 0 applied the checkpoint of section 9: the granularity of claim-pattern dependencies is already covered by earlier work, so the novelty of contribution 2 rests on two-level staleness, the formalisation on an append-only bitemporal RDF graph and the evaluation. Two-level staleness has partial precedent only in provenance maintenance (section 2.3), where none of the works read defines it as a level of staleness. This assessment rests on uneven reading: the data-citation papers most likely to hold a citation-level precedent were read only at abstract level, and their full texts must be read before the paper claims the definition as new (section 11.4).

### 4.2 Research questions and falsification conditions

| Research question | Testable hypothesis | Results that would overturn or narrow the claim |
| --- | --- | --- |
| RQ1 (graph channel): on which question types does adding a structured graph channel to hybrid lexical and dense retrieval improve accuracy, and do the gains come from the attribution guard, from structure or from open predicates? | Gains on attribution-sensitive state tracking, aggregation, multi-hop joins and point-in-time queries; ties on single-passage lookup. The attribution guard lets the system answer both "what was originally asked" and "what is chosen now", and stops restatements from counting as independent evidence. On open-domain dialogue, a claim graph with open predicates answers questions a fixed slot table cannot express; on MultiWOZ, whose schema is fixed, the two tie | Overturn: hybrid retrieval with the same answering LLM and budget ties on these slices. Narrow: hybrid retrieval over chunks tagged with speaker and dialogue act obtains most of the gain attributed to the guard, and the conclusion becomes "speaker and dialogue-act information helps", not "the attribution guard helps"; a deterministic rule that never writes system values ties with the attribution guard, which shows only that the rule agrees with the annotation convention; a fixed slot table ties on open-domain slices, and open predicates then bring no gain |
| RQ2 (view freshness): when must a view be rebuilt, how fine must the dependencies be, at what cost, and how common is each kind of staleness in natural dialogue? | Citation-based dependencies miss new matches, writes that supersede nothing but match a negated condition, and changes in aggregate members; claim-pattern-level decisions agree with full recomputation and over-mark less than predicate-level decisions; citation staleness is far more frequent than answer staleness in natural dialogue | Overturn: on the controlled sequences, claim-pattern-level decisions over-mark as much as predicate-level decisions, so the finer dependency buys nothing. Narrow: the three kinds of change that citation-based dependencies miss are rare in natural dialogue; or read-time re-query with fingerprints is not more expensive in any stratum (likely, given dialogue-scale graphs). The contribution then narrows to the staleness criterion, the measured natural distribution and their evaluation, stated as "exact staleness checks are cheap; push-based matching pays off only beyond the crossover found by the scale experiment". Also narrow: if, on extracted graphs, the end-to-end miss rate of claim-pattern-level decisions is no lower than that of the citation-based strategies because extraction-induced misses dominate, the staleness result is stated for gold graphs and the bottleneck is reported as extraction (phase 3 gate) |
| RQ3 (accuracy and cost): when does the accuracy–cost trade-off favour GRACE, and is caching LLM-rendered views necessary? | The answering LLM answers more accurately from LLM-rendered views than from template-serialised fact cards. Given that, when the same history is read many times, revisions occur and the context budget is tight, write cost is amortised and cache-adjusted cumulative cost is below that of full history, a summary rewritten at every update, and "no cache, resolve at query time" | Overturn: template serialisation is not worse in answer accuracy, so rendering, caching and maintenance are all unnecessary and the paper is about "a staleness criterion plus computing at query time"; savings come only from a shorter answer prompt and vanish once writing, compilation, validation and failed retries are counted; or the payback read count $M^{*}$ exceeds the actual read counts in the benchmarks |

RQ3 has four kinds of competitors: the full history given to the LLM (with and without prefix caching); compression (a rolling summary rewritten after every update, and an old summary reused without rewriting); hybrid retrieval, a fixed slot table, and an append-only memory without views that resolves conflicts at query time; and GRACE's own template-serialisation variant (the query re-run at every read, with no rendering and no caching). The variables are reads per history, revision density and context budget. Every regime reports its payback read count and marks where GRACE does not win.

### 4.3 Component analysis

The following are reported as ablations, not headline claims. Each keeps its own narrowing condition and is tested as rigorously as the research questions. The last column names the ablation in section 7.3.

| ID | Component | Hypothesis | Narrowing condition | Ablation |
| --- | --- | --- | --- | --- |
| C1 | Retrieval channels (lexical, dense, structured), removed one at a time | Each has a unique contribution: IDs, numbers and long-tail entities need lexical; paraphrase and coreference need dense; joins, counts and points in time need the graph | No slice changes when a channel is removed | D |
| C2 | Fusion (RRF, weighted) | RRF suffices | Weighted fusion is clearly better and becomes the main configuration | H |
| C3 | Routing (always three channels, rules) | Rule routing lowers per-read cost at comparable quality | Always-three is equally cheap, or rule routing loses accuracy | H |
| C4 | Evidence-driven assembly versus rank truncation | At the same token budget it raises the full evidence hit rate and lowers the ungrounded-answer rate | Fused top-k at equal budget achieves the same | E |
| C5 | Vocabulary evolution versus a frozen vocabulary with aliases | On unseen relation expressions and domain sense ambiguity, constrained local extension improves predicate alignment and query correctness | A frozen vocabulary with aliases is equally effective and cheaper, or schema growth cancels the gain | F |
| C6 | Writer scale and how LLM call types are invoked | A larger writer recovers part of the gain lost with extracted graphs; conditionally triggered calls beat fixed calls | The gain comes only from extra sampling | G |

## 5. System design

GRACE has two layers, the memory layer and the pipeline layer, and sends the working context to an LLM outside it. The memory layer only stores; the pipeline layer runs the write path, which updates the memory after each message, and the read path, which assembles the working context for a task. The layers, and GRACE and the LLM, exchange data only through interfaces that carry version numbers and evidence IDs.

### 5.1 Components and data flow

| Layer | Component | Inputs and persistent state | Output |
| --- | --- | --- | --- |
| Memory | Message log | Raw messages, speakers, message IDs, arrival sequence, available timestamps | Append-only; one version per message; idempotent retries |
| Memory | Text indexes | Each message and its spans | BM25 for entity names, numbers and IDs; dense index for coreference and paraphrase |
| Memory | Claim graph | Entities, events, claims, attributions, evidence spans | Indexed by entity, predicate, event, validity and version; only the currently accepted state is asserted |
| Memory | View store | Query, row-bound text, claims used, evidence cited, dependency patterns, cut-off version | Reusable text with evidence; answer-stale and citation-stale flags |
| Pipeline (write path) | Extraction, validation and commit | New message, local context, candidate entities and predicates | Claim patch with span anchors; change set; staleness marks on affected views |
| Pipeline (read path) | Query planning and compilation | Current task, relevant vocabulary fragment, time and provenance requirements | Typed intermediate representation, SPARQL, matched claims and evidence sets |
| Pipeline (read path) | Retrieval, fusion and assembly | Candidates from three channels, existing views, token budget | Working context: task, recent raw text, verified state, evidence spans, open items, each with its cost |
| LLM (outside GRACE) | Answering | Working context, output contract | An answer, a state, one request for further retrieval, or "unknown" |

Write path:

1. The raw text is appended to the log, and the BM25 and dense indexes are updated.
2. The writer extracts a claim patch with span anchors.
3. A program validates the structure and decides, by the attribution guard and the exclusivity rules, whether to append, supersede or keep in parallel.
4. The graph transaction commits and produces a change set (new claims, new attributions, new evidence links and supersession events).
5. Affected views are marked from the change set, and a new version is published.

Read path:

1. The task is parsed into the intermediate representation, which lists the variables or the evidence the answer needs.
2. The history identifier and the readable version are bound, and then graph queries and text retrieval are run.
3. Resident views are checked for staleness: the changed sentences of an answer-stale view are regenerated, a program patches the citations of a citation-stale view, and the engine falls back to raw text when staleness detection fails with an error or times out.
4. The working context is assembled within the budget.
5. The LLM answers; GRACE records the evidence IDs used and the actual token usage.

When a graph write fails, reads may use the committed text index and state its coverage explicitly; the write is retried from the log and publishes a new version atomically. While an index is incomplete, "not found" must not be treated as "does not exist".

### 5.2 Memory layer: the claim graph

The log and the claim graph are append-only: raw text is kept forever, supersession is written as a supersession event, and the state at any past moment can be read again.

**Objects a message can produce**

- An **episode** keeps the raw text. Each mention points to an entity; each piece of evidence points to a specific span, speaker and claim.
- A **claim** is a proposition: event or subject, predicate, object, scope, valid time or interval, knowledge version. When two messages state the same thing they share one claim node with two pieces of evidence. A message retry does not add a source.
- An **attribution** connects a speaker to a claim and carries a communicative function, a report mode, a polarity and a certainty. The system offering a train and the user accepting it are two attributions on the same claim. When two speakers take opposite stances on the same proposition, each has an attribution node; a denial does not create a second claim, and a change of stance adds an attribution instead of overwriting one.
- **Temporal expressions** are of three kinds: message order, world time reported by the source, and the reference time a question requires. Without a natural date only the order is kept and no absolute date is invented; for "last week" the original phrase and any available anchor are stored.

Writes store these objects as the four kinds of entries in section 3.2: claims, attributions and evidence links each carry a knowledge version, and supersession events carry a supersession version. Writes append only these four kinds of entries, so every write falls within the scope of the soundness proposition.

**Attributions have two axes.** The communicative-function axis takes the values request, offer, accept, reject, confirm, inform, commit and question, mapped to the dialogue-act inventory of ISO 24617-2. The report-mode axis takes the values own statement, quoting another, and hypothetical. The axes are annotated separately: "he said he wants to book the Saturday train" is an inform and also a quoted request.

**Vocabulary mapping** (property names to be checked against each specification before implementation)

| Model element | Vocabulary or practice | Notes |
| --- | --- | --- |
| Claim node | RDF 1.2 reifier (`rdf:reifies`), with an equivalent RDF 1.1 standard reification serialisation | The reified triple is not asserted by default, which fits requests, offers, quotes and hypotheticals. RDF 1.2 is a Candidate Recommendation and engine support is uneven, so a fallback is kept |
| Attribution and stance | GRaSP-style attribution nodes; `prov:wasAttributedTo` points to the speaker | Polarity and certainty sit on the attribution, not on the claim |
| Communicative function | ISO 24617-2 communicative functions as a SKOS concept scheme | No official RDF version was found; the scheme is built here with documented correspondences |
| Task state | schema.org Action and reservation status; user constraints (such as "arrive by 20:45") use local properties | An offer is a pending reservation and becomes confirmed after acceptance; constraints always belong to the request |
| Provenance | PROV-O, including the model and prompt version used for extraction | Assistant restatements are marked as derived sources and do not count as independent support |
| Span anchors | NIF or Web Annotation selectors | Evidence points to character ranges in a message |
| Valid time | OWL-Time; intervals are left-closed, right-open | Without dates, the message sequence number is the ordinal position |
| Knowledge time | PROV generation and invalidation times, mapped to version numbers | There is no W3C vocabulary for bitemporality; this is the plan's own mapping, and reads are described as version materialisation over an RDF archive |
| Structural validation | SHACL shapes, validating only the claims in the current patch | Domain/range inference, structural constraints and domain exclusivity rules are kept apart |

**Change types and update operations**

| Message type | Handling in the graph | Read effect |
| --- | --- | --- |
| The same fact confirmed again | Add an attribution and an evidence link to the same claim; assistant restatements are marked as derived | Retrievable by source; restatements add no independent support; affected views become citation-stale only |
| A real state change | When the attribution guard of section 3.2 passes, write a supersession event of kind change and a new claim | Both current and past state can be queried |
| Late correction | Write a supersession event of kind correction that points to the revised claim, and append the corrected claim with the past interval it applies to; the old knowledge snapshot remains readable | "What was known yesterday" and "yesterday, seen from today" can differ |
| Request, offer, accept | Separate attributions, each advancing only its own task state; an offer does not close the request's constraint | Both "what was originally asked" and "what was finally chosen" can be answered |
| Coexisting values | Without an exclusivity rule, keep parallel claims | Reasonable answers are not deleted by "latest sentence wins" |
| Contradictory evidence of unknown origin | Keep both attributions and mark the conflict | Return the conflict or report unknown |

**Vocabulary: a stable core plus local extension.** The core defines only basic concepts such as Person, Entity, Event, Request, Offer, Confirmation, Claim, Evidence and Time; it is frozen during development and shared globally. An alias table maps "arrive by" and "no later than" to the same constraint predicate. Only when a candidate predicate has no mapping or keeps producing type conflicts does the vocabulary-maintenance call propose an alias, a new predicate or a split; the proposal is validated by a program before commit, and a new predicate is first used only within the current history. When the version changes, old definitions are kept, affected queries are recompiled, and every call is counted. A supersession event is written automatically only when the scope is the same and an exclusivity condition really holds.

**Effect of vocabulary changes and entity merges on views.** When entity alignment finds two entities to be the same, it appends a versioned equivalence entry and rewrites no existing claim; queries are evaluated on the representative of each equivalence class. A vocabulary version change (an alias, a new predicate, a predicate split) and an entity merge both change the matching of claim patterns and fall outside the assumptions of the proposition in section 3.4. The main configuration takes the simplest option: when such an event occurs, every resident view of that history is invalidated and rebuilt at its next read. The number of events and the rebuild tokens they cause are reported separately; if they dominate maintenance cost, invalidation is restricted to views that involve the affected predicates or entities.

### 5.3 Query compilation and evidence

**Intermediate representation and compilation.** Query planning generates only an intermediate representation with a restricted grammar, for example `SELECT site WHERE deployment(service=Atlas, env=prod) AT(valid=d, known=r)`. A deterministic compiler turns it into parameterised SPARQL basic graph patterns, restricted aggregation and version filters. The grammar covers the six operations of section 3.3. Tasks covered by rule templates do not call an LLM; on a parse or type-check failure the engine falls back to text retrieval.

The query template below asks for "the accepted train and its arrival time". It is written with RDF 1.1 standard reification; `ex:` is an illustrative local prefix, and `ex:knownFrom` and `ex:supersededAt` stand for generation and invalidation times mapped to version numbers. `%r%` is a placeholder for the cut-off version: before parsing, the compiler replaces it with the integer literal of the version being read. It is not a SPARQL variable (`$r` and `?r` are both variables in SPARQL, and a filter over an unbound one drops every result), nor is it a hard-coded constant: whether the cut-off is fixed or moves forward decides whether a view can go stale (section 3.3). The query does not test the kind of a supersession event, because a current-state query excludes claims superseded by either kind.

```sparql
PREFIX ex:   <https://example.org/dialogue/>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?train ?arrives ?c ?att ?a WHERE {
  ?c   rdf:subject ex:request1 ; rdf:predicate ex:selectedService ;
       rdf:object ?train ; ex:knownFrom ?r1 .
  ?att ex:about ?c ; ex:function ex:Accept ;
       prov:wasAttributedTo ex:user ; ex:knownFrom ?r2 .
  ?a   rdf:subject ?train ; rdf:predicate ex:scheduledArrival ;
       rdf:object ?arrives ; ex:knownFrom ?r3 .
  FILTER(?r1 <= %r% && ?r2 <= %r% && ?r3 <= %r%)
  FILTER NOT EXISTS { ?c ex:supersededAt ?s1 . FILTER(?s1 <= %r%) }
  FILTER NOT EXISTS { ?a ex:supersededAt ?s2 . FILTER(?s2 <= %r%) }
}
```

The template contains two claim patterns, `(request1, selectedService, ?train)[user, accept]` and `(?train, scheduledArrival, ?arrives)`. They are the view's dependency patterns. The claim "selected train" is introduced by the system when it makes the offer and carries a (system, offer) attribution; when the user accepts, a (user, accept) attribution is added to the same claim. The speaker and the communicative function therefore sit on attributions and are not folded into predicates.

**The compiler fetches evidence in two steps.** The main query projects the claim and attribution nodes each answer uses (`?c`, `?att` and `?a` above); they form the witness. The compiler then generates a second query that fetches the evidence links (`prov:wasDerivedFrom`) of those nodes. Evidence is not joined in the main query, because a claim with several pieces of evidence would multiply the result rows by the combinations of evidence. One answer of the example depends on two messages at once: the user's acceptance and the system's offer. SPARQL itself does not return provenance, so the evidence set of every answer is constructed by the compiler.

**Scope notes.** Counts carry the note "counted within the scope observed up to version $r$", and empty results always state their evidence scope. A program generates the scope note at read time from the current version; it is not part of the view content (section 3.4). Exhaustive statements are supported only when source coverage is sufficient.

The paper states the SPARQL fragment the intermediate representation corresponds to, what it cannot express, and the share of each benchmark's questions that fall outside it. That share is first estimated by hand on development histories in phase 1 (section 6.5).

### 5.4 Views and freshness maintenance

**Two kinds of view.** A view is the object defined in section 3.4. Views differ in their life cycle.

- **Resident views** are materialised during ingestion from a template list, are stored with the history and are reused by later reads. Staleness detection and maintenance apply only to resident views.
- **Temporary views** are created for the current question while answering, discarded at the end of that question and never reused across questions. This keeps questions independent (section 6.8).

**Content comes from the query.** A view's answers, witnesses and evidence come from deterministic query evaluation. Result rows are turned into text in one of two ways, and the evaluation runs both (ablation C).

- **Template serialisation.** Each query template has a fixed sentence pattern; a program fills in the result rows to produce fact cards. No LLM is called.
- **LLM rendering.** The LLM writes the result rows as coherent text and derives no content. The correctness of a rebuild is therefore not limited by the writer's reasoning ability.

Template serialisation costs no LLM tokens, so it needs no cache: every read re-runs the query and refills the template, the write side has no rendering cost, and staleness does not arise. Caching rendered text and maintaining its freshness makes sense only if LLM rendering leads to clearly more accurate answers. This is the premise of RQ3 and is tested first, in phases 2 and 3 (section 9).

**Row binding and rendering checks.** Both kinds of output are organised by result row: every sentence is labelled with the IDs of the result rows it states, and an aggregate sentence is labelled with the aggregate value and its member rows. A summary sentence that mixes several facts is bound per item; a sentence that cannot be bound to result rows serves only as a retrieval cue. A program uses the binding for three things:

- **Checking LLM rendering.** Every value in a result row (entity name, number, time) must appear in the corresponding sentence, compared as normalised strings; the sentence must not contain an entity name or number from outside that row. A sentence that fails is replaced by the template serialisation of its row and counted in the rendering-failure rate.
- **Local rebuild.** When a view is answer-stale, only the sentences for new or changed rows are regenerated and the sentences for vanished rows are deleted; all other sentences are kept unchanged. When an aggregate value changes, the aggregate sentence is regenerated.
- **Patching citations.** When a view is citation-stale, the evidence list of each affected sentence is updated by row ID, without an LLM call.

**Extracting dependency patterns.** The compiler derives all claim patterns of a view directly from the intermediate representation, including patterns inside negated conditions and aggregations, the attribution constraint of each pattern, and any local filter on a pattern that involves only that pattern's own variables.

**Eight staleness-decision strategies.** Detection is a replaceable module, and the evaluation compares all eight:

| Strategy | What it does | Expected weakness | Counterpart in the literature |
| --- | --- | --- | --- |
| Never invalidate | Reuse a view forever once built | May answer wrongly after any update | Reusing an old summary |
| Full rebuild every turn | Rebuild every view after every new message | Correct but most expensive; equivalence reference | Rewriting the summary every time |
| Used claims only | Invalidate when a used claim is superseded | Misses new matches, writes that supersede nothing but match a negated condition, and changes in aggregate members | Citation keys; cascading invalidation along consumed records |
| Used claims plus negation and aggregation patterns | As above, and also invalidate when a write matches a claim pattern inside negation or aggregation | Misses new matches of views without aggregation | The strongest form of citation-based dependency; included for a fair comparison |
| Predicate level | Invalidate on any write to a relevant predicate | Over-marks and rebuilds too much | Coarse source keys; cache validation by index update time |
| Claim-pattern dependency (push) | At write time match the change set against each view's dependency patterns, optionally with local filters; marked views are rebuilt at the next read | Over-approximates under joins and negated conditions, causing unnecessary rebuilds | Pattern-matching cache invalidation (Martin et al.); finer than MemShift's definition-scope key once constants and local filters are applied |
| Read-time re-query with fingerprints (pull) | At read time re-run the query; regenerate only if the answer fingerprint changed, and only patch citations if the witness or evidence fingerprint changed | Pays one database query per relevant view at every read | Computing at query time; read-time re-validation in retrieval; re-execution with result-set checksums in dynamic data citation |
| Push filtering with read-time confirmation (hybrid) | At write time mark views by dependency pattern; at read time re-query fingerprints only for marked views and rebuild after confirmation | One extra pattern match on the write side | A combination of push and pull |

The last three rebuild lazily, at the next read. They differ as follows.

- Pull and hybrid both rely on fingerprint confirmation and spend exactly the same LLM tokens. They differ only in database cost: pull re-queries every relevant view, hybrid re-queries only marked views and pays for pattern matching at write time.
- Pure push does not confirm, so over-marked views are regenerated as well. Its LLM tokens are at least those of the other two, and the difference is the cost of over-marking.
- A dialogue-scale graph has only thousands to tens of thousands of claims, and a re-query takes milliseconds. On the benchmarks of this plan pull is therefore expected to be enough; push filtering matters only with many resident views, frequent writes and a large graph. A scale experiment locates that crossover (resident views × write rate × graph size, ablation A); "push beats pull" is not a hypothesis of the plan.

Read-time re-query is exact with respect to the claim graph and serves as the reference against which every other strategy's misses and over-marking are counted. It is exact only with respect to the claim graph: when extraction is wrong, every strategy on the graph misses together. That part is counted separately as end-to-end staleness against the event log (section 6.4). When the detection module fails with an error or times out, the engine falls back to raw-text retrieval.

**The writer never sees views.** The writer's input (section 5.6) never contains view text, staleness marks or fingerprints; it sees only the current message, local context, and candidate entities and predicates. Views and their marks are derived state, and the graph is written only from what messages state. Tether reports why this matters: storing withdrawals at write time, where later LLM writers read them, was less safe than recomputing them at read time, because those writers then failed to demote more failed objects. A configuration that breaks this constraint is reported as a deviation.

**View selection.** Questions are invisible during ingestion, so resident views can only be materialised from a template list. The main configuration uses six template families:

| Template family | Binding | Example |
| --- | --- | --- |
| Multi-valued attribute list of an entity | (entity, predicate) | Instruments Melanie plays |
| Current single-valued state of an entity | (entity, predicate with an exclusivity rule) | Site where a service is currently deployed |
| Member count | (entity, predicate) | Number of instruments mentioned |
| Original constraints of a task | Task | The original arrival requirement |
| Candidates awaiting acceptance | Task | Trains offered and not yet accepted |
| Current choice | Task | The accepted train and its arrival time |

A view is instantiated for a binding once the number of claims matching it reaches a threshold, frozen on development data. The template list and the threshold are released with the paper. Dynamic selection by observed read frequency is a contrast condition.

The evaluation reports the **view hit rate**: the share of reads in which a resident view supplied at least one piece of evidence that was used, and the share of reads served entirely by resident views. A low hit rate means natural data offers few views to maintain, and conclusions about maintenance then rest on the controlled sequences alone (checkpoint of phase 3, section 9).

### 5.5 Retrieval, fusion and assembly

**Routing.** The engine picks channels from structural signals: IDs favour BM25, paraphrase favours dense, relational joins, timing, counts and corrections favour the graph; with low confidence it uses all channels. Routing rules, weights and thresholds are tuned only on development data and compared with always using all three channels.

**Fusion.** Candidates from BM25, dense and graph paths are mapped to unified evidence IDs; the main configuration ranks them with RRF, compared with weighted fusion.

**Evidence-driven assembly.** The engine first keeps the current task and required instructions, reserves room for the output, then selects memory fragments by tokens:

1. List the variables the answer needs, for example "deadline, accepted train, its arrival time".
2. Filter the fused candidates by knowledge version, valid time, scope and attribution, then check which variables each candidate supports.
3. Within the budget, select greedily by "new requirements covered per added token". One source sentence may cover several; both ends of a two-hop path must be selected together.
4. If variables remain uncovered, expand one summary into raw text or issue one more restricted graph query. When the budget runs out, keep "unknown" or a partial answer, counted as failure or abstention.
5. Serialise into a fixed layout: task, recent raw text, verified state, evidence spans, open items, output contract. Every fragment carries a stable citation.

The same facts can be presented as raw text, source spans, structured fact cards or a local state summary. Asking "which train and when does it arrive" and asking "who confirmed it" should produce different working contexts.

### 5.6 The answering LLM and LLM call types

The answering LLM sees only the working context and has no direct access to the graph or the log; the same LLM can thus be used unchanged with every baseline, and what is compared is the context itself.

The answering LLM has four permitted outputs: an answer, a state, one request for further retrieval, or "unknown". In offline evaluation "unknown" counts as missing or abstention; follow-up questions and invented tool results do not count as success. Every final answer records all evidence IDs it used.

Each LLM call type has its own prompt template, and all are served by the same model by default:

| Call type | Where it runs | When it is called | Input and authorised output |
| --- | --- | --- | --- |
| Writing and entity alignment | Pipeline, write path | Every message or segment that needs extraction (extraction granularity is a factor of ablation G); structured tool events use a deterministic mapping | Current message, local context, candidate entities and predicates; outputs a claim patch with span anchors |
| Vocabulary maintenance | Pipeline, write path | A candidate predicate has no suitable mapping, type conflicts persist, or predicate misuse fails validation | Candidate definition, positive and negative examples, old version; outputs a proposal for an alias, new predicate or split, committed after program validation |
| Query planning | Pipeline, read path | Rule templates cannot cover the current task | Question, relevant vocabulary fragment, time and provenance requirements; outputs a typed intermediate representation, variables to fill and alternative channels |
| Verification and view rendering | Pipeline: verification on the read path; rendering on the write path, or at the next read for a lazy rebuild | Program validation meets an ambiguity, or a query result must be rendered as a view | Query result, source sentences, budget; outputs support, conflict or unknown, and text with evidence for every sentence |
| Answering | Outside GRACE | Every read | Working context and output contract; outputs an answer or a state |

**Prompt assembly.** In the main configuration, the instructions of each call type, the output JSON schemas and the examples are fixed. Only these are appended at call time: the current vocabulary version, definitions related to the current entities and predicates, and the remaining budget. A fixed prefix keeps retries idempotent and keeps prefix-cache hits. Reusing failure counterexamples within a history (for instance, a case where "latest arrival" was written as "actual arrival") would make write results depend on order and would change the prompt prefix, so it is not in the main configuration and is tested separately as a switch in ablation F.

**Constraints.** At test time only program checks and source support from the current history prefix are allowed; the evaluator or answers must not be used to correct prompts. At most one vocabulary proposal per message, and at most one compilation repair and one extra retrieval per read; exact limits are frozen on development data. Every call, retry and extra retrieval is counted.

## 6. Evaluation protocol

All benchmarks share one system. Each history is ingested independently, every benchmark keeps its native target, and results are reported per benchmark. Questions are answered independently on the snapshot of their stated version, and answering never writes to the history.

### 6.1 Read protocols

Where read points sit relative to writes decides what a benchmark can test. The evaluation uses three read protocols.

| Protocol | Read points | Writes between consecutive reads | What it can test |
| --- | --- | --- | --- |
| End of history | All questions at the final version $N$ | None | Answer quality and evidence recall; amortisation of write cost over $M$ reads; hit rate of resident views; recall of staleness detection for resident views materialised during ingestion |
| Per turn | After every user turn | One or two messages | Attribution handling and incremental state; over-marking on short histories |
| Interleaved | At versions spread across the history | Varies with the protocol | Precision and recall of staleness detection, and maintenance cost, on long histories |

Two consequences follow from section 3.

- **Under end-of-history reading, detection granularity cannot change cost.** The cheapest correct policy is to build every view once at version $N$. A view materialised during ingestion may well be stale at $N$, so a strategy that misses staleness still produces wrong answers there; but every strategy renders each view at most once before the reads, so finer detection cannot save rebuilds. A sequence of $M$ questions at $N$ has no writes in between, so once the resident views are rebuilt at version $N$ they stay fresh for all $M$ questions. Temporary views are discarded at the end of each question and never reused, so reuse across questions comes only from resident views. These $M$ reads measure the reuse of resident views and write amortisation, not maintenance.
- **Claims about maintenance cost are tested only under interleaved reading.** These are the controlled change sequences and the evidence-anchored streaming protocol for LoCoMo (section 6.5). MultiWOZ dialogues have only a dozen or so turns; per-turn reading gives natural data on over-marking but supports no conclusion about cost.

### 6.2 Benchmarks and terminology

Datasets name the same structure differently; this plan calls the unit of memory a **history**. A LoCoMo conversation is one independent history, roughly what some agent benchmarks and papers call a complete session, while LoCoMo and LongMemEval call the dated segments inside a history sessions. The mapping is given only here.

| Benchmark | One history (unit of memory) | Segment within a history | Single message |
| --- | --- | --- | --- |
| Controlled change sequences | One generated sequence | Episode (generator-defined) | Message |
| MultiWOZ | Dialogue (`dialogue_id`) | None | Turn |
| LoCoMo | Conversation (`sample_id`) | Session (dated) | Turn (`dia_id`) |
| LongMemEval | The chat history attached to each `question_id` | Session (one timestamped conversation) | Turn |
| HaluMem | All sessions of one user | Session | Turn |
| MemoryAgentBench | One context | Chunk (fed one at a time) | No common unit |

### 6.3 Benchmarks, tiers and protocols

Benchmarks fall into three tiers. The tier decides where results appear in the paper and in which order runs are scheduled. Rows marked "core" belong to the minimal publishable core of section 9.3; rows marked "optional" are done as capacity allows.

| Benchmark | Tier | Read protocol | Primary metrics | Serves |
| --- | --- | --- | --- | --- |
| Controlled change sequences (built here) | Main text (core) | Interleaved; read points scheduled by the generator, every message readable | Precision and recall of staleness decisions against read-time re-query; recall of end-to-end staleness against the event log; answer agreement with full rebuild; rebuild tokens | RQ2 (primary), RQ3 maintenance surface |
| MultiWOZ 2.4 (main); 2.2 and 2.1 score the same predictions | Main text (core), as a targeted diagnostic | Per turn: each dialogue initialised separately, real messages written incrementally, each user turn sees only its prefix and predicts the cumulative state | Retention of original constraints on turns after an offer; paired correctness of "original constraint" and "current choice"; stale-value use; overall JGA and slot F1 as reference | RQ1 (primary for the attribution guard); over-marking on natural per-turn data |
| LoCoMo | Main text (core) | End of history (native), plus evidence-anchored streaming | Token-F1 and calibrated blind-judge accuracy; evidence recall; view hit rate; under streaming, answer consistency between $v(q)$ and $N$, over-marking rate and rebuild tokens; cumulative tokens against read count; natural distribution of the seven change types (development histories) | RQ1, RQ2 (natural distribution and false positives), RQ3 amortisation |
| LongMemEval-S (cleaned) | Main text, adverse setting; three strata | End of history, one question per history; all sessions ingested, `question_date` kept, `has_answer` and `answer_session_ids` masked | Accuracy from the official per-type GPT-4o judge; session- and turn-level evidence recall | RQ1 and RQ3 in the adverse setting |
| HaluMem-Medium | Summary table (optional) | Session by session; extraction and updates scored against gold memory points and update labels | Operation-level accuracy of extraction and updates; QA accuracy | Graph quality; RQ2 support |
| MemoryAgentBench: LongMemEval(S\*) and FactConsolidation at 6K and 32K | Summary table (optional) | Context fed chunk by chunk, then several questions on the same context | Accuracy per competency; cumulative tokens against read count | RQ3 multi-read setting; FactConsolidation as RQ2 support |

Benchmarks considered and not evaluated: BEAM, Memora and STALE. BEAM would support RQ1 and RQ2, since it covers knowledge update and contradiction resolution; Memora and STALE would support only RQ2. None has per-message view-invalidation ground truth, and each adds an adapter, a judge and its own licence constraints. They remain in the related work. If budget remains after phase 6, one of them may be reported in the supplementary material, labelled as post-lock; the first choice is the 128K tier of BEAM. Whether the STALE data can be downloaded is unconfirmed and is checked before any use.

### 6.4 Controlled change sequences

The controlled sequences are the primary evidence for RQ2, so their design is fixed before any staleness result is seen. A search for dialogue-memory benchmarks with explicit bitemporal questions found none; this is weak negative evidence from a limited search. Existing controlled revision generators (StateMemBench and others) are cited and distinguished: they have neither bitemporal paired questions nor per-message view-invalidation ground truth.

**Content.** Natural English dialogue whose ground truth is a program event log. The sequences cover seven change types: a real state change that supersedes a cited claim (a supersession event of kind change); a new match (including empty to non-empty); a write that supersedes nothing but matches a negated condition, such as an acceptance or rejection that removes or adds an answer; a change in count or order; a late correction (a supersession event of kind correction, section 5.2); a repeated mention, which causes citation staleness only; and an irrelevant update. They also contain alternatives that are offered but never accepted, questions that presuppose an outdated state, and paired "known then" and "seen from now" questions.

**Generator outputs per sequence.** The message sequence; the event log; the gold claim graph at every version, with attributions and evidence links; a read schedule with gold answers and witness sets; and, for every template view and every message, whether the view is answer-stale and whether it is citation-stale (the per-message invalidation ground truth).

**Controlled variables.** Change-type mix; revision density (changes per 100 messages); read interval (messages between consecutive reads); reads per history; history length. The maintenance-cost surface of RQ3 is measured by sweeping revision density against reads per history at fixed length.

**Two references.** Staleness detection is evaluated against two references, and misses are counted by source.

- The reference with respect to the claim graph is read-time re-query. It measures the decision strategy itself: on the same graph, how much a strategy misses and how much it over-marks.
- The reference with respect to the event log is the per-message invalidation ground truth. It measures the end-to-end outcome: the share of cases where the ground truth says a view is stale and the system still sends the old content to the LLM.
- On extracted graphs, end-to-end misses minus decision misses are the extraction-induced misses (for example, the clarinet extracted under a different predicate is missed by every strategy on the graph, read-time re-query included).

On gold graphs, that claim-pattern-level detection misses nothing is guaranteed by the proposition of section 3.4, and the miss rate of citation-based strategies is fixed by the configured change mix. Gold-graph experiments are therefore a correctness check of the implementation and a measurement of over-marking, not an empirical finding. The empirical question is how often each change type occurs in natural dialogue, answered by the natural-distribution measurement of section 6.5.

**Validity.**

- Surface text is varied by rendering with a model not used by any evaluated system, so that no system shares the generator's phrasing.
- Two annotators audit the semantics of a sample of sequences against the event log: at least 5 sequences per template family, judging per message whether text and event agree, with Cohen's κ and the disagreement rate reported. The annotators are one author and one person not involved in building the system, chosen in phase 1.
- Splits are by template family: development and held-out families are disjoint.
- High scores on synthetic data do not substitute for results on natural benchmarks; the paper states this.

The full design (event grammar, templates, rendering, audit protocol, sizes) is a separate document produced in phase 1 (task T008): `docs/research/change-sequences.md`. Implementing the generator is the first item of phase 2.

### 6.5 Notes per benchmark

**MultiWOZ.**

- The test set has 1,000 dialogues and 7,372 user turns.
- The predictor projects the internal graph onto the official slots; the same projection is available to every system with a structured internal state.
- 2.4 re-annotates the same test dialogues, so one set of predictions is scored against 2.4, 2.2 and 2.1 at no extra inference cost. The 2.1 row allows comparison with published zero-shot LLM results.
- No later turns are read and gold states are never fed back.
- Two facts are established from the data in phase 1 (task T006) before they enter the paper: whether "2.2 writes system-offered values into the state, 2.4 does not" holds in general, and how many test turns accept or reject a system offer.
- **Operational definition of the metrics.** The "current choice" (a train ID, for example) is not an official slot, so there are two metrics. Retention of original constraints uses only the official 2.4 gold: on turns after a system offer, does the predicted state keep the original value of the user's constraint. Paired correctness needs derived gold: the offered entity is read from the dialogue-act annotation of the system turn, acceptance or rejection from the acts of the next user turn, and a rule generates the "current choice"; an item counts as correct only if both "original constraint" and "current choice" are right. Two annotators check the derivation rule on 200 turns and Cohen's κ is reported; the rule and the check are fixed and published in T006.
- **Winning on the annotation convention alone does not count.** A deterministic rule that never writes system values should tie with the attribution guard on retention of original constraints, and TripPy's system-inform memory did this long ago. That shows only that the rule agrees with the 2.4 convention. The evidence for the attribution guard is paired correctness: that rule cannot answer "current choice", and writing system values directly gets "original constraint" wrong.
- The count of offer turns decides how much weight MultiWOZ carries for RQ1. At an accuracy around 70%, about 400 turns give a 95% interval half-width of about 4.5 points. If the count yields a half-width above 5 points, the primary evidence for the claim about the attribution guard moves to the controlled sequences and MultiWOZ becomes support.
- MultiWOZ dialogues are short and the full history always fits in the window. The plan makes no cost or maintenance argument on it.

**LoCoMo.**

- The public file has 10 histories and 1,986 questions. In the official evaluation code, category 1 is multi-hop (282), 2 temporal (321), 3 open-domain (96), 4 single-hop (841) and 5 adversarial (446).
- The main evaluation uses categories 1 to 4, 1,540 questions. conv-26 and conv-49 form the development set (308 questions); the other 8 histories are held out (1,232 questions).
- If category 5 is evaluated for abstention, it is reported separately with the judging rule stated.
- Inputs exclude images, image captions and human-written summaries; questions whose answer appears only in an image caption are reported separately.
- LoCoMo has no update-centred questions; under end-of-history reading it contributes nothing to RQ2, and the paper says so.
- **Fragment coverage.** In phase 1 the 308 questions of the two development histories are annotated by hand: whether each can be expressed in the fragment of section 3.3 and, if not, why (open reasoning, date arithmetic, common sense, other). Two annotators overlap on 100 questions and Cohen's κ is reported. Coverage is an upper bound on the accuracy of the graph channel; if it is below one half, expectations for RQ1 on LoCoMo are lowered accordingly (section 9).
- An independent audit reports that 99 of the 1,540 answers are wrong and 57 evidence annotations are wrong. The auditor is anonymous and affiliated with a competing memory product, and the audit is not peer reviewed, but the per-question list is public. The plan spot-checks the list and reports both all 1,540 questions and the 1,441 remaining after removing the 99.

**LoCoMo evidence-anchored streaming.** Each question $q$ is posed at version $v(q)$, the end of the session containing the latest turn in its annotated evidence, and again at $N$. Ingestion continues after each read; the question's temporary artefacts are discarded as usual.

- The gold answer stays valid without re-annotation: it was written against the whole history, and all annotated evidence is visible at $v(q)$. This holds to the extent that the evidence annotation is complete. The 13 questions whose evidence is missing or unresolvable are excluded from streaming, and questions on the audit's evidence-error list are reported separately.
- Reads now interleave with writes: views stored during ingestion are read at scattered versions and go stale under later writes, so staleness strategies differ in cost on natural data.
- Asking the same question at $v(q)$ and $N$ against the same gold is a consistency check: a changed answer means later writes disturbed the system (wrong supersession, or a spurious staleness decision followed by a worse rebuild).
- Limitation: questions are asked only after their evidence is complete, so the protocol cannot measure true staleness where the answer should change (for example, asking about instruments between the violin and the clarinet). It measures the cost of false positives and the value of reuse; the controlled sequences measure misses and true staleness.
- Whether the protocol enters the main text depends on how widely $v(q)$ is spread (task T007). It is reported in the main text if a substantial share of held-out questions have $v(q)$ before the final session and adjacent reads are separated by real writes; otherwise it moves to the supplementary material. The exact threshold is fixed from the development histories before held-out data is used.

**Measuring the natural distribution of staleness.** This measurement answers how common the changes missed by citation-based dependencies are in natural dialogue, and it costs no answering tokens.

- The data are the extracted graphs of the two LoCoMo development histories and of the LongMemEval development histories. The extraction of the two LoCoMo histories is corrected by hand.
- For every template view of section 5.4 the query is re-run after every message; each change is assigned to one of the seven change types and classified as answer staleness or citation staleness.
- Reported: occurrences of each change type per thousand messages, the ratio of citation staleness to answer staleness, and how many of these natural changes each of the two citation-based strategies misses.
- Phase 1 makes a rough measurement with a one-off extraction prompt and hand-written queries; phase 3 repeats it with the final writer and compiler.

**LongMemEval-S.**

- 500 questions, each with its own history of about 115K tokens; 78 knowledge-update and 133 temporal-reasoning questions (per-type counts taken from tables in later papers, recomputed from the file after download).
- The main text uses three strata: knowledge update, temporal reasoning and multi-session (the multi-session count is recomputed from the file). The full set is reported in the supplementary material as capacity allows.
- The knowledge-update stratum is the one most relevant to the research claims of this plan, but it has only 78 questions, about 62 held out; at 70% accuracy the 95% interval half-width is about 11 points. It is reported descriptively and supports no significance claim.
- Splits are stratified by type and abstention label, about 20% development and 80% held out; the actual lists are published.
- With one question per history this is the least favourable setting for amortising write cost, and the plan reports it as such.
- Histories exceed the primary model's native window, so the full-history baseline uses the long-context second answering model. This is the most compute-intensive benchmark: its compute is reserved first in the budget, and it runs after the core is complete (section 9.3).

**HaluMem-Medium.**

- 20 users, each with about 70 sessions and about 160K tokens; 14,948 memory points and 3,467 questions, including 180 dynamic-update and 769 memory-conflict questions.
- It provides per-session gold memory points, update labels and links to replaced memories, so the write path can be scored separately from QA. Its update task corresponds to "a claim is revised", not to insertion-driven view staleness.
- The data is synthetic; the original paper uses GPT-4o for both judging and answering.
- Licence CC BY-NC-ND 4.0: derived annotated subsets cannot be published.

**MemoryAgentBench.**

- Context lengths range from 100K to 1.44M tokens, fed incrementally with several questions per context; it also takes the evaluation beyond two-party dialogue.
- LongMemEval(S\*) (5 contexts, 300 questions) is a multi-read version of LongMemEval and is the most useful part for RQ3.
- FactConsolidation is built by concatenating counterfactual edit pairs and has no dialogue, speakers or attribution. On its 262K-token multi-hop subtask no published method exceeds 7%, a floor effect; the plan uses only the 6K and 32K variants that fit the primary model's window, and reports them separately.

### 6.6 Research questions and their evidence

| Research question | Primary evidence | Support | Decisive ablations | Primary metrics |
| --- | --- | --- | --- | --- |
| RQ1 | MultiWOZ 2.4 turns after a system offer; multi-hop, temporal and aggregation slices of LoCoMo and LongMemEval-S | HaluMem; attribution probes in the controlled sequences | B, D | Paired correctness and retention of original constraints; paired differences in slice accuracy; stale-value use |
| RQ2 | Controlled change sequences, on gold and extracted graphs; the natural distribution of staleness on development histories | MultiWOZ per-turn state; LoCoMo streaming; HaluMem updates; FactConsolidation | A | Miss and over-marking rates against read-time re-query; end-to-end miss rate against the event log; agreement with full rebuild; rebuild tokens |
| RQ3 | Answer accuracy with template serialisation against LLM rendering; maintenance surface on the controlled sequences; amortisation curves on LoCoMo; LongMemEval-S as the adverse case | MemoryAgentBench LongMemEval(S\*) | C, G | Cumulative tokens at matched quality; $M^{*}$; cost per successful task |

### 6.7 Metrics

Metrics are computed per layer, so that "stored correctly", "given correctly" and "answered correctly" can be attributed separately.

$$
\mathrm{Acc}=\frac{1}{|I|}\sum_{i\in I}J(q_i,g_i,a_i),\qquad
\mathrm{Recall}_i=\frac{|R_i\cap e_i|}{|e_i|},\qquad
\mathrm{Full}_i=\mathbf 1[e_i\subseteq R_i]
$$

| Layer | Metrics | Notes |
| --- | --- | --- |
| Memory (stored state) | Claim precision, recall and F1; structural validation pass rate and retries; whether the cited span entails the claim; accuracy of the attribution and time fields; share of restatements counted as independent evidence; answer-coverage upper bound | Computed on annotated samples, HaluMem gold memory points and the gold graphs of the controlled sequences. Recall requires listing every claim in a stretch of messages and is expensive, so it is measured only on sampled segments: 40 segments of about 20 messages each from development histories, annotated independently by two annotators and then merged, with claim-level agreement reported. MultiWOZ dialogue-act annotation can check communicative functions (whether each version's files keep it is checked in phase 1) |
| Pipeline (context sent to the LLM) | Evidence recall and full hit; view hit rate; precision and recall of staleness decisions, with answer and citation staleness separated and decision misses separated from extraction-induced misses; agreement of views with full recomputation; share of stale content entering the prompt; rendering-check failure rate; parse-failure rate and fallback rate to text retrieval | Retrieval candidates and evidence actually included in the working context are counted separately |
| LLM (final answer) | Accuracy Acc ($J$ is a preregistered binary semantic judgement); token-F1; JGA and slot F1; ungrounded-answer rate; stale-value use; correct-abstention rate; under streaming, answer consistency between $v(q)$ and $N$ | Each benchmark keeps its native metrics and also reports a unified blind-judge accuracy |

**Evidence recall has two definitions.** The strict one counts a hit only when the source sentence enters the prompt; the lenient one credits derived items through their provenance links. One audit shows this choice changes ranking metrics for most queries and flips system rankings, so both are reported, together with how each baseline's evidence set is extracted. Annotated evidence may list only one set of usable sources; alternative sources are checked manually on a pre-drawn sample to avoid false misses.

**Judge calibration.** The blind judge fixes a model snapshot and prompt and includes deliberately wrong, vague answers as negative controls. The independent LoCoMo audit reports that the commonly used gpt-4o-mini judge accepts 62.81% of such answers. All systems share one answer prompt, because the answer prompt alone can move the same LLM's accuracy by more than ten points.

**Stratified reporting.** Results are stratified by history token-length quantile, revision frequency, actual reads per history and the number of segments the annotated evidence spans, and regions where GRACE does not win are reported explicitly. Stratum labels are used only on the scoring side.

### 6.8 Leakage prevention and validation

During writing, questions, reference answers and evidence annotations are invisible. Further rules:

- All baselines share the same dates and visible information; any experiment that shortens the input history marks the visible range and selection rule in its result table.
- Temporary views, compilation repairs and generated answers from answering are discarded at the end of the question and never appended to the history. Under streaming this holds at every read point.
- Two question orders are compared under fixed decoding on a sample, checking that index versions and per-question input evidence agree.
- Perfect extracted graphs, perfect intermediate representations and gold evidence appear only in explicitly labelled upper-bound experiments.
- Attributions, time filters, source citations and execution results of the intermediate representation are checked on a manually annotated subset.
- Splits, exclusion reasons and counts per category are frozen and published.

### 6.9 Statistical analysis

The main analysis uses question-level paired tests with history as a random effect; per-cluster differences and leave-one-cluster-out serve as sensitivity analyses.

- **LoCoMo has only 8 held-out clusters.** A two-sided sign test reaches p ≈ 0.008 only if all 8 histories move in the same direction, and p ≈ 0.07 with 7. Even treating the 1,232 questions as independent, the 95% interval half-width at 80% to 90% accuracy is about 1.7 to 2.2 points. No 1-point non-inferiority is claimed on LoCoMo.
- **Matched-quality criterion.** Non-inferiority margins are preregistered per benchmark during development, from sample sizes; where the data cannot support a margin, only paired-difference intervals are reported and no equivalence is claimed. Statistical power comes mainly from the controlled sequences, MultiWOZ, LongMemEval and HaluMem.
- **Form of the preregistration.** The protocol file (splits, metrics, non-inferiority margins, judge prompt, main configuration) is committed to the repository and tagged before any held-out data is run; its SHA-256 and the commit hash appear in the paper. The same file is registered on OSF for a third-party timestamp.
- **Small subsets are descriptive only.** LoCoMo open-domain has 96 questions; the LongMemEval knowledge-update stratum has about 62 held out; single-session preference and abstention have 30 each, about 24 held out after splitting.
- **Uncertainty is reported by source.** Judge reruns, answer prompt, answering model, sampling error and label noise are reported separately, not only the first.
- **Clustering units.** Controlled sequences by template family, LoCoMo by conversation, LongMemEval by instance (checking for highly overlapping histories), MultiWOZ by dialogue, HaluMem by user, MemoryAgentBench by context.

## 7. Models, baselines and ablations

Every comparison fixes the same answering LLM, the same answer prompt and the same set of context budgets; the only thing that varies is how the context sent to the LLM was produced.

### 7.1 Model configuration

| Item | Choice | Rationale and caveats |
| --- | --- | --- |
| Primary model | Qwen3-8B for writing, planning, rendering and answering; thinking disabled; chat template and tokenizer frozen | Same backbone as ProgMem and ReacTOD, allowing comparison. Native context 32,768 tokens. Disabling thinking may lower the writer's extraction quality, so "writer with thinking enabled" is a level of ablation G |
| Decoding | Temperature 0 | The model card recommends T=0.7 for non-thinking mode; 0 is a deliberate deviation for reproducibility, with a sensitivity run at the recommended setting |
| Contemporary small model | An open-weight model of the same size class released after Qwen3, chosen in phase 1 | Qwen3 was released in April 2025 and several generations of open-weight models have followed. Choosing early lets prompts be frozen for both models; the main conclusions are repeated on it in phase 7 |
| Long-context second answering model | An open-weight model whose native window holds a full LongMemEval-S history, chosen in phase 1 after checking its model card for licence and context length | Serves as the full-history baseline on long histories and as a check on model scale |
| Writer scale | A larger model of the primary model's family replaces both the writer and the answering LLM on a preregistered stratified subset | Estimates the write bottleneck; only within-family scale effects are claimed |
| Embedding | Qwen3-Embedding-0.6B; query instruction strings frozen and published | BM25 uses the same tokenisation and chunking; shorter histories use exact cosine, no approximate index |
| Reranking | No cross-encoder in the main configuration | Avoids attributing reranking gains to the graph; reranking is a separate condition switched on for all methods at once |
| Judging | A blind judge with a fixed model snapshot, chosen in phase 1 for availability until publication; LongMemEval additionally uses its official judge where available | Agreement between the fixed judge and the official judge is measured on development data and reported |
| Compute | Local 8×B200 processing independent histories in parallel; external APIs only for blind judging and disagreement review | APIs take no part in any graph-update decision |

Expected scores are calibrated to the small-model range. With 7–8B backbones, training-free systems reach roughly 25 to 38 token-F1 on LoCoMo; one preprint using a single judge reports LLM-judged accuracy for Qwen3-8B systems of 50.8 to 84.4 on LoCoMo and 63.4 to 77.4 on LongMemEval-S. These are not on the same scale as the 85 to 94 obtained with frontier models, nor consistent with each other, and serve only to estimate magnitude. HaluMem and MemoryAgentBench have no published results for 7–8B open models to refer to.

### 7.2 Baselines

All baselines below run under the protocol of this plan, with the same answering LLM and budgets.

| Group | Baseline | Explanation it rules out |
| --- | --- | --- |
| Raw text | Full history, with and without prefix caching; last-k; truncation to the same budget | A shorter complete raw text may already be optimal. When the full text exceeds the window, the share is disclosed and nothing is truncated silently |
| Retrieval | BM25, dense, and their RRF fusion | Strong text recall alone explains the gain. Direct comparison for RQ1 |
| Retrieval | The RRF fusion above, with speaker and dialogue-act tags prepended to every chunk (tags predicted by the same writer, their tokens counted in cost) | The cheapest way to supply speaker and dialogue-act information. If it obtains most of the gain attributed to the guard, the conclusion narrows to "speaker and dialogue-act information helps" |
| Compression | Rolling summary plus recent raw text, rewritten after every update; and reused without rewriting | Compression alone suffices; the two variants correspond to "expensive" and "wrong" |
| Structured | Fixed-schema slot table with speaker and communicative-function fields and provenance; slots defined on development data and then frozen | Structured fields alone suffice and open predicates are not needed. A relational encoding with the same fields carries the same information as the graph, and the plan does not compare the two engines |
| Structured | GRACE's template-serialisation variant: the query re-run at every read, results filled into fixed sentence patterns, no rendering and no caching | Whether LLM rendering and caching are necessary. If it ties on answer accuracy, view maintenance has no cost rationale |
| Structured | Append-only memory without views, resolving conflicts at query time, same backbone | Whether stored views are necessary. The most direct competitor on cost |
| External systems | Mem0 (in the minimal core) and Mem0g (optional) | The most common reference in recent comparison tables |
| External systems | Graphiti (optional), with its adaptation and failure rate published and a separate row on its native backbone | A temporal graph memory with invalidation. Small-model results in the literature conflict: Zep's LoCoMo token-F1 is 33.82 in one reproduction (Qwen2.5-7B) and 13.82 in ProgMem's table (Qwen3-8B) |
| MultiWOZ | ReacTOD reproduced on Qwen3-8B; deterministic overwrite on official slots; a deterministic rule that never writes system values; the same LLM outputting the cumulative state directly | ReacTOD reports 47.34 JGA zero-shot with Qwen3-8B on MultiWOZ 2.1 (with a verification loop), and only on 2.1. The never-write-system-values rule separates "agrees with the annotation convention" from "the attribution guard helps" |

The eight staleness-decision strategies are compared inside ablation A, all on the same claim graph, and mapped one by one to published dependency keys and cache-invalidation rules in section 5.4. A fixed-schema temporal graph is an arm of ablation F.

**Cited for reference only, not run under this protocol.** Scores are quoted with backbone and metric and never treated as same-protocol results.

| Work | Why it is not run |
| --- | --- |
| APEX-MEM, ProgMem | Different protocols; the query-time-resolution baseline and the Qwen3-8B backbone already cover the comparison |
| MemShift, Tether | Their dependency keys are reimplemented as strategies in ablation A; where their released code allows, the keys are rerun on the same backbone as a check |
| LightMem, a hierarchical system such as MemOS | Add breadth, not a distinct explanation to rule out |
| A raw-log search agent (grep, search, open) | Expensive, and the main comparison concerns context construction; Letta reports 74.0% on LoCoMo with gpt-4o-mini (LLM-judged, vendor report). May be run on the development set and reported in the supplementary material |
| A RAG pipeline tuned with the LongMemEval recipe (turn-level storage, fact-augmented keys, time-aware query expansion, Chain-of-Note reading) | Its answer-side techniques conflict with the fixed answer prompt and are orthogonal to how context is built |
| Supervised D3ST on MultiWOZ | Uses additional training; listed separately and never mixed into the training-free ranking |

### 7.3 Ablations

Each ablation changes one factor, controls samples and budgets, and reports interactions between components. Ablations A to D appear in the main text; E to H go to the supplementary material. E, F, H and the call-type invocation arm of G are done as capacity allows; the writer-scale, thinking and extraction-granularity arms of G run in phase 3, because extraction granularity is a design variable that the write budget forces a decision on (section 8.4). A, B and C run first because they decide whether the core claims hold; the template-serialisation arm of C already runs in phase 2.

| ID | Only factor changed | Most informative readout | Benchmarks | Serves |
| --- | --- | --- | --- | --- |
| A | Eight staleness-decision strategies (section 5.4), stratified by the seven change types; each on gold and extracted graphs. Read-time re-query is the reference with respect to the claim graph, the event log the end-to-end reference. Plus a scale experiment: resident views × write rate × graph size, comparing the database cost of push, pull and hybrid | Miss and over-marking rates; how much of the end-to-end misses is due to detection and how much to extraction; answer agreement with full rebuild; rebuild tokens; database time and the crossover where push starts to pay off; frequency of the seven change types in natural dialogue | Controlled sequences (primary); the natural-distribution measurement on development histories; MultiWOZ per turn and LoCoMo streaming (natural over-marking) | RQ2 |
| B | Attribution guard (off, on; with the guard off, attributions are still recorded but a new value always supersedes the old one) × representation (fixed slot table, open-predicate claim graph) × time (single, bitemporal), a 2×2×2 design; plus two single arms: hybrid retrieval over chunks tagged with speaker and dialogue act, and the deterministic rule that never writes system values | Paired correctness of "original constraint" and "current choice"; retention of original constraints; paired correctness on late corrections; difference between slot table and claim graph on open-domain slices; share of the guard's gain obtained by the tagging arm | MultiWOZ turns after an offer; controlled sequences (late corrections, known-then pairs); LoCoMo and LongMemEval slices | RQ1 |
| C | View content source (template serialisation of the query result; LLM rendering of the query result; LLM rewriting from raw text) × provenance (with, without), at a fixed display budget; a raw-text window as reference | Answer accuracy under the three sources, where the paired difference between the template arm and the LLM-rendering arm tests the premise of RQ3; accuracy after rebuild; rendering-check failure rate; wrong citations; write-side rendering cost | Controlled sequences; LoCoMo | RQ3, RQ2 |
| D | Remove BM25, dense or graph channel one at a time, at fixed total candidates and returned tokens; plus graph channel on/off × attribution-and-time verification on/off over the same candidates | Unique contribution per channel (IDs, numbers, long-tail entities against paraphrase); path evidence recall against stale-value use, separating verification gains from retrieval gains | LoCoMo; LongMemEval-S; MultiWOZ | RQ1, C1 |
| E | Fixed top-k or RRF truncation versus evidence-driven assembly; expandable pointers versus summaries only | Full evidence hit rate, ungrounded-answer rate, final prompt and total tokens | LoCoMo; LongMemEval-S | C4 |
| F | Frozen vocabulary, frozen plus aliases, local evolution; a fixed-schema temporal graph; dynamic examples and counterexamples switched off under the same schema; EDC-style and DIAL-KG-style incremental strategies | Predicate-linking accuracy on unseen expressions, schema growth, prompt cost; vocabulary and prompt contributions separated | Development histories of all main-text benchmarks | C5 |
| G | Invocation of LLM call types (single structured call, fixed routing, conditional triggering) at matched total call budget; writer scale (primary model, larger same-family model); writer thinking (off, on); extraction granularity (per message, per segment of several messages, per session) | Trigger precision, end-to-end cost, parse failure and repair rates; graph quality and answer quality under the larger writer and with thinking enabled; write tokens and graph quality at each extraction granularity; extra sampling excluded as the explanation | HaluMem; controlled sequences; LoCoMo | RQ3, C6 |
| H | Routing (rules, always three channels) and fusion (RRF, weighted) | Quality and per-read cost; evidence recall and accuracy per slice | LoCoMo; LongMemEval-S | C2, C3 |

Learned routing and learned fusion are not studied: they need training data the benchmarks do not provide under this protocol and are outside the research questions.

## 8. Cost accounting

Main results use cache-adjusted accounting, and cost differences are interpreted only on quality-matched pairs.

### 8.1 Accounting rules

- Input and output tokens are logged per call, covering extraction, vocabulary maintenance, rendering, planning, verification, retries and answering. Failed attempts count.
- When a tool or query result enters the next prompt, it is counted in that call's input.
- Every method reports three ledgers: logical tokens, tokens actually computed after prefix-cache reuse, and GPU seconds.
- Embedding tokens, database CPU, memory, p50 and p95 latency and tool-call counts are reported separately.
- Blind-judge calls are reported as evaluation overhead, not system cost.
- Equal token counts on different models are not read as equal prices.
- All methods use the same cache-friendly prompt layout: stable content first, question-specific content last.
- The memory budget of the answer prompt has four levels: 256, 512 and 1,024 tokens, and the actual full history; system instructions, the current question and the output reserve are fixed, and the real total input is published.

### 8.2 Formulas

Fix one history and $M$ independent questions. The cost of the full-history baseline without and with caching, and the cost of GRACE:

$$
T_{\mathrm{full}}=M\,H+\sum_{i=1}^{M}\bigl[L(q_i)+L(g_i)\bigr],\qquad
T_{\mathrm{full}}^{\mathrm{cache}}=H+c\,(M-1)\,H+\sum_{i=1}^{M}\bigl[L(q_i)+L(g_i)\bigr]
$$

$$
T_{\mathrm{sys}}=W(\mathcal H)+\sum_{i=1}^{M}\bigl(U_i+A_i\bigr),\qquad
M^{*}=\left\lceil \frac{W}{\Delta}\right\rceil
$$

$H$ is the token count of the serialised history; $c$ is the cost of cache-hit input relative to full price, measured as the compute ratio for local inference and the billing ratio for APIs. $W$ is the number of LLM tokens spent in one complete ingestion on extraction, graph building, vocabulary maintenance and view maintenance; $U_i$ is the tokens spent on planning, verification and compilation repair for question $i$; $A_i$ is the input and output of the final answer. Rendering triggered by a lazy rebuild at read time is view maintenance and is booked to $W$, not to $U_i$. $\Delta$ is how many more tokens per question the cache-adjusted full history spends than GRACE; if $\Delta$ is not positive there is no payback point. For per-turn and interleaved reading, $W$ is replaced by the sum of the write cost added before each read, and the full-history baseline is charged the actual prefix length at each read. The history is append-only and its prefix is stable, so the full-history baseline also benefits from prefix caching under interleaved reading: each read pays full price only for the messages added since the previous read, and the rest is charged at the cache ratio $c$. The cached full-history row is measured under this accounting, not estimated from the uncached one.

### 8.3 Results to report

- **Quality against total tokens.** Accuracy at equal budget; mean tokens at similar quality.
- **Amortisation curves.** On one snapshot, draw different numbers of independent questions with a fixed seed, reuse the same ingestion, and plot cumulative tokens against read count, reporting the crossing point at a quality threshold. Run on LoCoMo and MemoryAgentBench LongMemEval(S\*). Competitors: full history with prefix caching, query-time resolution without views, and GRACE's template-serialisation variant. These curves measure write amortisation and view reuse, not maintenance (section 6.1).
- **Maintenance surface.** On the controlled sequences, sweep revision density against reads per history and report, for each staleness strategy, rebuild tokens and total cost relative to full history and query-time resolution. LoCoMo streaming gives one natural point on this surface.
- **Cost per successful task.** Total cost including failures divided by the number of successes, with the success rate; undefined when nothing succeeds.
- **Before and after caching.** The same results reported under both accountings. The payback read count $M^{*}$ is plotted as a curve over the cache ratio $c$ from 0 to 1, with the measured value marked, not reported at one or two points only.

### 8.4 Design constraints implied by the accounting

These items are rough estimates from published numbers, not measurements, used to set the order of magnitude of the write budget.

- **LoCoMo.** About 150 questions per history. Sources give four different token counts per history (about 8K, 9K, 16K and 26K), so they must be recounted with the primary model's tokenizer. At 20K, full history without caching costs about 3M input tokens per history; if cache-hit input costs one tenth, that is only about 300K. The writer's budget per history should therefore be on the order of 100K tokens, fixed after recounting.
- **Per-message extraction does not fit this budget.** A history has about 600 turns (recomputed after download), so 100K tokens leave fewer than 170 tokens per message, while one extraction call must hold the instructions, the schema, candidate entities, examples and the output. Only two options are feasible: batch extraction over segments of several messages or over sessions; or a fixed instruction prefix that hits the prefix cache, so that only the varying part is paid at full price. Extraction granularity is therefore a design variable (ablation G). Phase 1 first works out on paper the write tokens at each granularity, plots the payback curve over $c$ against cached full history, and makes a go or no-go decision; if payback does not hold on LoCoMo, the paper says so and cost claims rest only on settings with more reads. Under segment extraction a claim's knowledge version is still the version of its evidence message; when a read falls inside a segment, the part that has arrived is extracted before answering, and that call is counted as usual.
- **LongMemEval.** One question per history; a method whose write cost exceeds about 115K tokens cannot pay back in tokens. What is compared here is quality and the use of the answering LLM's context window, and the plan does not claim end-to-end token savings on this benchmark.
- **Compute.** The raw LongMemEval-S histories total about 57.5M tokens. Extrapolating from published build costs with the same backbone, the write side needs 80M to 680M tokens for the full set, more than all other benchmarks combined; this is why the main text uses three strata.

"Counting writes" and "payback question counts" have published precedents, and write-side tokens are commonly reported. This plan's increment is limited to four items: quality-matched comparison, cost per successful task including failed attempts, maintenance cost under updates, and before-and-after-caching comparison on small open-weight models. Write costs reported by other papers are not quoted for comparison, because the same system's accounting can differ by an order of magnitude between papers; every baseline is remeasured under the same accounting.

## 9. Implementation phases and scope of conclusions

Implementation has eight phases, numbered 0 to 7, each ending with a checkpoint. When a checkpoint fails, the corresponding claim is narrowed, and no component is added. Section 9.4 gives durations and staffing.

| Phase | Work | Output | Checkpoint: what to do if this happens |
| --- | --- | --- | --- |
| 0. Novelty check | Read the definition of scope keys in MemShift's appendix, and Martin et al. (2010) in full; search for "incremental maintenance of provenance or lineage" and for database work on "materialised views maintained by LLMs"; revise the wording of sections 2 and 3 accordingly | An item-by-item comparison of claim-pattern dependencies with existing dependency keys; final wording of the proposition and the staleness definition | Claim-pattern dependencies are already covered: claim no novelty in granularity, and narrow the contribution to two-level staleness, the formalisation on append-only bitemporal RDF and the evaluation on natural dialogue. Two-level staleness also has precedent: the paper becomes evaluation-led |
| 1. Pilot measurements | Run full history, text retrieval, rolling summary and the fixed slot table on development histories; freeze English prompts, counters, budgets and judge; recompute every benchmark's counts from the data files. Count MultiWOZ offer turns, check the 2.2/2.4 convention and fix the rule for derived gold (T006); compute the distribution of $v(q)$ for LoCoMo streaming (T007); write the controlled-sequence generator design (T008). Three cheap checks: annotate fragment coverage by hand; work out on paper the write budget at each extraction granularity; roughly measure the natural distribution of the seven change types. Choose the contemporary small model, the long-context answering model, the judge snapshot and the second annotator | History length distributions, cost of full-text completion, measured cache ratio; offer-turn counts and the resulting interval width; $v(q)$ spread and writes between adjacent reads; fragment coverage; payback curves over $c$; occurrences of the seven change types per thousand messages; generator design; model and judge choices | Few offer turns: the primary evidence for the claim about the attribution guard moves to the controlled sequences. Narrow $v(q)$ spread: LoCoMo streaming moves to the supplementary material. Fragment coverage below one half: lower expectations for RQ1 on LoCoMo and position the graph channel as a specialised channel. The write budget cannot pay back even on paper: claim no token savings on LoCoMo. The three kinds of change missed by citation-based dependencies are rare in natural dialogue: state that view maintenance targets high-revision workloads, with RQ2 resting on the controlled sequences |
| 2. Core mechanism on gold graphs | Implement the controlled-sequence generator; implement the claim model and validation shapes, the intermediate-representation compiler, views and the eight staleness strategies; compare full and local rebuilds turn by turn on gold graphs from the generator's event log; run the template-serialisation and LLM-rendering arms of ablation C on gold graphs; run the scale experiment for push, pull and hybrid | Ablation A on gold graphs; correct handling of new matches, an acceptance removing a candidate, confirmations that keep original constraints, and late corrections; answer accuracy of the template arm against the rendering arm; the crossover where push starts to pay off. These results are enough for a preprint | Template serialisation ties on answer accuracy: the paper becomes "a staleness criterion plus computing at query time", view maintenance is no longer a cost claim, and the cost experiments after phase 3 shrink accordingly. Read-time re-query is not more expensive anywhere in the range of the scale experiment: RQ2 narrows to "exact staleness checks are cheap". Claim-pattern-level decisions over-mark as much as predicate-level decisions on the controlled sequences: the RQ2 hypothesis on dependency granularity is overturned (section 4.2), and no benefit is claimed for the finer dependency |
| 3. End-to-end extraction and planning | Switch on the writer and the query planner; count extraction errors, planning errors and compilation failures separately; repeat the natural-distribution measurement with the final writer; rerun ablation C on extracted graphs | Graph-quality table; ablation A on extracted graphs, with decision misses separated from extraction-induced misses; view hit rate; ablation C; the writer-scale, thinking and extraction-granularity arms of ablation G | Most gains vanish on extracted graphs: conclude that the bottleneck is extraction and key alignment, and report how much the larger writer recovers. Low view hit rate: maintenance conclusions rest on the controlled sequences alone |
| 4. Context assembly and baselines | Implement routing, fusion and evidence-driven assembly; connect every baseline; run the three ledgers end to end | Ablations B and D, and E as capacity allows; quality-against-tokens curves on development data | Tagged hybrid retrieval obtains most of the gain attributed to the guard: the conclusion narrows to "speaker and dialogue-act information helps". The fixed slot table ties on open-domain slices: claim no gain from open predicates, and present RDF only as a standards-based representation |
| 5. Vocabulary evolution (optional) | Only if the frozen vocabulary shows real naming conflicts, add the conditionally triggered vocabulary-maintenance call | Ablations F and H; the call-type invocation arm of ablation G | A frozen vocabulary with aliases is equally effective: use it in the main configuration and report dynamic vocabulary as a negative result |
| 6. Lock and formal evaluation | Freeze configuration, splits, judging rules and budgets and preregister in the form of section 6.9; run all held-out sets and all baselines | Result tables for the main-text benchmarks, controlled probes with human audit; amortisation curves and maintenance surface; the summary-table benchmarks as capacity allows | No tuning after the lock; every deviation from the preregistration is disclosed |
| 7. Robustness checks | Long-context second answering model, contemporary small model, recommended decoding, reranking switched on | Whether the main conclusions and key failure modes hold under other configurations | Conclusions hold only on the primary model: restrict the claimed scope accordingly |

### 9.1 Scope of conclusions

- If the input to the LLM shrinks but end-to-end tokens grow, the conclusion narrows to "better use of the LLM's context window".
- If template-serialised fact cards match LLM-rendered views in answer accuracy, the paper is about "a staleness criterion plus computing at query time" and does not claim that maintained views are cheaper.
- If tagged hybrid retrieval obtains most of the gain attributed to the guard, only "speaker and dialogue-act information helps" is claimed. If the never-write-system-values rule also ties on paired correctness, no effect of the attribution guard is claimed.
- If the fixed slot table matches the claim graph on open-domain slices, no gain from open predicates is claimed. In no case is a graph claimed to beat a relational table with the same fields.
- If read-time re-query is not more expensive anywhere in the range of the scale experiment, the conclusion narrows to "exact staleness checks are cheap": the contribution is the staleness criterion and its evaluation, and push-based matching is reported as one implementation.
- If bitemporality helps only on synthetic data, the plan claims only that GRACE handles the mechanism.
- If full text is generally best on short histories, "when to switch on the graph channel" becomes an empirical result; similar findings exist, so this is supporting evidence only.
- Maintenance-cost claims rest on interleaved reading only; amortisation under end-of-history reading is never presented as evidence about maintenance. No cost argument is made on MultiWOZ.
- Gold-graph results are a correctness check, not an empirical finding; empirical conclusions come from extracted graphs and the natural-distribution measurement.
- The benchmarks are English everyday and task-oriented dialogues. No claim is made about extraction quality in specialised domains, or in dialogues whose speakers use different domain vocabularies.
- All performance gains, absolute times and API costs await measurement; the plan presupposes no numbers.

### 9.2 Main text and supplementary material

The paper follows the requirement that the 15-page LNCS main text be self-contained; reviewers are not obliged to read appendices. At the target conference the 15 pages exclude references, acknowledgements and the end-of-paper statements (as checked against the call), and an optional appendix of at most 2 pages is allowed. The rows below add up to 14.5 pages; page figures are targets for planning.

| Content | Location | Target pages |
| --- | --- | --- |
| Motivation, the three limitations, method in brief, contributions and three research questions | Main text | 1.5 |
| Related work, organised by the rows of section 2.1 | Main text | 1.5 |
| Formalisation: four kinds of entries, the two-level staleness definition, observation, proposition, exactness conditions | Main text | 1 |
| Claim model and vocabulary-mapping essentials; one query example; the two kinds of view, row binding and the eight strategies | Main text | 2.5 |
| Evaluation setup: read protocols, one benchmark table with tiers, baselines, models, cost accounting in brief | Main text | 2 |
| Results for RQ2: ablation A on the controlled sequences, gold and extracted graphs; the natural distribution of staleness; the crossover from the scale experiment; natural over-marking from MultiWOZ and LoCoMo streaming | Main text | 1.5 |
| Results for RQ1: MultiWOZ turns after an offer and ablation B; LoCoMo and LongMemEval-S slices | Main text | 1.5 |
| Results for RQ3: template serialisation against LLM rendering (ablation C); maintenance surface and amortisation curves; LongMemEval-S as the adverse case | Main text | 1 |
| One table for ablation D; one table for HaluMem and MemoryAgentBench as capacity allows | Main text | 1 |
| Discussion, scope of conclusions, limitations | Main text | 1 |
| Full proof, list of fragment assumptions, refined decision strategies, full intermediate-representation grammar | Supplementary | — |
| Full vocabulary, validation shapes, both serialisation examples, all query templates and prompts | Supplementary | — |
| Controlled-sequence generator design, audit records, construction of LoCoMo streaming read points, the view template list | Supplementary | — |
| LongMemEval-S full set (as capacity allows); LoCoMo on 1,441 cleaned questions; category 5; image-only questions | Supplementary | — |
| Ablations E to H; details behind the summary tables | Supplementary | — |
| Judge calibration, uncertainty decomposition, stratified results | Supplementary | — |
| Per-call token ledger, split lists, adaptation details of external baselines | Supplementary and the repository released with the paper | — |

### 9.3 Minimal publishable core

The full plan exceeds what a 15-page paper can hold. The table marks out a minimal core: with this part alone, each of the three claims still has its primary evidence. The rest is done as capacity allows and goes to the summary table or the supplementary material.

| Part | Content | Phases |
| --- | --- | --- |
| Core | The revised formalisation: four kinds of entries, two-level staleness, the soundness proposition and exactness conditions | 0, 2 |
| Core | Ablation A under three conditions: gold graphs, extracted graphs and the natural distribution of staleness; plus the scale experiment | 1, 2, 3 |
| Core | The template-serialisation arm of ablation C, against LLM rendering | 2, 3 |
| Core | The writer-scale, thinking and extraction-granularity arms of ablation G | 3 |
| Core | Ablation B on MultiWOZ, including the two single arms (tagged hybrid retrieval and the never-write-system-values rule) | 4 |
| Core | The maintenance surface (controlled sequences) and the LoCoMo amortisation curves | 3, 4, 6 |
| Core | Main-text baselines: full history, hybrid retrieval, rolling summary, fixed slot table, query-time resolution, Mem0; ablation D | 4, 6 |
| After the core | The three LongMemEval-S strata: required for the full paper and reported in the main text, not needed for the preprint; the most compute-intensive item, run after the core is complete | 6 |
| Optional | HaluMem-Medium and MemoryAgentBench | 6 |
| Optional | Ablation E (evidence-driven assembly against rank truncation) | 4 |
| Optional | Vocabulary evolution in phase 5; ablations F, the call-type invocation arm of G, and H | 5 |
| Optional | Mem0g and Graphiti; the full LongMemEval-S set | 6 |
| Optional | Robustness checks in phase 7 other than the contemporary small model | 7 |

At the end of phase 2 the formalisation, ablation A on gold graphs, the scale experiment and first results for the template arm are all available. At least five closely related preprints appeared in the two months before this plan was written, so the plan releases a preprint at that point, limited to these four items, and keeps the results on extracted graphs and natural benchmarks for the full paper. Double-anonymous review constrains the timing: the anonymity period of the target conference runs from one month before the submission deadline until notification, and no non-anonymised preprint may be posted or updated during it. The preprint is therefore released before the anonymity period starts; if that is missed, it waits until after notification.

### 9.4 Durations and staffing

The durations below are planning estimates for one full-time researcher working with coding agents. They have not been matched to actual staffing and are revised once staffing is known.

| Phase | Estimated duration | Additional people needed |
| --- | --- | --- |
| 0. Novelty check | 1 week | None |
| 1. Pilot measurements | 3 weeks | Second annotator: fragment coverage (100 overlapping questions), MultiWOZ derived gold (200 turns) |
| 2. Core mechanism on gold graphs | 5 weeks, of which 2 for the generator | Second annotator: sequence audit |
| 3. End-to-end extraction and planning | 4 weeks | Second annotator: graph quality (40 segments), correcting the extraction of the two LoCoMo development histories |
| 4. Context assembly and baselines | 4 weeks | None |
| 5. Vocabulary evolution (optional) | 2 weeks | None |
| 6. Lock and formal evaluation | 3 weeks, mostly compute | None |
| 7. Robustness checks | 2 weeks | None |

The core (phases 0 to 4 and phase 6) adds up to about 20 weeks, with the preprint around week 9. Manual annotation is estimated at 60 to 80 person-hours in total, more than half of it for graph-quality recall and extraction correction. This is the item most likely to overrun; if it does, the number of graph-quality segments is reduced first, not the sequence audit.

## 10. Risks and mitigations

The four largest risks: claim-pattern dependencies may already be covered by a closely related preprint; template serialisation may make cached views unnecessary; the extraction quality of a small-model writer may drag down the graph channel and every conclusion that depends on it; and read-time re-query may make push-based detection unnecessary.

| Risk | Evidence or symptom | Mitigation |
| --- | --- | --- |
| Claim-pattern dependencies already covered | Phase 0 found the pattern-matching principle in Martin et al. (2010), whose rule also invalidates rendered application objects; MemShift's definition-scope key is sound but coarser than claim patterns with constants and local filters; two-level staleness has only partial precedent in provenance maintenance, on uneven reading | Applied: no novelty is claimed for the granularity; the contribution rests on two-level staleness, the formalisation on append-only bitemporal RDF and the evaluation on natural dialogue (section 4.1) |
| Template serialisation is enough | View content comes from deterministic queries and the LLM only renders it; fact cards may yield equally accurate answers | The template arm is in the main text and runs in phase 2; if it ties, the paper is about "a staleness criterion plus computing at query time", and the staleness definition, the detection evaluation and the natural-distribution measurement still stand |
| Unreliable writer extraction | Small models have high format-error rates in structured writing; most systems miss many required updates | Output constrained by JSON schema and structurally validated; raw-text path kept on failure; graph quality reported in its own table; gold and extracted graphs reported separately, with decision misses separated from extraction-induced misses; a larger writer and enabled thinking estimate the ceiling |
| Write budget cannot pay back | On LoCoMo the budget is under 170 tokens per message, which per-message extraction cannot meet | Extraction granularity is a design variable; phase 1 works it out on paper and plots payback curves over $c$; if it cannot pay back, no token savings are claimed on that benchmark |
| Read-time re-query is enough | Published query-time numbers are good; on dialogue-scale graphs a re-query takes milliseconds and costs no LLM tokens | Read-time re-query is a formal arm and the exact reference; a hybrid arm and a scale experiment report the crossover where push starts to pay off; the paper is written so that its results stand even if pull wins |
| Too few interleaved reads in natural data | End-of-history benchmarks cannot test maintenance; LoCoMo streaming may have little spread in $v(q)$; the hit rate of resident views may be low | Maintenance claims rest on the controlled sequences; the view hit rate is reported; LoCoMo streaming is promoted to the main text only if T007 shows enough spread |
| Too few changes in natural dialogue | LoCoMo has no update-centred questions; the streaming protocol cannot measure true staleness by design | Re-query after every message on the extracted graphs of development histories and measure the natural distribution of the seven change types directly; if changes are few, state the applicable workload plainly |
| Synthetic sequences dismissed | The main RQ2 evidence is generated data; on gold graphs, missing nothing is guaranteed by the proposition and miss rates follow from the change mix | Gold-graph results are treated as a correctness check only; empirical conclusions come from extracted graphs and the natural-distribution measurement; generator design fixed before results; rendering by a model outside the evaluated systems; two-annotator audit; splits by template family; generator and logs released |
| Gap pre-empted | At least five related preprints appeared in the two months before this plan was written, two of which frame derived memory as views | Release a preprint after phase 2 (section 9.3); search again before finalising, including database work on "materialised views maintained by LLMs" |
| Relevance to the Semantic Web questioned | Relevance is the first review criterion; agents and memory are not in the call topics; reviewers will ask "why RDF" | No claim that a graph beats a relational table. The answer rests on four points: claims, attributions, provenance and time each use standard vocabularies (RDF 1.2 reifiers, PROV-O, OWL-Time); validation uses SHACL; queries are a well-defined SPARQL fragment; and the memory can be read and checked by other tools. The gain from open predicates is tested against the fixed slot table |
| Formalisation judged not new | The soundness proposition is an instance of known results | Stated honestly; novelty limited to two-level staleness, which has only partial precedent (section 4.1), the four kinds of entries covering attributions and evidence, and measurements on dialogue workloads |
| Query planning errors | Systems where LLMs write SPARQL directly fail on entity binding, silent empty results and missing aggregation | Only a restricted intermediate representation is generated; type checking; empty results state their evidence scope; failures fall back to text retrieval and the fallback rate is reported |
| Full history wins | Short histories fit in the window, and giving the LLM the full text is often the strongest row | Stratify by history length and read count; report losing regions explicitly; state conclusions as conditions of applicability, not general superiority |
| No gain from graph over flat structure | At small scale flat and graph memory score almost the same; most questions may fall outside the query fragment | Measure fragment coverage in phase 1; 2×2×2 over attribution guard, representation and time; look for the graph channel's value only on join, count and point-in-time slices |
| No precedent for the attribution guard | Outside dialogue state tracking, no study tests the offer–request distinction; a score on MultiWOZ may only reflect a projection rule that agrees with the annotation convention | Treated as an RQ1 hypothesis with narrowing conditions; paired correctness, with the never-write-system-values rule and tagged hybrid retrieval as controls; sample size counted in phase 1 (T006) |
| Ageing primary model and judge | Qwen3-8B dates from April 2025; judge snapshots get retired | Contemporary small model and judge snapshot chosen in phase 1; judge agreement with official judges measured; main conclusions repeated on the newer model |
| Vocabulary and templates overfit the development histories | The core vocabulary, view templates and prompts are all frozen on 2 LoCoMo development histories | Report the predicate miss rate and view hit rate on held-out histories; check templates and vocabulary on the controlled sequences and the LongMemEval development histories as well; if overfitting is clear, enlarge the development set and re-split before preregistration |
| Manual annotation overruns | Graph-quality recall requires listing every claim in a stretch of messages | Annotate sampled segments only; durations and person-hours in section 9.4; reduce graph-quality annotation first on overrun |
| Benchmark label noise and lenient judges | LoCoMo gold has errors; common judges accept vague wrong answers | Two-version reporting; judge negative controls; fixed answer prompt; uncertainty reported by source |
| External baselines run weakly | Graphiti's small-model scores vary widely in the literature | Publish adaptation, version and failure rate; keep a native-backbone row; separate native and same-backbone tables |
| Standards not yet stable | RDF 1.2 and SPARQL 1.2 are not yet Recommendations, and engine support is uneven | Define the model once with both RDF 1.2 and RDF 1.1 serialisations; queries run under RDF 1.1 |
| Data licence limits | LoCoMo is CC BY-NC 4.0; HaluMem forbids derivatives | Publish only split lists, scripts and pointers to annotation differences; never redistribute re-annotated data |

## 11. Reproducibility and sources

Data statistics cited in this plan are of two kinds: those already recomputed from the original files, with hashes in section 11.1; and those taken from papers or data cards, recomputed and registered with hashes at first download.

### 11.1 Data files and counts

| Original file | SHA-256 | Licence |
| --- | --- | --- |
| LoCoMo `locomo10.json` | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` | CC BY-NC 4.0 |
| LongMemEval `longmemeval_oracle.json` | `821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c` | Repository MIT |
| MultiWOZ 2.2 `test/dialogues_001.json` | `d6f43876cf130fdb2dfa8f96bc056b0995354137f02122e004925d01264ed386` | Repository MIT; licence of the data itself to be checked |
| MultiWOZ 2.2 `test/dialogues_002.json` | `89af95d8f596a448e733d59b31be78f1dd1632eddd99d5cb298a3fcb1ac9d185` | Same as above |

- **LoCoMo counts.** Build a `dia_id` dictionary per `sample_id`. All 1,986 questions decompose into 446 (category 5) plus 1,201 (evidence within one segment) plus 326 (evidence across segments) plus 13 (evidence missing or not fully resolvable). The last 13 stay in answer evaluation and are removed from the denominator of evidence metrics and from streaming.
- **LongMemEval.** The main experiments use `longmemeval_s_cleaned.json` (MIT); its hash, split lists and a per-`question_id` history-overlap audit are published with the formal run manifest. What the cleaned version changes relative to the original must be established and recorded.
- **MultiWOZ 2.4 and 2.1.** The files are downloaded under `data/multiwoz`, each version with a `MANIFEST.sha256`. The manifest checksum is recorded when the benchmark is bound in `configs/benchmarks/multiwoz.yaml`; whether each version keeps dialogue-act annotation is checked in T006.
- **HaluMem.** CC BY-NC-ND 4.0. Whether the 3,122 updated memories are included in the 14,948 memory points must be confirmed from the files.
- **MemoryAgentBench.** The data card states MIT; it is checked against the licence statement in the paper before registration.
- Files without a listed hash are registered at first download.

### 11.2 Materials released with the paper

- The claim model's vocabulary, validation shapes and examples of both serialisations.
- The intermediate-representation grammar, the compiler, all query templates and the template list of resident views.
- The full proof of the proposition and the list of fragment assumptions.
- Prompts and output schemas for every LLM call type, and the frozen decoding settings.
- Split lists, exclusion reasons and counts per category.
- The preregistered protocol file and its hash; the rule for MultiWOZ derived gold and its check records.
- The LoCoMo streaming read-point lists ($v(q)$ per question).
- Per-call token-ledger records and aggregation scripts.
- The controlled-sequence generator, event logs and audit records.
- Versions, adaptation patches and failure rates of external baselines.

During review these materials are provided through an anonymous link.

### 11.3 References

Reading depth: "full" means the method, experiments and limitations were read; "abstract" means only the abstract level; "unread" means the original has not been obtained and must be read before citing. An entry without a depth mark was not read specifically for this plan; its original text is read before any specific result from it is cited. "Preprint" means not peer reviewed.

**Context, compression and retrieval**

- Liu et al., Lost in the Middle. TACL 2024
- Hsieh et al., RULER. COLM 2024
- Wang et al., Recursively Summarizing Enables Long-Term Dialogue Memory. Neurocomputing 2025
- Packer et al., MemGPT (preprint). arXiv 2310.08560
- Jiang et al., LLMLingua. EMNLP 2023
- Robertson and Zaragoza, The Probabilistic Relevance Framework: BM25 and Beyond. 2009
- Karpukhin et al., Dense Passage Retrieval. EMNLP 2020
- Cormack, Clarke and Büttcher, Reciprocal Rank Fusion. SIGIR 2009

**Memory systems and closest work**

- Zep: A Temporal Knowledge Graph Architecture for Agent Memory (full). arXiv 2501.13956 · Graphiti
- APEX-MEM (full). ACL 2026
- ProgMem (full). Findings of IJCNLP-AACL 2026
- Mem0 and Mem0g (full). ECAI 2025; arXiv 2504.19413
- LightMem (full). arXiv 2510.18866
- PACMI (preprint, full). arXiv 2610.05732
- MemoRepair (preprint, full). arXiv 2605.07242
- MemTX (preprint, full). arXiv 2607.23929
- Kumiho (preprint, full). arXiv 2603.17244
- Memories That Outlive Their Reasons: Dependency-Tethered Memory for Tool-Using LLM Agents (preprint, full). arXiv 2610.25123
- MemShift (preprint, full, including appendices C and F). arXiv 2611.02338
- MemDerive (preprint, full). arXiv 2610.25373
- StateMem and StateMemBench: Can Agent Memory Systems Track Evolving State? (preprint, full). arXiv 2608.19652
- StateGraph and StateChangeBench: A State Change Is Local, Its Consequences Are Not (preprint, full). arXiv 2611.02912
- MemIR (preprint). arXiv 2605.25869
- Deng et al., Stale, Misattributed, or Late: Where Personal Memory Fails Before Generation (speaker misattribution in multi-session stores; a controlled revision generator) (preprint). arXiv 2610.10265
- GroundedCache (preprint, full). arXiv 2605.27494
- CacheSense (not found under this name)
- FreshCache, freshness-aware semantic caching (preprint, unread). arXiv 2607.04281
- LeanMem (preprint). arXiv 2608.03463
- A second preprint reporting full-history Qwen3-8B accuracy on LoCoMo (preprint, abstract). arXiv 2606.20911
- Does Memory Need Graphs? (preprint). arXiv 2601.01280
- Anatomy of Agentic Memory (preprint). arXiv 2602.19320
- A unified reproduction study of memory systems. arXiv 2604.01707
- Letta, Benchmarking AI Agent Memory (vendor blog). letta.com

**RDF dialogue memory, querying and standards**

- Vossen et al., Leolani (abstract). arXiv 1806.01526
- An and Gentile, RDF-based conversational memory (full). CEUR Vol-4210
- Martin, Unbehauen and Auer, Improving the Performance of Semantic Web Applications with SPARQL Query Caching (full). ESWC 2010
- Williams and Weaver, Enabling Fine-Grained HTTP Caching of SPARQL Query Results. ISWC 2011
- Ali et al., a survey of SPARQL query processing. arXiv 2102.13027
- Incremunica (full). ESWC 2025 Resource Track
- SPARQLprov. PVLDB 2021
- BEAR: query types for RDF archives. Project page
- BiTRDF; Bi-VAKs: bitemporal RDF models
- Arenas and Ugarte, Designing a Query Language for RDF: Marrying Open and Closed Worlds (full). TODS 2017
- W3C, SPARQL 1.1 Query Language. Recommendation, 2013
- W3C, PROV-O: The PROV Ontology. Recommendation
- W3C, Shapes Constraint Language (SHACL). Recommendation
- W3C, RDF 1.2 Concepts and Abstract Data Model. Candidate Recommendation Snapshot, 2026-04-07
- ISO 24617-2:2020, Dialogue acts

**View maintenance, independence and provenance**

- Blakeley, Coburn and Larson, Updating Derived Relations: Detecting Irrelevant and Autonomously Computable Updates (full). VLDB 1986
- Levy and Sagiv, Queries Independent of Updates (full). VLDB 1993
- Gupta and Mumick, survey of materialised view maintenance (1995)
- Motik et al., Maintenance of Datalog Materialisations Revisited. Artificial Intelligence 2019
- DBSP. PVLDB 2023
- Green, Karvounarakis and Tannen, Provenance Semirings. PODS 2007
- Geerts et al., spm-semiring: provenance for non-monotone SPARQL queries
- Amsterdamer, Deutch and Tannen, Provenance for Aggregate Queries. PODS 2011
- Green, Karvounarakis, Ives and Tannen, Update Exchange with Mappings and Provenance (ORCHESTRA; maintenance section read). VLDB 2007
- Liu, Taylor, Zhou, Ives and Loo, Recursive Computation of Regions and Connectivity in Networks (absorption provenance; technical report read). ICDE 2009
- RDA Working Group on Data Citation, Precise, Actionable Reference to Dynamic Data (full). Recommendation, revised 2025-04-04
- Enzyme: Incremental View Maintenance for Data Engineering (preprint). arXiv 2603.27775
- Shankar and Parameswaran, Building Reactive LLM Pipelines with Motion (abstract). SIGMOD 2024 demo
- Semantic-operator systems: LOTUS, Palimpzest, DocETL
- Doyle, A Truth Maintenance System (1979)
- Adapton. PLDI 2014
- Agrawal, Chaudhuri and Narasayya, Automated Selection of Materialized Views and Indexes for SQL Databases. VLDB 2000

**Vocabulary and graph construction**

- Extract, Define, Canonicalize. EMNLP 2024
- AutoSchemaKG. ACL 2026
- DIAL-KG (preprint). arXiv 2603.20059

**Dialogue state tracking**

- TripPy. arXiv 2005.02877
- ParsingDST. arXiv 2310.10520
- ReacTOD (preprint). arXiv 2605.19077
- Description-Driven Task-Oriented Dialog Modeling (D3ST). arXiv 2201.08904

**Benchmarks and evaluation methodology**

- Evaluating Very Long-Term Conversational Memory of LLM Agents (LoCoMo). ACL 2024 · data
- Independent LoCoMo audit (not peer reviewed). GitHub
- LongMemEval. ICLR 2025 · code · data
- MultiWOZ 2.1, 2.2, 2.4. Papers · data
- HaluMem. arXiv 2511.03506 · data card
- MemoryAgentBench. arXiv 2507.05257 · data card
- BEAM (related; not evaluated). ICLR 2026; arXiv 2510.27246
- Memora (related; not evaluated). Findings of ACL 2026; arXiv 2604.20006
- STALE (related; not evaluated; first half of the body read). arXiv 2605.06527
- LoCoMo-Plus (preprint, unread; tests recall of implicit constraints, not directly about updates; not included). arXiv 2602.10715
- Same Ranking, Different Winner: an audit of what evidence scoring counts. Findings of EMNLP 2026
- Pollertlam and Kornsuwannawit, payback analysis with cache discounts (preprint). arXiv 2603.04814
- A unified evaluation study of memory methods. IJCNLP-AACL 2026
- MERIT (preprint, abstract). arXiv 2609.05441

**Models**

- Qwen3-8B. Model card
- Qwen3-Embedding-0.6B. Model card

### 11.4 Items to verify

The first four items belonged to phase 0 and were closed by T011 on 2026-11-23; results and sources are in `docs/research/literature.md` (Phase 0 novelty check).

- MemShift's scope key: closed. It fingerprints a hand-coded record range per definition, including the definition's condition and window, and is coarser than claim patterns with constants and local filters.
- The rule of Martin et al. (2010): closed. It covers OPTIONAL and FILTER, treats insertions and deletions alike and has a soundness proposition with a proof (Proposition 1); section 3.4 is worded accordingly.
- Precedent for a separate witness or evidence level: closed for phase 0. Provenance maintenance (ORCHESTRA, absorption provenance) tracks provenance-only changes, but no work read defines them as a level of staleness. The data-citation papers were read only at abstract level (see the item below).
- LLM-maintained materialised views and semantic operators: closed. No overlap found; most items were read at abstract or snippet level, so this search is repeated with the others before the paper is finalised.

The remaining items are completed in their phase or before the paper is finalised.

- How the timing of the preprint relates to the anonymity period of the target conference (section 9.3).
- MultiWOZ: the 2.2 and 2.4 annotation conventions, offer-turn counts, whether each version's files keep dialogue-act annotation, and the check of the derived-gold rule (T006).
- The spread of $v(q)$ in LoCoMo and the threshold for promoting streaming to the main text (T007); turns and tokens per history.
- The contemporary small model, the long-context second answering model and the judge snapshot: licence, context length and availability checked against model cards and provider notices.
- Who the second annotator is, and whether the durations of section 9.4 match actual staffing.
- Numbers marked "to be re-checked" in section 2.2.
- HaluMem: how the claim graph is projected onto the scoring interface of "memories extracted per session", fixed before the adapter is written.
- The generative-AI authorship policy of the target conference, checked before submission.
- Full texts of the data-citation papers (Buneman and Silvello 2010; Davidson et al. 2017; Wu et al. 2018; ProvCite 2019) and of Trio's lineage maintenance, read before the paper claims two-level staleness as new.
- Foundational references (Elkan 1990, the temporal RDF line, Doyle, Adapton, Gupta and Mumick) checked against the originals before citing.
- Counts and licences of every benchmark recomputed and registered from the files after download.
