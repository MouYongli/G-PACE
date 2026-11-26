"""E002: replay extracted change sets, re-query the template views after every message, type
every change (plan 6.5, "Measuring the natural distribution of staleness").

For one history, `measure_history` commits the stored change sets of an extraction run version by
version into a fresh claim graph and keeps the resident views of the six template families
(plan 5.4) with the frozen view code (`context/views/`). After each commit, for every resident
view built before it (cut-off t-1):

1. **Marks.** The write-side strategies see the change set: the two citation-based strategies of
   plan 5.4 (`used_claims`, `used_claims_patterns`, arms of `configs/views/staleness.yaml`), the
   claim-pattern push with local filters and the predicate level (for over-marking), and a
   candidate filter: the claim-pattern push without local filters, the "claim pattern" rung of
   plan 3.4's ladder, which is sound (plan 3.4 proposition; no entity merges or vocabulary
   changes happen here), so a view it does not mark is unchanged.
2. **Reference.** Every candidate view is re-queried at t and compared with its cut-off by the
   answer, witness and evidence fingerprints (`staleness.base.compare`, the exact reference). With
   `full_check` every view is re-queried and a stale view outside the filter is counted as a
   soundness violation (expected 0).
3. **Change type.** The decision list of docs/research/change-sequences.md section 4.1 on the
   change set, with W_b (claims in the view's witnesses at t-1) and R_b (claims matching a claim
   pattern by subject and predicate) taken from the view instead of the reference functions, as
   section 4.1 prescribes for extracted graphs. "Newly matches" is read as "enters the witnesses
   between t-1 and t".
4. **Maintenance.** A stale view is repaired at t (`ViewStore.maintain`, confirm on; template
   rendering, no model call), so the next comparison is again between adjacent versions.
5. **Instantiation.** `ViewStore.materialise` at t (threshold of the view config). Creating a view
   is not a staleness event; creations are counted separately.

Task families need two fixed speakers (user, assistant). A history with two peers (LoCoMo) is
measured in both orientations; the entity families are measured once, in orientation 0.

Output per history: one event record per (version, view, orientation) that is stale, typed C1-C6
or marked by any strategy, and counters of everything else. Totals are computed from the event
records by `eval/analysis/metrics/natural_staleness.py`.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entries import SupersessionKind
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import PredicateSpec, Vocabulary
from grace.context.pipeline.query.ir import Var
from grace.context.views.dependencies import NEGATED
from grace.context.views.staleness import make_strategy
from grace.context.views.staleness.base import compare
from grace.context.views.staleness.matching import Index, Options, claim_matches
from grace.context.views.store import ViewStore
from grace.context.views.template_families import ViewConfig, load_families
from grace.context.views.view import View

ENTITY_FAMILIES = ("list", "current", "count")
TASK_FAMILIES = ("constraints", "pending", "choice")
# Strategy name -> (registered strategy, options). The citation arms follow
# configs/views/staleness.yaml; `filter` is the sound candidate filter of step 1.
STRATEGIES: dict[str, tuple[str, dict[str, Any]]] = {
    "used_claims": ("used_claims", {"watch_mentions": False}),
    "used_claims_patterns": ("used_claims_patterns",
                             {"watch_mentions": False, "local_filters": True}),
    "claim_pattern_filters": ("claim_pattern_push", {"local_filters": True}),
    "predicate_level": ("predicate_level", {}),
    "filter": ("claim_pattern_push", {"local_filters": False}),
}
REPORTED = ("used_claims", "used_claims_patterns", "claim_pattern_filters", "predicate_level")
NO_FILTERS = Options(local_filters=False)
STALE_TYPES = ("C1", "C2", "C3", "C4", "C5", "C6")


def vocabulary_from(table: Mapping[str, Mapping[str, Any]], version: str) -> Vocabulary:
    """The run-local predicate table of one history (`vocabulary.json` of the extraction)."""
    return Vocabulary(version, {p: PredicateSpec(p, bool(spec["exclusive"]))
                                for p, spec in table.items()})


# ---------------------------------------------------------------------------------------------
# Change type (change-sequences.md 4.1 on extracted graphs)


def _touched(cs: ChangeSet, index: Index) -> list:
    claims = list(cs.claims)
    for e in (*cs.attributions, *cs.evidence_links, *cs.supersessions):
        c = index.claims.get(e.claim_id)
        if c is not None:
            claims.append(c)
    return list({c.claim_id: c for c in claims}.values())


def classify(view: View, cs: ChangeSet, index: Index, witnesses_after: frozenset[str],
             answers_before_empty: bool) -> tuple[str, list[str]]:
    """Change type of change set `cs` for `view` (cut-off t-1); `index` includes `cs`.

    Returns (type, sub-kinds): C1..C7 or `untouched`; C2 carries `empty_to_nonempty`, C7 the
    sub-kinds a, b of section 4.1 (c, a join pattern matched without a partner, is reported as a).
    """
    deps = view.dependencies
    family = view.binding.family if view.binding else None
    w_before = view.used_claims()
    # R_b ignores attribution constraints and filters (section 4.1): match on the patterns with
    # their attribution constraint removed.
    relaxed = [replace(dp, pattern=replace(dp.pattern, attribution=None)) for dp in deps]

    def relevant(c) -> bool:
        return any(claim_matches(dp, c, index, NO_FILTERS) for dp in relaxed)

    claims = {c.claim_id: c for c in _touched(cs, index)}
    for s in cs.supersessions:                                           # 1: C5
        c = index.claims.get(s.claim_id)
        if s.kind is SupersessionKind.CORRECTION and c is not None and relevant(c):
            return "C5", []
    for s in cs.supersessions:                                           # 2: C1
        if s.kind is SupersessionKind.CHANGE and s.claim_id in w_before:
            return "C1", []
    negated = [dp for dp in deps if dp.role == NEGATED]
    for a in cs.attributions:                                            # 3: C3
        c = index.claims.get(a.claim_id)
        if c is not None and relevant(c) and any(
                claim_matches(dp, c, index, NO_FILTERS, attribution=a) for dp in negated):
            return "C3", []
    new = [cid for cid in claims if cid in witnesses_after and cid not in w_before
           and relevant(claims[cid])]
    if new:                                                              # 4, 5: C4, C2
        if family == "count" or (family in ("current", "choice") and not answers_before_empty):
            return "C4", []
        return "C2", ["empty_to_nonempty"] if answers_before_empty else []
    for e in (*cs.attributions, *cs.evidence_links):                     # 6: C6
        if e.claim_id in w_before:
            return "C6", []
    predicates = [dp.pattern.predicate for dp in deps]
    subs = set()
    for c in claims.values():                                            # 7: C7
        if any(isinstance(p, Var) or p == c.predicate for p in predicates):
            subs.add("a" if relevant(c) else "b")
    if subs:
        return "C7", sorted(subs)
    return "untouched", []


# ---------------------------------------------------------------------------------------------
# Replay


@dataclass
class Orientation:
    index: int
    user: str
    assistant: str
    families: tuple[str, ...]


@dataclass
class HistoryResult:
    history_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    counters: Counter = field(default_factory=Counter)
    views_created: Counter = field(default_factory=Counter)      # family -> views
    soundness_violations: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0

    def summary(self) -> dict[str, Any]:
        return {"history_id": self.history_id,
                "counters": {"|".join(map(str, k)): v for k, v in sorted(self.counters.items())},
                "views_created": dict(sorted(self.views_created.items())),
                "soundness_violations": self.soundness_violations,
                "seconds": round(self.seconds, 3)}


def orientations(speakers: Sequence[str], role_speakers: Mapping[str, str] | None
                 ) -> list[Orientation]:
    """One orientation for a user/assistant history, two for a history of two peers."""
    if role_speakers is not None:
        return [Orientation(0, role_speakers["user"], role_speakers["assistant"],
                            ENTITY_FAMILIES + TASK_FAMILIES)]
    if len(speakers) != 2:
        raise ValueError(f"a peer history needs exactly two speakers, got {list(speakers)}")
    a, b = speakers
    return [Orientation(0, a, b, ENTITY_FAMILIES + TASK_FAMILIES),
            Orientation(1, b, a, TASK_FAMILIES)]


def _marks(strategy, cs: ChangeSet, views: list[View]) -> dict[str, str]:
    strategy.index.add(cs)
    return {m.view_id: m.level for m in strategy._marks(cs, views)}


def measure_history(history_id: str, changesets: Sequence[ChangeSet], messages: Sequence,
                    vocabulary: Vocabulary, base: ViewConfig, orients: Sequence[Orientation],
                    *, benchmark: str, full_check: bool = False) -> HistoryResult:
    """Replay one history (module docstring). `messages` are the history's message records in
    version order; `changesets` has one change set per version 1..N."""
    start = time.perf_counter()
    if [cs.version for cs in changesets] != list(range(1, len(messages) + 1)):
        raise ValueError(f"{history_id}: change sets must cover versions 1..{len(messages)}")
    result = HistoryResult(history_id)
    graph = ClaimStore(history_id)
    stores, strategies = [], []
    for o in orients:
        config = replace(base, families=o.families,
                         speakers={"user": o.user, "assistant": o.assistant})
        store = ViewStore(history_id, config=config, families=load_families(o.families),
                          vocabulary=vocabulary)
        stores.append(store)
        strategies.append({name: make_strategy(s, store, **opts)
                           for name, (s, opts) in STRATEGIES.items()})
    for cs, message in zip(changesets, messages, strict=True):
        graph.commit(cs)
        for o, store, strats in zip(orients, stores, strategies, strict=True):
            views = store.views()
            marks = {name: _marks(s, cs, views) for name, s in strats.items()}
            index = strats["filter"].index
            for view in views:
                family = view.binding.family
                filtered = view.view_id in marks["filter"]
                marked = {name: marks[name].get(view.view_id) for name in REPORTED}
                evaluation = None
                if filtered or full_check:
                    evaluation, _ = store.evaluate(view.view_id, graph, cs.version)
                    level = compare(view, evaluation).level
                    after = frozenset(c for r in evaluation.rows for w in r.witnesses
                                      for c in w.claims)
                elif any(marked.values()):
                    # Outside the sound filter the view is unchanged (no re-query needed); it is
                    # still typed, because another strategy marked it (over-marking).
                    level, after = "none", view.used_claims()
                else:
                    result.counters[(benchmark, o.index, family, "untouched", "none",
                                     "unmarked")] += 1
                    continue
                kind, subs = classify(view, cs, index, after, not view.rows)
                if level != "none" and not filtered:
                    result.soundness_violations.append(
                        {"version": cs.version, "view_id": view.view_id,
                         "orientation": o.index, "level": level})
                if level != "none" or kind in STALE_TYPES or any(marked.values()):
                    result.events.append({
                        "benchmark": benchmark, "history_id": history_id,
                        "version": cs.version, "message_id": message.message_id,
                        "speaker": message.speaker, "orientation": o.index,
                        "view_id": view.view_id, "family": family, "outcome": level,
                        "type": kind, "subtypes": subs, "marks": marked,
                        "entries": {"claims": len(cs.claims),
                                    "attributions": len(cs.attributions),
                                    "evidence_links": len(cs.evidence_links),
                                    "supersessions": len(cs.supersessions)}})
                else:
                    result.counters[(benchmark, o.index, family, kind, level, "unmarked")] += 1
                if level != "none":
                    store.maintain(view.view_id, graph, cs.version, confirm=True,
                                   evaluation=evaluation)
            for view_id in store.materialise(graph, cs.version):
                result.views_created[store.get(view_id).binding.family] += 1
    result.seconds = time.perf_counter() - start
    return result
