---
id: T008
title: Controlled change-sequence generator design
created: 2026-11-22
---

# T008 · Controlled change-sequence generator design

## Goal

A design document for the controlled change-sequence generator, the primary evidence for RQ2 (plan section 6.4), fixed before any staleness result is seen. The generator skeleton in T002 implements this design.

## Scope

- In scope: event grammar for the seven change types (superseding a cited claim, new match including empty to non-empty, negation hit by an acceptance or rejection, count or order change, late correction, repeated mention, irrelevant update) plus unconfirmed alternatives, presupposition questions and paired known-then / seen-from-now questions; template families and the development / held-out family split; the read schedule; controlled variables (change-type mix, revision density, read interval, reads per history, history length) and the sweep for the maintenance surface; outputs per sequence (messages, event log, gold claim graph per version, gold answers and witness sets, per-message per-view staleness); surface rendering by a model outside the evaluated systems; the two-annotator audit protocol; target sizes and a power estimate; how StateMemBench and other generators differ.
- Out of scope: implementing the generator (T002 skeleton, later tasks); running any system.
- Candidate worker subtasks: none; a reviewer reads the design at a pinned SHA.

## Acceptance

- [ ] The design document covers every item in scope and maps each output to the metric in plan section 6.7 that consumes it.
- [ ] Gold staleness for template views is derivable from the event log by a deterministic procedure stated in the document.
- [ ] The document states whether that procedure is independent of the query compiler of the system under test. Decision D013 recommends one small function per template family that reads the event log directly. If the ground truth were computed by running compiled queries on the gold graph, the end-to-end reference would share the compiler with the system, and a compiler error would be invisible in the miss rate. If the design chooses otherwise, it gives the reason.
- [ ] A read-only review at a pinned SHA finds no open blocking issue.

## Deliverables

Design document under `docs/research/` (location agreed with the plan owner), referenced from plan section 6.4.

## Log

- 2026-11-22: created from plan section 9, phase 1 (registered by T005).
- 2026-11-23: scope updated to the seven change types of plan section 6.4 (negation hit and repeated mention added; empty to non-empty folded into new match).
- 2026-11-24: acceptance item on the independence of the invalidation ground truth added from decision D013.
- 2026-11-25: manager session `m01-T008` started on branch `task/T008-change-sequence-design` from `4a1662616cd5d04c3967615b6ddaa57c8fbebd00`; Issue #24 opened.
- 2026-11-25: design written in `docs/research/change-sequences.md` and referenced from plan section 6.4 (English and Chinese). Gold staleness is computed by one reference function per view template over the event log, independent of the query compiler, as D013 recommends; compiled re-query on gold graphs is a cross-check. Seven open questions for the plan owner and T014 / T017 are listed in section 14 of the design.
- 2026-11-25: PR #27 merged after a read-only review at `8b78403c` (approve, no blocking issue). The ten non-blocking findings were addressed in a follow-up PR: consequence of rejecting G2(ii), question-level change-type label, fixture dates, G-L count, pair and question counts with the recomputed half-width, ties in historical state, bindings per sequence, audit question sample, terminology question, G7/G8 order and the `assistant` → `agent` role mapping.
