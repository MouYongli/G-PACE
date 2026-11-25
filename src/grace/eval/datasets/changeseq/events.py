"""Event grammar and event log (design docs/research/change-sequences.md, section 3).

The event log has one record per message, lambda_t = (t, u_t, theta_t, E_t): version, speaker,
world timestamp and a possibly empty list of primitive events. The three primitives map
deterministically to the four entry kinds of the claim graph (`gold.py`):

- `NewClaim(c, s, p, o, tau)`: a claim and its evidence link;
- `Stance(c, f, rho, pi, derived)`: an attribution of the message speaker, and an evidence link if
  the message has none on `c` yet;
- `Supersede(c, eta)`: a supersession event. It names the replacing claim (or none, a removal) and
  the licensing stance a' of the attribution guard (G2), so the gold entry needs no inference.

Event IDs are the entry IDs of the gold graph, so witnesses computed from the log name graph
entries. `check_log` checks the well-formedness constraints G1-G8 of section 3.2.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

FUNCTIONS = ("request", "offer", "accept", "reject", "confirm", "inform", "commit", "question")
REPORT_MODES = ("own", "quote", "hypothetical")
POLARITIES = ("positive", "negative")
KINDS = ("change", "correction")
OBJECT_TYPES = ("string", "time", "entity")
NON_ENDORSING = {"request", "offer", "question"}


class LogError(ValueError):
    """An event or a log record is malformed."""


@dataclass(frozen=True)
class NewClaim:
    claim_id: str
    subject: str
    predicate: str
    object: str            # lexical form, or the entity ID when `object_type` is `entity`
    object_type: str
    start: str | None = None
    end: str | None = None

    def __post_init__(self) -> None:
        if self.object_type not in OBJECT_TYPES:
            raise LogError(f"NewClaim {self.claim_id}: object_type {self.object_type!r}")
        if self.start is not None and self.end is not None and not self.start < self.end:
            raise LogError(f"NewClaim {self.claim_id}: start {self.start} not before end")

    @property
    def proposition(self) -> tuple:
        return (self.subject, self.predicate, self.object, None, self.start, self.end)


@dataclass(frozen=True)
class Stance:
    attribution_id: str
    claim_id: str
    function: str
    report_mode: str = "own"
    polarity: str = "positive"
    derived: bool = False

    def __post_init__(self) -> None:
        if (self.function not in FUNCTIONS or self.report_mode not in REPORT_MODES
                or self.polarity not in POLARITIES):
            raise LogError(f"Stance {self.attribution_id}: bad field in {self!r}")


@dataclass(frozen=True)
class Supersede:
    supersession_id: str
    claim_id: str
    kind: str
    attribution_id: str               # the licensing stance a' (G2)
    replacing_claim_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise LogError(f"Supersede {self.supersession_id}: kind {self.kind!r}")


Event = NewClaim | Stance | Supersede
_EVENT_TYPES = {"NewClaim": NewClaim, "Stance": Stance, "Supersede": Supersede}


@dataclass(frozen=True)
class Macro:
    """The planned change a message realises: name, intended type and focus binding."""

    macro_id: str
    name: str
    intended_type: str
    focus: str


@dataclass(frozen=True)
class LogRecord:
    """lambda_t: one message of the event log, with the cue the renderer needs."""

    version: int
    message_id: str
    episode: str
    speaker: str
    timestamp: str
    events: tuple[Event, ...] = ()
    macro: Macro | None = None
    cue: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_filler(self) -> bool:
        return not self.events

    def to_record(self) -> dict[str, Any]:
        return {
            "version": self.version, "message_id": self.message_id, "episode": self.episode,
            "speaker": self.speaker, "timestamp": self.timestamp,
            "events": [{"type": type(e).__name__, **asdict(e)} for e in self.events],
            "macro": asdict(self.macro) if self.macro else None,
            "cue": dict(self.cue),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_record(), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_record(cls, raw: Mapping[str, Any]) -> LogRecord:
        events = []
        for e in raw["events"]:
            e = dict(e)
            kind = _EVENT_TYPES.get(e.pop("type", None))
            if kind is None:
                raise LogError(f"version {raw['version']}: unknown event type")
            events.append(kind(**e))
        macro = Macro(**raw["macro"]) if raw.get("macro") else None
        return cls(raw["version"], raw["message_id"], raw["episode"], raw["speaker"],
                   raw["timestamp"], tuple(events), macro, dict(raw.get("cue") or {}))


def claims_of(log: Iterable[LogRecord]) -> dict[str, tuple[int, NewClaim]]:
    """Claim ID -> (introduction version, NewClaim)."""
    return {e.claim_id: (r.version, e) for r in log for e in r.events if isinstance(e, NewClaim)}


# ---------------------------------------------------------------------------------------------
# Well-formedness (design section 3.2)


def check_log(log: list[LogRecord], authority: Mapping[str, str], exclusive: Iterable[str],
              catalogue_predicate: str, choice_predicate: str) -> list[str]:
    """Return every violation of G1-G8 (empty when the log is well formed).

    `authority` maps each predicate to its authority speaker; `exclusive` names the exclusive
    predicates. G7 is checked here on the events (fillers have none); the text side of G7 is the
    renderer's forbidden-value check and the audit.
    """
    exclusive = set(exclusive)
    problems: list[str] = []
    claims: dict[str, NewClaim] = {}
    propositions: set[tuple] = set()
    stances: dict[str, list[tuple[str, Stance, int]]] = defaultdict(list)  # claim -> (u, a, t)
    superseded: set[str] = set()
    versions = [r.version for r in log]
    if versions != list(range(1, len(log) + 1)):
        problems.append("versions are not 1..N")
    for r in log:
        t = r.version
        if r.macro is None and r.events:
            problems.append(f"{t}: events without a macro")
        if r.cue.get("skeleton") == "filler" and r.events:
            problems.append(f"{t}: G7 filler with events")
        new_here = {e.claim_id: e for e in r.events if isinstance(e, NewClaim)}
        here = {e.attribution_id: e for e in r.events if isinstance(e, Stance)}
        for c in new_here.values():
            if c.proposition in propositions:
                problems.append(f"{t}: G1 claim {c.claim_id} repeats a proposition")
            if not any(s.claim_id == c.claim_id for s in here.values()):
                problems.append(f"{t}: claim {c.claim_id} has no stance in its message")
        for s in here.values():
            if s.claim_id not in claims and s.claim_id not in new_here:
                problems.append(f"{t}: stance {s.attribution_id} on unknown claim {s.claim_id}")
                continue
            claim = claims.get(s.claim_id) or new_here[s.claim_id]
            if s.function == "confirm" and s.claim_id in new_here:
                problems.append(f"{t}: G4 confirm on a claim introduced in the same message")
            if s.claim_id in new_here and claim.predicate != choice_predicate:
                endorsing = (s.function == "inform" and s.report_mode == "own"
                             and s.polarity == "positive" and r.speaker == authority.get(
                                 claim.predicate))
                blocked = s.function in NON_ENDORSING or s.report_mode != "own"
                if not (endorsing or blocked):
                    problems.append(f"{t}: G4 claim {s.claim_id} introduced by {s.function} of "
                                    f"{r.speaker}")
            if s.claim_id in new_here and claim.predicate == choice_predicate:
                if s.function != "offer" or r.speaker != "assistant":
                    problems.append(f"{t}: choice claim {s.claim_id} not introduced by an offer")
        # G5: offers carry catalogue facts of the offered item.
        for s in here.values():
            if s.function == "offer" and s.claim_id in new_here:
                item = new_here[s.claim_id].object
                if not any(c.subject == item and c.predicate == catalogue_predicate
                           and any(a.claim_id == c.claim_id and a.function == "inform"
                                   for a in here.values())
                           for c in new_here.values()):
                    problems.append(f"{t}: G5 offer of {item} without its catalogue claim")
        # G6 and G8 (acceptances and rejections of the choice predicate).
        for s in here.values():
            claim = claims.get(s.claim_id)
            if claim is None or claim.predicate != choice_predicate or r.speaker != "user":
                continue
            history = stances[s.claim_id]
            if s.function == "accept" and any(f.function == "reject" and u == "user"
                                              for u, f, _ in history):
                problems.append(f"{t}: G6 re-acceptance of rejected {s.claim_id}")
            if s.function == "reject" and any(f.function == "accept" for _, f, _ in history):
                choice = _current_choice(claims, stances, superseded, claim.subject,
                                         choice_predicate)
                if choice == s.claim_id and _accepted_unrejected(
                        claims, stances, superseded, claim.subject, choice_predicate) - {
                            s.claim_id}:
                    problems.append(f"{t}: G8 rejection of the current choice falls back")
        # G2 and G3.
        for sup in (e for e in r.events if isinstance(e, Supersede)):
            if sup.claim_id in superseded:
                problems.append(f"{t}: G3 claim {sup.claim_id} superseded twice")
            old = claims.get(sup.claim_id)
            licence = here.get(sup.attribution_id)
            if old is None or licence is None:
                problems.append(f"{t}: G2 supersession {sup.supersession_id} without its claim "
                                f"or licensing stance in the message")
                continue
            if licence.report_mode != "own":
                problems.append(f"{t}: G2 licence {licence.attribution_id} is not own")
            if sup.replacing_claim_id is not None:
                rep = new_here.get(sup.replacing_claim_id)
                ok = (rep is not None and licence.claim_id == rep.claim_id
                      and (rep.subject, rep.predicate) == (old.subject, old.predicate)
                      and old.predicate in exclusive and licence.polarity == "positive")
                if not ok:
                    problems.append(f"{t}: G2(i) supersession {sup.supersession_id} not licensed "
                                    f"by a replacing claim on an exclusive predicate")
            elif not (licence.claim_id == old.claim_id and licence.polarity == "negative"):
                problems.append(f"{t}: G2(ii) removal {sup.supersession_id} without a negative "
                                f"own stance on the claim")
            if not any(u == r.speaker and f.function == licence.function
                       for u, f, _ in stances[old.claim_id]):
                problems.append(f"{t}: G2 no earlier attribution on {old.claim_id} with the "
                                f"speaker and function of the licence")
        # Commit the message.
        for c in new_here.values():
            claims[c.claim_id] = c
            propositions.add(c.proposition)
        for s in here.values():
            stances[s.claim_id].append((r.speaker, s, t))
        superseded.update(e.claim_id for e in r.events if isinstance(e, Supersede))
    return problems


def _accepted_unrejected(claims, stances, superseded, task, choice_predicate) -> set[str]:
    out = set()
    for cid, c in claims.items():
        if c.subject != task or c.predicate != choice_predicate or cid in superseded:
            continue
        fs = {(u, s.function) for u, s, _ in stances[cid] if s.report_mode == "own"
              and s.polarity == "positive"}
        if ("user", "accept") in fs and ("user", "reject") not in fs:
            out.add(cid)
    return out


def _current_choice(claims, stances, superseded, task, choice_predicate) -> str | None:
    keys = [(t, cid) for cid in _accepted_unrejected(claims, stances, superseded, task,
                                                     choice_predicate)
            for u, s, t in stances[cid] if u == "user" and s.function == "accept"]
    return max(keys)[1] if keys else None
