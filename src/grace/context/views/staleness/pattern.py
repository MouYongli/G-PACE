"""Push strategies on dependency patterns (plan 5.4): predicate level; claim-pattern push,
optionally with local filters.

- `PredicateLevel` marks a view on any write to one of its predicates: a new claim with that
  predicate, or an attribution, supersession or evidence link on such a claim. A pattern with a
  predicate variable depends on every predicate. Evidence links mark citation level, everything
  else answer level. "Coarse source keys"; it over-marks and rebuilds too much.
- `ClaimPatternPush` matches every change set against the view's claim patterns at write time
  (`matching.triggers`), with attribution constraints and, with `local_filters` (default), the
  local filters of each pattern; `local_filters: false` is the "claim pattern" rung, `true` the
  "claim pattern with local filters" rung of plan 3.4's ladder. Marked views are rebuilt at the
  next read without confirmation, so an over-marked view is regenerated as well (an answer mark
  regenerates every sentence).

Both are sound (no false negatives against re-query, plan 3.4 proposition), provided the
vocabulary and entity identities are unchanged; vocabulary changes and entity merges invalidate
every view through the store.
"""

from __future__ import annotations

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.pipeline.query.ir import Var
from grace.context.views.staleness.base import Mark, Strategy, marks_from
from grace.context.views.staleness.matching import ANSWER, CITATION, Trigger, claim_of, triggers
from grace.context.views.view import View


def view_predicates(view: View) -> frozenset[str] | None:
    """The predicates a view depends on; None if a pattern has a predicate variable."""
    predicates = [dp.pattern.predicate for dp in view.dependencies]
    if any(isinstance(p, Var) for p in predicates):
        return None
    return frozenset(predicates)


class PredicateLevel(Strategy):
    name = "predicate_level"

    def _marks(self, changeset: ChangeSet, views: list[View]) -> list[Mark]:
        entries = []
        for kind, items, level in (("claim", changeset.claims, ANSWER),
                                   ("attribution", changeset.attributions, ANSWER),
                                   ("supersession", changeset.supersessions, ANSWER),
                                   ("evidence", changeset.evidence_links, CITATION)):
            for e in items:
                c = claim_of(e, self.index)
                if c is not None:
                    entries.append((kind, e.entry_id, level, c.predicate))
        out = []
        for v in views:
            predicates = view_predicates(v)
            found = [Trigger(level, eid, kind, -1, "predicate")
                     for kind, eid, level, p in entries if predicates is None or p in predicates]
            out += marks_from(v.view_id, found)
        return out


class ClaimPatternPush(Strategy):
    name = "claim_pattern_push"
    option_names = ("local_filters",)

    def _marks(self, changeset: ChangeSet, views: list[View]) -> list[Mark]:
        options = self.matching()
        return [m for v in views for m in marks_from(
            v.view_id, triggers(v.dependencies, changeset, self.index, options))]
