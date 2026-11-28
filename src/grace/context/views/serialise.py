"""Template-serialisation variant of the views (plan 7.2; ablation C template arm; T027).

"GRACE's template-serialisation variant: the query re-run at every read, results filled into
fixed sentence patterns, no rendering and no caching" (plan 7.2). It stands beside the view store
(`store.py`), which keeps resident views across reads and maintains them: `serialise_at_read`
instead builds the views of every binding that reaches its threshold at the read version on a
fresh store with the `TemplateRenderer` (fixed sentence patterns, no model call) and returns them;
nothing is kept, so there is no staleness to detect and no view to maintain, and every read pays
the queries again (database time is in each view's evaluation, recorded by the store's events,
which are returned with the views).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import Vocabulary
from grace.context.pipeline.query.grammar import to_text
from grace.context.views.render import TemplateRenderer
from grace.context.views.store import MaintenanceEvent, ViewStore
from grace.context.views.template_families import (
    TemplateFamily,
    ViewConfig,
    candidate_bindings,
    load_families,
)
from grace.context.views.view import View


@dataclass(frozen=True)
class Serialised:
    version: int
    views: tuple[View, ...]
    events: tuple[MaintenanceEvent, ...]   # one build event per view, with its database time


def serialise_at_read(graph: ClaimStore, version: int, *, config: ViewConfig | None = None,
                      families: Mapping[str, TemplateFamily] | None = None,
                      vocabulary: Vocabulary | None = None) -> Serialised:
    """Every instantiated view at `version`, template-serialised; nothing is cached."""
    store = ViewStore(graph.history_id, TemplateRenderer(), config=config, families=families,
                      vocabulary=vocabulary)
    ids = store.materialise(graph, version)
    return Serialised(version, tuple(store.get(i) for i in ids), tuple(store.events))


class SerialisedViews:
    """The view component of the template-serialisation variant (the engine's `views` slot, the
    interface of `engine.Views`): nothing is stored at write; at a read, the plan's query is
    matched against the bindings the graph instantiates at the read version, and the matching
    view is evaluated and template-serialised on a fresh store, then dropped. No staleness
    marks, no maintenance, no model call. A view counts only if it reaches the instantiation
    threshold, as a resident view would."""

    def __init__(self, history_id: str, config: ViewConfig, vocabulary: Vocabulary | None,
                 families: Mapping[str, TemplateFamily] | None = None):
        self.history_id, self.config, self.vocabulary = history_id, config, vocabulary
        self.families = dict(families) if families is not None else load_families(
            config.families)
        self._graph: ClaimStore | None = None
        self._version: int | None = None
        self._read_id: str | None = None
        self.events: list[MaintenanceEvent] = []   # build events of the latest read

    def on_commit(self, changeset, graph: ClaimStore):
        return [], []

    def on_read(self, graph: ClaimStore, version: int, read_id: str):
        self._graph, self._version, self._read_id = graph, version, read_id
        self.events = []
        return [], []

    def hit(self, plan) -> View | None:
        if self._graph is None or not plan.view_eligible or plan.query is None:
            return None
        store = ViewStore(self.history_id, TemplateRenderer(), config=self.config,
                          families=self.families, vocabulary=self.vocabulary)
        target = to_text(plan.query)
        state = self._graph.state(self._version)
        for binding in candidate_bindings(state, self.families, self.config, self.vocabulary):
            query, _ = store.bind(binding)
            if to_text(query) != target:
                continue
            view = store.build(binding, self._graph, self._version, read_id=self._read_id)
            self.events += store.events
            claims = {c for r in view.rows for w in r.witnesses for c in w.claims}
            return view if len(claims) >= self.config.threshold(binding.family) else None
        return None

    def save(self, directory: Path) -> list[Path]:
        return []

    def restore(self, directory: Path, graph: ClaimStore) -> None:
        pass


def serialised_views(*, writer=None, client=None, view_config: ViewConfig | None = None,
                     **options):
    """Component factory (`config/registry.py`, name `serialised-views`) for the engine's
    `views` slot: `make(history, vocabulary)` gives one `SerialisedViews` per history."""
    if options:
        raise TypeError(f"serialised-views takes no options, got {sorted(options)}")
    config = view_config or ViewConfig()

    def make(history, vocabulary) -> SerialisedViews:
        return SerialisedViews(history.history_id, config, vocabulary)
    return make
