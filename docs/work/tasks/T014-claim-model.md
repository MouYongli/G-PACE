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
