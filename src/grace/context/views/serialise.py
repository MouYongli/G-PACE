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

from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import Vocabulary
from grace.context.views.render import TemplateRenderer
from grace.context.views.store import MaintenanceEvent, ViewStore
from grace.context.views.template_families import TemplateFamily, ViewConfig
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
