"""Independent re-evaluation of the views on the gold claim graph (T015 acceptance item 3).

`invalidation.py` computes (ans, wit, ev) from the event log. This module computes the same values
a second way: from the committed gold graph, reading `ClaimStore.state(t)` (the entries stamped
<= t, as the T014 store returns them) at every version, with its own code for the six view
templates of design section 6.2. Agreement at every version and binding checks the event-log ->
graph mapping (`gold.py`) and the reference functions against each other.

It shares only the `Binding` and `World` data classes with `invalidation.py`; it imports nothing
from `context/pipeline/query/` and runs no SPARQL. The cross-check against read-time re-query
with the compiled IR of T017 (design section 6.4) is a separate follow-up once T017 lands; with
this independent reference that check will also test the compiler.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from grace.context.memory.graph.entries import (
    Attribution,
    Claim,
    Entity,
    Polarity,
    ReportMode,
    SupersessionKind,
)
from grace.context.memory.graph.store import ClaimStore, GraphState
from grace.eval.datasets.changeseq.invalidation import Binding, World


def _obj(claim: Claim) -> str:
    return claim.object.id if isinstance(claim.object, Entity) else claim.object.lexical


class _Index:
    """Per-version index of a GraphState: attributions, evidence and supersessions per claim."""

    def __init__(self, state: GraphState):
        self.state = state
        self.atts: dict[str, list[Attribution]] = defaultdict(list)
        for a in state.attributions.values():
            self.atts[a.claim_id].append(a)
        self.msgs: dict[str, set[str]] = defaultdict(set)
        for e in state.evidence_links.values():
            self.msgs[e.claim_id].add(e.message_id)
        self.superseded = {s.claim_id for s in state.supersessions.values()}
        self.by_sp: dict[tuple[str, str], list[Claim]] = defaultdict(list)
        for c in state.claims.values():
            self.by_sp[(c.subject, c.predicate)].append(c)

    def own_positive(self, cid: str, speaker: str, function: str,
                     exclude_derived: bool = False) -> list[Attribution]:
        return [a for a in self.atts.get(cid, ()) if a.speaker == speaker
                and a.function.value == function and a.report_mode is ReportMode.OWN
                and a.polarity is Polarity.POSITIVE and not (exclude_derived and a.derived)]

    def live(self, subject: str, predicate: str) -> list[Claim]:
        return [c for c in self.by_sp.get((subject, predicate), ())
                if c.claim_id not in self.superseded]


def evaluate(index: _Index, b: Binding, world: World) -> dict[str, Any]:
    """Canonical {"ans", "wit", "ev"} of binding b on the graph state of `index`."""
    pairs: list[tuple[Any, frozenset]] = []           # (answer, witness set)
    if b.template in ("V1", "V2", "V3"):
        auth = world.authority[b.predicate]
        members = []
        for c in index.live(b.subject, b.predicate):
            endorse = index.own_positive(c.claim_id, auth, "inform", exclude_derived=True)
            if endorse and (b.template != "V2" or c.valid_time.end is None):
                members.append((c, endorse))
        if b.template == "V2" and members:
            members = [max(members, key=lambda m: (m[0].version, m[0].claim_id))]
        for c, endorse in members:
            pairs += [(_obj(c), frozenset({c.claim_id, a.attribution_id})) for a in endorse]
        if b.template == "V3":
            # One witness, the union of the members' witnesses (plan 3.4).
            n = len({_obj(c) for c, _ in members})
            union = frozenset(e for _, w in pairs for e in w)
            pairs = [(n, union)] if union else []
            answers = {n}
        else:
            answers = {a for a, _ in pairs}
    elif b.template == "V4":
        for q in sorted(world.constraint_predicates):
            for c in index.live(b.subject, q):
                for a in index.own_positive(c.claim_id, "user", "request"):
                    pairs.append(((q, _obj(c)), frozenset({c.claim_id, a.attribution_id})))
        answers = {a for a, _ in pairs}
    elif b.template == "V5":
        for c in index.live(b.subject, world.choice_predicate):
            if (index.own_positive(c.claim_id, "user", "accept")
                    or index.own_positive(c.claim_id, "user", "reject")):
                continue
            for a in index.own_positive(c.claim_id, "assistant", "offer"):
                pairs.append((_obj(c), frozenset({c.claim_id, a.attribution_id})))
        answers = {a for a, _ in pairs}
    elif b.template == "V6":
        accepted = []
        for c in index.live(b.subject, world.choice_predicate):
            if index.own_positive(c.claim_id, "user", "reject"):
                continue
            accepted += [(a.version, c.claim_id, c, a)
                         for a in index.own_positive(c.claim_id, "user", "accept")]
        if accepted:
            top = max(accepted, key=lambda x: (x[0], x[1]))[2]
            for _, _, _, a in (x for x in accepted if x[2].claim_id == top.claim_id):
                for d in index.live(_obj(top), world.catalogue_predicate):
                    for ad in index.own_positive(d.claim_id, "assistant", "inform"):
                        pairs.append(((_obj(top), _obj(d)), frozenset(
                            {top.claim_id, a.attribution_id, d.claim_id, ad.attribution_id})))
        answers = {a for a, _ in pairs}
    else:
        raise ValueError(f"unknown template {b.template}")
    wit: dict[Any, set[frozenset]] = defaultdict(set)
    for a, w in pairs:
        wit[a].add(w)
    if b.template == "V3" and not pairs:
        wit = {0: set()}
    claims = {e for _, w in pairs for e in w if e in index.state.claims}
    ev = set().union(*(index.msgs[c] for c in claims)) if claims else set()

    def js(x):
        return list(x) if isinstance(x, tuple) else x

    return {"ans": sorted(js(a) for a in answers),
            "wit": sorted([js(a), sorted(sorted(w) for w in ws)] for a, ws in wit.items()),
            "ev": sorted(ev)}


def historical(index: _Index, subject: str, predicate: str, tau: str, world: World,
               dates: dict[int, str], undated: str) -> str | None:
    """Hist on the graph: corrected claims excluded, changes kept (design section 6.2)."""
    corrected = {s.claim_id for s in index.state.supersessions.values()
                 if s.kind is SupersessionKind.CORRECTION}
    auth = world.authority[predicate]
    best = None
    for c in index.by_sp.get((subject, predicate), ()):
        if c.claim_id in corrected or not index.own_positive(c.claim_id, auth, "inform", True):
            continue
        start = c.valid_time.start or ("" if undated == "neg-inf" else dates[c.version])
        end = c.valid_time.end
        if start <= tau and (end is None or tau < end):
            key = (start, c.version, c.claim_id)
            if best is None or key > best[0]:
                best = (key, _obj(c))
    return best[1] if best else None


def reevaluate(store: ClaimStore, bindings: Sequence[Binding], world: World,
               versions: Sequence[int]) -> dict[str, dict[int, dict[str, Any]]]:
    """binding_id -> version -> canonical value, evaluated on `store.state(version)`."""
    out: dict[str, dict[int, dict[str, Any]]] = {b.binding_id: {} for b in bindings}
    for t in versions:
        index = _Index(store.state(t))
        for b in bindings:
            out[b.binding_id][t] = evaluate(index, b, world)
    return out


def disagreements(store: ClaimStore, bindings: Sequence[Binding], world: World,
                  reference: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Every (version, binding) where the graph re-evaluation differs from the event-log
    reference values (`GoldStaleness.values`)."""
    versions = range(len(next(iter(reference.values()))))
    graph = reevaluate(store, bindings, world, versions)
    return [f"t={t} {b.binding_id}: log {reference[b.binding_id][t]} != graph "
            f"{graph[b.binding_id][t]}"
            for b in bindings for t in versions
            if reference[b.binding_id][t] != graph[b.binding_id][t]]
