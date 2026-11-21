# Introduction (draft)

Status: draft for discussion. Citations are numbered in order of first appearance. References follow the Springer LNCS style (splncs04), with a DOI or stable URL for every entry; they were checked against publisher, arXiv, W3C and ISO records on 2026-11-21.

## Context is a scarce resource

LLM-based agents accumulate interaction histories that grow without bound, while the context available to the model at each step is bounded. Larger windows only partly relax this constraint. The computational and monetary cost of each call grows with the length of the input. Models also use long inputs unevenly: accuracy drops when the relevant information sits in the middle of the input [1], and the effective context length is often far shorter than the advertised one [2]. Reading the full history at every step is therefore expensive, and it is not guaranteed to be the most accurate option either.

## Existing approaches

Current systems reduce the context an agent reads in three main ways.

- **Compaction.** The history, or its older part, is replaced by a shorter derived text. Examples are rolling or recursive summaries [3], hierarchical memory that pages content in and out of the context [4], the automatic context compaction built into agent harnesses, and token-level prompt compression [5]. Compaction keeps the read cost low and preserves a coherent narrative of the history.
- **Retrieval.** The history is stored externally, and a compact context is assembled at each step through *hybrid retrieval*. It combines lexical matching with BM25 [6], which is robust for names, numbers and identifiers, with dense, embedding-based retrieval [7], which is robust for paraphrase and coreference, and fuses the two rankings, for instance with Reciprocal Rank Fusion (RRF) [8]. Retrieval is effective when the answer is located in a few self-contained passages.
- **Structured memory.** Facts are extracted into memory records, state tables or graphs and queried at read time [9, 10].

## Where these approaches fail

Each family breaks down when the state described by the history *evolves*. We identify three failure modes.

- **Stale derived context.** A compacted text is computed from earlier turns. Later turns revise facts, extend sets, or accept and reject proposals, and the compacted text becomes invalid without any signal to the agent. Because a summary does not record which part of the history each of its sentences depends on, the only safe remedy is to regenerate it in full, which reintroduces the cost that compaction was meant to avoid. Compaction is also lossy: details discarded at compaction time cannot be recovered when a later question needs them.
- **Attribution.** A system offer and a user request may be lexically and semantically near-identical, yet only one of them should determine the current constraint. Neither ranked passages nor free-text summaries make this distinction explicit.
- **Dispersed evidence.** Questions about sets, counts, latest states or the state at a past point in time require combining evidence scattered across the history. Ranked passages do not provide this combination, and summaries provide it only for the questions anticipated when they were written.

## Knowledge graphs as a structured complement

Knowledge graphs address these failure modes directly.

- **Attribution.** Reification in RDF 1.2 [11] makes it possible to represent what was *said* separately from what is *accepted*, and to attribute each statement to a speaker and a communicative function.
- **Time.** A bitemporal model separates the time at which a fact holds (valid time) from the time at which it was recorded (transaction time).
- **Exact queries.** SPARQL [12] provides exact joins, aggregation and time-sliced selection, and it returns the provenance of each answer.

Existing graph-based agent memories adopt parts of this design. Zep/Graphiti, for instance, invalidates individual edges on conflict [10], and provenance-based approaches propagate invalidation from the facts that a derived artifact consumed [13, 14]. None of them, however, treats derived context as a materialized view whose validity is determined by the *query* it answers. This is the gap between compaction and graph memory that we target: compaction produces derived context without knowing when it expires, while graph memory knows when individual facts change but not when the derived context built on them does.

## Approach

We propose a *graph-enhanced context engine*: a structured channel added to hybrid lexical–dense retrieval, together with query-defined derived context.

- **Claims.** Each message is extracted into claims, represented with RDF 1.2 reifiers [11] so that they are not asserted by default.
- **Attribution and evidence.** Each claim is linked to its speaker through an attribution node that carries a communicative function as defined in ISO 24617-2 [15], and to character-level evidence spans in the source message.
- **Versioning.** The graph is append-only and bitemporal.
- **Query compilation.** For each task, the engine compiles a typed intermediate representation into a restricted fragment of SPARQL 1.1 [12].
- **Fusion and assembly.** It fuses the structured results with lexical and dense candidates and assembles a token-budgeted context in which every item cites its source messages.
- **Views.** Frequently read derived context is maintained as *views*: query-defined materializations, rendered into text by an LLM, that are re-rendered only when they become stale. A view plays the role of a compacted summary, but because it is defined by a query, the engine can decide when it expires and rebuild only that view.

## Objectives

The engine pursues two objectives jointly. The first is to *preserve or improve task accuracy* relative to full-history reading, compaction and hybrid retrieval. The second is to *reduce end-to-end token cost*, accounting for every LLM call on both the write path (extraction, validation, view rendering, failed attempts) and the read path (planning, answering).

## Research questions

**RQ1: Where does the graph channel improve accuracy?** On which question types does adding the structured channel to hybrid lexical–dense retrieval improve task accuracy? We hypothesize gains on attribution-sensitive state tracking, aggregation, multi-hop joins and time-sliced queries, and parity on single-passage lookup. We further ask whether these gains require a graph, or whether a role-annotated relational state table with the same fields and provenance achieves them.
*Falsified if* hybrid retrieval with the same reader and token budget matches the graph-enhanced configuration on these slices. *Narrowed if* the role-annotated table matches the graph: we then attribute the gains to attribution alone.

**RQ2: When must a view be re-rendered?** We define a view with cutoff version $r_0$ to be *stale* at version $r$ iff the answer set of its defining query, or the witness sets of those answers, differs between $r_0$ and $r$. Invalidation based on witnesses (why-provenance) misses insertions that create new answers. For non-monotone operators, such as negation (which encodes supersession), counting and latest-state selection, it also misses insertions that remove or change answers. In an append-only graph every revision is an insertion, so this case is the norm rather than an edge case.

We compare six strategies:

- no invalidation;
- full recomputation, which serves as the reference;
- witness-based invalidation;
- predicate-level invalidation;
- push-based matching of changesets against the triple patterns of view queries;
- pull-based re-evaluation with answer fingerprints.

We assess each strategy by its agreement with full recomputation and by its re-rendering cost.
*Narrowed if* insertion-induced staleness is rare in natural dialogue, or if pull-based re-evaluation is equally exact and no more costly. The contribution then reduces to the staleness criterion and its evaluation.

**RQ3: When does the accuracy–cost trade-off favor the graph-enhanced engine?** We characterize the accuracy–cost Pareto frontier of our engine against three kinds of baselines. The first is full-history reading, with and without prefix caching. The second is compaction, both rolling summaries regenerated after every update and summaries reused without regeneration. The third is hybrid retrieval, a role-annotated state table, and an append-only memory that resolves conflicts at query time without views. We vary the number of reads per history, revision density and context budget. For each regime, we report the break-even number of reads $M^{*}$ at which cumulative write-side cost is amortized, and we identify the regimes in which the engine does not dominate.
*Falsified if* the savings stem only from shorter reader prompts and vanish once write-side cost is counted, or if $M^{*}$ exceeds the number of reads observed in the benchmarks.

**Component analyses** (reported as ablations, not headline claims):

- retrieval channels (lexical, dense, structured), each removed in turn;
- fusion methods (RRF, weighted, learned);
- routing (always-all, rule-based, learned);
- context assembly driven by evidence requirements, compared with rank-and-truncate;
- vocabulary evolution, compared with a frozen vocabulary plus aliases.

## References

[1] Liu, N.F., Lin, K., Hewitt, J., Paranjape, A., Bevilacqua, M., Petroni, F., Liang, P.: Lost in the middle: How language models use long contexts. Transactions of the Association for Computational Linguistics 12, 157–173 (2024). https://doi.org/10.1162/tacl_a_00638

[2] Hsieh, C.P., Sun, S., Kriman, S., Acharya, S., Rekesh, D., Jia, F., Zhang, Y., Ginsburg, B.: RULER: What's the real context size of your long-context language models? In: Proceedings of the First Conference on Language Modeling (COLM) (2024). https://arxiv.org/abs/2404.06654

[3] Wang, Q., Fu, Y., Cao, Y., Wang, S., Tian, Z., Ding, L.: Recursively summarizing enables long-term dialogue memory in large language models. Neurocomputing 639, 130193 (2025). https://doi.org/10.1016/j.neucom.2025.130193

[4] Packer, C., Wooders, S., Lin, K., Fang, V., Patil, S.G., Stoica, I., Gonzalez, J.E.: MemGPT: Towards LLMs as operating systems. arXiv preprint arXiv:2310.08560 (2023). https://arxiv.org/abs/2310.08560

[5] Jiang, H., Wu, Q., Lin, C.Y., Yang, Y., Qiu, L.: LLMLingua: Compressing prompts for accelerated inference of large language models. In: Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing (EMNLP), pp. 13358–13376. Association for Computational Linguistics, Singapore (2023). https://doi.org/10.18653/v1/2023.emnlp-main.825

[6] Robertson, S., Zaragoza, H.: The probabilistic relevance framework: BM25 and beyond. Foundations and Trends in Information Retrieval 3(4), 333–389 (2009). https://doi.org/10.1561/1500000019

[7] Karpukhin, V., Oğuz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen, D., Yih, W.t.: Dense passage retrieval for open-domain question answering. In: Proceedings of the 2020 Conference on Empirical Methods in Natural Language Processing (EMNLP), pp. 6769–6781. Association for Computational Linguistics (2020). https://doi.org/10.18653/v1/2020.emnlp-main.550

[8] Cormack, G.V., Clarke, C.L.A., Büttcher, S.: Reciprocal rank fusion outperforms Condorcet and individual rank learning methods. In: Proceedings of the 32nd International ACM SIGIR Conference on Research and Development in Information Retrieval (SIGIR), pp. 758–759. ACM (2009). https://doi.org/10.1145/1571941.1572114

[9] Chhikara, P., Khant, D., Aryan, S., Singh, T., Yadav, D.: Mem0: Building production-ready AI agents with scalable long-term memory. In: ECAI 2025. Frontiers in Artificial Intelligence and Applications. IOS Press (2025). https://doi.org/10.3233/FAIA251160. Preprint: arXiv:2504.19413

[10] Rasmussen, P., Paliychuk, P., Beauvais, T., Ryan, J., Chalef, D.: Zep: A temporal knowledge graph architecture for agent memory. arXiv preprint arXiv:2501.13956 (2025). https://arxiv.org/abs/2501.13956

[11] Hartig, O., Champin, P.A., Kellogg, G., Seaborne, A. (eds.): RDF 1.2 Concepts and Abstract Data Model. W3C Candidate Recommendation Snapshot, 7 April 2026. https://www.w3.org/TR/2026/CR-rdf12-concepts-20260407/

[12] Harris, S., Seaborne, A. (eds.): SPARQL 1.1 Query Language. W3C Recommendation, 21 March 2013. https://www.w3.org/TR/2013/REC-sparql11-query-20130321/

[13] Wang, Y., Liu, J., Zhang, J., Wu, Z., Duan, Y., Zheng, M., Cai, T.: PACMI: Provenance-aware cascading memory invalidation for long-term LLM agents. arXiv preprint arXiv:2610.05732 (2026). https://arxiv.org/abs/2610.05732

[14] Zhao, Y., Dai, C., Kou, M., Xiu, Y.: MemoRepair: Barrier-first cascade repair in agentic memory. arXiv preprint arXiv:2605.07242 (2026). https://arxiv.org/abs/2605.07242

[15] ISO: ISO 24617-2:2020 Language resource management — Semantic annotation framework (SemAF) — Part 2: Dialogue acts. Edition 2. International Organization for Standardization, Geneva (2020). https://www.iso.org/standard/76443.html
