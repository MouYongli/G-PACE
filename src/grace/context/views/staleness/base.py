"""Strategy interface: receives change sets at write time, decides at read time (plan 5.4).

A strategy works on the resident views of one `ViewStore` over one claim graph, through the seam
T018 documented in `views/store.py`:

- `write(changeset, graph)` is called once per committed change set, in version order, after the
  commit (and after `ViewStore.materialise`). It always passes the change set to
  `ViewStore.note_changeset` first, so a vocabulary change or an entity merge invalidates every
  resident view whatever the strategy (plan 5.2); an invalidated view is rebuilt in full at its
  next maintenance. It then sets the strategy's dirty marks (`ViewStore.mark`) and, for "rebuild
  every turn", maintains every view at once.
- `read(graph, version, read_id=...)` is called before a read uses the views. It selects the views
  the strategy considers stale, re-queries them first if the strategy confirms by fingerprints,
  and has them maintained lazily (`ViewStore.maintain`, trigger `read`, still ledger category W).
  A view that is not selected keeps its cut-off: a missed staleness is scored against that old
  cut-off later (docs/research/change-sequences.md, section 6.3).

Views whose query fixes its cut-off (`AT(known=r0)`) never go stale (time-travel stability, plan
3.3) and are skipped by every strategy.

**Logs.** Every call returns a record and appends it to `log`: per write the dirty marks with the
entries that triggered them and the matching time (`match_ms`, write-side CPU, no database); per
read and view whether it was flagged, whether it was re-queried with the database time of that
check (`check_db_ms`), the fingerprint verdict, and the maintenance action with its own database
time (`maintain_db_ms`), units rendered and model call IDs. `StrategyLog.summary()` totals marks,
rebuilds, citation repairs and the three times separately.

`fingerprint_staleness` is the exact reference: read-time re-query compared by the answer,
witness and evidence fingerprints (plan 3.4). Misses and over-marking of every strategy are counted
against it.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.store import ClaimStore
from grace.context.views.rebuild import CITATION_REPAIR, FULL_REBUILD, LOCAL_REBUILD, Evaluation
from grace.context.views.staleness.matching import ANSWER, CITATION, Index, Options, Trigger
from grace.context.views.store import MaintenanceEvent, ViewStore
from grace.context.views.view import View

NONE = "none"
REBUILDS = (FULL_REBUILD, LOCAL_REBUILD)


class StrategyError(ValueError):
    """A strategy was misconfigured or fed change sets out of order."""


# ---------------------------------------------------------------------------------------------
# Fingerprints: the exact reference


@dataclass(frozen=True)
class Staleness:
    answer: bool = False
    citation: bool = False

    @property
    def stale(self) -> bool:
        return self.answer or self.citation

    @property
    def level(self) -> str:
        return ANSWER if self.answer else CITATION if self.citation else NONE


def compare(view: View, evaluation: Evaluation) -> Staleness:
    """Two-level staleness of `view` (cut-off r0) given its re-query at r (plan 3.4)."""
    old, new = view.fingerprints, evaluation.result.fingerprints()
    if old.get("answers") != new["answers"]:
        return Staleness(answer=True)
    return Staleness(citation=any(old.get(k) != new[k] for k in ("witnesses", "evidence")))


def fixed_cutoff(view: View) -> bool:
    return view.query.at.known is not None


def fingerprint_staleness(store: ViewStore, view_id: str, graph: ClaimStore,
                          version: int | None = None) -> Staleness:
    """The exact reference for a resident view at `version` (does not change the view)."""
    view = store.get(view_id)
    if fixed_cutoff(view):
        return Staleness()
    evaluation, _ = store.evaluate(view_id, graph, version)
    return compare(view, evaluation)


# ---------------------------------------------------------------------------------------------
# Records


@dataclass(frozen=True)
class Mark:
    view_id: str
    level: str                  # answer or citation
    triggers: tuple[str, ...]   # "<kind>:<entry id>@<pattern index>/<role>" or a reason

    def to_record(self) -> dict[str, Any]:
        return {"view_id": self.view_id, "level": self.level, "triggers": list(self.triggers)}


def _event_record(event: MaintenanceEvent) -> dict[str, Any]:
    return event.to_record()


@dataclass
class WriteRecord:
    version: int
    invalidated: bool
    marks: list[Mark] = field(default_factory=list)
    match_ms: float = 0.0
    maintenance: list[MaintenanceEvent] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {"kind": "write", "version": self.version, "invalidated": self.invalidated,
                "marks": [m.to_record() for m in self.marks],
                "match_ms": round(self.match_ms, 3),
                "maintenance": [_event_record(e) for e in self.maintenance]}


@dataclass(frozen=True)
class ViewCheck:
    view_id: str
    cutoff: int                 # the view's cut-off before the read
    flagged: str                # answer, citation, invalid or none (the store's flags)
    checked: bool               # re-queried for fingerprints
    fingerprint: str | None     # answer, citation, none; None when not re-queried
    check_db_ms: float
    action: str | None          # maintenance action, None when the view was left as it is
    maintain_db_ms: float
    units_rendered: int
    call_ids: tuple[str, ...]

    @property
    def maintained(self) -> bool:
        return self.action is not None

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["call_ids"] = list(self.call_ids)
        record["check_db_ms"] = round(self.check_db_ms, 3)
        return record


@dataclass
class ReadRecord:
    version: int
    read_id: str | None
    checks: list[ViewCheck] = field(default_factory=list)

    def maintained(self) -> set[str]:
        return {c.view_id for c in self.checks if c.maintained}

    def to_record(self) -> dict[str, Any]:
        return {"kind": "read", "version": self.version, "read_id": self.read_id,
                "checks": [c.to_record() for c in self.checks]}


@dataclass
class StrategyLog:
    strategy: str
    options: Mapping[str, Any]
    records: list[WriteRecord | ReadRecord] = field(default_factory=list)

    def writes(self) -> list[WriteRecord]:
        return [r for r in self.records if isinstance(r, WriteRecord)]

    def reads(self) -> list[ReadRecord]:
        return [r for r in self.records if isinstance(r, ReadRecord)]

    def summary(self) -> dict[str, Any]:
        """Totals; dirty marks, rebuilds and the three times are kept apart."""
        marks = Counter(m.level for w in self.writes() for m in w.marks)
        events = [e for w in self.writes() for e in w.maintenance]
        checks = [c for r in self.reads() for c in r.checks]
        actions = Counter(e.action for e in events) + Counter(
            c.action for c in checks if c.action is not None)
        return {
            "strategy": self.strategy, "options": dict(self.options),
            "writes": len(self.writes()), "reads": len(self.reads()),
            "invalidations": sum(w.invalidated for w in self.writes()),
            "marks_answer": marks[ANSWER], "marks_citation": marks[CITATION],
            "checks": sum(c.checked for c in checks),
            "maintenance": dict(sorted(actions.items())),
            "rebuilds": sum(actions[a] for a in REBUILDS),
            "citation_repairs": actions[CITATION_REPAIR],
            "units_rendered": sum(e.units_rendered for e in events)
            + sum(c.units_rendered for c in checks),
            "llm_calls": sum(len(e.call_ids) for e in events)
            + sum(len(c.call_ids) for c in checks),
            "match_ms": round(sum(w.match_ms for w in self.writes()), 3),
            "check_db_ms": round(sum(c.check_db_ms for c in checks), 3),
            "maintain_db_ms": round(sum(e.db_ms for e in events)
                                    + sum(c.maintain_db_ms for c in checks), 3),
        }

    def save(self, path: Path) -> Path:
        """One JSON line per record, then the summary as the last line."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for record in self.records:
                handle.write(json.dumps(record.to_record(), ensure_ascii=False) + "\n")
            handle.write(json.dumps({"kind": "summary", **self.summary()}) + "\n")
        return path


# ---------------------------------------------------------------------------------------------
# Strategy


class Strategy:
    """Base class; subclasses set the class attributes and override `_marks` or `_eager`.

    - `requery`: re-query a selected view and compare fingerprints before maintaining it;
    - `confirm`: let the re-evaluation decide the repair (`ViewStore.maintain(confirm=True)`);
      without it an answer mark regenerates every sentence (pure push);
    - `select_all`: select every view at a read (pull), not only flagged ones.
    """

    name: ClassVar[str] = "base"
    requery: ClassVar[bool] = False
    confirm: ClassVar[bool] = False
    select_all: ClassVar[bool] = False
    option_names: ClassVar[tuple[str, ...]] = ()

    def __init__(self, store: ViewStore, **options: Any):
        if unknown := sorted(set(options) - set(self.option_names)):
            raise StrategyError(f"strategy {self.name}: unknown options {unknown}; expected "
                                f"{list(self.option_names)}")
        self.store = store
        self.options = dict(options)
        self.index = Index()
        self.log = StrategyLog(self.name, self.options)

    def matching(self) -> Options:
        return Options(attribution=self.options.get("attribution", True),
                       local_filters=self.options.get("local_filters", True))

    def prime(self, changesets: Iterable[ChangeSet]) -> None:
        """Index change sets committed before the strategy started (no marks, no log)."""
        for cs in changesets:
            self.index.add(cs)

    # -- write side ----------------------------------------------------------------------------

    def write(self, changeset: ChangeSet, graph: ClaimStore) -> WriteRecord:
        if graph.head < changeset.version:
            raise StrategyError(f"change set {changeset.version} is not committed (head "
                                f"{graph.head}); call write after the commit")
        invalidated = self.store.note_changeset(changeset)
        self.index.add(changeset)
        views = [v for v in self.store.views()
                 if v.cutoff < changeset.version and not fixed_cutoff(v)]
        start = time.perf_counter()
        marks = self._marks(changeset, views)
        match_ms = (time.perf_counter() - start) * 1000
        for m in marks:
            self.store.mark(m.view_id, answer=m.level == ANSWER, citation=m.level == CITATION)
        record = WriteRecord(changeset.version, invalidated, marks, match_ms)
        record.maintenance = self._eager(changeset, graph, views)
        self.log.records.append(record)
        return record

    def _marks(self, changeset: ChangeSet, views: list[View]) -> list[Mark]:
        return []

    def _eager(self, changeset: ChangeSet, graph: ClaimStore, views: list[View]
               ) -> list[MaintenanceEvent]:
        return []

    # -- read side -----------------------------------------------------------------------------

    def read(self, graph: ClaimStore, version: int | None = None, *, read_id: str | None,
             view_ids: Iterable[str] | None = None) -> ReadRecord:
        """Check and repair the views a read may use (all resident views by default)."""
        version = graph.head if version is None else version
        ids = sorted(view_ids) if view_ids is not None else [v.view_id
                                                             for v in self.store.views()]
        record = ReadRecord(version, read_id)
        for view_id in ids:
            record.checks.append(self._check(view_id, graph, version, read_id))
        self.log.records.append(record)
        return record

    def _flagged(self, view_id: str) -> str:
        flags = self.store.flags(view_id)
        return ("invalid" if flags.invalid else ANSWER if flags.answer_stale
                else CITATION if flags.citation_stale else NONE)

    def _select(self, view: View, flagged: str) -> bool:
        return self.select_all or flagged != NONE

    def _check(self, view_id: str, graph: ClaimStore, version: int, read_id: str | None
               ) -> ViewCheck:
        view = self.store.get(view_id)
        flagged = self._flagged(view_id)
        if fixed_cutoff(view) or not self._select(view, flagged):
            return ViewCheck(view_id, view.cutoff, flagged, False, None, 0.0, None, 0.0, 0, ())
        evaluation, check_ms, verdict = None, 0.0, None
        if self.requery:
            evaluation, check_ms = self.store.evaluate(view_id, graph, version)
            verdict = compare(view, evaluation).level
        event = self.store.maintain(view_id, graph, version, read_id=read_id,
                                    confirm=self.confirm, evaluation=evaluation)
        return ViewCheck(view_id, view.cutoff, flagged, self.requery, verdict, check_ms,
                         event.action, event.db_ms, event.units_rendered, event.call_ids)


def trigger_names(triggers: Iterable[Trigger]) -> tuple[str, ...]:
    return tuple(sorted({f"{t.kind}:{t.entry}@{t.pattern}/{t.role}" for t in triggers}))


def marks_from(view_id: str, triggers: list[Trigger]) -> list[Mark]:
    """At most one mark per view: answer if any trigger is answer-level, else citation."""
    if not triggers:
        return []
    level = ANSWER if any(t.level == ANSWER for t in triggers) else CITATION
    return [Mark(view_id, level, trigger_names(triggers))]
