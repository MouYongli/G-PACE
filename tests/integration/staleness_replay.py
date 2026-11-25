"""Replay of the staleness strategies over the change sets of a gold graph (T019 tests).

The change-sequence generator (`eval/datasets/changeseq/`) is used only here, in tests: `context/`
never imports `eval/`. Its six view templates V1-V6 are mapped to the template families of T018
(`list`, `current`, `count`, `constraints`, `pending`, `choice`); the entity families read the
`inform` of the authority speaker `user` (`state_speaker: user`), the change-sequence convention
(finding F1: the fragment's `[u, f]` cannot also require report mode own, positive polarity and
not derived, so on stances it cannot tell apart the views and the generator's reference may
differ; the misses below are counted against read-time re-query of the views themselves, which
F1 does not affect).

`replay` commits the change sets one by one, passes each to the strategy, and at every read point
first computes the exact reference (`fingerprint_staleness`, read-time re-query) of every view,
then lets the strategy check and repair. An instance is one (read point, view): it is stale if the
reference says so, and missed if it is stale and the strategy did not maintain the view, or if it
is answer-stale and the strategy decided citation level only (a citation mark, or a citation
verdict of its fingerprint check). The second condition matters because every maintenance
re-evaluates the view: a citation-level mark on an answer-stale view still gets it repaired, but
the decision was wrong and, with a citation-only repair path, the answer would be lost.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.store import ClaimStore
from grace.context.views.staleness import Strategy, make_arm
from grace.context.views.staleness.base import fingerprint_staleness
from grace.context.views.store import ViewStore
from grace.context.views.template_families import ViewConfig
from grace.context.views.view import Binding
from grace.eval.datasets.changeseq import gold
from grace.eval.datasets.changeseq.invalidation import Binding as GoldBinding
from grace.eval.datasets.changeseq.invalidation import World, gold_staleness

FAMILY = {"V1": "list", "V2": "current", "V3": "count", "V4": "constraints", "V5": "pending",
          "V6": "choice"}
CHANGE_TYPES = ("C1", "C2", "C3", "C4", "C5", "C6", "C7")


def view_binding(b: GoldBinding) -> Binding:
    return Binding(FAMILY[b.template], b.subject, b.predicate)


def view_config(world: World) -> ViewConfig:
    return ViewConfig(state_speaker="user", choice_predicate=world.choice_predicate)


@dataclass(frozen=True)
class Instance:
    version: int
    view_id: str
    binding_id: str | None
    reference: str          # answer, citation, none
    maintained: bool
    decided: str            # the fingerprint verdict if re-queried, else the store's flags
    change_types: frozenset[str]

    @property
    def stale(self) -> bool:
        return self.reference != "none"

    @property
    def missed(self) -> bool:
        if not self.stale:
            return False
        return not self.maintained or (self.reference == "answer"
                                       and self.decided not in ("answer", "invalid"))


@dataclass
class Replay:
    strategy: Strategy
    store: ViewStore
    graph: ClaimStore
    instances: list[Instance] = field(default_factory=list)

    def misses(self) -> list[Instance]:
        return [i for i in self.instances if i.missed]

    def types_stale(self) -> set[str]:
        return {t for i in self.instances if i.stale for t in i.change_types}

    def types_seen(self) -> set[str]:
        return {t for i in self.instances for t in i.change_types}


@dataclass(frozen=True)
class Sequence:
    """The change sets of one gold graph, its view bindings and the generator's change types."""

    history_id: str
    changesets: tuple[ChangeSet, ...]
    bindings: tuple[Binding, ...]
    gold_ids: Mapping[str, str]                       # view ID -> generator binding ID
    types: Mapping[tuple[str, int], str]              # (binding ID, version) -> change type
    config: ViewConfig

    @classmethod
    def from_log(cls, log, world: World, bindings: Iterable[GoldBinding], history_id: str,
                 labels=None) -> Sequence:
        bindings = list(bindings)
        store = gold.build_store(log, history_id, validate=None)
        if labels is None:
            labels = gold_staleness(log, world, bindings).labels
        types = {(x["binding_id"], x["version"]): x["change_type"] for x in labels
                 if x["change_type"] != "untouched"}
        views = tuple(view_binding(b) for b in bindings)
        return cls(history_id, tuple(store.changesets()), views,
                   {v.view_id: b.binding_id for v, b in zip(views, bindings, strict=True)},
                   types, view_config(world))


def replay(seq: Sequence, arm: str | Callable[[ViewStore], Strategy], *, start: int = 0,
           read_every: int = 1, stop: int | None = None, mode: str = "rdf11") -> Replay:
    """Views are built at `start` (0: before the first message); the replay ends at `stop`."""
    graph = ClaimStore(seq.history_id, mode)
    store = ViewStore(seq.history_id, config=seq.config)
    strategy = make_arm(arm, store) if isinstance(arm, str) else arm(store)
    head = max(cs.version for cs in seq.changesets) if stop is None else stop
    for cs in seq.changesets:
        if cs.version <= start:
            graph.commit(cs)
    strategy.prime(cs for cs in seq.changesets if cs.version <= start)
    for b in seq.bindings:
        store.build(b, graph, start)
    out = Replay(strategy, store, graph)
    last_read = start
    for cs in seq.changesets:
        if cs.version <= start:
            continue
        if cs.version > head:
            break
        graph.commit(cs)
        strategy.write(cs, graph)
        v = cs.version
        if (v - start) % read_every and v != head:
            continue
        reference = {b.view_id: fingerprint_staleness(store, b.view_id, graph, v).level
                     for b in seq.bindings}
        record = strategy.read(graph, v, read_id=f"read-{v}")
        maintained = record.maintained()
        for check in record.checks:
            gid = seq.gold_ids.get(check.view_id)
            types = frozenset(seq.types[(gid, t)] for t in range(last_read + 1, v + 1)
                              if (gid, t) in seq.types)
            out.instances.append(Instance(v, check.view_id, gid, reference[check.view_id],
                                          check.view_id in maintained,
                                          check.fingerprint if check.checked else check.flagged,
                                          types))
        last_read = v
    return out
