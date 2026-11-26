"""The two trivial strategies of plan 5.4: never invalidate, and full rebuild every turn.

- `NeverInvalidate` reuses a view forever once built ("reusing an old summary"). It still passes
  every change set to the view store, so the invalidation flags of a vocabulary change or an
  entity merge are recorded, but it never acts on them or on anything else.
- `RebuildEveryTurn` rebuilds every resident view in full after every committed change set, at
  write time ("rewriting the summary every time"). It is correct but the most expensive, and is
  the equivalence reference for the rebuild cost.
"""

from __future__ import annotations

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.store import ClaimStore
from grace.context.views.staleness.base import Mark, Strategy
from grace.context.views.staleness.matching import ANSWER
from grace.context.views.store import MaintenanceEvent
from grace.context.views.view import View


class NeverInvalidate(Strategy):
    name = "never_invalidate"

    def _select(self, view: View, flagged: str) -> bool:
        return False


class RebuildEveryTurn(Strategy):
    name = "rebuild_every_turn"

    def _marks(self, changeset: ChangeSet, views: list[View]) -> list[Mark]:
        return [Mark(v.view_id, ANSWER, ("every-turn",)) for v in views]

    def _eager(self, changeset: ChangeSet, graph: ClaimStore, views: list[View]
               ) -> list[MaintenanceEvent]:
        return [self.store.maintain(v.view_id, graph, changeset.version, confirm=False)
                for v in views]
