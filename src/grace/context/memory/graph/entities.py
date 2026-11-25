"""Entity equivalence entries and class representatives (plan 5.2, "Effect of vocabulary changes
and entity merges on views").

When entity alignment finds two entities to be the same, it appends a versioned equivalence entry;
no existing claim is rewritten. Queries are evaluated on the representative of each class. An
equivalence is not one of the four entry kinds: it falls outside the assumptions of the soundness
proposition (plan 3.4), and the engine invalidates every view of the history when one is committed.
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
