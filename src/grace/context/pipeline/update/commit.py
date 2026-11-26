"""Graph transaction of one version (plan 5.1, write step 4).

`ChangeSetBuilder` collects the entries of one version with history-unique IDs and builds the
`ChangeSet`; `commit_version` commits it to the claim store. IDs are derived from the version and a
counter per kind (`c12.1`, `a12.1`, `e12.1`, `s12.1`, `q12.1`, `l12.1`), so they are unique
across kinds within a history because each version is committed once, and a retry of the same unit
produces the same IDs (the store treats an identical retry as a no-op).

A change set the store rejects (a commit rule, SHACL, or a contract check of `ChangeSet` itself)
is not partially written: the version is committed as an empty change set instead, so the
raw-text path and later versions are unaffected, and the error is returned for the update record.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entities import EntityEquivalence, EntityLabel
from grace.context.memory.graph.entries import (
    Attribution,
    Claim,
    Entity,
    EntryError,
    EvidenceLink,
    Span,
    Supersession,
    SupersessionKind,
    Term,
    ValidTime,
)
from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.update.validate import Stance

PREFIX = {"claim": "c", "attribution": "a", "evidence": "e", "supersession": "s",
          "equivalence": "q", "label": "l"}


@dataclass
class ChangeSetBuilder:
    history_id: str
    version: int
    vocabulary_version: str | None = None
    claims: list[Claim] = field(default_factory=list)
    attributions: list[Attribution] = field(default_factory=list)
    evidence: list[EvidenceLink] = field(default_factory=list)
    supersessions: list[Supersession] = field(default_factory=list)
    merges: list[EntityEquivalence] = field(default_factory=list)
    labels: list[EntityLabel] = field(default_factory=list)
    _counter: Counter = field(default_factory=Counter)
    _evidence_keys: set = field(default_factory=set)

    def _id(self, kind: str) -> str:
        self._counter[kind] += 1
        return f"{PREFIX[kind]}{self.version}.{self._counter[kind]}"

    def claim(self, subject: str, predicate: str, obj: Term, scope: str | None,
              valid_time: ValidTime) -> Claim:
        claim = Claim(self._id("claim"), subject, predicate, obj, scope, valid_time,
                      self.version)
        self.claims.append(claim)
        return claim

    def attribution(self, claim_id: str, speaker: str, stance: Stance,
                    message_id: str) -> Attribution:
        attribution = Attribution(self._id("attribution"), claim_id, speaker, stance.function,
                                  stance.report_mode, stance.polarity, stance.certainty,
                                  stance.derived, message_id, self.version)
        self.attributions.append(attribution)
        return attribution

    def evidence_link(self, claim_id: str, message_id: str, span: Span | None) -> None:
        key = (claim_id, message_id, span)
        if key in self._evidence_keys:
            return
        self._evidence_keys.add(key)
        self.evidence.append(EvidenceLink(self._id("evidence"), claim_id, message_id, span,
                                          self.version))

    def supersession(self, claim_id: str, kind: SupersessionKind, valid_end: str | None,
                     replacing_claim_id: str | None, attribution_id: str) -> Supersession:
        s = Supersession(self._id("supersession"), claim_id, kind, valid_end,
                         replacing_claim_id, attribution_id, self.version)
        self.supersessions.append(s)
        return s

    def equivalence(self, entity_a: str, entity_b: str) -> EntityEquivalence:
        q = EntityEquivalence(self._id("equivalence"), entity_a, entity_b, self.version)
        self.merges.append(q)
        return q

    def label(self, entity: str, label: str) -> EntityLabel:
        x = EntityLabel(self._id("label"), entity, label, self.version)
        self.labels.append(x)
        return x

    def named_entities(self) -> set[str]:
        """Entities the entries so far name: subjects, entity objects, speakers, merged ones."""
        out = {c.subject for c in self.claims}
        out |= {c.object.id for c in self.claims if isinstance(c.object, Entity)}
        out |= {a.speaker for a in self.attributions}
        out |= {e for q in self.merges for e in (q.entity_a, q.entity_b)}
        return out

    def build(self) -> ChangeSet:
        return ChangeSet(self.history_id, self.version, tuple(self.claims),
                         tuple(self.attributions), tuple(self.evidence),
                         tuple(self.supersessions), self.vocabulary_version, tuple(self.merges),
                         tuple(self.labels))


def commit_version(store: ClaimStore, builder: ChangeSetBuilder, *, validate: bool
                   ) -> tuple[ChangeSet, str | None]:
    """Commit the builder's change set; on rejection commit an empty one (module docstring).

    Returns the committed change set and the rejection message, if any.
    """
    try:
        return store.commit(builder.build(), validate=validate), None
    except EntryError as exc:  # CommitError and CommitConflict are EntryErrors
        error = f"{type(exc).__name__}: {exc}"
    empty = ChangeSet(builder.history_id, builder.version,
                      vocabulary_version=builder.vocabulary_version)
    return store.commit(empty), error
