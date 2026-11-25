---
id: T015
title: Controlled change-sequence generator
created: 2026-11-23
---

# T015 · Controlled change-sequence generator

## Goal

The generator designed in T008: natural English dialogues whose ground truth is a program event log, covering the seven change types of plan section 6.4, with a gold claim graph at every version, a read schedule with gold answers and witnesses, and per-message answer and citation staleness for every template view.

## Scope

- In scope:
  - Controlled variables: change mix, revision density, read interval, reads per history, history length.
  - Surface text rendered by a model that no evaluated system uses.
  - Development and held-out template families are disjoint.
- Out of scope: Auditing the sequences (T016).
- Layout (decision D013): the generator goes to `src/grace/eval/datasets/changeseq/`, its grammar and template families to `resources/changeseq/`, and the adapter that reads the generated dataset to `src/grace/eval/datasets/benchmarks/`. From `src/grace/context/` the generator imports only `memory/graph/`, for the entry types of the gold graph.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Gold graphs validate against the shapes of T014.
- [ ] Invalidation truth is computed as the design of T008 prescribes; if that is from the event log without the query compiler, the generator does not import `context/pipeline/query/`.
- [ ] Invalidation truth agrees with re-evaluating each view on the gold graph at every version. With an independent ground truth this check also tests the compiler.
- [ ] `make test` and `make lint` pass.

## Deliverables

Generator under `src/grace/eval/datasets/changeseq/`; configs; generated development sequences in a run directory.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-24: layout and the acceptance item on the invalidation ground truth added from decision D013.
- 2026-11-25: manager session `m01-T015` started on `task/T015-change-sequence-generator` from `2304a4714cdd262941846cd764c9fbd818e155a4`; Issue #59. Scope of this round: the generator core, no model calls.
- 2026-11-25: generator core implemented: event log with the seven change types and G1-G8 checks, gold claim graph on the T014 store (SHACL-validated), the six reference functions and Hist computed from the event log (no query compiler), per-message answer and citation staleness with change types and the section 4.2 invariants, an independent re-evaluation of every view on the gold graph at every version, read schedules U/A/P with questions, gold answers, witnesses and pairs, 20 scenario families with the committed split (5 development, 15 held-out), the `change-seq` adapter, and a deterministic template renderer (development and test renderer only). Deferred: the paper's model renderer (model not chosen, D006) and the cross-check against the compiled IR of T017.
- 2026-11-25: first development run `T015-devsmoke-20261125T023057Z` failed on the G1 check (a date correction reused an earlier claim's value and start); fixed in `fcb3aea`. Run `T015-devsmoke-20261125T023552Z` (code `fcb3aea`, clean, seed 20261125, `configs/changeseq/dev-smoke.yaml`) completed: 25 development-family sequences, 5,000 messages, 9,422 questions over 8 schedules, every check passed; a second run reproduced the dataset manifest byte for byte. Template renderer, no model calls, no held-out family generated.
- 2026-11-25: PR #62 (generator core) reviewed and merged. T015 stays active until the model renderer exists (D006 choice pending) and the cross-check against the T017 compiler is run.
- 2026-11-25: manager session `m01-T015b` resumed on `task/T015-cross-check` from `795cb9ea1946fdcf72d572baf62a103531f0a06b` for acceptance item 3. Cross-check `grace.cli.data.changeseq_crosscheck` (in `cli/`, since `eval/datasets/changeseq/` must not import `context/pipeline/query/`) compiles the six view templates to the T017 IR and executes them on the gold graph at every version. Run `T015-crosscheck-20261125T175858Z` (code `9e08aae`, clean; upstream dataset `T015-devsmoke-20261125T023552Z`, config `configs/changeseq/dev-smoke.yaml`, seed 20261125; 25 development sequences, 75,375 (binding, version) pairs per graph, rdf11 and rdf12 give identical results). On the own-positive projection (only the attributions the fragment's `[u, f]` can tell apart): V1, V3-V6 agree everywhere, the answer and citation staleness labels agree everywhere (0 of 75,000 disagree), and 2,929 V2 pairs differ only in witnesses. On the full graph: 16,782 value and 475 label disagreements, all in V1-V3; 13,853 of them are explained by the attribution-constraint gap and the other 2,929 are those V2 pairs. No fault found on the generator side. Two findings on the T017 side, for its owner: (F1) `[u, f]` cannot require report mode own, positive polarity or not derived (query-ir.md 7.2; design 6.2 asked T017 to confirm); (F2) `LATEST BY version` keys each row on max(claim, attribution) version, so restating the selected claim drops its earlier witnesses, against plan 3.4 and design 6.2. V3 witness convention differs (one witness set per member versus one union witness); compared after normalisation. The model renderer stays open (D006).
- 2026-11-25: manager session `m01-T015c` resumed on `task/T015-model-renderer` from `59a0dd1e14de62016c8eebb33df56e1ef828a701` (fast-forwarded to `cf686d77bc1f817f9cd4a5f123d7073df2705bda` after the main rewrite, rebased onto `7d7587a` after PR #87). Scope: the model renderer of design section 7 with the renderer chosen in D006, and the V3 witness decision below.
- 2026-11-25: user decision: the V3 (count view) witness follows plan 3.4 as written, one witness that is the union of the counted members' witnesses (as the T017 compiler and T018's `count_witnesses` do), not one witness set per member. Changed in the event-log reference (`invalidation.py`) and the independent graph re-evaluation (`regraph.py`); the cross-check compares raw witnesses (normalisation removed) and takes the run's node from `--task` or the `--out` node directory instead of hard-coding T015. `GENERATOR_VERSION = changeseq-generator-2` in `meta.json` and `dataset.json` tells the datasets apart. On the development set only `reference.jsonl` changes; events, labels and schedules are byte-identical to generator 1 (`T015-devsmoke-20261125T023552Z`). The design table (change-sequences.md 6.2, V3 row) still says "one witness set per member" and needs its owner's edit.
- 2026-11-25: model renderer (`eval/datasets/changeseq/model_renderer.py`): Mistral-Small-3.2-24B-Instruct-2506 at `95a6d26c4bfb886c58daf9d3f7332c857cb27b43` (Apache 2.0, not gated; Mistral-format weights, tekken.json v11), pinned in `configs/models/mistral-small-3.2-24b.yaml`, served by vLLM 0.34.0 with `--tokenizer-mode mistral --config-format mistral --load-format mistral`, images off, 16 GiB KV cache on GPU 3. Prompt `render-changeseq` (sha256 `84ed03f3…`), temperature 0.15 (model card), seed = message seed + attempt, three attempts then the template sentence. The driver additionally requires the message's dates (a date of the episode year may omit the year), the task label and the companion's name, and forbids the other companions. A local Tekken counter matches the server's prompt_tokens on every call.
- 2026-11-25: run `T015-devmodel-20261125T192037Z` (code `574f3a1`, clean, `configs/changeseq/dev-model.yaml`, seed 20261125, 25 development sequences, 5,000 messages, 5,017 model calls, all ok, 0 token-count mismatches): fallback rate per family apartment-search 0.2%, car-rental 0.1%, flight-travel 0.0%, hotel-stay 0.1%, train-travel 0.1%; no family over the 10% limit. Every generator check passed; events, labels, references, graphs and schedules are byte-identical to the template run `T015-devsmoke-20261125T192500Z` of the same code. 14.9% of the model messages equal the template sentence (mostly short ones). Rendering is not bit-reproducible: an earlier run on the same generator code (`T015-devmodel-20261125T191349Z`, pre-rebase commit) shares 64.3% of the texts; the rendered text is frozen with the dataset (design section 7). Questions keep the template text. No held-out family generated.
- 2026-11-25: cross-check rerun `T015-crosscheck-20261125T192600Z` (code `574f3a1`, clean, task T015; upstream `T015-devmodel-20261125T192037Z`; rdf11 and rdf12; T017 with the F1 default of PR #87): 75,375 (binding, version) pairs per graph and mode, 0 value and 0 label disagreements on the full graph and on the own-positive control, raw V3 witness differences 0 (previously 5,288 own-positive and 7,241 full under the per-member convention). The own-positive graph is kept as a control for the F1 attribution default. Acceptance: items 1-4 met; the model renderer exists and the development data is regenerated with it.
