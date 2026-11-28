"""View store of one history: resident and temporary life cycles, staleness flags, maintenance.

Life cycles (plan 5.4):

- **Resident** views are materialised during ingestion from the template families
  (`materialise`, called after each commit), stored with the history and reused by later reads.
  Staleness detection and maintenance apply only to them.
- **Temporary** views are built inside `question(read_id)` for one question and discarded when it
  ends; they never enter the store, so questions stay independent (plan 6.8). A query marked
  temporary (relative time resolved by `compile.absolutize`) can only define a temporary view.

Maintenance (`maintain`) re-evaluates the view's query at the version read and applies what the
evaluation calls for (`rebuild.classify`): a local rebuild of an answer-stale view, a citation
repair of a citation-stale view (no renderer, so no LLM call), or only a cut-off advance. A view
invalidated by a vocabulary change or an entity merge (`note_changeset`), or marked answer-stale
and maintained with `confirm=False`, is rebuilt in full. Every maintenance appends a
`MaintenanceEvent` with the units rendered, the sentences kept, the rendering-check counts, the
IDs of the model calls made (each also a record in the run's `calls.jsonl`) and the database time.

Seam for the staleness strategies of T019 (`views/staleness/`). Deciding *when* a view is stale
is not done here. A strategy

1. reads, per resident view (`views()`), its `dependencies` (claim patterns with role, local
   filters, aggregation and selection flags), `used_claims()`, `used_attributions()`, `cutoff`
   and `fingerprints` (answers, witnesses, evidence of the query at the cut-off), and receives
   the change set of every commit;
2. marks views with `mark(view_id, answer=..., citation=...)` (push), or re-queries and compares
   fingerprints itself (pull);
3. has marked views maintained with `maintain(view_id, graph, version, read_id=..., confirm=...)`,
   lazily at the next read (`read_id` set: trigger `read`, still ledger category W) or eagerly at
   write time (no `read_id`: trigger `write`). `confirm=True` lets the re-evaluation decide the
   repair (pull, hybrid); `confirm=False` regenerates every sentence of an answer-stale mark (pure
   push, which regenerates over-marked views as well).

A strategy that re-queries first uses `evaluate(view_id, graph, version)` and passes the result to
`maintain(..., evaluation=...)`, so the view's query runs once per check (hooks added by T019).

`note_changeset` must still see every change set, whatever the strategy, because vocabulary
changes and entity merges invalidate every resident view of the history (plan 5.2).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import Vocabulary
from grace.context.pipeline.query.ir import Query
from grace.context.views.rebuild import (
    ADVANCE,
    BUILD,
    CITATION_REPAIR,
    FULL_REBUILD,
    LOCAL_REBUILD,
    Compiled,
    Evaluation,
    classify,
    evaluate,
    full_build,
    local_rebuild,
    repair_citations,
)
from grace.context.views.render import (
    RenderContext,
    Rendered,
    Renderer,
    RenderSpec,
    TemplateRenderer,
    humanise,
)
from grace.context.views.template_families import (
    TemplateFamily,
    ViewConfig,
    candidate_bindings,
    load_families,
)
from grace.context.views.view import Binding, Lifecycle, Sentence, View, ViewError, units

VIEWS_FILE = "views.jsonl"
EVENTS_FILE = "view_events.jsonl"


@dataclass
class Flags:
    """Staleness flags of a resident view, set by a strategy (`mark`) or by invalidation."""

    answer_stale: bool = False
    citation_stale: bool = False
    invalid: str | None = None  # reason of a whole-history invalidation, if any


@dataclass(frozen=True)
class MaintenanceEvent:
    view_id: str
    version: int
    trigger: str
    read_id: str | None
    action: str
    units_rendered: int
    sentences_kept: int
    llm_sentences: int
    failed_sentences: int
    fallback_units: int
    call_ids: tuple[str, ...]
    db_ms: float

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["call_ids"] = list(self.call_ids)
        return record


class ViewStore:
    """The views of one history (see the module docstring)."""

    def __init__(self, history_id: str, renderer: Renderer | None = None, *,
                 config: ViewConfig | None = None,
                 families: Mapping[str, TemplateFamily] | None = None,
                 vocabulary: Vocabulary | None = None):
        self.history_id = history_id
        self.config = config or ViewConfig()
        self.families = dict(families) if families is not None else load_families(
            self.config.families)
        self.renderer = renderer or TemplateRenderer()
        self.vocabulary = vocabulary
        self._views: dict[str, View] = {}
        self._flags: dict[str, Flags] = {}
        self._compiled: dict[tuple[str, str], Compiled] = {}
        self._vocabulary_version = vocabulary.version if vocabulary else None
        self.events: list[MaintenanceEvent] = []

    # -- reading -------------------------------------------------------------------------------

    def views(self) -> list[View]:
        """The resident views, by view ID."""
        return [self._views[k] for k in sorted(self._views)]

    def get(self, view_id: str) -> View:
        return self._views[view_id]

    def flags(self, view_id: str) -> Flags:
        return self._flags[view_id]

    def __contains__(self, view_id: object) -> bool:
        return view_id in self._views

    def __len__(self) -> int:
        return len(self._views)

    # -- specs and evaluation ------------------------------------------------------------------

    def spec(self, view: View) -> RenderSpec:
        b = view.binding
        if b is None:
            return RenderSpec(view.title, view.columns, view.is_count)
        family = self.families[b.family]
        return RenderSpec(view.title, view.columns, view.is_count, b.subject, b.predicate,
                          family.sentence)

    def _compile(self, view_id: str, query: Query, mode: str) -> Compiled:
        key = (view_id, mode)
        if key not in self._compiled:
            self._compiled[key] = Compiled.of(query, mode)
        return self._compiled[key]

    def bind(self, binding: Binding) -> tuple[Query, str]:
        family = self.families[binding.family]
        query = family.bind(binding, self.config)
        title = family.title.format(subject=binding.subject,
                                    predicate=humanise(binding.predicate or ""))
        return query, title

    def _context(self, version: int, read_id: str | None):
        return RenderContext("read" if read_id else "write", self.history_id, version, read_id)

    def _make(self, view_id: str, binding: Binding | None, title: str, query: Query,
              evaluation: Evaluation, lifecycle: Lifecycle, sentences=()) -> View:
        r = evaluation.result
        return View(view_id, self.history_id, lifecycle, binding, title, query, r.cutoff,
                    r.variables, r.is_count, evaluation.rows, tuple(sentences),
                    r.fingerprints())

    def _render_new(self, view: View, version: int, read_id: str | None
                    ) -> tuple[View, Rendered, int]:
        sentences, rendered, n = full_build(self.spec(view), view.rows, self.renderer,
                                            self._context(version, read_id))
        return _with(view, sentences), rendered, n

    # -- resident life cycle -------------------------------------------------------------------

    def build(self, binding: Binding, graph: ClaimStore, version: int | None = None, *,
              read_id: str | None = None) -> View:
        """Build the resident view of `binding` at `version` from scratch and store it.

        Replaces a stored view of the same binding (a full rebuild; also the reference that local
        rebuilds are tested against).
        """
        version = graph.head if version is None else version
        query, title = self.bind(binding)
        start = time.perf_counter()
        evaluation = evaluate(self._compile(binding.view_id, query, graph.mode), graph, version)
        db_ms = (time.perf_counter() - start) * 1000
        return self._store_built(binding, title, query, evaluation, version, read_id, db_ms,
                                 BUILD)

    def _store_built(self, binding, title, query, evaluation, version, read_id, db_ms, action):
        if query.temporary:
            raise ViewError(f"{binding.view_id}: a temporary query cannot define a resident view")
        skeleton = self._make(binding.view_id, binding, title, query, evaluation,
                              Lifecycle.RESIDENT, _placeholder(evaluation.rows))
        view, rendered, n = self._render_new(skeleton, version, read_id)
        self._views[view.view_id] = view
        self._flags[view.view_id] = Flags()
        self._event(view.view_id, version, read_id, action, n, 0, rendered, db_ms)
        return view

    def materialise(self, graph: ClaimStore, version: int | None = None) -> list[str]:
        """Instantiate every binding whose query reaches its threshold at `version` (write time).

        Returns the IDs of the views instantiated now; existing views are left as they are.
        """
        version = graph.head if version is None else version
        state = graph.state(version)
        new = []
        for binding in candidate_bindings(state, self.families, self.config, self.vocabulary):
            if binding.view_id in self._views:
                continue
            query, title = self.bind(binding)
            start = time.perf_counter()
            evaluation = evaluate(self._compile(binding.view_id, query, graph.mode), graph,
                                  version)
            db_ms = (time.perf_counter() - start) * 1000
            claims = {c for r in evaluation.rows for w in r.witnesses for c in w.claims}
            if len(claims) < self.config.threshold(binding.family):
                continue
            self._store_built(binding, title, query, evaluation, version, None, db_ms, BUILD)
            new.append(binding.view_id)
        return new

    def mark(self, view_id: str, *, answer: bool = False, citation: bool = False) -> None:
        flags = self._flags[view_id]
        flags.answer_stale |= answer
        flags.citation_stale |= citation

    def invalidate_all(self, reason: str) -> None:
        for flags in self._flags.values():
            flags.invalid = reason

    def note_changeset(self, changeset: ChangeSet) -> bool:
        """Invalidate every resident view on an entity merge or a vocabulary version change
        (plan 5.2). Returns whether it did."""
        if changeset.history_id != self.history_id:
            raise ViewError(f"change set of {changeset.history_id} given to the view store of "
                            f"{self.history_id}")
        reasons = []
        if changeset.entity_merges:
            reasons.append(f"entity merge at version {changeset.version}")
        new = changeset.vocabulary_version
        if new is not None:
            if self._vocabulary_version is not None and new != self._vocabulary_version:
                reasons.append(f"vocabulary {self._vocabulary_version} -> {new} at version "
                               f"{changeset.version}")
            self._vocabulary_version = new
        if reasons:
            self.invalidate_all("; ".join(reasons))
        return bool(reasons)

    def evaluate(self, view_id: str, graph: ClaimStore, version: int | None = None
                 ) -> tuple[Evaluation, float]:
        """Re-query a resident view at `version` without changing it; returns the evaluation and
        the database time in ms (hook for read-time re-query, T019)."""
        version = graph.head if version is None else version
        view = self._views[view_id]
        start = time.perf_counter()
        evaluation = evaluate(self._compile(view_id, view.query, graph.mode), graph, version)
        return evaluation, (time.perf_counter() - start) * 1000

    def maintain(self, view_id: str, graph: ClaimStore, version: int | None = None, *,
                 read_id: str | None = None, confirm: bool = True,
                 evaluation: Evaluation | None = None) -> MaintenanceEvent:
        """Re-evaluate a resident view at `version` and repair it (module docstring).

        `evaluation`: the result of `evaluate(view_id, graph, version)` already obtained by a
        strategy's fingerprint check; it is reused, and the event then books no database time
        (the strategy has booked it to its check).
        """
        version = graph.head if version is None else version
        view, flags = self._views[view_id], self._flags[view_id]
        if version < view.cutoff:
            raise ViewError(f"view {view_id} has cut-off {view.cutoff}; cannot maintain it at "
                            f"{version}")
        if evaluation is None:
            start = time.perf_counter()
            evaluation = evaluate(self._compile(view_id, view.query, graph.mode), graph,
                                  version)
            db_ms = (time.perf_counter() - start) * 1000
        else:
            expected = version if view.query.at.known is None else view.query.at.known
            if evaluation.result.cutoff != expected:
                raise ViewError(f"view {view_id}: evaluation at cut-off "
                                f"{evaluation.result.cutoff} given for a maintenance at "
                                f"{expected}")
            db_ms = 0.0
        fresh = self._make(view_id, view.binding, view.title, view.query, evaluation,
                           Lifecycle.RESIDENT, _placeholder(evaluation.rows))
        context = self._context(version, read_id)
        rendered, kept, n = Rendered(()), 0, 0
        if flags.invalid or (flags.answer_stale and not confirm):
            action = FULL_REBUILD
            new, rendered, n = self._render_new(fresh, version, read_id)
        else:
            action = classify(view, evaluation)
            if action == LOCAL_REBUILD:
                sentences, rendered, kept, n = local_rebuild(view, self.spec(view),
                                                             evaluation.rows, self.renderer,
                                                             context)
            elif action == CITATION_REPAIR:
                sentences = repair_citations(view, evaluation.rows)
                kept = len(sentences)
            else:
                sentences = view.sentences
                kept = len(sentences)
            new = _with(fresh, sentences)
        self._views[view_id] = new
        self._flags[view_id] = Flags()
        return self._event(view_id, version, read_id, action, n, kept, rendered, db_ms)

    def _event(self, view_id, version, read_id, action, units_rendered, kept, rendered: Rendered,
               db_ms) -> MaintenanceEvent:
        event = MaintenanceEvent(view_id, version, "read" if read_id else "write", read_id,
                                 action, units_rendered, kept, rendered.llm_sentences,
                                 rendered.failed_sentences, rendered.fallback_units,
                                 rendered.call_ids, round(db_ms, 3))
        self.events.append(event)
        return event

    # -- temporary life cycle ------------------------------------------------------------------

    @contextmanager
    def question(self, read_id: str) -> Iterator[TemporaryViews]:
        """Temporary views of one question; all are discarded when the block ends."""
        temporary = TemporaryViews(self, read_id)
        try:
            yield temporary
        finally:
            temporary.close()

    # -- save and restore ----------------------------------------------------------------------

    def save(self, directory: Path) -> list[Path]:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        views = directory / VIEWS_FILE
        with views.open("w", encoding="utf-8") as handle:
            for view in self.views():
                record = {"view": view.to_record(),
                          "flags": asdict(self._flags[view.view_id]),
                          "vocabulary_version": self._vocabulary_version}
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        events = directory / EVENTS_FILE
        with events.open("w", encoding="utf-8") as handle:
            for event in self.events:
                handle.write(json.dumps(event.to_record(), ensure_ascii=False) + "\n")
        return [views, events]

    @classmethod
    def restore(cls, directory: Path, history_id: str, renderer: Renderer | None = None, *,
                config: ViewConfig | None = None,
                families: Mapping[str, TemplateFamily] | None = None,
                vocabulary: Vocabulary | None = None) -> ViewStore:
        store = cls(history_id, renderer, config=config, families=families,
                    vocabulary=vocabulary)
        directory = Path(directory)
        # JSON Lines are split on "\n" only: str.splitlines() also splits on U+2028
        # and U+0085, which json.dumps(ensure_ascii=False) leaves inside strings.
        text = (directory / VIEWS_FILE).read_text(encoding="utf-8")
        for line in filter(None, text.split("\n")):
            record = json.loads(line)
            view = View.from_record(record["view"])
            if view.history_id != history_id or view.lifecycle is not Lifecycle.RESIDENT:
                raise ViewError(f"{directory}: view {view.view_id} does not belong here")
            store._views[view.view_id] = view
            store._flags[view.view_id] = Flags(**record["flags"])
            store._vocabulary_version = record["vocabulary_version"]
        events = directory / EVENTS_FILE
        if events.exists():
            # JSON Lines are split on "\n" only: str.splitlines() also splits on U+2028
            # and U+0085, which json.dumps(ensure_ascii=False) leaves inside strings.
            text = events.read_text(encoding="utf-8")
            for line in filter(None, text.split("\n")):
                record = json.loads(line)
                record["call_ids"] = tuple(record["call_ids"])
                store.events.append(MaintenanceEvent(**record))
        return store


class TemporaryViews:
    """Views of one question; never stored, never reused, unusable once the question ends."""

    def __init__(self, store: ViewStore, read_id: str):
        self.store, self.read_id = store, read_id
        self._open = True
        self.built: list[View] = []

    def build(self, query: Query, graph: ClaimStore, version: int | None = None, *,
              title: str | None = None) -> View:
        if not self._open:
            raise ViewError(f"the question {self.read_id} has ended; its views are discarded")
        version = graph.head if version is None else version
        view_id = f"temporary:{self.read_id}:{len(self.built)}"
        start = time.perf_counter()
        evaluation = evaluate(Compiled.of(query, graph.mode), graph, version)
        db_ms = (time.perf_counter() - start) * 1000
        skeleton = self.store._make(view_id, None, title or "query result", query, evaluation,
                                    Lifecycle.TEMPORARY, _placeholder(evaluation.rows))
        view, rendered, n = self.store._render_new(skeleton, version, self.read_id)
        self.store._event(view_id, version, self.read_id, BUILD, n, 0, rendered, db_ms)
        self.built.append(view)
        return view

    def close(self) -> None:
        self._open = False
        self.built.clear()


def _placeholder(rows):
    """Sentences that satisfy the view invariant until the real ones are attached."""
    return tuple(Sentence("", u) for u in units(rows))


def _with(view: View, sentences) -> View:
    return replace(view, sentences=tuple(sentences))


__all__ = ["ADVANCE", "BUILD", "CITATION_REPAIR", "FULL_REBUILD", "LOCAL_REBUILD", "Flags",
           "MaintenanceEvent", "TemporaryViews", "ViewStore"]
