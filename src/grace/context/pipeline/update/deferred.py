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
from grace.context.memory.graph.store import GraphState
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
        if claim_id in self.claims:
            raise ValueError(f"claim {claim_id} already noted")
        self.claims[claim_id] = ClaimHint(exclusive, correction)

    def note_ending(self, attribution_id: str, kind: SupersessionKind,
                    valid_end: str | None = None) -> None:
        if attribution_id in self.endings:
            raise ValueError(f"ending {attribution_id} already noted")
        self.endings[attribution_id] = EndingHint(SupersessionKind(kind), valid_end)

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


def _prefix(state: GraphState, version: int, supersessions: dict) -> GraphState:
    """The entries stamped before `version`, with the supersessions derived so far."""
    def before(entries):
        return MappingProxyType({k: e for k, e in entries.items() if e.version < version})
    return GraphState(version - 1, before(state.claims), before(state.attributions),
                      before(state.evidence_links), MappingProxyType(dict(supersessions)),
                      before(state.equivalences), before(state.labels))


def _apply(decision: Decision, attribution_id: str, version: int,
           derived: dict[str, Supersession], pending: Pending) -> None:
    for s in decision.supersede:
        sid = f"resolved-{len(derived) + 1}"
        derived[sid] = Supersession(sid, s.claim_id, s.kind, s.valid_end, s.replacing_claim_id,
                                    attribution_id, version)
        pending.superseded.add(s.claim_id)


def resolve_at_read(state: GraphState, log: ResolutionLog, guard: Guard) -> Resolution:
    """Replay the guard over `state` (which must hold no supersession) at every call."""
    if state.supersessions:
        raise ValueError("the append-only write path commits no supersessions; got "
                         f"{len(state.supersessions)}")
    derived: dict[str, Supersession] = {}
    conflicts: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    versions = sorted({a.version for a in state.attributions.values()})
    for version in versions:
        prefix = _prefix(state, version, derived)
        pending = Pending(reps=replace(state, version=version).representatives())
        seen_first: set[str] = set()

        for a in (a for a in state.attributions.values() if a.version == version):
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
    resolved = replace(state, supersessions=MappingProxyType(derived))
    return Resolution(resolved, tuple(conflicts), tuple(blocked))
