"""Query result types, the three fingerprints and read-time scope notes (plan 3.4, 5.3).

- `Witness`: one minimal witness, a set of claim IDs and the IDs of the attributions that satisfy
  attribution constraints (why-provenance of the positive part; negation contributes nothing).
- `Answer`: one answer tuple with all its minimal witnesses and the evidence of their claims.
- `QueryResult`: the answers of `Q[r]` on `G_r` plus the evidence per claim; `fingerprints()`
  gives the three fingerprints (answers, witnesses, evidence) that read-time re-query compares.

The scope note of empty results and counts is not part of the result or of any fingerprint: a
program generates it at read time (`scope_note`), so that it never makes a view stale (plan 3.4).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from grace.context.memory.graph.entries import Entity, Value
from grace.context.pipeline.query.ir import Predicate

AnswerValue = Entity | Value | Predicate


def value_key(value: AnswerValue) -> tuple[str, str, str]:
    """A total, deterministic order on answer values."""
    if isinstance(value, Entity):
        return ("entity", "", value.id)
    if isinstance(value, Predicate):
        return ("predicate", "", value.name)
    return ("value", value.datatype, value.lexical)


def value_record(value: AnswerValue) -> dict[str, str]:
    if isinstance(value, Predicate):
        return {"predicate": value.name}
    return value.to_record()


@dataclass(frozen=True, order=True)
class Witness:
    """One minimal witness: sorted claim IDs and attribution IDs."""

    claims: tuple[str, ...]
    attributions: tuple[str, ...] = ()

    @classmethod
    def of(cls, claims, attributions=()) -> Witness:
        return cls(tuple(sorted(set(claims))), tuple(sorted(set(attributions))))

    def issubset(self, other: Witness) -> bool:
        return set(self.claims) <= set(other.claims) and \
            set(self.attributions) <= set(other.attributions)

    def union(self, other: Witness) -> Witness:
        return Witness.of((*self.claims, *other.claims),
                          (*self.attributions, *other.attributions))

    def to_record(self) -> dict[str, list[str]]:
        return {"claims": list(self.claims), "attributions": list(self.attributions)}


def minimal(witnesses) -> tuple[Witness, ...]:
    """Keep the witnesses that contain no other witness (minimal why-provenance), sorted."""
    unique = sorted(set(witnesses))
    return tuple(w for w in unique if not any(o != w and o.issubset(w) for o in unique))


@dataclass(frozen=True)
class Answer:
    values: tuple[AnswerValue, ...]
    witnesses: tuple[Witness, ...]
    evidence: tuple[str, ...] = ()

    def to_record(self) -> dict:
        return {"values": [value_record(v) for v in self.values],
                "witnesses": [w.to_record() for w in self.witnesses],
                "evidence": list(self.evidence)}


@dataclass(frozen=True)
class QueryResult:
    """Answers of a query at one cut-off version.

    `variables` names the answer columns (for a count, the grouping variables, then the counted
    variable, whose value is the integer count). `evidence` maps every witness claim to its
    unified evidence IDs (`message_id` or `message_id#char=start,end`, as in
    `memory/history/spans.py`); it is empty when the query has no provenance expansion.
    """

    variables: tuple[str, ...]
    answers: tuple[Answer, ...]
    cutoff: int
    is_count: bool = False
    temporary: bool = False
    evidence: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))

    @property
    def empty(self) -> bool:
        return not self.answers

    def answer_set(self) -> frozenset[tuple[AnswerValue, ...]]:
        return frozenset(a.values for a in self.answers)

    def witness_set(self) -> frozenset:
        return frozenset((a.values, a.witnesses) for a in self.answers)

    def evidence_set(self) -> frozenset[str]:
        return frozenset(e for a in self.answers for e in a.evidence)

    def fingerprints(self) -> dict[str, str]:
        """SHA-256 of the canonical answers, witnesses and evidence (plan 3.4 staleness)."""
        answers = sorted(json.dumps([value_record(v) for v in a.values], sort_keys=True)
                         for a in self.answers)
        witnesses = sorted(
            json.dumps([[value_record(v) for v in a.values],
                        [w.to_record() for w in a.witnesses]], sort_keys=True)
            for a in self.answers)
        evidence = sorted(self.evidence_set())
        return {name: _sha(data) for name, data in (
            ("answers", answers), ("witnesses", witnesses), ("evidence", evidence))}

    def to_record(self) -> dict:
        return {"variables": list(self.variables), "cutoff": self.cutoff,
                "is_count": self.is_count, "temporary": self.temporary,
                "answers": [a.to_record() for a in self.answers]}


def _sha(data) -> str:
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scope_note(result: QueryResult) -> str | None:
    """The read-time scope note of an empty result or a count; `None` for other results.

    Generated from the result's cut-off when it is read; never stored with a view.
    """
    r = result.cutoff
    if result.is_count:
        return f"Counted within the scope observed up to version {r}."
    if result.empty:
        return f"No matching claim within the scope observed up to version {r}."
    return None
