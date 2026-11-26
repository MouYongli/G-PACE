---
id: T014
title: Claim model and bitemporal store
created: 2026-11-23
---

# T014 · Claim model and bitemporal store

## Goal

The append-only, bitemporal RDF claim graph of plan sections 3.2 and 5.2: claims, attributions, evidence links and supersession events, each with a version stamp; the vocabulary mapping; SHACL shapes; and a store that commits one version per message and reads any past version.

## Scope

- In scope:
  - Vocabulary with PROV-O, OWL-Time, a SKOS scheme for communicative functions, and both the RDF 1.2 reifier and the RDF 1.1 reification serialisation.
  - SHACL shapes that validate only the claims touched by a patch.
  - Store API: append a change set, read at a version, idempotent retry.
- Out of scope: Extraction (T022); query compilation (T017).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Contract tests cover the four entry kinds, append-only behaviour and time-travel stability.
- [ ] Both serialisations round-trip on fixtures.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` graph package; shapes and vocabulary files; contract section for the claim graph.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-T014` started on `task/T014-claim-model` from `985d232`; Issue #33. No workers; the manager writes the code. Run directory `runs/T014/`.
- 2026-11-25: merged `origin/main` at `23d14fb` (context API of T003); `history/log.py` and `history/spans.py` use `Message` from `context/api.py`.
- 2026-11-25: added the "Claim graph" contract section (v0.1), `context/memory/graph/` (entries, change sets, vocabulary, entities, RDF 1.1 and RDF 1.2 mapping, pyoxigraph store, SHACL of touched claims), `context/memory/history/` (log, spans), `resources/rdf/` (core vocabulary, communicative-function scheme, shapes, predicate table) and contract tests on the worked-example fixture. Open questions 2 and 6 of `docs/research/change-sequences.md` answered in the contract section: supersession of kind change may carry a valid end; the guard covers removal without a replacing claim (G2(ii)).
- 2026-11-26: follow-up session `m01-T014b` on `fix/T014-valid-end-tiebreak` from `de5056b` (user decision 2026-11-26: fix the A6 tie-break before E003). The effective valid end now takes, among the earliest-stamped change supersessions that state a valid end, the earliest valid end by value (`entries.effective_change_end`, used by `GraphState.valid_end` and `matching.Index.valid_end`; `compile.earliest_change_end` compares valid ends instead of entry IRIs). Change sets reject same-stamp valid ends of one claim that are not comparable (`check_change_ends`). Contract "Claim graph" v0.2. Regression test `tests/integration/test_valid_end_tiebreak.py` fails on the previous code (missed mark for IDs `s0`, `s:2`). No generated (E004, E005) or extracted (E002) graph has a change supersession with a valid end; replays of 15 generated development sequences are unchanged. Resolves formalisation discrepancy 11.
- 2026-11-26: follow-up session `m01-T014c` on `fix/T014-entity-labels` from `main` at `fc50f18` (user decision 2026-11-26: entity labels, the surface names behind the writer's grammar-safe IDs, become part of the claim graph). Contract "Claim graph" v0.3: a versioned `EntityLabel` entry (`label_id`, `entity`, `label`, `version`) in an optional `entity_labels` list of the change set (omitted when empty, so earlier change sets serialise byte for byte as before); RDF `gx:label/<id> a g:EntityLabel ; g:labelOf <entity> ; rdfs:label "name" ; g:knownFrom v` (exact both ways, SHACL shape added); written once per entity (store rule); merges never rewrite labels (`display_name` follows the representative); labels are display data and enter no answer, witness, evidence or fingerprint and invalidate no view. The writer (T022) writes each label at the first version that names the entity; the T025 recall probe reads labels from the graph (falling back to `writer.json` for older runs). Tests `tests/contracts/test_entity_labels.py` and three writer tests; compiled results and fingerprints on the worked example and a generated development sequence are identical with and without labels; generated sequences carry no labels, so E004 and E005 numbers cannot change. Fixture `tests/fixtures/graph/entity-labels/`.
- 2026-11-27: user decisions on the three open questions of the entity-label follow-up (PR #133), recorded by the integration owner: (1) views will render entity labels instead of grammar-safe IDs, reading labels at each view's own cut-off; display text only, fingerprints unchanged; done in the next views or rendering change (T018 log). (2) Labels stay immutable and cannot be corrected for now; revisit only if E006 finds wrong first-mention labels. (3) The query planner (T023) will read names through `display_name()` from the graph instead of the recall probe, at its next change (T023 log).
