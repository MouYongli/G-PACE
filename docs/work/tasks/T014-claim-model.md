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
