"""Append-only, bitemporal claim store on pyoxigraph (plan 3.2, 5.1, 5.2).

Contract: docs/research/contracts.md, "Claim graph".

One `ClaimStore` holds the claim graph of one history. `commit` appends the change set of one
version as one transaction and returns it; nothing is ever updated or deleted. Every entry carries
its version stamp, so a read at cut-off version r sees exactly the entries stamped <= r, whatever
was committed later (time-travel stability, plan 3.3).

Commit rules (checked before anything is written; a failed commit writes nothing):

- the change set names this store's history;
- its version is greater than the head; a version at or below the head is accepted only as a retry
  of the identical change set already committed there, which is a no-op (idempotent retry);
- entry IDs are new and unique across all kinds within the history;
- every reference (claim of an attribution, evidence link or supersession; replacing claim;
  licensing attribution) names an entry of the right kind in the store or the same change set;
- a new claim does not repeat the proposition (s, p, o, scope, valid time) of a claim that is
  currently accepted; a repeated mention adds an attribution and an evidence link instead;
- a replacing claim has the subject, predicate and scope of the claim it replaces, and the
  licensing attribution is on the superseded claim or on the replacing claim;
- an entity has at most one label in the history: a label is written once and never changes.

The attribution guard and the exclusivity rules are not commit rules: they decide *whether* to
supersede and live in `pipeline/update/guard.py` (T022), so that a variant without the guard can
still write. SHACL validation of the touched claims is `validate` (see `shacl.py`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pyoxigraph as ox

from grace.context.memory.graph import rdf
from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entities import (
    EntityEquivalence,
    EntityLabel,
    display_name,
    labels_at,
    representatives,
)
from grace.context.memory.graph.entries import (
    Attribution,
    Claim,
    EntryError,
    EvidenceLink,
    Supersession,
    SupersessionKind,
    effective_change_end,
)
from grace.context.memory.graph.vocabulary import PREFIXES

CUTOFF = "%r%"
SNAPSHOT_FILES = ("store.json", "changesets.jsonl", "graph.nt")


class CommitError(EntryError):
    """A change set violates a commit rule; nothing was written."""


class CommitConflict(CommitError):
    """A retry at a committed version differs from the change set committed there."""


@dataclass(frozen=True)
class GraphState:
    """The entries visible at cut-off `version`: G_version as Python objects (read-only)."""

    version: int
    claims: MappingProxyType
    attributions: MappingProxyType
    evidence_links: MappingProxyType
    supersessions: MappingProxyType
    equivalences: MappingProxyType
    labels: MappingProxyType = MappingProxyType({})   # label ID -> EntityLabel

    def attributions_on(self, claim_id: str) -> list[Attribution]:
        return sorted((a for a in self.attributions.values() if a.claim_id == claim_id),
                      key=lambda a: (a.version, a.attribution_id))

    def evidence_for(self, claim_id: str) -> list[EvidenceLink]:
        return sorted((e for e in self.evidence_links.values() if e.claim_id == claim_id),
                      key=lambda e: (e.version, e.evidence_id))

    def supersessions_of(self, claim_id: str) -> list[Supersession]:
        return sorted((s for s in self.supersessions.values() if s.claim_id == claim_id),
                      key=lambda s: (s.version, s.supersession_id))

    def is_current(self, claim_id: str) -> bool:
        """"Currently accepted": no supersession event of either kind (plan 3.3)."""
        return not self.supersessions_of(claim_id)

    def is_corrected(self, claim_id: str) -> bool:
        """Excluded from the past state as well: superseded by a correction (plan 3.2)."""
        return any(s.kind is SupersessionKind.CORRECTION for s in self.supersessions_of(claim_id))

    def valid_end(self, claim_id: str) -> str | None:
        """Effective valid end of a claim as known at this version.

        The claim's own end if it has one; otherwise the earliest `valid_end` among the change
        supersessions with the earliest stamp that state one (`effective_change_end`); otherwise
        None (open, or ended at an unknown time).
        """
        claim = self.claims[claim_id]
        if claim.valid_time.end is not None:
            return claim.valid_time.end
        return effective_change_end(self.supersessions_of(claim_id))

    def representatives(self) -> dict[str, str]:
        return representatives(self.equivalences.values(), self.version)

    def entity_labels(self) -> dict[str, str]:
        """Entity ID -> label, for the labels visible at this version (display data only)."""
        return labels_at(self.labels.values(), self.version)

    def display_name(self, entity: str) -> str:
        """The label of `entity` at this version, following merges (`entities.display_name`);
        the ID itself when no label applies."""
        return display_name(entity, self.entity_labels(), self.representatives())


class ClaimStore:
    """The claim graph of one history; `mode` picks the claim serialisation (`rdf11`, `rdf12`)."""

    def __init__(self, history_id: str, mode: rdf.Mode = "rdf11"):
        if mode not in rdf.MODES:
            raise ValueError(f"unknown serialisation mode {mode!r}; expected one of {rdf.MODES}")
        self.history_id = history_id
        self.mode = mode
        self.graph = ox.Store()
        self._changesets: dict[int, ChangeSet] = {}
        self._entries: dict[str, object] = {}
        # Latest claim per proposition, and the claims superseded at the head: the index of the
        # "no repeated current proposition" rule.
        self._current: dict[tuple, str] = {}
        self._superseded: set[str] = set()
        self._labelled: dict[str, str] = {}   # entity ID -> label ID
        self._head = 0

    # -- writing -------------------------------------------------------------------------------

    @property
    def head(self) -> int:
        """The last committed version (0 when nothing is committed)."""
        return self._head

    def commit(self, changeset: ChangeSet, *, validate: bool = False) -> ChangeSet:
        """Append the change set of one version; return the committed change set.

        A retry of the identical change set at a committed version returns the stored one and
        writes nothing. With `validate=True`, the touched claims are also SHACL-validated first.
        """
        if changeset.history_id != self.history_id:
            raise CommitError(f"change set of history {changeset.history_id!r} committed to "
                              f"store of {self.history_id!r}")
        canonical = changeset.canonical()
        if changeset.version <= self._head:
            stored = self._changesets.get(changeset.version)
            if stored is not None and stored == canonical:
                return stored
            raise CommitConflict(
                f"version {changeset.version} is at or below the head {self._head} and "
                + ("differs from the change set committed there" if stored is not None
                   else "was never committed (the graph is append-only)"))
        self._check(canonical)
        if validate:
            report = self.validate(canonical)
            if not report.conforms:
                raise CommitError(f"SHACL validation failed at version {changeset.version}:\n"
                                  f"{report.text}")
        quads = [ox.Quad(t.subject, t.predicate, t.object, ox.DefaultGraph())
                 for t in rdf.changeset_triples(canonical, self.mode)]
        self.graph.extend(quads)
        self._changesets[canonical.version] = canonical
        for entry in canonical.all_entries():
            self._entries[entry.entry_id] = entry
        self._superseded.update(s.claim_id for s in canonical.supersessions)
        self._current.update({c.proposition: c.claim_id for c in canonical.claims})
        self._labelled.update({x.entity: x.label_id for x in canonical.entity_labels})
        self._head = canonical.version
        return canonical

    def _check(self, cs: ChangeSet) -> None:
        new = {e.entry_id: e for e in cs.all_entries()}
        if clash := sorted(new.keys() & self._entries.keys()):
            raise CommitError(f"version {cs.version}: entry IDs already in the store: {clash}")
        known = {**self._entries, **new}

        def need(entry_id: str | None, kind: type, where: str) -> None:
            if entry_id is not None and not isinstance(known.get(entry_id), kind):
                raise CommitError(f"version {cs.version}: {where} names unknown "
                                  f"{kind.__name__} {entry_id!r}")

        for a in cs.attributions:
            need(a.claim_id, Claim, f"attribution {a.attribution_id}")
        for e in cs.evidence_links:
            need(e.claim_id, Claim, f"evidence link {e.evidence_id}")
        for s in cs.supersessions:
            where = f"supersession {s.supersession_id}"
            need(s.claim_id, Claim, where)
            need(s.replacing_claim_id, Claim, where)
            need(s.attribution_id, Attribution, where)
            licence = known[s.attribution_id]
            if licence.claim_id not in {s.claim_id, s.replacing_claim_id}:
                raise CommitError(f"version {cs.version}: {where}: licensing attribution "
                                  f"{s.attribution_id} is on neither the superseded nor the "
                                  f"replacing claim")
            if s.replacing_claim_id is not None:
                old, rep = known[s.claim_id], known[s.replacing_claim_id]
                if (old.subject, old.predicate, old.scope) != (rep.subject, rep.predicate,
                                                               rep.scope):
                    raise CommitError(f"version {cs.version}: {where}: replacing claim "
                                      f"{rep.claim_id} differs in subject, predicate or scope")
        for x in cs.entity_labels:
            if x.entity in self._labelled:
                raise CommitError(f"version {cs.version}: label {x.label_id}: entity "
                                  f"{x.entity!r} already has label {self._labelled[x.entity]} "
                                  f"(labels are written once)")
        superseded = self._superseded | {s.claim_id for s in cs.supersessions}
        current = {p: cid for p, cid in self._current.items() if cid not in superseded}
        for c in cs.claims:
            if c.proposition in current:
                raise CommitError(f"version {cs.version}: claim {c.claim_id} repeats the "
                                  f"proposition of current claim {current[c.proposition]}")
            current[c.proposition] = c.claim_id

    def validate(self, changeset: ChangeSet):
        """SHACL report for the claims the change set touches (and its own entries) only."""
        from grace.context.memory.graph import shacl

        return shacl.validate_changeset(self, changeset)

    # -- reading -------------------------------------------------------------------------------

    def changeset(self, version: int) -> ChangeSet | None:
        return self._changesets.get(version)

    def changesets(self, after: int = 0, upto: int | None = None) -> list[ChangeSet]:
        """Committed change sets with `after < version <= upto`, in version order."""
        upto = self._head if upto is None else upto
        return [self._changesets[v] for v in sorted(self._changesets) if after < v <= upto]

    def versions(self) -> tuple[int, ...]:
        return tuple(sorted(self._changesets))

    def state(self, version: int) -> GraphState:
        """G_version: every entry stamped at most `version`."""
        if version < 0:
            raise ValueError(f"version must be >= 0, got {version}")
        kinds = (Claim, Attribution, EvidenceLink, Supersession, EntityEquivalence, EntityLabel)
        groups: dict[type, dict] = {k: {} for k in kinds}
        for entry in self._entries.values():
            if entry.version <= version:
                groups[type(entry)][entry.entry_id] = entry
        return GraphState(version, *(MappingProxyType(groups[k]) for k in kinds))

    def triples(self, version: int | None = None) -> Iterator[ox.Triple]:
        """The stored triples of the entries stamped at most `version` (all when None)."""
        for cs in self.changesets(upto=version):
            yield from rdf.changeset_triples(cs, self.mode)

    def query(self, sparql: str, version: int | None = None):
        """Run SPARQL on the store; `%r%` is replaced by the integer literal of `version`.

        The standard prefixes of the vocabulary (`g:`, `gp:`, `ge:`, `rdf:`, `prov:` ...) are
        predeclared.
        """
        if CUTOFF in sparql:
            if version is None:
                raise ValueError(f"the query contains {CUTOFF} but no version was given")
            if not isinstance(version, int) or isinstance(version, bool) or version < 0:
                raise ValueError(f"version must be an integer >= 0, got {version!r}")
            sparql = sparql.replace(CUTOFF, str(version))
        return self.graph.query(sparql, prefixes=PREFIXES)

    # -- save and restore ----------------------------------------------------------------------

    def save(self, directory: Path) -> list[Path]:
        """Write `store.json`, `changesets.jsonl` and `graph.nt` into `directory` (must be empty
        or absent). The change sets are the source of truth; `graph.nt` is checked on restore."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            raise FileExistsError(f"snapshot directory is not empty: {directory}")
        meta = {"history_id": self.history_id, "mode": self.mode, "head": self._head,
                "versions": list(self.versions())}
        paths = [directory / name for name in SNAPSHOT_FILES]
        paths[0].write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        paths[1].write_text("".join(cs.to_json() + "\n" for cs in self.changesets()),
                            encoding="utf-8")
        paths[2].write_text(rdf.to_ntriples(self.triples()), encoding="utf-8")
        return paths

    @classmethod
    def restore(cls, directory: Path) -> ClaimStore:
        """Rebuild a store by replaying the saved change sets; fail if the graph differs."""
        directory = Path(directory)
        meta = json.loads((directory / "store.json").read_text(encoding="utf-8"))
        store = cls(meta["history_id"], meta["mode"])
        for line in (directory / "changesets.jsonl").read_text(encoding="utf-8").splitlines():
            store.commit(ChangeSet.from_json(line))
        if store.head != meta["head"] or list(store.versions()) != meta["versions"]:
            raise ValueError(f"{directory}: replayed versions differ from store.json")
        saved = (directory / "graph.nt").read_text(encoding="utf-8")
        if rdf.to_ntriples(store.triples()) != saved:
            raise ValueError(f"{directory}: replayed graph differs from graph.nt")
        return store
