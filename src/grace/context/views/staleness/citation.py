"""Citation-based strategies (plan 5.4): used claims only; used claims plus the claim patterns
inside negation and aggregation.

Both watch the entries a view has consumed: its used claims (the claims of its witnesses at its
cut-off). A supersession event pointing to a used claim marks the view answer-stale: plan 5.4
defines the arm as "invalidate when a used claim is superseded", and plan 3.4 says a citation-based
dependency sees "the insertions that point at entries the view has already consumed (supersession
events)". With `watch_mentions: true` (a variant, off by default) a new attribution or evidence
link on a used claim also marks the view citation-stale, which catches repeated mentions (C6);
since every mark leads to a re-evaluation in `ViewStore.maintain`, the variant also repairs
negation hits that happen to be stances on a used claim (an acceptance of a pending offer), so it
no longer shows the weakness the plan attributes to the arm.

`UsedClaimsPlusPatterns` also marks a view answer-stale when a write matches a claim pattern
inside its negated condition or a pattern it aggregates over (the strongest form of
citation-based dependency, plan 3.4); matching follows `matching.py`, with local filters and
attribution constraints unless switched off.

Neither is on the ladder of sound strategies: both miss new matches of views without aggregation,
and used claims only also misses negation hits and changes of aggregate members (plan 3.4,
"Observation"). The tests show these misses on the worked example.
"""

from __future__ import annotations

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.views.dependencies import NEGATED
from grace.context.views.staleness.base import Mark, Strategy, marks_from
from grace.context.views.staleness.matching import ANSWER, CITATION, Trigger, triggers
from grace.context.views.view import View


def used_claim_triggers(view: View, cs: ChangeSet, watch_mentions: bool) -> list[Trigger]:
    used = view.used_claims()
    out = [Trigger(ANSWER, s.supersession_id, "supersession", -1, "used")
           for s in cs.supersessions if s.claim_id in used]
    if watch_mentions:
        out += [Trigger(CITATION, a.attribution_id, "attribution", -1, "used")
                for a in cs.attributions if a.claim_id in used]
        out += [Trigger(CITATION, e.evidence_id, "evidence", -1, "used")
                for e in cs.evidence_links if e.claim_id in used]
    return out


class UsedClaims(Strategy):
    name = "used_claims"
    option_names = ("watch_mentions",)

    def _marks(self, changeset: ChangeSet, views: list[View]) -> list[Mark]:
        watch = self.options.get("watch_mentions", False)
        return [m for v in views
                for m in marks_from(v.view_id, used_claim_triggers(v, changeset, watch))]


class UsedClaimsPlusPatterns(Strategy):
    name = "used_claims_patterns"
    option_names = ("watch_mentions", "local_filters", "attribution")

    def _marks(self, changeset: ChangeSet, views: list[View]) -> list[Mark]:
        watch = self.options.get("watch_mentions", False)
        out = []
        for v in views:
            found = used_claim_triggers(v, changeset, watch)
            watched = [dp.role == NEGATED or dp.aggregated for dp in v.dependencies]
            found += [t for t in triggers(v.dependencies, changeset, self.index,
                                          self.matching()) if watched[t.pattern]]
            out += marks_from(v.view_id, found)
        return out
