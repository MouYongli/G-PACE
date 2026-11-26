---
id: D010
title: "Phase 4 gate: attribution-guard and open-predicate claims"
created: 2026-11-23
---

# D010 · Phase 4 gate: attribution-guard and open-predicate claims

## Context

The baseline comparisons decide the wording of RQ1 (plan section 9, phase 4 checkpoint).

## Options

- Tagged hybrid retrieval obtains most of the gain attributed to the guard: claim only that speaker and dialogue-act information helps.
- The 'system values are not written' rule also ties on paired correctness: claim no effect of the attribution guard.
- The slot table ties on open-domain slices: claim no gain from open predicates; RDF is a standards-based carrier only.
- Otherwise: keep RQ1 as planned.

## Decision

Pending. To be taken when the nodes this decision depends on are resolved.

## Consequences

Feeds the lock (D012).

## Revisit when

Held-out results contradict the development comparison.

## Log

- 2026-11-23: proposed as part of the full project DAG.
- 2026-11-24: renamed from `D010-gate-role-claims.md` and retitled to follow the plan terminology (attribution guard instead of roles).
- 2026-11-26: evidence from the T022 writer smoke run `T022-20261126T184442Z-2a64` (Qwen3-8B, LoCoMo dev; development data, not a D010 measurement): the removal rule G2(ii) alone, which checks only that the ending stance comes from the same speaker with a matching function, let one message of conv-49 (`D16:10`, "I lost my job last month") end ten unrelated claims of its speaker. By user decision of 2026-11-26 the writer now drops an ending stance on a known claim unless its quote, found in the message, shares a content word with the claim's object (`validate.ending_evidence`, T022 follow-up `m01-T022c`); replayed on that run's 19 committed removals it keeps 2. In the comparison runs it dropped 54 ending stances for Qwen3-8B (`T022-20261126T214758Z-613e`, at most 2 removals per message) and 2 for Qwen3-32B (`T022-20261126T214758Z-c1fa`). This check is a writer-side filter in front of the guard; the guard's rules are unchanged.
