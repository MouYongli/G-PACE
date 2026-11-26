"""Candidate entities, predicates and known claims shown to the writer (plan 5.1, 5.6).

The writer receives "current message, local context, candidate entities and predicates" (plan 5.6).
Everything here comes from the claim graph at the writer's head and from the vocabulary; nothing
comes from views, staleness marks or fingerprints, which `pipeline/update/` cannot import
(structure.md: `update/` imports only `memory/`).

- **Predicates**: every predicate of the vocabulary in force (seed plus history-local), with its
  exclusivity and aliases, the most used first, at most `max_predicates`.
- **Entities**: entity IDs that occur as subject, entity object or speaker of a currently accepted
  claim, ranked by word overlap with the unit and then by recency, at most `max_entities`.
- **Known claims**: currently accepted claims, each under a handle `k<i>` valid for this call only,
  ranked as in E002's one-off writer: claims touched in the last `recent_versions` versions first,
  then by word overlap with the unit, then by recency; at most `max_claims`. A claim is listed with
  the last few stances on it, so the writer can tell an offer from an accepted option.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from grace.context.memory.graph.entries import Claim, Entity, Value
from grace.context.memory.graph.store import GraphState
from grace.context.memory.graph.vocabulary import Vocabulary

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("the and for with that this was are you your have has had not but from they "
                  "she her his him its our out all any can did does what when who how why "
                  "about just like really been will would there their them then than very".split())


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP}


def object_text(claim: Claim) -> str:
    obj = claim.object
    return obj.id if isinstance(obj, Entity) else obj.lexical


def object_label(claim: Claim) -> str:
    obj = claim.object
    if isinstance(obj, Value) and obj.datatype != "string":
        return f"{obj.lexical} ({obj.datatype})"
    if isinstance(obj, Value):
        return f'"{obj.lexical}"'
    return obj.id


def claim_label(claim: Claim) -> str:
    parts = [claim.subject, claim.predicate, object_label(claim)]
    if claim.scope is not None:
        parts.append(f"scope {claim.scope}")
    vt = claim.valid_time
    if vt.start or vt.end:
        parts.append(f"valid {vt.start or '?'}..{vt.end or 'open'}")
    elif vt.expression:
        parts.append(f"time {vt.expression}")
    return " | ".join(parts)


@dataclass(frozen=True)
class KnownClaim:
    handle: str
    claim_id: str
    label: str
    stances: tuple[str, ...]


@dataclass(frozen=True)
class Candidates:
    """What one writer call sees of the graph; `handles` maps `k<i>` to claim IDs."""

    predicates: tuple[tuple[str, bool, tuple[str, ...]], ...]
    entities: tuple[str, ...]
    claims: tuple[KnownClaim, ...]

    @property
    def handles(self) -> dict[str, str]:
        return {k.handle: k.claim_id for k in self.claims}

    def predicate_lines(self) -> str:
        out = []
        for name, exclusive, aliases in self.predicates:
            line = f"- {name}: {'single' if exclusive else 'multi'}"
            if aliases:
                line += " (also: " + ", ".join(aliases) + ")"
            out.append(line)
        return "\n".join(out) or "(none yet)"

    def entity_lines(self) -> str:
        return ", ".join(self.entities) or "(none yet)"

    def claim_lines(self) -> str:
        if not self.claims:
            return "(none)"
        return "\n".join(f"{k.handle}: {k.label}"
                         + (f" [{'; '.join(k.stances)}]" if k.stances else "")
                         for k in self.claims)


def _stance_text(a) -> str:
    parts = [a.speaker]
    if a.polarity.value == "negative":
        parts.append("not")
    parts.append(a.function.value)
    if a.report_mode.value != "own":
        parts.append(f"({a.report_mode.value})")
    return " ".join(parts)


def build_candidates(state: GraphState, vocabulary: Vocabulary, unit_text: str, version: int,
                     *, predicate_uses: Mapping[str, int] | None = None,
                     speakers: Iterable[str] = (), max_claims: int = 40,
                     max_predicates: int = 80, max_entities: int = 40,
                     recent_versions: int = 8, stances_shown: int = 3) -> Candidates:
    """The candidates for a unit whose text is `unit_text`, at writer head `state`."""
    uses = Counter(predicate_uses or {})
    aliases: dict[str, list[str]] = {}
    for alias, target in vocabulary.aliases.items():
        aliases.setdefault(target, []).append(alias)
    names = sorted(vocabulary.predicates, key=lambda p: (-uses[p], p))[:max_predicates]
    predicates = tuple((p, vocabulary.predicates[p].exclusive, tuple(sorted(aliases.get(p, ()))))
                       for p in names)

    unit_words = words(unit_text)
    current = [c for c in state.claims.values() if state.is_current(c.claim_id)]
    last_touch: dict[str, int] = {}
    stances: dict[str, list] = {}
    for a in state.attributions.values():
        stances.setdefault(a.claim_id, []).append(a)
        last_touch[a.claim_id] = max(last_touch.get(a.claim_id, 0), a.version)
    for e in state.evidence_links.values():
        last_touch[e.claim_id] = max(last_touch.get(e.claim_id, 0), e.version)

    scored = []
    for c in current:
        touched = last_touch.get(c.claim_id, c.version)
        recent = touched >= version - recent_versions
        overlap = len(unit_words & words(claim_label(c)))
        if recent or overlap:
            scored.append((not recent, -overlap, -touched, c.claim_id))
    chosen = sorted(scored)[:max_claims]
    chosen_claims = sorted((state.claims[s[3]] for s in chosen),
                           key=lambda c: (c.version, c.claim_id))
    known = []
    for i, c in enumerate(chosen_claims, start=1):
        on = sorted(stances.get(c.claim_id, []), key=lambda a: (a.version, a.attribution_id))
        known.append(KnownClaim(f"k{i}", c.claim_id, claim_label(c),
                                tuple(_stance_text(a) for a in on[-stances_shown:])))

    entity_touch: dict[str, int] = {s: 0 for s in speakers}
    for c in current:
        touched = last_touch.get(c.claim_id, c.version)
        for e in (c.subject, c.object.id if isinstance(c.object, Entity) else None):
            if e is not None:
                entity_touch[e] = max(entity_touch.get(e, 0), touched)
    ranked = sorted(entity_touch, key=lambda e: (-len(unit_words & words(e)), -entity_touch[e], e))
    return Candidates(predicates, tuple(sorted(ranked[:max_entities])), tuple(known))


def unit_text(texts: Sequence[str]) -> str:
    return " ".join(texts)
