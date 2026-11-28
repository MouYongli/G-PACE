"""Query-time conflict resolution for the append-only baseline (plan 7.2; T027).

"Append-only memory without views, resolving conflicts at query time, same backbone" (plan 7.2):
the write path commits claims, attributions and evidence links but no supersession events, and
keeps no views. At every read, `resolve_at_read` replays the attribution guard
(`guard.py`, the component this one stands beside) over the stored entries in version order and
returns the graph state with the supersessions that the write-time guard would have committed.
Nothing is cached: every read pays the replay again, which is the cost the baseline exists to
measure against stored views.

What the guard needs and the claim graph does not store is recorded by the write path in a
`ResolutionLog` (append-only, saved with the engine): per new claim, whether its predicate had an
exclusivity rule and whether the writer marked it as a correction; per ending stance, the kind of
ending and its valid end. These are the same inputs `updater.py` passes to `Guard.replacement`
and `Guard.removal`.

Order within one version: the first attribution of each claim new at that version is guarded as
a replacement, and every other attribution in stored order, ending stances included; the updater
handles a message's claims before its stances, so the replay matches it except when one message
both ends a claim and repeats it (not seen in the writer's output so far).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from grace.context.memory.graph.entries import Supersession, SupersessionKind
from grace.context.memory.graph.store import ClaimStore, GraphState
from grace.context.pipeline.update.guard import Decision, Guard, Pending

LOG_FILE = "resolution-log.json"


@dataclass(frozen=True)
class ClaimHint:
    exclusive: bool
    correction: bool = False


@dataclass(frozen=True)
class EndingHint:
    kind: SupersessionKind
    valid_end: str | None = None


@dataclass
class ResolutionLog:
    """Guard inputs recorded at write time (module docstring); entries are never changed."""

    claims: dict[str, ClaimHint] = field(default_factory=dict)
    endings: dict[str, EndingHint] = field(default_factory=dict)

    def note_claim(self, claim_id: str, *, exclusive: bool, correction: bool = False) -> None:
        hint = ClaimHint(exclusive, correction)
        if self.claims.get(claim_id, hint) != hint:
            raise ValueError(f"claim {claim_id} already noted with other inputs")
        self.claims[claim_id] = hint

    def note_ending(self, attribution_id: str, kind: SupersessionKind,
                    valid_end: str | None = None) -> None:
        hint = EndingHint(SupersessionKind(kind), valid_end)
        if self.endings.get(attribution_id, hint) != hint:
            raise ValueError(f"ending {attribution_id} already noted with other inputs")
        self.endings[attribution_id] = hint

    def to_record(self) -> dict[str, Any]:
        return {"claims": {k: [v.exclusive, v.correction] for k, v in self.claims.items()},
                "endings": {k: [v.kind.value, v.valid_end] for k, v in self.endings.items()}}

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> ResolutionLog:
        return cls({k: ClaimHint(bool(e), bool(c)) for k, (e, c) in record["claims"].items()},
                   {k: EndingHint(SupersessionKind(kind), end)
                    for k, (kind, end) in record["endings"].items()})

    def save(self, directory: Path) -> list[Path]:
        path = Path(directory) / LOG_FILE
        path.write_text(json.dumps(self.to_record(), sort_keys=True), encoding="utf-8")
        return [path]

    @classmethod
    def restore(cls, directory: Path) -> ResolutionLog:
        return cls.from_record(json.loads((Path(directory) / LOG_FILE).read_text(
            encoding="utf-8")))


@dataclass(frozen=True)
class Resolution:
    state: GraphState                       # the stored state plus the derived supersessions
    conflicts: tuple[dict[str, Any], ...] = ()
    blocked: tuple[dict[str, Any], ...] = ()


def _apply(decision: Decision, attribution_id: str, version: int,
           derived: dict[str, Supersession], pending: Pending) -> None:
    for s in decision.supersede:
        sid = f"resolved-{len(derived) + 1}"
        derived[sid] = Supersession(sid, s.claim_id, s.kind, s.valid_end, s.replacing_claim_id,
                                    attribution_id, version)
        pending.superseded.add(s.claim_id)


def _by_version(entries) -> dict[int, list]:
    out: dict[int, list] = {}
    for e in entries.values():
        out.setdefault(e.version, []).append(e)
    return out


def resolve_at_read(state: GraphState, log: ResolutionLog, guard: Guard) -> Resolution:
    """Replay the guard over `state` (which must hold no supersession) at every call.

    One pass in version order: the prefix state the guard sees at version v holds the entries
    stamped before v and the supersessions derived so far (live dictionaries, grown after v)."""
    if state.supersessions:
        raise ValueError("the append-only write path commits no supersessions; got "
                         f"{len(state.supersessions)}")
    kinds = (state.claims, state.attributions, state.evidence_links, state.equivalences,
             state.labels)
    groups = [_by_version(k) for k in kinds]
    live: list[dict] = [{} for _ in kinds]
    derived: dict[str, Supersession] = {}
    base = GraphState(0, *(MappingProxyType(d) for d in live[:3]), MappingProxyType(derived),
                      *(MappingProxyType(d) for d in live[3:]))
    conflicts: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    versions = sorted(set().union(*(g.keys() for g in groups)))
    for version in versions:
        prefix = replace(base, version=version - 1)
        pending = Pending(reps=replace(state, version=version).representatives())
        seen_first: set[str] = set()
        for a in groups[1].get(version, ()):
            claim = state.claims[a.claim_id]
            if claim.version == version and a.claim_id not in seen_first:
                seen_first.add(a.claim_id)
                hint = log.claims.get(a.claim_id, ClaimHint(False))
                decision = guard.replacement(prefix, claim, a, exclusive=hint.exclusive,
                                             correction=hint.correction, pending=pending)
                _apply(decision, a.attribution_id, version, derived, pending)
                conflicts += [{"version": version, "kept": c.kept_claim_id,
                               "new": c.new_claim_id, "reason": c.reason}
                              for c in decision.conflicts]
                pending.add_claim(claim)
            elif a.attribution_id in log.endings:
                ending = log.endings[a.attribution_id]
                current = a.claim_id not in pending.superseded and (
                    a.claim_id not in prefix.claims or prefix.is_current(a.claim_id))
                if not current:
                    blocked.append({"version": version, "claim": a.claim_id,
                                    "reason": "not_current"})
                else:
                    decision = guard.removal(prefix, a.claim_id, a, kind=ending.kind,
                                             valid_end=ending.valid_end, pending=pending)
                    if decision.blocked:
                        blocked.append({"version": version, "claim": a.claim_id,
                                        "reason": decision.blocked})
                    _apply(decision, a.attribution_id, version, derived, pending)
            pending.add_attribution(a)
        for group, target in zip(groups, live, strict=True):
            for e in group.get(version, ()):
                target[e.entry_id] = e
    resolved = replace(state, supersessions=MappingProxyType(dict(derived)))
    return Resolution(resolved, tuple(conflicts), tuple(blocked))


def resolved_store(store: ClaimStore, version: int, log: ResolutionLog, guard: Guard
                   ) -> ClaimStore:
    """A fresh claim store of the entries up to `version` plus the supersessions derived at
    this read (`resolve_at_read`), for the read path's queries; built anew at every read."""
    resolution = resolve_at_read(store.state(version), log, guard)
    extra: dict[int, list[Supersession]] = {}
    for s in resolution.state.supersessions.values():
        extra.setdefault(s.version, []).append(s)
    out = ClaimStore(store.history_id, store.mode)
    for cs in store.changesets(upto=version):
        out.commit(replace(cs, supersessions=cs.supersessions + tuple(extra.pop(cs.version,
                                                                                ()))))
    if extra:
        raise ValueError(f"derived supersessions at versions without a change set: {sorted(extra)}")
    return out


class QueryTimeResolution:
    """Per-history component of the append-only variant (the engine's extension hook, see
    `context/engine.py`): the updater records guard inputs in `deferred` and commits no
    supersession; every read queries `read_graph`, resolved at that read."""

    def __init__(self, guard: Guard):
        self.guard = guard
        self.deferred = ResolutionLog()

    def extractor(self, default):
        return default

    def read_graph(self, store: ClaimStore, version: int) -> ClaimStore:
        return resolved_store(store, version, self.deferred, self.guard)

    def state_facts(self, task, request: str) -> list:
        return []

    def save(self, directory: Path) -> list[Path]:
        Path(directory).mkdir(parents=True, exist_ok=True)
        return self.deferred.save(directory)

    def restore(self, directory: Path) -> None:
        self.deferred = ResolutionLog.restore(directory)


def query_time_resolution(*, writer, client=None, view_config=None, **options):
    """Component factory (`config/registry.py`, name `query-time-resolution`): one
    `QueryTimeResolution` per history, with the writer config's guard setting."""
    if options:
        raise TypeError(f"query-time-resolution takes no options, got {sorted(options)}")
    return lambda history: QueryTimeResolution(Guard(enabled=writer.guard))
