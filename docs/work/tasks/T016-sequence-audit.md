---
id: T016
title: Sequence audit
created: 2026-11-23
---

# T016 · Sequence audit

## Goal

Evidence that the generated text says what the event log says (plan section 6.4, validity): two annotators judge, message by message, whether text and events agree.

## Scope

- In scope:
  - At least 5 sequences per template family.
  - Cohen's kappa and the disagreement rate are reported.
- Out of scope: Changing the generator design.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Audit records are committed.
- [ ] Template families with systematic mismatches are fixed in T015 or excluded, with the reason recorded.

## Deliverables

Audit records under `docs/research/`.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-T016` started on `task/T016-sequence-audit` from base `63f9d4fff7021651c9626af18bdc0a25ce50e557`; Issue #93. Dependency T015 is done. Input: the model-rendered development dataset `T015-devmodel-20261125T192037Z` (generator `changeseq-generator-2`, manifest `9b147185…515a` verified, 25 sequences, development families only). No model calls.
- 2026-11-25: guideline `docs/research/sequence-audit.md` (labels of design section 8, with optional subclasses for missing discourse signal, foreshadowing, alias and contradiction; ten tie rules; ten worked examples), code (`eval/analysis/annotation/sequence_sheet.py`, `eval/analysis/annotation/sequence.py`, `cli/annotate/sequence.py`) and unit tests on synthetic label files and a synthetic dataset committed (`9dba6c5`).
- 2026-11-25: run `T016-sample-20261125T201137Z` (code `9dba6c5`, clean; seed `T016-audit-v1`): `sample.json` and `sheet.csv` under `docs/research/annotations/sequence-audit/`. 5 sequences per development family (all of them; densities 1, 3, 10, 10, 30), one 30-message window each after the setup episode with 10 read-only context messages, at most 5 primary-schedule questions per window with pairs whole: 25 windows, 750 audit messages, 121 audit questions; 2 pilot windows (hotel-stay, flight-travel; 60 messages, 7 questions) not counted. Annotator columns empty.
- 2026-11-25: agent pre-annotation `labels-agent-m01-T016.csv` (`annotator: agent-m01-T016`; an agent pre-annotation, not a human annotator), run `T016-preannot-20261125T201800Z`. Preliminary mismatch rate (750 audit messages): apartment-search 0/150, car-rental 2/150 (1.3%), flight-travel 3/150 (2.0%), hotel-stay 2/150 (1.3%), train-travel 1/150 (0.7%); overall 8/750 = 1.1% (window bootstrap 95% 0.4–1.9%); 3 `unnatural`. No family above the 5% limit. flight-travel is flagged by the repeat rule (`missing` on skeleton `past` 3 times). Across families the same pattern occurs 6 times (car-rental 2, flight-travel 3, train-travel 1): a past-dated `livesIn` or `homeAirport` claim with a short interval rendered as a stay ("I was in Cologne from 26 January until 12 February", "Yuki was at Dresden Airport from 16 to 25 September"), so the residence or home-airport meaning is lost (guideline T4). A program scan of the whole dataset (supporting, not labels) finds "was in/at" in 12/38 car-rental, 7/49 train-travel and 2/46 flight-travel `past` messages. The other two mismatches are hotel-stay: an add rendered with "Actually," that implies a replacement, and a filler asking about the companion's job. Questions: 119/121 agree, 2 `ambiguous`, both resting on such a stay-like evidence message. Preliminary only; not the human audit of plan 6.4.
- 2026-11-25: proposed fix for T015 (not applied here; outside this write scope): the `past` skeleton of `livesIn` and `homeAirport` must keep the predicate verb ("lived in", "usually flew out of"), for example by a rendering-prompt rule or an output check that rejects "was in"/"was at"; or the generator avoids day-scale intervals for residence predicates. The decision whether to fix or exclude follows the human audit and the integration owner.
- 2026-11-25: the two annotators (one author and one person not involved in building the system, design section 8) are not assumed; no placeholder second label set is made. Human labels, kappa and adjudication are open; T016 stays active until they exist.
