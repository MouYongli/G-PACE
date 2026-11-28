"""The assembler: demand -> filter -> select -> expand -> layout, within a token budget (plan 5.5).

`Assembler.assemble` builds the working context of one read from the items the engine collected.
Its configuration (`configs/assembly/*.yaml`, `AssemblyConfig`) fixes:

- `selection`: `greedy` (main configuration: new demand coverage per added token) or `truncate`
  (comparison mode: rank truncation, `truncate_k` optional).
- `fill`: in greedy mode, fill the budget left after coverage in rank order. Rank truncation is
  this fill rule alone (`select.truncate`), so the two modes differ only in the selection rule.
- `recent_messages`: the last k visible messages, kept first in the "recent raw text" section
  (0 switches the section off).
- `open_items`: list the still uncovered variables in the context. The fallback `answer`
  variable (`Demand.fallback`) is never listed: it stays open in the record but is not shown.
- `max_expansions`: assembler expansions per read (0 or 1). Demand-driven expansion is part of
  the greedy method; rank truncation never expands.
- `support_threshold`, `support_stem`: the lexical support rule (`demand.Support`); unfrozen
  placeholders until they are fixed on development data.
- `min_budget`: the smallest budget accepted; it must hold the empty-context marker.
- `state_items`: admit state items (query answers and view sentences, `items.STATE_KINDS`).
  False drops them before the filter (reason `state_off`): the graph's structured state is not
  shown, while the graph channel's evidence messages still are (ablation D, E012). Main
  configuration: true.
- `verification`: apply the attribution-and-time checks of the filter (`retired`, `valid`,
  `scope`, `attribution`, `filter.reason`). False keeps only the version guarantee and the
  duplicate and group rules (ablation D, E012). This is the deterministic read-time filter, not
  the verification LLM call of plan 5.6, which is not implemented. Main configuration: true.

Budget. `budget` is the memory budget of the read in tokens of the answering model's tokenizer
(256, 512 or 1,024; `None` is the full history). Selection works on per-item estimates (the line
of an item plus its line break, with section headings reserved); the serialised text is then
counted exactly, and while it exceeds the budget the last-taken unit is dropped. So
`context.tokens == count(context.text) <= budget` always holds, and the `TokenLedger` splits the
total into fragment lines and layout tokens.

Full history (`budget=None`): every item that passes the filter is shown, without selection or
expansion; the engine passes the visible log as items (`items.history_items`) plus anything else
it wants shown.

One extra retrieval per read (plan 5.6; `budgets.yaml` `further_retrieval_per_read: 1`). The
assembler's query expansion and the answering LLM's `retrieve` output share one counter: the
engine passes `retrieval_used=True` once either has happened, and the assembler then proposes no
query. A pending query expansion sets `Assembly.retrieval_used`; at such a read the answering
LLM's `retrieve` output is resolved as `unknown` (chosen over withholding the option so that the
pinned answer prompt stays identical for every system; enforced where the answer is parsed, see
the T026 log). A summary expansion reads the message log and is not a retrieval.
`query_expansion=False` (the engine passes it when the plan fell back) proposes no query: the
query would be the request again and would only spend the read's one retrieval (s00-super,
2026-11-28, E013 diagnosis).

The engine's read path, step by step:

1. `demand = demand_of(request, plan.variables)`; `items` from retrieval, query answers, views.
2. `a = assembler.assemble(task, demand, items, budget, constraints)`.
3. If `a.pending` is a query expansion, run one restricted query for `a.pending.variables`, turn
   the answers into items, and call `assemble(..., items + new, ..., expansions_used=1,
   retrieval_used=True)`. The trace records this as the read's further retrieval.
4. `a.context` is the working context; `api.read_trace(a.context, ...)` gives the trace, whose
   included IDs and provenance are the evidence IDs shown to the answering LLM.
   `a.utilisation` (tokens / budget) and `a.expansions_used` go into the assembly record.

A further retrieval requested by the answering LLM (only when `a.retrieval_used` is False) is
served the same way with the new candidates, the `expansions_used` of the read and
`retrieval_used=True` (no query expansion on top of it; a summary expansion is still possible if
the read made none).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from grace.context import api
from grace.context.memory.history.log import MessageLog
from grace.context.pipeline.assembly import layout
from grace.context.pipeline.assembly.demand import Demand, Support, Variable
from grace.context.pipeline.assembly.expand import Expansion, expand_summary, propose
from grace.context.pipeline.assembly.filter import Constraints, filter_items
from grace.context.pipeline.assembly.items import STATE_KINDS, Item, recent_items
from grace.context.pipeline.assembly.select import MODES, Unit, greedy, truncate, units_of

CONFIG_KEYS = {"version", "selection", "fill", "truncate_k", "recent_messages", "open_items",
               "max_expansions", "support_threshold", "support_stem", "min_budget",
               "state_citations", "state_items", "verification"}


@dataclass(frozen=True)
class AssemblyConfig:
    selection: str = "greedy"
    fill: bool = True
    truncate_k: int | None = None
    recent_messages: int = 0
    open_items: bool = True
    max_expansions: int = 1
    support_threshold: float = 0.5
    support_stem: int = 5
    min_budget: int = 16
    # Message IDs in front of state-section items (views, claims); False is the "without source
    # annotation" arm of ablation C (E010). Selection costs follow the shown lines.
    state_citations: bool = True
    state_items: bool = True       # ablation D (E012), module docstring
    verification: bool = True      # ablation D (E012), module docstring

    def __post_init__(self) -> None:
        if self.selection not in MODES:
            raise ValueError(f"selection must be one of {MODES}")
        if self.max_expansions not in (0, 1):
            raise ValueError("plan 5.6 allows at most one extra retrieval per read")
        if self.recent_messages < 0:
            raise ValueError("recent_messages must be >= 0")
        if self.truncate_k is not None and self.truncate_k < 1:
            raise ValueError("truncate_k must be >= 1")
        Support(self.support_threshold, self.support_stem)

    def to_record(self) -> dict[str, Any]:
        return {"version": 1, "selection": self.selection, "fill": self.fill,
                "truncate_k": self.truncate_k, "recent_messages": self.recent_messages,
                "open_items": self.open_items, "max_expansions": self.max_expansions,
                "support_threshold": self.support_threshold, "support_stem": self.support_stem,
                "min_budget": self.min_budget, "state_citations": self.state_citations,
                "state_items": self.state_items, "verification": self.verification}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AssemblyConfig:
        if not isinstance(raw, Mapping) or raw.get("version") != 1:
            raise ValueError("assembly config: expected a mapping with version: 1")
        if unknown := sorted(set(raw) - CONFIG_KEYS):
            raise ValueError(f"assembly config: unknown keys {unknown}")
        return cls(**{k: v for k, v in raw.items() if k != "version"})

    @classmethod
    def load(cls, path: Path) -> AssemblyConfig:
        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Assembly:
    """The result of one assembly: the working context and how it was chosen."""

    context: api.WorkingContext
    demand: Demand
    constraints: Constraints
    selection: str
    covered: tuple[str, ...]
    open: tuple[Variable, ...]
    candidates: int
    dropped: tuple[tuple[str, str], ...]
    ledger: layout.TokenLedger
    expansion: Expansion | None = None
    expansion_done: bool = False
    expansions_used: int = 0
    retrieval_used: bool = False
    coverage: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def utilisation(self) -> float | None:
        """Tokens used / budget (None for the full history)."""
        b = self.context.budget_tokens
        return None if b is None else self.context.tokens / b

    @property
    def pending(self) -> Expansion | None:
        """A query expansion the engine must run, or None."""
        return self.expansion if self.expansion is not None and not self.expansion_done else None

    def to_record(self) -> dict[str, Any]:
        return {"read_id": self.context.read_id, "selection": self.selection,
                "demand": self.demand.to_record(), "constraints": self.constraints.to_record(),
                "covered": list(self.covered), "open": [v.to_record() for v in self.open],
                "candidates": self.candidates,
                "dropped": [{"id": i, "reason": r} for i, r in self.dropped],
                "coverage": {k: list(v) for k, v in self.coverage.items()},
                "expansion": self.expansion.to_record() if self.expansion else None,
                "expansion_done": self.expansion_done,
                "expansions_used": self.expansions_used,
                "retrieval_used": self.retrieval_used,
                "tokens": self.context.tokens, "budget_tokens": self.context.budget_tokens,
                "utilisation": self.utilisation, "ledger": self.ledger.to_record()}


class Assembler:
    """Builds working contexts; `count` is the answering model's token counter for plain text.

    `log` (the history's message log) enables the recent-messages section and summary expansion;
    `history` supplies segment times for messages without their own timestamp."""

    def __init__(self, config: AssemblyConfig, count: Callable[[str], int], *,
                 log: MessageLog | None = None, history: api.HistoryInfo | None = None,
                 counter_name: str = "unnamed"):
        self.config = config
        self.history = history
        self.count = count
        self.log = log
        self.counter_name = counter_name
        self.support = Support(config.support_threshold, config.support_stem)

    # ------------------------------------------------------------------------------------------
    def assemble(self, task: api.ReadTask, demand: Demand, items: Sequence[Item],
                 budget: int | None, constraints: Constraints | None = None, *,
                 expansions_used: int = 0, retrieval_used: bool = False,
                 query_expansion: bool = True) -> Assembly:
        c = constraints or Constraints(version=task.version)
        if c.version != task.version:
            raise ValueError(f"constraints bound to version {c.version}, read {task.read_id} "
                             f"to {task.version}")
        if not self.config.verification:
            c = Constraints(version=c.version, current_only=False)
        if budget is not None and budget < self.config.min_budget:
            raise ValueError(f"budget {budget} < min_budget {self.config.min_budget}")
        recent = (recent_items(self.log, task.version, self.config.recent_messages,
                               self.history)
                  if self.log is not None else [])
        recent_ids = {i.item_id for i in recent}
        pool = recent + [i for i in items if i.item_id not in recent_ids]
        state_off: tuple[tuple[str, str], ...] = ()
        if not self.config.state_items:
            state_off = tuple((i.item_id, "state_off") for i in pool if i.kind in STATE_KINDS)
            pool = [i for i in pool if i.kind not in STATE_KINDS]
        filtered = filter_items(pool, c)
        kept = list(filtered.kept)
        cache: dict[str, frozenset[str]] = {}

        def covers(item: Item) -> frozenset[str]:
            if item.item_id not in cache:
                cache[item.item_id] = self.support.covers(item, demand.variables)
            return cache[item.item_id]

        show_open = self.config.open_items
        if budget is None:
            selected = kept
        else:
            selected, show_open = self._fit(self._select(kept, demand, budget, covers), demand,
                                            budget, covers)
        expansion, done = None, False
        if (budget is not None and self.config.selection == "greedy"
                and expansions_used < self.config.max_expansions):
            open_now = self._open(selected, demand, covers)
            have = {i.item_id for i in kept}
            raws: dict[str, list[Item]] = {}

            def raw_of(summary: Item) -> list[Item]:
                if summary.item_id not in raws:
                    out = expand_summary(summary, self.log, task.version, self.history)
                    raws[summary.item_id] = [i for i in filter_items(out, c).kept
                                             if i.item_id not in have]
                return raws[summary.item_id]

            def summary_covers(summary: Item) -> frozenset[str]:
                return frozenset().union(*(covers(i) for i in raw_of(summary)))

            used_now = self.count(layout.serialise(
                selected, self._listed(open_now, demand) if show_open else (),
                self.config.state_citations).text)
            chosen_ids = {i.item_id for i in selected}

            def summary_fits(summary: Item) -> bool:
                room = budget - used_now
                if summary.item_id in chosen_ids:
                    room += self._cost(summary)
                return sum(self._cost(i) for i in raw_of(summary)) <= room

            expansion = propose(open_now, kept, covers,
                                summary_covers=summary_covers if self.log is not None else None,
                                summary_fits=summary_fits)
            if expansion is not None and expansion.kind == "summary":
                summary = next(i for i in kept if i.item_id == expansion.item_id)
                trial = [i for i in kept if i.item_id != summary.item_id] + raw_of(summary)
                t_selected, t_show = self._fit(self._select(trial, demand, budget, covers),
                                               demand, budget, covers)
                t_open = {v.name for v in self._open(t_selected, demand, covers)}
                if t_open < {v.name for v in open_now}:  # strictly better, else keep the summary
                    kept, selected, show_open = trial, t_selected, t_show
                    done = True
                    expansions_used += 1
                else:  # the summary stays; unsupported variables may still get the query
                    expansion = propose(open_now, kept, covers)
            if expansion is not None and expansion.kind == "query":
                if retrieval_used or not query_expansion:
                    expansion = None  # the read's one extra retrieval is spent, or a fallback plan
                else:
                    expansions_used += 1
                    retrieval_used = True
        open_vars = self._open(selected, demand, covers)
        serialised = layout.serialise(selected,
                                      self._listed(open_vars, demand) if show_open else (),
                                      self.config.state_citations)
        frags = layout.fragments(serialised, self.count)
        tokens = self.count(serialised.text)
        context = api.WorkingContext(task.read_id, task.history_id, task.version, budget,
                                     tokens, serialised.text, frags)
        covered = tuple(n for n in demand.names if n not in {v.name for v in open_vars})
        coverage = {i.item_id: tuple(sorted(covers(i))) for i in serialised.items if covers(i)}
        return Assembly(context, demand, c, self.config.selection, covered, tuple(open_vars),
                        len(pool), state_off + filtered.dropped,
                        layout.ledger(serialised.text, frags, self.count, budget,
                                      self.counter_name),
                        expansion, done, expansions_used, retrieval_used, coverage)

    # ------------------------------------------------------------------------------------------
    def _cost(self, item: Item) -> int:
        return layout.item_cost(item, self.count, self.config.state_citations)

    def _open(self, selected: Sequence[Item], demand: Demand, covers) -> list[Variable]:
        have = set().union(*(covers(i) for i in selected)) if selected else set()
        return [v for v in demand.variables if v.name not in have]

    @staticmethod
    def _listed(open_vars: Sequence[Variable], demand: Demand) -> Sequence[Variable]:
        """The open variables shown under "Open items": none for the fallback demand."""
        return () if demand.fallback else open_vars

    def _select(self, kept: Sequence[Item], demand: Demand, budget: int, covers) -> list[Unit]:
        units = units_of(kept, self._cost, covers)
        sections = {i.layout_section for i in kept}
        headings = sum(self.count(layout.HEADINGS[s] + layout.SEPARATOR) for s in sections)
        room = budget - headings
        taken: list[Unit] = []
        used = 0
        for u in units:  # recent raw text first, in log order
            if all(i.layout_section == "recent" for i in u.items) and used + u.tokens <= room:
                taken.append(u)
                used += u.tokens
        rest = [u for u in units if u not in taken]
        if self.config.selection == "truncate":
            return truncate(rest, room, k=self.config.truncate_k, taken=taken)
        return greedy(rest, demand.names, room, fill=self.config.fill, taken=taken)

    def _fit(self, chosen: list[Unit], demand: Demand, budget: int, covers
             ) -> tuple[list[Item], bool]:
        """Drop the last-taken units until the exact count of the serialised text fits; return
        the items and whether the open items are listed."""
        chosen = list(chosen)
        while True:
            items = [i for u in chosen for i in u.items]
            open_vars = (self._listed(self._open(items, demand, covers), demand)
                         if self.config.open_items else [])
            text = layout.serialise(items, open_vars, self.config.state_citations).text
            if self.count(text) <= budget:
                return items, self.config.open_items
            if not chosen:
                break
            chosen.pop()
        # Nothing selected and the open items alone do not fit: the context is the empty marker
        # (min_budget guarantees that it fits); the open items are then not listed.
        if self.count(layout.EMPTY) > budget:
            raise ValueError(f"budget {budget} cannot hold the empty context")
        return [], False
