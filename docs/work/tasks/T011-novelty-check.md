---
id: T011
title: Novelty check of claim-pattern dependencies
created: 2026-11-23
---

# T011 · Novelty check of claim-pattern dependencies

## Goal

Establish, before any other work starts, whether the claim-pattern dependency granularity and the two-level staleness definition of plan section 3.4 are already covered by published work, and fix the wording of plan sections 2 and 3 accordingly. This is phase 0 of plan section 9 and the largest novelty risk of the plan.

## Scope

- In scope:
  - Reading in full: the definition of scope keys in MemShift's appendix; Martin, Unbehauen and Auer (2010). Tether, StateMem and StateGraph were already read in full in PR #11; only their comparison rows remain to be written.
  - Two dedicated searches: incremental maintenance of provenance or lineage (precedent for treating a change of witnesses or evidence as a separate level of staleness); database work on "materialised views maintained by LLMs" and semantic operators.
  - Revising the provisional statements in plan sections 2.1, 2.2, 3.4 and 5.4, the reading-depth labels in section 11.3 and the first four items of section 11.4, in both `plan.md` and `plan.zh-CN.md`.
- Out of scope: the remaining items of plan section 11.4; any implementation.
- Candidate worker subtasks: none.

## Acceptance

- [ ] An item-by-item comparison of claim-pattern dependencies with MemShift's definition-scope key, Martin et al.'s invalidation rule, and the dependency links of Tether, StateMem and StateGraph is written down, each row citing the section or page it rests on.
- [ ] For Martin et al. (2010) the comparison states whether the rule handles OPTIONAL and FILTER, whether insertions and deletions are treated alike, and whether a correctness lemma is given.
- [ ] Both searches are recorded with their queries, the date and what was found or not found.
- [ ] Plan sections 2 and 3 carry no statement marked provisional for these three works, and the checkpoint of phase 0 is applied: if claim-pattern dependencies are already covered, the contribution list in section 4.1 is narrowed as the checkpoint says.
- [ ] `make test` and `make lint` pass.

## Deliverables

Comparison notes in `docs/research/literature.md`; revised `docs/research/plan.md` and `docs/research/plan.zh-CN.md`.

## Log

- 2026-11-23: created from plan section 9, phase 0, at the user's request.
- 2026-11-23: PR #11 (merged as a75a699) read the rest of Tether and StateMem and StateGraph in full, and revised plan sections 2.1, 2.2, 5.4, 11.3 and 11.4 accordingly. Scope narrowed to the remaining reading; the comparison rows for these three works are still owed in `docs/research/literature.md`.
- 2026-11-23: manager session m01-T011 started on `task/T011-novelty-check` from c76e265; Issue #14 opened.
- 2026-11-23: read MemShift (appendices C and F, and code), Martin et al. (2010, full text from the publisher PDF) and section anchors of Tether, StateMem and StateGraph; ran both searches. Comparison and search records added to `docs/research/literature.md`; plan sections 2, 3.4, 4.1, 5.4, 10, 11.3 and 11.4 revised in both languages. Phase 0 checkpoint applied: granularity covered by Martin et al., no novelty claimed for it; two-level staleness has only partial precedent. Recommended D005 option: the second.
- 2026-11-23: reviewer subagent checked 7c26e86 (approve with nits): no misquotes or wrong page numbers; three framing claims were too strong (scope key "coarser" without qualification, granularity "equal" to Martin et al.'s rule, two-level precedent stated without the reading-depth caveat). Fixed in the follow-up commit, with the smaller literature fixes.
