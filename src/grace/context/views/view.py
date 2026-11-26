"""A view: its six components and the binding of sentences to result rows (plan 3.4, 5.4).

A view has six components (plan 3.4): the query template with its bound parameters (`query`,
`binding`), the cut-off version (`cutoff`), text with evidence cited for every sentence
(`sentences`), the claims and attributions used (the witnesses of `rows`), the evidence cited (the
evidence of `rows`), and the dependency patterns (`dependencies`).

Rows and sentences:

- A `Row` is one result row of the query at the cut-off: its answer values, its minimal
  witnesses and the evidence of their claims. Its ID is a hash of its identity, so the same
  answer has the same row ID in every rebuild: the values for a plain row; the grouping values for
  the aggregate row of a count, whose count value may change under a stable ID. An aggregate row
  lists its member rows (the distinct counted values) in `members`.
- A `Sentence` states one or more rendering units and is labelled with their row IDs. A unit is
  one plain row, or an aggregate row together with all its members ("an aggregate sentence is
  labelled with the aggregate value and its member rows"). Its evidence is the union of the
  evidence of its rows, so a citation patch is a pure function of the rows (`rebuild.py`).

The scope note of empty results and counts is not part of a view (plan 3.4): `text()` generates it
from the version being read.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from grace.context.memory.graph.entries import Entity, Value
from grace.context.pipeline.query.grammar import parse, to_text
from grace.context.pipeline.query.ir import Predicate, Query
from grace.context.pipeline.query.result import (
    Answer,
    AnswerValue,
    QueryResult,
    Witness,
    scope_note,
    value_record,
)
from grace.context.views.dependencies import DependencyPattern, dependency_patterns

SOURCES = ("template", "llm", "fallback")


class ViewError(ValueError):
    """A malformed view, binding or view record."""


class Lifecycle(StrEnum):
    RESIDENT = "resident"    # materialised from a template list, stored, maintained, reused
    TEMPORARY = "temporary"  # built for one question, discarded when it ends, never reused


def value_from_record(record: Mapping[str, Any]) -> AnswerValue:
    if set(record) == {"entity"}:
        return Entity(record["entity"])
    if set(record) == {"predicate"}:
        return Predicate(record["predicate"])
    if set(record) == {"value", "datatype"}:
        return Value(record["value"], record["datatype"])
    raise ViewError(f"not an answer value record: {record!r}")


def row_id(values: tuple[AnswerValue, ...], aggregate: bool = False) -> str:
    text = json.dumps([value_record(v) for v in values], sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return ("a" if aggregate else "r") + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Binding:
    """The parameters a template family is bound with: (entity, predicate) or a task entity."""

    family: str
    subject: str
    predicate: str | None = None

    @property
    def view_id(self) -> str:
        return ":".join(x for x in (self.family, self.subject, self.predicate) if x)

    def to_record(self) -> dict[str, Any]:
        return {"family": self.family, "subject": self.subject, "predicate": self.predicate}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Binding:
        return cls(record["family"], record["subject"], record.get("predicate"))


@dataclass(frozen=True)
class Row:
    row_id: str
    values: tuple[AnswerValue, ...]
    witnesses: tuple[Witness, ...] = ()
    evidence: tuple[str, ...] = ()
    aggregate: bool = False
    members: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[AnswerValue, ...]:
        """Identity of the row across rebuilds: the grouping values of an aggregate."""
        return self.values[:-1] if self.aggregate else self.values

    def to_record(self) -> dict[str, Any]:
        return {"row_id": self.row_id, "values": [value_record(v) for v in self.values],
                "witnesses": [w.to_record() for w in self.witnesses],
                "evidence": list(self.evidence), "aggregate": self.aggregate,
                "members": list(self.members)}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Row:
        return cls(record["row_id"], tuple(value_from_record(v) for v in record["values"]),
                   tuple(Witness(tuple(w["claims"]), tuple(w["attributions"]))
                         for w in record["witnesses"]),
                   tuple(record["evidence"]), bool(record["aggregate"]),
                   tuple(record["members"]))


@dataclass(frozen=True)
class Sentence:
    """A sentence, the IDs of the rows it states, the evidence it cites, and where it came from.

    `source`: `template` (template serialisation), `llm` (LLM rendering that passed the
    rendering check), `fallback` (the template serialisation that replaced a failed LLM sentence).
    """

    text: str
    rows: tuple[str, ...]
    evidence: tuple[str, ...] = ()
    source: str = "template"

    def __post_init__(self) -> None:
        if not self.rows:
            raise ViewError("a sentence states at least one row")
        if self.source not in SOURCES:
            raise ViewError(f"unknown sentence source {self.source!r}")

    def to_record(self) -> dict[str, Any]:
        return {"text": self.text, "rows": list(self.rows), "evidence": list(self.evidence),
                "source": self.source}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Sentence:
        return cls(record["text"], tuple(record["rows"]), tuple(record["evidence"]),
                   record["source"])


def count_witnesses(answer: Answer, members: tuple[Row, ...]) -> tuple[Witness, ...]:
    """Witnesses of the aggregate row of a count.

    The single place that fixes the convention for counting views. Now: the compiler's form, one
    witness that is the union of the members' witnesses (plan 3.4). The change-sequence generator
    keeps one witness set per member instead; which form is canonical is not decided yet
    (T015 cross-check), and changing it here changes every count view consistently.
    """
    return answer.witnesses


def build_rows(result: QueryResult, members: QueryResult | None = None) -> tuple[Row, ...]:
    """Rows of a query result; for a count, `members` is the result of its member query.

    Plain rows keep the order of the result. For a count, the member rows come first (in the order
    of the member result), then the aggregate rows.
    """
    if not result.is_count:
        return tuple(Row(row_id(a.values), a.values, a.witnesses, a.evidence)
                     for a in result.answers)
    if members is None:
        raise ViewError("a count view needs the result of its member query")
    groups = len(result.variables) - 1
    member_rows = [Row(row_id(a.values), a.values, a.witnesses, a.evidence)
                   for a in members.answers]
    rows: list[Row] = list(member_rows)
    for a in result.answers:
        group = a.values[:groups]
        ids = tuple(r.row_id for r in member_rows if r.values[:groups] == group)
        own = tuple(r for r in member_rows if r.row_id in ids)
        rows.append(Row(row_id(group, aggregate=True), a.values, count_witnesses(a, own),
                        a.evidence, aggregate=True, members=ids))
    return tuple(rows)


def units(rows: tuple[Row, ...]) -> list[tuple[str, ...]]:
    """Rendering units in row order: each plain row that is no member, and each aggregate with
    its members."""
    member_ids = {m for r in rows if r.aggregate for m in r.members}
    out = []
    for r in rows:
        if r.aggregate:
            out.append((r.row_id, *r.members))
        elif r.row_id not in member_ids:
            out.append((r.row_id,))
    return out


def sentence_evidence(row_ids, rows: Mapping[str, Row]) -> tuple[str, ...]:
    return tuple(sorted({e for rid in row_ids for e in rows[rid].evidence}))


def order_sentences(sentences, rows: tuple[Row, ...]) -> tuple[Sentence, ...]:
    """Canonical order: by the first row each sentence states, in row order."""
    position = {r.row_id: i for i, r in enumerate(rows)}
    return tuple(sorted(sentences, key=lambda s: (min(position[r] for r in s.rows), s.rows)))


@dataclass(frozen=True)
class View:
    """One view of one history (see the module docstring)."""

    view_id: str
    history_id: str
    lifecycle: Lifecycle
    binding: Binding | None
    title: str
    query: Query
    cutoff: int
    columns: tuple[str, ...]
    is_count: bool
    rows: tuple[Row, ...]
    sentences: tuple[Sentence, ...]
    fingerprints: Mapping[str, str] = field(default_factory=dict)
    dependencies: tuple[DependencyPattern, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fingerprints", MappingProxyType(dict(self.fingerprints)))
        if not self.dependencies:
            object.__setattr__(self, "dependencies", dependency_patterns(self.query))
        ids = [r.row_id for r in self.rows]
        if len(set(ids)) != len(ids):
            raise ViewError(f"view {self.view_id}: duplicate row IDs")
        covered = [rid for s in self.sentences for rid in s.rows]
        if len(set(covered)) != len(covered):
            raise ViewError(f"view {self.view_id}: a row is stated by two sentences")
        expected = {rid for u in units(self.rows) for rid in u}
        if set(covered) != expected:
            raise ViewError(f"view {self.view_id}: sentences state {sorted(set(covered))}, "
                            f"rows are {sorted(expected)}")

    # -- the components ------------------------------------------------------------------------

    def row(self, rid: str) -> Row:
        for r in self.rows:
            if r.row_id == rid:
                return r
        raise KeyError(rid)

    def witnesses(self) -> frozenset[Witness]:
        return frozenset(w for r in self.rows for w in r.witnesses)

    def used_claims(self) -> frozenset[str]:
        return frozenset(c for w in self.witnesses() for c in w.claims)

    def used_attributions(self) -> frozenset[str]:
        return frozenset(a for w in self.witnesses() for a in w.attributions)

    def evidence(self) -> frozenset[str]:
        return frozenset(e for r in self.rows for e in r.evidence)

    def text(self, read_version: int | None = None) -> str:
        """The view text with the citations of every sentence; the scope note of an empty view
        or a count is generated here from the version being read, never stored."""
        lines = [f"{s.text} [{', '.join(s.evidence)}]" if s.evidence else s.text
                 for s in self.sentences]
        version = self.cutoff if read_version is None else read_version
        note = scope_note(QueryResult(self.columns, () if not self.rows else (None,), version,
                                      is_count=self.is_count))
        if note:
            lines.append(note)
        return "\n".join(lines)

    # -- records -------------------------------------------------------------------------------

    def to_record(self) -> dict[str, Any]:
        return {"view_id": self.view_id, "history_id": self.history_id,
                "lifecycle": self.lifecycle.value,
                "binding": self.binding.to_record() if self.binding else None,
                "title": self.title, "query": to_text(self.query), "cutoff": self.cutoff,
                "columns": list(self.columns), "is_count": self.is_count,
                "rows": [r.to_record() for r in self.rows],
                "sentences": [s.to_record() for s in self.sentences],
                "fingerprints": dict(self.fingerprints),
                "dependencies": [d.to_record() for d in self.dependencies]}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> View:
        query = parse(record["query"])
        view = cls(record["view_id"], record["history_id"], Lifecycle(record["lifecycle"]),
                   Binding.from_record(record["binding"]) if record["binding"] else None,
                   record["title"], query, int(record["cutoff"]), tuple(record["columns"]),
                   bool(record["is_count"]),
                   tuple(Row.from_record(r) for r in record["rows"]),
                   tuple(Sentence.from_record(s) for s in record["sentences"]),
                   record["fingerprints"])
        if [d.to_record() for d in view.dependencies] != record["dependencies"]:
            raise ViewError(f"view {view.view_id}: stored dependency patterns differ from those "
                            "of its query")
        return view
