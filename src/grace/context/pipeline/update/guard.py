"""Attribution guard and exclusivity rules (plan 3.2, 5.2; contracts.md, "Claim graph").

The guard decides, by program, whether a new stance supersedes an existing claim. It is not a
store rule, so a variant without it (`Guard(enabled=False)`, "latest value wins" on exclusive
predicates, for the ablation of the guard) can still write.

**Replacement (plan 3.2).** A new claim c' introduced with attribution a' supersedes a currently
accepted claim c only if

1. c and c' have the same subject (up to entity equivalence at the writer's head), predicate and
   scope, and the predicate has an exclusivity rule;
2. some attribution on c has the same speaker and the same communicative function as a';
3. the report mode of a' is own statement.

Two further conditions make the rule well defined on stored claims; both only keep claims side by
side, so they never make the guard less strict than plan 3.2:

4. a' is positive: a denial of c' cannot establish c' as the new state (plan 5.2: a denial is a
   stance, never a second claim);
5. both claims are open-ended (no stated valid end): a claim of a closed past interval ("I lived
   in Hamburg until 2015") describes another time and competes with nothing.

The supersession has kind `correction` when the writer marked c' as a correction, else `change`;
a change carries `valid_end` = the start of c' when c' is dated (contracts.md, valid end).

**Removal (G2(ii)).** A stance a' on c itself that asks to end c supersedes it without a replacing
claim only if a' is own and negative and its speaker and function equal those of some earlier
attribution on c. No exclusivity rule is needed.

**Conflicts.** When conditions 1 and 5 hold but 2, 3 or 4 fail, both claims are kept and the pair
is reported as a conflict (plan 3.2: "conflicting statements by different speakers are both kept and
the conflict is marked"). The claim graph has no conflict entry; a conflict is recoverable from the
graph (two current open-ended claims of one exclusive predicate, subject and scope) and is listed in
the update record.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from grace.context.memory.graph.entries import (
    Attribution,
    Claim,
    Polarity,
    ReportMode,
    SupersessionKind,
)
from grace.context.memory.graph.store import GraphState


@dataclass(frozen=True)
class Supersede:
    """Supersede `claim_id`; `replacing_claim_id` is None for a removal."""

    claim_id: str
    kind: SupersessionKind
    replacing_claim_id: str | None
    valid_end: str | None


@dataclass(frozen=True)
class Conflict:
    """Claims kept side by side although they compete for one exclusive slot."""

    kept_claim_id: str
    new_claim_id: str
    reason: str   # which guard condition failed: speaker_or_function, report_mode, polarity


@dataclass(frozen=True)
class Decision:
    supersede: tuple[Supersede, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    blocked: str | None = None   # a removal the guard refused, and why


def _same_subject(a: str, b: str, reps: Mapping[str, str]) -> bool:
    return reps.get(a, a) == reps.get(b, b)


def _speaker_function_match(new: Attribution, on: Iterable[Attribution],
                            reps: Mapping[str, str]) -> bool:
    return any(_same_subject(a.speaker, new.speaker, reps) and a.function is new.function
               for a in on)


@dataclass
class Pending:
    """Entries of the change set being built: claims added so far, attributions on any claim, and
    claims already superseded in it. Two statements in one message are guarded like two
    messages."""

    claims: list[Claim] = field(default_factory=list)
    attributions: dict[str, list[Attribution]] = field(default_factory=dict)
    superseded: set[str] = field(default_factory=set)
    reps: dict[str, str] | None = None   # entity representatives incl. merges of this change set

    def add_claim(self, claim: Claim) -> None:
        self.claims.append(claim)

    def add_attribution(self, attribution: Attribution) -> None:
        self.attributions.setdefault(attribution.claim_id, []).append(attribution)


def _attributions(state: GraphState, pending: Pending, claim_id: str,
                  skip: str | None = None) -> list[Attribution]:
    on = list(state.attributions_on(claim_id)) if claim_id in state.claims else []
    return on + [a for a in pending.attributions.get(claim_id, ()) if a.attribution_id != skip]


@dataclass(frozen=True)
class Guard:
    """`enabled=False` is the no-guard variant: on an exclusive predicate any positive new claim
    replaces the current open-ended values, whoever stated them and in whatever mode, and any
    negative stance can end a claim."""

    enabled: bool = True

    def replacement(self, state: GraphState, new: Claim, attribution: Attribution, *,
                    exclusive: bool, correction: bool, pending: Pending | None = None
                    ) -> Decision:
        """Decision for new claim `new` (not yet in `state`) with attribution `attribution`.

        `state` is the graph at the writer's head; `pending` the change set built so far.
        """
        if not exclusive or new.valid_time.end is not None:
            return Decision()
        pending = pending or Pending()
        reps = pending.reps if pending.reps is not None else state.representatives()
        supersede, conflicts = [], []
        candidates = [c for c in state.claims.values() if state.is_current(c.claim_id)]
        candidates += [c for c in pending.claims if c.claim_id not in state.claims]
        for old in candidates:
            if old.claim_id in pending.superseded or old.claim_id == new.claim_id:
                continue
            if (old.predicate != new.predicate or old.scope != new.scope
                    or not _same_subject(old.subject, new.subject, reps)):
                continue
            if old.valid_time.end is not None:
                continue
            on = _attributions(state, pending, old.claim_id)
            reason = None
            if self.enabled:
                if not _speaker_function_match(attribution, on, reps):
                    reason = "speaker_or_function"
                elif attribution.report_mode is not ReportMode.OWN:
                    reason = "report_mode"
            if reason is None and attribution.polarity is not Polarity.POSITIVE:
                reason = "polarity"
            if reason is not None:
                conflicts.append(Conflict(old.claim_id, new.claim_id, reason))
                continue
            kind = SupersessionKind.CORRECTION if correction else SupersessionKind.CHANGE
            end = new.valid_time.start if kind is SupersessionKind.CHANGE else None
            supersede.append(Supersede(old.claim_id, kind, new.claim_id, end))
        return Decision(tuple(supersede), tuple(conflicts))

    def removal(self, state: GraphState, claim_id: str, attribution: Attribution, *,
                kind: SupersessionKind, valid_end: str | None,
                pending: Pending | None = None) -> Decision:
        """Decision for a stance `attribution` on `claim_id` that asks to end it (G2(ii))."""
        pending = pending or Pending()
        if claim_id in pending.superseded:
            return Decision(blocked="already_superseded")
        if attribution.polarity is not Polarity.NEGATIVE:
            return Decision(blocked="polarity")
        if self.enabled:
            if attribution.report_mode is not ReportMode.OWN:
                return Decision(blocked="report_mode")
            earlier = _attributions(state, pending, claim_id, skip=attribution.attribution_id)
            reps = pending.reps if pending.reps is not None else state.representatives()
            if not _speaker_function_match(attribution, earlier, reps):
                return Decision(blocked="speaker_or_function")
        end = valid_end if kind is SupersessionKind.CHANGE else None
        return Decision((Supersede(claim_id, kind, None, end),))
