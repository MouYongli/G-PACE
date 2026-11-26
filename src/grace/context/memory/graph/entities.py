"""Entity equivalences, entity labels, class representatives and display names (plan 5.2, "Effect
of vocabulary changes and entity merges on views"; contracts.md, "Claim graph").

When entity alignment finds two entities to be the same, it appends a versioned equivalence entry;
no existing claim is rewritten. Queries are evaluated on the representative of each class. An
equivalence is not one of the four entry kinds: it falls outside the assumptions of the soundness
proposition (plan 3.4), and the engine invalidates every view of the history when one is committed.

An entity label records the surface name an entity ID was made from (version 0.3 of the
contract). It is display data, read by no query: it changes no answer, witness, evidence or
fingerprint, and invalidates no view.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from grace.context.memory.graph.entries import EntryError, _check_id, _check_version, _fields


@dataclass(frozen=True)
class EntityEquivalence:
    """From version `version` on, entities `entity_a` and `entity_b` denote the same thing."""

    equivalence_id: str
    entity_a: str
    entity_b: str
    version: int

    def __post_init__(self) -> None:
        for name in ("equivalence_id", "entity_a", "entity_b"):
            _check_id("EntityEquivalence", name, getattr(self, name))
        if self.entity_a == self.entity_b:
            raise EntryError("EntityEquivalence: an entity is trivially equivalent to itself")
        _check_version("EntityEquivalence", self.version)

    @property
    def entry_id(self) -> str:
        return self.equivalence_id

    def to_record(self) -> dict[str, Any]:
        return {"equivalence_id": self.equivalence_id, "entity_a": self.entity_a,
                "entity_b": self.entity_b, "version": self.version}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> EntityEquivalence:
        return cls(**_fields(cls, record))


def representatives(equivalences: Iterable[EntityEquivalence], version: int) -> dict[str, str]:
    """Map every entity named by an equivalence visible at `version` to its class representative.

    The representative is the smallest entity ID of the class (by code point), so the mapping at a
    cut-off version does not depend on the order in which the equivalences were committed.
    Entities in no equivalence map to themselves and are omitted.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for eq in equivalences:
        if eq.version <= version:
            a, b = find(eq.entity_a), find(eq.entity_b)
            if a != b:
                parent[max(a, b)] = min(a, b)
    return {x: find(x) for x in parent}


@dataclass(frozen=True)
class EntityLabel:
    """From version `version` on, entity `entity` is shown to people and models as `label`.

    The label is the surface name the entity ID was made from. It is display data: no query reads
    it, so it enters no answer, witness, evidence or fingerprint, and committing one invalidates no
    view. Like an equivalence it is not one of the four entry kinds. A label is written once per
    entity and history and never changes (`ClaimStore` rejects a second label for an entity); an
    entity merge does not rewrite labels (`display_name`).
    """

    label_id: str
    entity: str
    label: str
    version: int

    def __post_init__(self) -> None:
        for name in ("label_id", "entity", "label"):
            _check_id("EntityLabel", name, getattr(self, name))
        _check_version("EntityLabel", self.version)

    @property
    def entry_id(self) -> str:
        return self.label_id

    def to_record(self) -> dict[str, Any]:
        return {"label_id": self.label_id, "entity": self.entity, "label": self.label,
                "version": self.version}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> EntityLabel:
        return cls(**_fields(cls, record))


def labels_at(labels: Iterable[EntityLabel], version: int) -> dict[str, str]:
    """Entity ID -> label for the labels stamped at most `version`.

    A store holds at most one label per entity; for a bare collection that holds more, the label
    with the earliest stamp (then the smallest label ID) wins, so the result is deterministic.
    """
    best: dict[str, EntityLabel] = {}
    for item in labels:
        if item.version <= version:
            seen = best.get(item.entity)
            if seen is None or (item.version, item.label_id) < (seen.version, seen.label_id):
                best[item.entity] = item
    return {e: item.label for e, item in sorted(best.items())}


def display_name(entity: str, labels: Mapping[str, str], reps: Mapping[str, str]) -> str:
    """The name to show for `entity` at one cut-off (labels and representatives of that cut-off).

    Its own label; else, when it belongs to an equivalence class, the label of the class
    representative, else the label of the smallest labelled member of the class (by code point);
    else the entity ID itself. Queries evaluate on representatives, so this names an answer value
    after a merge; the merge itself already invalidates every view (plan 5.2).
    """
    if entity in labels:
        return labels[entity]
    rep = reps.get(entity, entity)
    if rep in labels:
        return labels[rep]
    members = sorted(e for e, r in reps.items() if r == rep and e in labels)
    return labels[members[0]] if members else entity
