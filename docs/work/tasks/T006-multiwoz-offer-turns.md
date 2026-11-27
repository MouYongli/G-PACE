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

- [x] Counts of accept and reject offer turns in the test set, per version and per domain, recorded in a run directory with code SHA, data checksums and command.
- [x] The share of offer turns where 2.2 and 2.4 disagree on the offered slot value, with at least 50 manually checked examples and the precision of the identification rule.
- [x] The 95% interval half-width implied by the counts at 70% accuracy, and the resulting recommendation under the rule in plan section 6.5.

## Deliverables

Bash entry point under `scripts/` calling Python under `src/grace/cli/`, a short report linked from this file, the MultiWOZ card fields in `docs/research/benchmarks.md` requested from its owner.

Report: [`docs/research/multiwoz-offer-turns.md`](../../research/multiwoz-offer-turns.md); manual check sample: [`docs/research/multiwoz-offer-turns-check.tsv`](../../research/multiwoz-offer-turns-check.tsv).

## Log

- 2026-11-22: created from plan section 9, phase 1 (registered by T005).
- 2026-11-22: paths and dependencies updated after T009 (package `grace`) and T010 (downloads) were merged.
- 2026-11-25: manager session `m01-T006` started on `task/T006-multiwoz-offer-turns` from `9fdde49b5022e5cef0bae94e68073444b1702d15`; Issue #46. No worker sessions; the manager writes the code.
- 2026-11-25: rule and census committed (`e771234`, fix `8780c2f`). Formal runs at `8780c2f`: test `T006-20261125T010248Z-25f5`, dev `T006-20261125T010238Z-7565` (both `completed`, model-free, manifests verified). Test: 2,022 offer turns, 1,104 accept and 45 reject (2.1 acts); 2.2/2.4 disagree on the offered value in 21.7% of accept/reject turns (26.3% exact); half-width 2.65 points at 70%, so MultiWOZ remains primary evidence (reject-only slice: 13.4 points, descriptive only). The 2.2-writes/2.4-does-not convention does not hold in general.
- 2026-11-25: manual precision check on 60 development turns (30 accept, 30 reject): 56/60 = 93.3%, checked by the agent session, pending human confirmation. The two-annotator check on 200 turns with Cohen's kappa (plan 6.5) is still open.
- 2026-11-25: merged `origin/main` (D007, PR #50). The 60-turn agent check stays labelled "checked by the agent session, pending human confirmation"; human confirmation, and the two-annotator check with kappa, are done by the second annotator the user names under D007. The precision is not human-verified.
- 2026-11-25: PR #53 merged. Acceptance items 1 and 3 met; item 2 waits for the human check by the D007 annotator.
- 2026-11-25: user decisions: the derived-gold rule keeps implicit acceptance (1,104 accept turns, half-width 2.65 points); plan 6.5 and the SNG0296 example in plan 3.5 rewritten to the data (the 2.2/2.4 convention does not hold in general); the second annotator is a graduate research assistant of the user (D007).
- 2026-11-28: first human check recorded by the integration owner on the user's instruction (user decision of 2026-11-28, same handling as T012). The label file is not committed; only the numbers below are recorded, and the annotator is recorded anonymously (`anonymous_1`). Sample: 200 development turns (186 dialogues; 150 labelled accept, 50 labelled reject), every label equal to the 2.1-act label of the formal dev run `T006-20261125T010238Z-7565`; no test turn. Precision of the rule: 173/200 = **86.5%** (Wilson 95% 81.1-90.6%); accept 130/150 = 86.7% (80.3-91.2%), reject 43/50 = 86.0% (73.8-93.1%); weighted by the test counts (1,104 accept, 45 reject) 86.6%. This is below the 93.3% of the 60-turn agent check. Errors among accept labels (20): the user declines the booking and only asks about the entity (partial acceptance, 8); the system turn makes no new offer or the user continues an earlier request (8); the user chooses none of several listed options (4). Errors among reject labels (7): the user refines, corrects or goes along with the system turn without turning anything down (5); no new offer in the system turn (1); a spelling variant of the same entity in the act slot value (1). Incorrect by offer kind: booking-inform 12/51, select 7/28, inform-entity 10/109, recommend 4/41, offerbook 2/36 (a turn can carry several kinds); by domain: restaurant 13/58, hotel 8/56, attraction 4/38, train 2/48. Against the agent check on the 29 turns both cover (the agent is not a human annotator, so this is not human agreement): 28/29 agree, kappa 0.78. Effect on plan 6.5: discounted by the human precision, n = 995 of the 1,149 test accept-or-reject turns and the half-width at 70% accuracy is 2.85 points (was 2.74 with the agent precision), still below 5 points, so the D007 option 'few MultiWOZ offer turns' is not triggered by this round; the reject-only slice stays descriptive. Acceptance item 2 is met by this check (200 turns, one human annotator). T006 is marked done with a remark: **a second human annotator labels the same turns later; Cohen's kappa (plan 6.5) and the comparison of the two human label sets come from that round, and if the two differ widely the rule and the numbers above are analysed again**; any change is recorded here.
