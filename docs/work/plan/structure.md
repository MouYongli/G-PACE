# Code Structure

This file describes how the code in `src/grace/` is organised: the packages, what each file is for, and which package may import which. The reasons for the layout are recorded in `docs/work/decisions/D013-code-structure.md`. The system itself is specified in `docs/research/plan.md` (section 5 for GRACE, sections 6 to 8 for the experiments).

`structure_full.md` shows the same layout as one tree down to every file.

File names are a starting point and may change as tasks implement them. The package boundaries and the dependency rules are fixed by D013; changing them needs a new decision.

## Overview

```text
GRACE/
├── src/grace/
│   ├── cli/                    entry points only, no logic
│   ├── config/                 config loading, component registry, paths
│   ├── llm/                    the only exit for model calls
│   ├── context/                GRACE itself (plan section 5)
│   │   ├── api.py              the ContextEngine interface and its types
│   │   ├── engine.py           assembly of GraceEngine; order of write and read steps
│   │   ├── memory/             memory layer: storage only
│   │   │   ├── history/        message log, versions, evidence spans
│   │   │   ├── index/          BM25 and dense indexes
│   │   │   └── graph/          claim graph
│   │   ├── pipeline/           pipeline layer, split by function
│   │   │   ├── update/         extraction, validation, attribution guard, commit
│   │   │   ├── query/          intermediate representation, planning, compilation, execution
│   │   │   ├── retrieval/      three channels, routing, fusion
│   │   │   └── assembly/       evidence-driven context assembly
│   │   └── views/              views: templates, store, rendering, staleness, rebuild
│   └── eval/                   experiment apparatus (plan sections 6 to 8)
│       ├── datasets/           experiment inputs
│       │   ├── benchmarks/     benchmark adapters, splits
│       │   └── changeseq/      generator of the controlled change sequences
│       ├── engines/            the systems under comparison
│       │   ├── baselines/      engines that do not use the GRACE assembly
│       │   └── oracles/        gold components for labelled upper-bound experiments
│       ├── runner/             how experiments run
│       │   ├── harness/        experiments that call the answering LLM
│       │   └── probes/         experiments that ask no questions
│       └── analysis/           after a run; reads run directories only
│           ├── judging/        blind judge and its calibration
│           ├── metrics/        metrics per layer, cost ledgers
│           └── reporting/      statistics and tidy tables; no plotting
├── resources/                  research objects released with the code; frozen at the configuration lock (D012)
│   ├── prompts/                one directory per LLM call type, including answering and judging
│   ├── rdf/                    core vocabulary, communicative-function scheme, SHACL shapes, aliases, exclusivity rules
│   ├── views/                  one query template and sentence pattern per template family
│   ├── schemas/                JSON Schemas for LLM outputs and for stored records
│   └── changeseq/              event grammar and template families of the generator
├── configs/
│   ├── common/                 settings shared by every experiment and never varied; holds paths.yaml
│   ├── data/                   download sources
│   ├── benchmarks/             version, manifest checksum, splits
│   ├── models/                 models, decoding, embedding, judge snapshot
│   ├── engines/                one file per ContextEngine configuration: GRACE, its variants, the baselines
│   └── experiments/            one file per E<NNN>: engine × benchmark × protocol × budget × seed
├── tests/
│   ├── contracts/              interface tests, import rules, gold sentinel, lock check
│   ├── integration/
│   ├── docs/
│   └── fixtures/
├── scripts/                    bash entry points only
├── envs/serve/                 GPU inference environment
├── docs/
└── paper/                      figure scripts read only the tidy tables written by reporting
```

`views/` sits beside `memory/` and `pipeline/` although the plan assigns the view store to the memory layer. The package holds the store together with the logic that maintains it (rendering, staleness decisions, rebuild), because these change together and are compared together in ablations A and C.

## Dependency rules

Between packages:

- `config/` and `llm/` import neither `context/` nor `eval/`.
- `eval/` may import `context/`; `context/` never imports `eval/`. The engine therefore cannot reach gold data through an import.
- `cli/` may import any package; no package imports `cli/`.
- The component registry in `config/` stores only a mapping from names to import paths and loads lazily, so it does not break the first rule.

Inside `context/`:

- The order is `api.py` ← `memory` ← `pipeline` ← `views` ← `engine.py`. `api.py` imports nothing else from `context/`.
- `views/` imports only `query/` from `pipeline/` and only `graph/` from `memory/` (for change sets). No package under `pipeline/` imports `views/`.
- `pipeline/update/` imports only `memory/`. This keeps views out of the writer's reach (plan section 5.4, "The writer never sees views").
- The packages under `pipeline/` do not call each other. The order of steps is written only in `engine.py`:
  - `write`: append to the history → update → mark stale views.
  - `read`: query → retrieval → check and repair views → assembly.
- A variant replaces a component (for example, "no views" is an empty view component). `engine.py` contains no branches for variants.

Inside `eval/`:

- The order is `datasets` ← `engines` ← `runner`.
- `analysis/` imports none of the other three groups and no internal package of `context/`. It reads only files in run directories; gold data also reaches it as files.
- `engines/baselines/` does not import `datasets/`. From `context/` it imports only `api.py` and `memory/index/`, so that retrieval baselines share GRACE's tokenisation and chunking.
- `engines/oracles/` is the only place that may import gold data from `datasets/` and hand it to a system.

An import-check test in `tests/contracts/` enforces these rules. Import rules cannot stop the harness from passing gold data to a system, so a second test plants a sentinel string in the gold data and asserts that it appears in no input any system receives.

## Dependency diagrams

In all three diagrams an arrow points from the importing package to the imported one. An arrow that is not drawn is an import that is not allowed.

### Between packages

Each layer may import only the layers below it. The right-hand column lists the directories each layer reads or writes.

```text
+-----------------------------------+
|               cli                 |
+-----------------------------------+
|               eval                |  ..>  data/ (read)    runs/ (write)
+-----------------------------------+
|              context              |  ..>  resources/ (vocabulary, view templates)
+-----------------------------------+
|               llm                 |  ..>  resources/ (prompts, schemas)
+-----------------------------------+
|              config               |  ..>  configs/ (read)
+-----------------------------------+
```

### Inside `context/`

```text
                         +-------------+
                         |  engine.py  |
                         +------+------+
                                |
        +-----------------------+---------------------------------------+
        |                       |                                       |
        v                       |                                       |
+----------------+              |                                       |
| views/         |              |                                       |
|   staleness/   |              |                                       |
|   (others)     |              |                                       |
+---+--------+---+              |                                       |
    |        |                  v                                       |
    |        |    +--------------------------------------------------+  |
    |        |    | pipeline/                                        |  |
    |        +--->| query/      update/       assembly/   retrieval/ |  |
    |             +---+----------+---+-----------+-------------+-----+  |
    |                 |          |   |           |             |        |
    |                 v          v   v           v             v        |
    |             +--------------------------------------------------+  |
    |             | memory/                                          |  |
    +------------>| [   graph/    ] [   history/   ]      [ index/  ]|<-+
                  +-------------------------+------------------------+
                                            |
                                            v
                                      +-----------+
                                      |  api.py   |
                                      +-----------+
```

| Importer | Imports | Why |
| --- | --- | --- |
| `engine.py` | `views/`, `pipeline/`, `memory/` | The only place that connects the parts and fixes the order of steps |
| `views/` | `pipeline/query/` | View content comes from query results |
| `views/staleness/` | `memory/graph/` | Staleness decisions read change sets |
| `query/` | `graph/` | Runs queries on the claim graph |
| `update/` | `graph/`, `history/` | Reads messages, writes claims |
| `assembly/` | `history/` | Fetches raw text and evidence spans |
| `retrieval/` | `index/` | Searches the BM25 and dense indexes |
| `memory/` | `api.py` | Uses the interface types, such as `Message` |

Two kinds of arrow are omitted. Every package may import `api.py`. The five places that call a model point to `llm/`: the writer and vocabulary maintenance in `update/`, planning in `query/`, verification in `assembly/`, rendering in `views/`, and embedding in `index/`.

### Inside `eval/`

The first three groups are linked by imports:

```text
+---------------------------------------------+
| runner/                                     |
|    harness/                  probes/        |
+-------+-----------------------------+-------+
        |                             |
        v                             |
+---------------------------------+   |
| engines/                        |   |
|    baselines/      oracles/     |   |
+-----------------------+---------+   |
                        |             |
                        v             v
+---------------------------------------------+
| datasets/                                   |
|    benchmarks/               changeseq/     |
+---------------------------------------------+
```

- The arrow from `engines/` to `datasets/` starts only at `oracles/` and ends at the gold data in `benchmarks/`. `baselines/` has no such arrow.
- `runner/` imports `engines/`, and also imports `datasets/benchmarks/` directly for message streams and read points.

`analysis/` exchanges only files with the other groups:

```text
runner/  --writes-->  [ run directory ]  --read by-->  analysis/
                             ^                           judging/ -> metrics/ -> reporting/
                             |                              |           |
                             +----------- write ------------+-----------+
```

Rescoring and judge reruns therefore never rerun a system.

Each package of `eval/` may import a different part of `context/`:

| Package | May import from `context/` | Why |
| --- | --- | --- |
| `runner/harness/` | `api.py` only | Treats GRACE and the baselines alike |
| `runner/probes/` | Internal packages | Drives components such as `staleness/` directly |
| `engines/baselines/` | `api.py`, `memory/index/` | Implements the interface; shares tokenisation and chunking |
| `engines/oracles/` | Internal packages | Implements the extractor and planner interfaces to inject gold data |
| `datasets/benchmarks/` | `api.py` only | Uses the interface types |
| `datasets/changeseq/` | `memory/graph/` only | Represents gold graphs with the entry types; never imports `pipeline/query/` |
| `analysis/` | Nothing | Reads files only |

The arrows to `llm/` are omitted: `harness/` (answering), `baselines/`, `judging/` and `changeseq/` (surface rendering).

## How experiments run

Experiments take four forms and are served by two packages:

| Form | Examples | Where |
| --- | --- | --- |
| End-to-end question answering | E011 to E014, E016 to E019 | `runner/harness/` |
| Question answering on gold graphs | E005 | `runner/harness/`, gold graph injected by `engines/oracles/` |
| Component experiments on gold graphs, no questions | E003, E004 | `runner/probes/`, gold graph injected by `engines/oracles/` |
| Measurements without questions | E002, E006, E009 | `runner/probes/` |

- **Gold graphs enter through an interface.** Extraction in `pipeline/update/` is a replaceable step, and `engines/oracles/` supplies an implementation that reads the gold graph.
- **Ablation A is a replay.** The change set of every version and the dependency records of every view are stored, and the eight staleness strategies each run over the same records.
- **A run has stages.** The system stage, judging and scoring; each stage reads only the files of the stage before it.
- **Whether the system stage splits further depends on the read protocol.** A read changes resident views, because the result of a lazy rebuild is kept and booked to W.
  - End of history: ingestion and reading are two stages, and one ingestion snapshot serves all four budget levels and the read-side ablations (D, E, H).
  - Per turn and interleaved: writes and reads alternate on the same live state and form one stage; every cell runs its own pass.

## Baselines and variants

- A system that reuses the GRACE assembly is a file in `configs/engines/`. Examples are template serialisation, query-time resolution without views, and the fixed slot table. The replaced component lives in `context/`, next to the component it replaces.
- `eval/engines/baselines/` holds only systems that do not use the GRACE assembly: raw text, retrieval, rolling summary, Mem0, ReacTOD and the like.

## What the interface must support

The interface in `context/api.py` follows from five requirements of the plan:

- A read is bound to a version. A read never writes to the history or the claim graph; a lazy rebuild of a resident view is kept, and the temporary artefacts of a question are discarded when the question ends.
- State can be saved and restored, so that ingestion is reused under end-of-history reading and long histories can resume.
- The answering LLM may request one further retrieval; baselines take the same path.
- Under segment extraction, when a read falls inside a segment, the engine first extracts the part that has arrived.
- Every write and read returns a trace: retrieval candidates, the evidence actually included with its provenance links, view hits and staleness decisions.

## Cost accounting

- The caller tags each call with its ledger category; the categories are defined in `llm/`. Rendering triggered by a lazy rebuild at read time is booked to W, which the harness cannot infer from the stage.
- Embedding and judging calls also go through `llm/`; judging is tagged as evaluation overhead.
- External systems (Mem0, Graphiti) send their own requests. They are pointed at the recording OpenAI-compatible endpoint that `llm/` provides.
- Database time and latency have no package of their own: each component times itself and writes the result into the trace, which `runner/harness/outputs.py` stores.

## Guards written into code

- Every split is loaded through one function in `eval/datasets/benchmarks/`. It refuses to load a held-out split until the preregistration tag of T033 exists.
- `run.json` records the checksum of `resources/`. After D012 a test compares it with the value at the lock.
- `resources/` and `configs/` are read from the current worktree (`REPO_ROOT`); `data/` and `runs/` are read from `PROJECT_ROOT`.

## Where types live

There is no shared records package. A type lives with the code that produces it.

| Type | Location |
| --- | --- |
| `Message`, `ReadTask`, `WorkingContext`, write and read traces | `context/api.py` |
| LLM call record, ledger categories | `llm/records.py` |
| Claim, attribution, evidence link, supersession event | `context/memory/graph/entries.py` |
| Change set | `context/memory/graph/changeset.py` |
| Claim patch | `context/pipeline/update/patch.py` |
| Intermediate representation, claim pattern | `context/pipeline/query/ir.py` |
| Query result (answers, witnesses, evidence, fingerprints) | `context/pipeline/query/result.py` |
| Retrieval candidate | `context/pipeline/retrieval/candidates.py` |
| View | `context/views/view.py` |
| History, question, gold data | `eval/datasets/benchmarks/records.py` |
| Prediction | `eval/runner/harness/outputs.py` |
| Judgement | `eval/analysis/judging/judge.py` |

## Files

The node in brackets is the plan node whose title matches the package. It is a guide for spotting overlapping write scopes; the `WRITE_SCOPE` of an assignment is authoritative.

### Base packages

```text
cli/
├── data/
│   ├── download.py         download benchmarks (exists)
│   └── changeseq.py        build the controlled-sequence dataset
└── run/
    ├── experiment.py       expand an experiment config into cells and schedule their stages
    ├── system.py           system stage: ingestion, reading and answering
    ├── probe.py            entry point for probes
    ├── judge.py            judging stage
    ├── score.py            scoring stage
    └── report.py           tidy tables from a list of run IDs

config/                     (T009)
├── paths.py                REPO_ROOT, PROJECT_ROOT, shared directories, resources (moved from grace/paths.py)
├── schema.py               structure and validation of the four config kinds: experiment, engine, model, benchmark
├── loader.py               read YAML, resolve references between configs, write the resolved config and its checksum
├── registry.py             component name → import path, loaded lazily
└── freeze.py               checksums of resources/ and of the locked configs

llm/                        (T004)
├── client.py               chat completion; retries and failures are recorded
├── embedding.py            embedding
├── tokens.py               token counting with the model's tokenizer and chat template
├── prompts.py              load templates from resources/prompts; fixed prefix first, varying part last; template hash
├── structured.py           parse and validate output against resources/schemas; failures go back to the caller
├── records.py              call record, call types, ledger categories; logical tokens, tokens after caching, GPU seconds; writes calls.jsonl
└── proxy.py                recording OpenAI-compatible endpoint for external systems
```

### `context/memory/`

```text
history/                    (T014)
├── log.py                  append-only message log; version allocation; idempotent retries
└── spans.py                span anchors; unified evidence IDs

index/                      (T025)
├── chunking.py             tokenisation and chunking, shared by BM25, dense and the retrieval baselines
├── bm25.py
└── dense.py                exact cosine; embeddings come through llm/

graph/                      (T014)
├── entries.py              the four kinds of entries: claim, attribution, evidence link, supersession event; communicative function, report mode, supersession kind
├── rdf.py                  mapping between entries and triples; RDF 1.1 standard reification, RDF 1.2 as the alternative
├── store.py                pyoxigraph store; append-only commit that returns a change set; SPARQL execution
├── changeset.py            change set and its serialisation (stored for replay)
├── vocabulary.py           core vocabulary, alias table, exclusivity rules; vocabulary versions
└── entities.py             entity equivalence entries and class representatives
```

All three stores read at a cut-off version, and each implements its own save and restore.

### `context/pipeline/`

```text
update/                     (T022; vocab.py belongs to T032)
├── patch.py                claim patch with span anchors
├── extract.py              extractor interface; the LLM writer; deterministic mapping for structured tool events
├── candidates.py           local context, candidate entities and predicates for the writer
├── segment.py              extraction granularity: per message, per segment, per session; flush when a read falls inside a segment
├── validate.py             SHACL validation of the current patch only; span-anchor checks
├── guard.py                attribution guard and exclusivity rules: append, supersede or keep in parallel
├── commit.py               turn the decided patch into a graph transaction; retry from the log on failure
└── vocab.py                vocabulary-maintenance call (phase 5, optional)

query/                      (T017; plan.py belongs to T023)
├── ir.py                   typed intermediate representation: claim patterns, the six operations, valid time and cut-off version; type check
├── templates.py            rule templates for tasks that need no LLM call
├── plan.py                 planning: rule templates first, then the LLM; one compilation repair
├── compile.py              intermediate representation → SPARQL: main query and evidence query; cut-off substitution; relative time to absolute intervals
├── patterns.py             dependency patterns from the intermediate representation, including those inside negation and aggregation, with local filters
├── execute.py              run at a given version; build answers, witnesses and evidence sets
└── result.py               query result types; the three fingerprints; scope notes

retrieval/                  (T025)
├── candidates.py           candidate type
├── text.py                 BM25 and dense channels
├── graph.py                graph channel: maps query results passed in by the engine to candidates
├── route.py                routing rules; all channels when confidence is low
└── fuse.py                 RRF and weighted fusion

assembly/                   (T026)
├── demand.py               the variables an answer needs
├── filter.py               filter by version, valid time, scope and attribution; verification call on ambiguity
├── select.py               greedy selection by new requirements covered per added token; fixed top-k truncation as the contrast
├── expand.py               when variables stay uncovered, produce one request for expansion or a further query, executed by the engine
└── layout.py               serialisation into the fixed layout; citations; token cost per fragment
```

`retrieval/graph.py` and `assembly/expand.py` never call `query/`. The first receives results from the engine; the second hands a request back to the engine. This is how "the packages under `pipeline/` do not call each other" is kept.

### `context/views/`

```text
views/
├── view.py                 the six components of a view; binding of sentences to result rows        (T018)
├── template_families.py    the six template families; instantiation threshold; bindings             (T018)
├── store.py                view store; resident and temporary life cycles; staleness flags          (T018)
├── render.py               template serialisation; LLM rendering; rendering check and fallback      (T018)
├── rebuild.py              local rebuild; citation patching; full invalidation on vocabulary or entity changes  (T018)
└── staleness/              (T019)
    ├── base.py             strategy interface: receives change sets at write time, decides at read time
    ├── trivial.py          never invalidate; full rebuild every turn
    ├── citation.py         used claims only; used claims plus negation and aggregation patterns
    ├── pattern.py          predicate level; claim-pattern push, optionally with local filters
    └── requery.py          read-time re-query with fingerprints; push filtering with read-time confirmation
```

`staleness/` is its own package because T018 and T019 are separate tasks, and the replay probe needs only this package.

### `eval/datasets/`

```text
benchmarks/                 (T002; derived gold for MultiWOZ belongs to T006, LoCoMo read points to T007)
├── records.py              history and question (visible to systems); gold data (scoring side only)
├── base.py                 adapter interface; data version, manifest checksum and count checks
├── splits.py               the single entry point for loading splits; held-out guard
├── multiwoz.py             includes the rule that derives the "current choice" gold
├── locomo.py               includes the computation of v(q)
├── longmemeval.py
├── halumem.py
├── memoryagentbench.py
└── changeseq.py            reads the generated dataset

changeseq/                  (T015; audit.py belongs to T016)
├── events.py               event grammar and event log
├── template_families.py    template families; change-type mix, revision density, read interval and the other controlled variables
├── gold.py                 event log → gold graph, attributions and evidence links at every version
├── schedule.py             read schedule, gold answers and witness sets; paired "known then" and "seen from now" questions
├── invalidation.py         answer-stale and citation-stale ground truth per message and view; computed from the event log, not through the query compiler
├── render.py               surface text rendered with a model no evaluated system uses
├── audit.py                sample export for the two annotators; agreement statistics
└── build.py                write the dataset and its manifest
```

### `eval/engines/`

```text
baselines/                  (T003; tagged belongs to T027, multiwoz to T028, mem0 to T029, graphiti to T034)
├── raw.py                  full history with and without prefix caching; last-k; truncation to the same budget
├── retrieval.py            BM25, dense, RRF
├── tagged.py               RRF with speaker and dialogue-act tags
├── summary.py              rolling summary: rewritten after every update; reused without rewriting
├── multiwoz.py             ReacTOD reproduction; deterministic overwrite; the rule that never writes system values; direct state output
├── mem0.py
└── graphiti.py             optional

oracles/
├── graph.py                extractor that reads the gold graph
├── ir.py                   planner that returns the perfect intermediate representation
└── evidence.py             working context built from gold evidence
```

### `eval/runner/`

```text
harness/                    (starts in T003; streaming belongs to T031)
├── rundir.py               exclusive creation; run.json life cycle; run ID; reference to an upstream run
├── cells.py                experiment config → cells (engine × benchmark × protocol × budget × seed)
├── protocols.py            the three read protocols → read schedule per history; the two readings of LoCoMo streaming
├── drive.py                alternate writes and reads by the schedule; histories in parallel; resume per history
├── snapshot.py             save and restore engine state; reuse of an upstream ingestion
├── answer.py               the answering LLM: shared answer prompt, four permitted outputs, one further retrieval
└── outputs.py              storage of predictions, working contexts and traces

probes/
├── replay.py               replay the eight staleness strategies over stored change sets, with read-time re-query as reference  (E003, E008)
├── scale.py                resident views × write rate × graph size; push, pull and hybrid                                      (E004)
├── natural.py              re-run template views after every message and assign each change to one of the seven types          (E002, E009)
└── extract.py              run the writer only and export the extracted graph                                                  (E006)
```

### `eval/analysis/`

```text
judging/                    (T004; calibration belongs to T035)
├── judge.py                blind judge: fixed snapshot and prompt, system identity hidden
├── official.py             the official per-type judge of LongMemEval
└── calibration.py          negative controls; agreement between the two judges; judge reruns

metrics/                    (starts in T004; cost.py belongs to T030)
├── align.py                align predictions and gold data by key; the abort conditions of the contract
├── answer.py               accuracy, token-F1, abstention, ungrounded answers, stale-value use, consistency between v(q) and N
├── dst.py                  JGA, slot F1, retention of original constraints, paired correctness
├── evidence.py             strict and lenient evidence recall, full hit, view hit rate
├── staleness.py            precision and recall of decisions; end-to-end misses; extraction-induced misses; agreement with full rebuild
├── graph.py                claim precision, recall and F1; attribution and time fields; operation-level accuracy on HaluMem
├── cost.py                 the three ledgers, W/U/A, payback read count, cost per successful task
└── strata.py               stratum labels, used on the scoring side only

reporting/                  (T035, T036)
├── collect.py              explicit list of run IDs → tidy tables; rejects runs that are unfinished or have dirty code
├── stats.py                paired tests, models with history as a random effect, sign tests, leave-one-cluster-out, non-inferiority
├── curves.py               data for amortisation curves, the maintenance surface and payback over the cache ratio
└── tables.py               CSV for each table of the paper
```

### Non-code directories

```text
resources/
├── prompts/                one directory per call type: writer, vocabulary, planner, verifier, renderer, answer, judge
├── rdf/                    core vocabulary, SKOS scheme of communicative functions, SHACL shapes, alias table, exclusivity rules
├── views/                  one file per template family: query template and sentence pattern
├── schemas/                llm/ (output of each call type) and records/ (each stored record)
└── changeseq/              event grammar, template families

configs/
├── common/paths.yaml
├── data/sources.yaml
├── benchmarks/             one file per benchmark
├── models/                 primary model, contemporary small model, long-context model, larger writer, embedding, judge
├── engines/                grace.yaml; one file per variant and per baseline
└── experiments/            E<NNN>-<slug>.yaml

tests/
├── contracts/              import rules, gold sentinel, lock check, record formats; one interface test suite run against every engine
├── integration/            all stages run end to end on a synthetic history
├── docs/
└── fixtures/               synthetic benchmarks; a small history with its gold graph
```
