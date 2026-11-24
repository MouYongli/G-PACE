---
id: T006
title: MultiWOZ offer-turn census
created: 2026-11-22
---

# T006 · MultiWOZ offer-turn census

## Goal

Establish from the data how much evidence MultiWOZ can give the attribution-guard claim of RQ1 (plan sections 6.5 and 9, phase 1). Count the test-set user turns that accept or reject a system offer, and check whether "2.2 writes system-offered values into the state, 2.4 does not" holds in general. The counts decide whether MultiWOZ offer turns remain the primary evidence for the attribution-guard claim or become support for the controlled sequences.

## Scope

- In scope: MultiWOZ 2.1, 2.2 and 2.4 test sets; a deterministic, model-free script that identifies offer turns from dialogue-act annotation and from state differences between versions; per-domain and per-slot counts; whether each version's files keep dialogue-act annotation; a manually checked sample of identified turns.
- Out of scope: any LLM run; training or tuning; other benchmarks.
- Candidate worker subtasks: one worker for the script and report.
- Dependency note: the data is downloaded with T010 (`scripts/data/b1_multiwoz.sh`); only the MultiWOZ adapter of T002 is needed besides.

## Acceptance

- [ ] Counts of accept and reject offer turns in the test set, per version and per domain, recorded in a run directory with code SHA, data checksums and command.
- [ ] The share of offer turns where 2.2 and 2.4 disagree on the offered slot value, with at least 50 manually checked examples and the precision of the identification rule.
- [ ] The 95% interval half-width implied by the counts at 70% accuracy, and the resulting recommendation under the rule in plan section 6.5.

## Deliverables

Bash entry point under `scripts/` calling Python under `src/grace/cli/`, a short report linked from this file, the MultiWOZ card fields in `docs/research/benchmarks.md` requested from its owner.

## Log

- 2026-11-22: created from plan section 9, phase 1 (registered by T005).
- 2026-11-22: paths and dependencies updated after T009 (package `grace`) and T010 (downloads) were merged.
