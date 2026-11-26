# Code Structure: Full Tree

The complete layout down to every file, in one tree. `structure.md` is the specification: it gives the dependency rules and the full responsibility of each file. When the two disagree, `structure.md` is right and this file is updated.

```text
GRACE/
├── src/grace/
│   ├── cli/                            entry points only, no logic
│   │   ├── data/
│   │   │   ├── download.py             download benchmarks (exists)
│   │   │   └── changeseq.py            build the controlled-sequence dataset
│   │   └── run/
│   │       ├── experiment.py           expand an experiment config into cells, schedule stages
│   │       ├── system.py               system stage: ingestion, reading and answering
│   │       ├── probe.py                probes
│   │       ├── judge.py                judging stage
│   │       ├── score.py                scoring stage
│   │       └── report.py               tidy tables from a list of run IDs
│   │
│   ├── config/                         configuration
│   │   ├── paths.py                    REPO_ROOT, PROJECT_ROOT, shared directories
│   │   ├── schema.py                   structure and validation of the four config kinds
│   │   ├── loader.py                   read YAML, resolve references, write the resolved config
│   │   ├── registry.py                 component name → import path
│   │   └── freeze.py                   checksums of resources and locked configs
│   │
│   ├── llm/                            the only exit for model calls
│   │   ├── client.py                   chat completion
│   │   ├── embedding.py                embedding
│   │   ├── tokens.py                   token counting
│   │   ├── prompts.py                  template loading, fixed-prefix assembly
│   │   ├── structured.py               output parsing against JSON Schema
│   │   ├── records.py                  call records, ledger categories; writes calls.jsonl
│   │   └── proxy.py                    recording endpoint for external systems
│   │
│   ├── context/                        GRACE itself (plan section 5)
│   │   ├── api.py                      ContextEngine interface, its types, write and read traces
│   │   ├── engine.py                   assembly of GraceEngine; order of write and read steps
│   │   ├── memory/                     memory layer: storage only
│   │   │   ├── history/
│   │   │   │   ├── log.py              append-only message log, version allocation
│   │   │   │   └── spans.py            span anchors, evidence IDs
│   │   │   ├── index/
│   │   │   │   ├── chunking.py         tokenisation and chunking
│   │   │   │   ├── bm25.py
│   │   │   │   └── dense.py
│   │   │   └── graph/
│   │   │       ├── entries.py          claim, attribution, evidence link, supersession event
│   │   │       ├── rdf.py              mapping between entries and triples
│   │   │       ├── store.py            store, commit, SPARQL execution
│   │   │       ├── changeset.py        change set
│   │   │       ├── vocabulary.py       vocabulary, aliases, exclusivity rules
│   │   │       └── entities.py         entity equivalence
│   │   ├── pipeline/                   pipeline layer, split by function
│   │   │   ├── update/                 write path
│   │   │   │   ├── patch.py            claim patch
│   │   │   │   ├── extract.py          extractor interface, LLM writer
│   │   │   │   ├── candidates.py       candidate entities and predicates for the writer
│   │   │   │   ├── segment.py          extraction granularity
│   │   │   │   ├── validate.py         SHACL validation
│   │   │   │   ├── guard.py            attribution guard
│   │   │   │   ├── commit.py           graph transaction
│   │   │   │   ├── updater.py          write loop: units, retries, failure handling
│   │   │   │   └── vocab.py            vocabulary maintenance (optional)
│   │   │   ├── query/
│   │   │   │   ├── ir.py               intermediate representation, claim patterns
│   │   │   │   ├── templates.py        rule templates
│   │   │   │   ├── plan.py             planning
│   │   │   │   ├── compile.py          intermediate representation → SPARQL
│   │   │   │   ├── patterns.py         dependency patterns
│   │   │   │   ├── execute.py          execution; answers, witnesses, evidence
│   │   │   │   └── result.py           result types, fingerprints
│   │   │   ├── retrieval/
│   │   │   │   ├── candidates.py       candidate type
│   │   │   │   ├── text.py             BM25 and dense channels
│   │   │   │   ├── graph.py            graph channel
│   │   │   │   ├── route.py            routing
│   │   │   │   ├── fuse.py             fusion
│   │   │   │   └── retrieve.py         retrieval config and retriever
│   │   │   └── assembly/
│   │   │       ├── demand.py           variables an answer needs
│   │   │       ├── filter.py           filtering and verification
│   │   │       ├── select.py           greedy selection within the budget
│   │   │       ├── expand.py           expansion request when variables stay uncovered
│   │   │       └── layout.py           serialisation into the fixed layout
│   │   └── views/
│   │       ├── view.py                 view and row binding
│   │       ├── template_families.py    the six template families
│   │       ├── store.py                view store
│   │       ├── render.py               template serialisation, LLM rendering
│   │       ├── rebuild.py              local rebuild, citation patching
│   │       └── staleness/              the eight staleness-decision strategies
│   │           ├── base.py             strategy interface
│   │           ├── trivial.py          never invalidate; full rebuild every turn
│   │           ├── citation.py         the two citation-based strategies
│   │           ├── pattern.py          predicate level; claim-pattern push
│   │           └── requery.py          read-time re-query; hybrid
│   │
│   └── eval/                           experiment apparatus (plan sections 6 to 8)
│       ├── datasets/                   experiment inputs
│       │   ├── benchmarks/
│       │   │   ├── records.py          history, question, gold data
│       │   │   ├── base.py             adapter interface, manifest checks
│       │   │   ├── splits.py           split loading, held-out guard
│       │   │   ├── multiwoz.py
│       │   │   ├── locomo.py
│       │   │   ├── longmemeval.py
│       │   │   ├── halumem.py
│       │   │   ├── memoryagentbench.py
│       │   │   └── changeseq.py
│       │   └── changeseq/              generator of the controlled change sequences
│       │       ├── events.py           event grammar, event log
│       │       ├── template_families.py template families, controlled variables
│       │       ├── gold.py             gold graph at every version
│       │       ├── schedule.py         read schedule, gold answers
│       │       ├── invalidation.py     invalidation ground truth, from the event log
│       │       ├── render.py           surface text rendering
│       │       ├── audit.py            audit samples, agreement
│       │       └── build.py            dataset and manifest
│       ├── engines/                    the systems under comparison
│       │   ├── baselines/              engines that do not use the GRACE assembly
│       │   │   ├── raw.py              full history, last-k, truncation
│       │   │   ├── retrieval.py        BM25, dense, RRF
│       │   │   ├── tagged.py           RRF with speaker and dialogue-act tags
│       │   │   ├── summary.py          rolling summary
│       │   │   ├── multiwoz.py         MultiWOZ baselines
│       │   │   ├── mem0.py
│       │   │   └── graphiti.py         optional
│       │   └── oracles/                labelled upper-bound experiments only
│       │       ├── graph.py            gold-graph extractor
│       │       ├── ir.py               perfect intermediate representation
│       │       └── evidence.py         gold evidence
│       ├── runner/                     how experiments run
│       │   ├── harness/                experiments that call the answering LLM
│       │   │   ├── rundir.py           run directory, run.json
│       │   │   ├── cells.py            experiment config → cells
│       │   │   ├── protocols.py        read protocols → read schedule
│       │   │   ├── drive.py            alternate writes and reads
│       │   │   ├── snapshot.py         save and restore engine state
│       │   │   ├── answer.py           the answering LLM
│       │   │   └── outputs.py          predictions, working contexts, traces
│       │   └── probes/                 experiments that ask no questions
│       │       ├── replay.py           replay of the eight staleness strategies
│       │       ├── scale.py            push, pull and hybrid at scale
│       │       ├── natural.py          natural distribution of staleness
│       │       └── extract.py          writer only
│       └── analysis/                   after a run; reads run directories only
│           ├── judging/
│           │   ├── judge.py            blind judge
│           │   ├── official.py         official LongMemEval judge
│           │   └── calibration.py      calibration
│           ├── metrics/
│           │   ├── align.py            alignment of predictions and gold data
│           │   ├── answer.py           answer metrics
│           │   ├── dst.py              MultiWOZ metrics
│           │   ├── evidence.py         evidence recall, view hit rate
│           │   ├── staleness.py        staleness-decision metrics
│           │   ├── graph.py            graph-quality metrics
│           │   ├── cost.py             cost ledgers
│           │   └── strata.py           stratum labels
│           └── reporting/              no plotting
│               ├── collect.py          run IDs → tidy tables
│               ├── stats.py            statistical tests
│               ├── curves.py           curve data
│               └── tables.py           tables of the paper
│
├── resources/                          released with the code; frozen at D012
│   ├── prompts/                        one directory per LLM call type
│   ├── rdf/                            vocabulary, SHACL shapes, aliases, exclusivity rules
│   ├── views/                          query template and sentence pattern per template family
│   ├── schemas/                        JSON Schemas for LLM outputs and stored records
│   └── changeseq/                      event grammar and template families
├── configs/
│   ├── common/paths.yaml               shared by every experiment, never varied
│   ├── data/sources.yaml               download sources
│   ├── benchmarks/                     version, manifest checksum, splits
│   ├── models/                         models, decoding, embedding, judge snapshot
│   ├── engines/                        GRACE, its variants, the baselines
│   └── experiments/                    one file per E<NNN>
├── tests/
│   ├── contracts/                      import rules, gold sentinel, lock check, interface tests
│   ├── integration/
│   ├── docs/
│   └── fixtures/
├── scripts/                            bash entry points only
├── envs/serve/                         GPU inference environment
├── docs/
└── paper/                              figure scripts read only reporting's tidy tables
```
