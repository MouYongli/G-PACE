"""Fingerprint strategies (plan 5.4): read-time re-query (pull); push filtering with read-time
confirmation (hybrid).

- `Requery` keeps no write-side state. At every read it re-runs the query of every view the read
  may use and compares the answer, witness and evidence fingerprints with those stored at the
  view's cut-off; the store then regenerates only changed rows (answer fingerprint changed),
  patches citations (witness or evidence fingerprint changed) or only advances the cut-off. Exact
  with respect to the claim graph: the reference the other strategies are scored against.
- `PushConfirm` marks views at write time exactly as `ClaimPatternPush` and, at a read, re-queries
  only the marked views and repairs them after confirmation. It spends the same LLM tokens as
  pull and differs only in database cost (fewer re-queries, plus pattern matching on writes).

The re-query is booked as `check_db_ms` of the read record; the maintenance reuses its evaluation
(`ViewStore.maintain(evaluation=...)`), so a view's query runs once per check.
"""

from __future__ import annotations

from grace.context.views.staleness.base import Strategy
from grace.context.views.staleness.pattern import ClaimPatternPush


class Requery(Strategy):
    name = "requery"
    requery = True
    confirm = True
    select_all = True


class PushConfirm(ClaimPatternPush):
    name = "push_confirm"
    requery = True
    confirm = True
