"""One bounded expansion when variables stay open (plan 5.5, step 4; plan 5.6 "Constraints").

After selection, if some demand variables are still uncovered, the assembler makes at most one
expansion per read:

1. **Expand a summary into raw text.** If the raw text of a candidate summary (kind `summary`
   with `expands_to`) supports an open variable, its raw messages replace it as candidates. The
   assembler does this itself, from the message log (`memory/history/`, the one memory package
   `assembly/` may read).
2. **One more restricted graph query.** Otherwise the assembler returns a pending `Expansion` of
   kind `query`, naming the open variables. The engine runs it (the planner and `query/` belong to
   the engine; `assembly/` never calls them, structure.md) and calls the assembler again with the
   new items and `expansions_used=1`, which forbids a second expansion.

When the budget runs out or the expansion finds nothing, the variables stay open: the layout lists
them as open items, and the answering LLM answers "unknown" or partially, which is scored as
failure or abstention.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from grace.context import api
from grace.context.memory.history.log import MessageLog
from grace.context.pipeline.assembly.demand import Variable
from grace.context.pipeline.assembly.items import Item, message_item

KINDS = ("summary", "query")


@dataclass(frozen=True)
class Expansion:
    """One expansion: of a summary (done by the assembler) or a further query (by the engine)."""

    kind: str
    variables: tuple[Variable, ...]
    item_id: str | None = None
    message_ids: tuple[str, ...] = ()
    query: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"expansion kind {self.kind!r} not in {KINDS}")
        if (self.kind == "summary") != (self.item_id is not None):
            raise ValueError("a summary expansion names its item, a query expansion does not")

    def to_record(self) -> dict:
        return {"kind": self.kind, "variables": [v.to_record() for v in self.variables],
                "item_id": self.item_id, "message_ids": list(self.message_ids),
                "query": self.query}


def propose(open_variables: Sequence[Variable], candidates: Sequence[Item],
            covers: Callable[[Item], frozenset[str]], *,
            summary_covers: Callable[[Item], frozenset[str]] | None = None,
            summary_fits: Callable[[Item], bool] | None = None) -> Expansion | None:
    """The one expansion for the open variables, or None.

    - A summary is expanded only when its raw text supports an open variable
      (`summary_covers`, None when there is no message log) and its raw replacement fits the
      room left in the budget (`summary_fits`). The summary whose raw text covers the most open
      variables wins, then the better rank.
    - Otherwise a further query is proposed for the open variables that no candidate supports.
      A variable that is open only because a supporting candidate did not fit gets no query: the
      query could only find what the budget already excludes.
    """
    if not open_variables:
        return None
    names = {v.name for v in open_variables}
    if summary_covers is not None:
        scored = [(summary_covers(i) & names, i) for i in candidates
                  if i.kind == "summary" and i.expands_to
                  and (summary_fits is None or summary_fits(i))]
        scored = [(hit, i) for hit, i in scored if hit]
        if scored:
            hit, best = min(scored, key=lambda p: (-len(p[0]), p[1].rank if p[1].rank is not None
                                                   else float("inf")))
            return Expansion("summary", tuple(v for v in open_variables if v.name in hit),
                             item_id=best.item_id, message_ids=best.expands_to)
    supported = set().union(*(covers(i) for i in candidates)) if candidates else set()
    unsupported = tuple(v for v in open_variables if v.name not in supported)
    if not unsupported:
        return None
    return Expansion("query", unsupported, query="; ".join(v.describes for v in unsupported))


def expand_summary(summary: Item, log: MessageLog, version: int,
                   history: api.HistoryInfo | None = None) -> list[Item]:
    """The raw messages of `summary` visible at `version`, ranked like the summary.

    The messages get no program coverage from the summary: each message supports a variable
    only through its own text (a cheap "ok, thanks" does not inherit the summary's coverage).
    Repeated message IDs are expanded once.
    """
    out = []
    for message_id in dict.fromkeys(summary.expands_to):
        try:
            message = log.by_id(message_id, version)
        except KeyError:
            continue
        out.append(message_item(message, rank=summary.rank, history=history))
    return out
