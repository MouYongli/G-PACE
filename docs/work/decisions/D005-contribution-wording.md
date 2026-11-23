---
id: D005
title: Wording of the proposition and contribution scope
created: 2026-11-23
---

# D005 · Wording of the proposition and contribution scope

## Context

T011 compares claim-pattern dependencies with MemShift's definition-scope key and with the invalidation rule of Martin et al. (2010), and searches for precedents of two-level staleness. The outcome fixes the wording of plan sections 2, 3.4 and 4.1.

## Options

- Claim the claim-pattern granularity as new.
- Claim no novelty in granularity; keep two-level staleness, the formalisation on append-only bitemporal RDF and the evaluation on natural dialogue.
- If two-level staleness also has precedent, make the paper evaluation-led.

## Decision

Option 2: claim no novelty in granularity; keep two-level staleness, the formalisation on append-only bitemporal RDF and the evaluation on natural dialogue.

- The pattern-matching invalidation rule and its compositional soundness argument are credited to Martin, Unbehauen and Auer (2010), whose Proposition 1 covers AND, OPTIONAL, UNION and FILTER under insertion and deletion. Claim patterns lift the matching unit from a triple pattern to a reified claim with an attribution constraint; the lift is an implementation detail.
- The soundness proposition of plan section 3.4 is stated as an extension of that proposition (NOT EXISTS, distinct counting, latest-state selection, version-bounded reads, witnesses and evidence) with exactness conditions, labelled as routine.
- MemShift's definition-scope key is the closest agent-memory key; it is sound but coarser than claim patterns with constants and local filters.
- Two-level staleness is kept as a contribution: only partial precedent was found (provenance maintenance in ORCHESTRA and absorption provenance), and no work read defines it as a level of staleness.

Evidence: T011 (PR #15), `docs/research/literature.md` section "Phase 0 novelty check"; wording applied in plan sections 2, 3.4, 4.1, 5.4, 10, 11.3 and 11.4.

## Consequences

Blocks the final formalisation (T020), the preprint (T021) and the paper (T036). It does not block engineering: the implementation is the same under every option.

## Revisit when

- A new preprint in the area appears before submission.
- The full texts of the data-citation papers listed in plan section 11.4 (Buneman and Silvello; Davidson et al.; Wu et al.; ProvCite) or Trio's lineage maintenance show a citation-level precedent for two-level staleness; option 3 then applies.

## Log

- 2026-11-23: proposed as part of the full project DAG.
- 2026-11-23: accepted by the user: option 2, on the evidence of T011 (PR #15).
