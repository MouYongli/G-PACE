"""Change set: the entries one commit adds, and their stored form (contracts.md, "Claim graph").

A change set is what the graph transaction of version r produces (plan 5.1, write step 4): new
claims, attributions, evidence links and supersession events, all stamped r, plus the vocabulary
version in force, any entity equivalences and any entity labels. It is stored one record per
committed version in `changesets.jsonl` of a run (contracts.md, "Experiment run") so that staleness
strategies can be replayed over it (ablation A) and a store can be rebuilt from it.

Entity labels (contract version 0.3) are optional in the record: a change set without labels is
stored without the `entity_labels` key, byte for byte as before 0.3, and a record without the key
is read as a change set without labels.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from grace.context.memory.graph.entities import EntityEquivalence, EntityLabel
from grace.context.memory.graph.entries import (
    ENTRY_KINDS,
    Attribution,
    Claim,
    Entry,
    EntryError,
    EvidenceLink,
    Supersession,
    _check_id,
    _check_version,
    check_change_ends,
)

RECORD_FIELDS = ("history_id", "version", "entries", "vocabulary_version", "entity_merges")
OPTIONAL_FIELDS = ("entity_labels",)   # since contract version 0.3; omitted when empty


@dataclass(frozen=True)
class ChangeSet:
    """The entries added at `version` of history `history_id`.

    Within each kind, entries are kept in the order given; `canonical()` sorts them by ID.
    """

    history_id: str
    version: int
    claims: tuple[Claim, ...] = ()
    attributions: tuple[Attribution, ...] = ()
    evidence_links: tuple[EvidenceLink, ...] = ()
    supersessions: tuple[Supersession, ...] = ()
    vocabulary_version: str | None = None
    entity_merges: tuple[EntityEquivalence, ...] = field(default=())
    entity_labels: tuple[EntityLabel, ...] = field(default=())

    def __post_init__(self) -> None:
        _check_id("ChangeSet", "history_id", self.history_id)
        _check_version("ChangeSet", self.version)
        if self.vocabulary_version is not None:
            _check_id("ChangeSet", "vocabulary_version", self.vocabulary_version)
        for kind, cls in (*ENTRY_KINDS.items(), ("entity_merges", EntityEquivalence),
                          ("entity_labels", EntityLabel)):
            items = getattr(self, kind)
            if not isinstance(items, tuple):
                object.__setattr__(self, kind, items := tuple(items))
            for item in items:
                if not isinstance(item, cls):
                    raise EntryError(f"ChangeSet.{kind}: expected {cls.__name__}, got {item!r}")
                if item.version != self.version:
                    raise EntryError(f"ChangeSet {self.version}: {kind} entry {item.entry_id} "
                                     f"has version {item.version}")
        seen: set[str] = set()
        for item in self.all_entries():
            if item.entry_id in seen:
                raise EntryError(f"ChangeSet {self.version}: duplicate entry ID {item.entry_id}")
            seen.add(item.entry_id)
        labelled: set[str] = set()
        for item in self.entity_labels:
            if item.entity in labelled:
                raise EntryError(f"ChangeSet {self.version}: entity {item.entity!r} has more "
                                 f"than one label")
            labelled.add(item.entity)
        check_change_ends(self.supersessions, f"ChangeSet {self.version}")

    def entries(self) -> Iterator[Entry]:
        """The four kinds of entries, in the order claims, attributions, evidence, supersessions."""
        for kind in ENTRY_KINDS:
            yield from getattr(self, kind)

    def all_entries(self) -> Iterator[Entry | EntityEquivalence | EntityLabel]:
        yield from self.entries()
        yield from self.entity_merges
        yield from self.entity_labels

    @property
    def empty(self) -> bool:
        return not any(True for _ in self.all_entries())

    def canonical(self) -> ChangeSet:
        """The same change set with the entries of each kind sorted by ID."""
        def by_id(items):
            return tuple(sorted(items, key=lambda e: e.entry_id))
        return ChangeSet(self.history_id, self.version, by_id(self.claims),
                         by_id(self.attributions), by_id(self.evidence_links),
                         by_id(self.supersessions), self.vocabulary_version,
                         by_id(self.entity_merges), by_id(self.entity_labels))

    def touched_claim_ids(self) -> frozenset[str]:
        """Claims this change set adds or adds an entry to: the scope of SHACL validation."""
        ids = {c.claim_id for c in self.claims}
        ids |= {e.claim_id for e in (*self.attributions, *self.evidence_links,
                                     *self.supersessions)}
        ids |= {s.replacing_claim_id for s in self.supersessions if s.replacing_claim_id}
        return frozenset(ids)

    def to_record(self) -> dict[str, Any]:
        """The `changesets.jsonl` record; entries of each kind sorted by ID. `entity_labels` is
        present only when the change set has labels."""
        c = self.canonical()
        record = {
            "history_id": c.history_id,
            "version": c.version,
            "entries": {kind: [e.to_record() for e in getattr(c, kind)] for kind in ENTRY_KINDS},
            "vocabulary_version": c.vocabulary_version,
            "entity_merges": [e.to_record() for e in c.entity_merges],
        }
        if c.entity_labels:
            record["entity_labels"] = [e.to_record() for e in c.entity_labels]
        return record

    def to_json(self) -> str:
        return json.dumps(self.to_record(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ChangeSet:
        if not isinstance(record, Mapping):
            raise EntryError(f"ChangeSet: expected an object, got {type(record).__name__}")
        if unknown := sorted(record.keys() - set(RECORD_FIELDS) - set(OPTIONAL_FIELDS)):
            raise EntryError(f"ChangeSet: unknown fields {unknown}")
        if missing := sorted(set(RECORD_FIELDS) - record.keys()):
            raise EntryError(f"ChangeSet: missing fields {missing}")
        entries = record["entries"]
        if not isinstance(entries, Mapping) or set(entries) != set(ENTRY_KINDS):
            raise EntryError(f"ChangeSet.entries: expected exactly the keys {list(ENTRY_KINDS)}")
        kinds = {}
        for kind, entry_cls in ENTRY_KINDS.items():
            if not isinstance(entries[kind], list):
                raise EntryError(f"ChangeSet.entries.{kind}: expected a list")
            kinds[kind] = tuple(entry_cls.from_record(item) for item in entries[kind])
        merges = record["entity_merges"]
        if not isinstance(merges, list):
            raise EntryError("ChangeSet.entity_merges: expected a list")
        labels = record.get("entity_labels", [])
        if not isinstance(labels, list):
            raise EntryError("ChangeSet.entity_labels: expected a list")
        return cls(history_id=record["history_id"], version=record["version"], **kinds,
                   vocabulary_version=record["vocabulary_version"],
                   entity_merges=tuple(EntityEquivalence.from_record(m) for m in merges),
                   entity_labels=tuple(EntityLabel.from_record(x) for x in labels))

    @classmethod
    def from_json(cls, line: str) -> ChangeSet:
        return cls.from_record(json.loads(line))
