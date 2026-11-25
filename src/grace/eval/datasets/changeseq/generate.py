"""Sequence planner: the productions of the event grammar (design sections 3.3, 5 and 10).

`plan_sequence` turns a scenario family, a cell config and a seed into an event log. It is
deterministic given its inputs: every random choice comes from a `random.Random` seeded from the
sequence seed and a purpose label.

Procedure:

1. Episodes and dates: the setup episode is the first L_0 messages; later episodes have lengths in
   the grammar's range and dates a few days apart. Every message carries its episode date.
2. Setup: the world is introduced (the exclusive and multi-valued state of the user and of one
   companion, one constraint of the first task); no reads happen before L_0.
3. Budget: macro counts per change type from `CellConfig.counts` (largest-remainder rounding of
   the mix for C1-C5, the nuisance rates for C6 and C7), placed on distinct message slots after
   L_0 in a seeded random order. Each slot realises its type with a macro whose preconditions
   hold (an offer precedes its acceptance, a correction targets a claim from an earlier
   episode); when none holds, a later planned type is moved forward. Unrealisable slots become
   fillers and are counted in `unrealised`.
4. Every other message is a filler with no events (G7).

The planner keeps its own small world model for preconditions; the gold semantics are computed
afterwards from the log alone (`invalidation.py`), and `check_log` verifies G1-G8.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from grace.eval.datasets.changeseq.events import (
    Event,
    LogRecord,
    Macro,
    NewClaim,
    Stance,
    Supersede,
)
from grace.eval.datasets.changeseq.invalidation import Binding, World
from grace.eval.datasets.changeseq.template_families import (
    ASSISTANT,
    BUDGETED,
    USER,
    CellConfig,
    ScenarioFamily,
    StatePredicate,
    grammar,
)


def sub_rng(seed: int | str, purpose: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{seed}:{purpose}".encode()).hexdigest(), 16))


def render_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B')} {d.year}"


def _shift(iso: str, days: int) -> str:
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=days)).isoformat()


def _dates_between(lo: str, hi: str) -> list[str]:
    """ISO dates d with lo <= d <= hi."""
    a, b = dt.date.fromisoformat(lo), dt.date.fromisoformat(hi)
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


@dataclass
class _Claim:
    event: NewClaim
    version: int
    episode: int
    endorsed: bool
    superseded: bool = False
    floor: str | None = None      # earliest admissible start of a dated replacement


@dataclass
class _Task:
    task_id: str
    label: str
    offers_max: int
    no_accept: bool
    constraints: dict[str, str] = field(default_factory=dict)   # predicate -> current claim
    offers: list[str] = field(default_factory=list)              # choice claims
    accepted: dict[str, int] = field(default_factory=dict)       # claim -> acceptance version
    rejected: set[str] = field(default_factory=set)

    def pending(self) -> list[str]:
        return [c for c in self.offers if c not in self.accepted and c not in self.rejected]

    def accepted_unrejected(self) -> list[str]:
        return [c for c in self.accepted if c not in self.rejected]

    def choice(self) -> str | None:
        live = self.accepted_unrejected()
        return max(live, key=lambda c: (self.accepted[c], c)) if live else None


@dataclass
class PlannedSequence:
    """The event log of one sequence and the world it was planned in."""

    sequence_id: str
    family: ScenarioFamily
    cell: CellConfig
    seed: int
    log: list[LogRecord]
    companion: str
    tasks: list[tuple[str, str]]          # (task ID, label)
    setup_length: int
    planned: dict[str, int]
    realised: dict[str, int]
    unrealised: dict[str, int]

    @property
    def world(self) -> World:
        return world_of(self.family)

    def bindings(self) -> list[Binding]:
        return bindings_of(self.family, self.companion, [t for t, _ in self.tasks])

    def entity_label(self, entity: str) -> str:
        return {t: label for t, label in self.tasks}.get(entity, entity)


def world_of(family: ScenarioFamily) -> World:
    g = grammar()
    authority = {p: family.authority(p) for p in family.predicate_names()}
    authority[g.choice_predicate] = ASSISTANT
    return World(authority=authority,
                 constraint_predicates=frozenset(c.predicate for c in family.task.constraints),
                 choice_predicate=g.choice_predicate,
                 catalogue_predicate=family.task.catalogue.predicate)


def bindings_of(family: ScenarioFamily, companion: str, tasks: list[str]) -> list[Binding]:
    """Every binding the world admits (design section 12.1: about 15 per sequence)."""
    out = []
    for x in (USER, companion):
        out += [Binding("V1", x, family.multi.predicate), Binding("V3", x, family.multi.predicate),
                Binding("V2", x, family.exclusive.predicate)]
    for k in tasks:
        out += [Binding("V4", k), Binding("V5", k), Binding("V6", k)]
    return out


class _Planner:
    def __init__(self, family: ScenarioFamily, cell: CellConfig, seed: int, sequence_id: str):
        self.g = grammar()
        self.family, self.cell, self.seed, self.sequence_id = family, cell, seed, sequence_id
        self.rng = sub_rng(seed, "plan")
        self.L = cell.length
        self.L0 = self.g.setup_length(self.L)
        self.companion = self.rng.choice(family.companions)
        self.claims: dict[str, _Claim] = {}
        self.propositions: set[tuple] = set()
        self.counters = Counter()
        self.items = list(i for i, _ in family.task.items)
        self.rng.shuffle(self.items)
        letters = self.g.task_letters[: self.g.n_tasks]
        self.tasks = [
            _Task(f"k{i + 1}", f"the {family.task.noun} {letter}",
                  self.rng.choice(self.g.offers_per_task), self.rng.random() < self.g.p_no_accept)
            for i, letter in enumerate(letters)]
        self.arr: dict[str, str] = {}                 # item -> current catalogue claim
        self.item_of: dict[str, str] = {}             # choice claim -> item
        self.records: list[LogRecord] = []
        self._episodes()

    # -- identifiers and dates ------------------------------------------------------------------

    def _id(self, prefix: str) -> str:
        self.counters[prefix] += 1
        return f"{prefix}{self.counters[prefix]}"

    def _episodes(self) -> None:
        start = dt.date(2025, 1, 1) + dt.timedelta(days=self.rng.randrange(540))
        self.episode_of = [0] * (self.L + 1)
        self.date_of = [""] * (self.L + 1)
        date = start.isoformat()
        lo, hi = self.g.episode_length
        bounds = [(1, self.L0)]
        t = self.L0 + 1
        while t <= self.L:
            n = self.rng.randint(lo, hi)
            bounds.append((t, min(self.L, t + n - 1)))
            t += n
        gap_lo, gap_hi = self.g.episode_gap_days
        for episode, (a, b) in enumerate(bounds):
            if episode:
                date = _shift(date, self.rng.randint(gap_lo, gap_hi))
            for v in range(a, b + 1):
                self.episode_of[v], self.date_of[v] = episode, date
        self.episode_bounds = bounds

    # -- surface helpers -------------------------------------------------------------------------

    def surface(self, predicate: str, value: str) -> str:
        kind = self.family.datatype(predicate)
        if kind == "time":
            return value[:5]
        if kind == "entity":
            return self.family.task.item_label(value)
        return value

    def stmt(self, spec: StatePredicate, x: str, o: str, form: str, speaker: str = USER) -> str:
        forms = {"state": ("first", "third"), "change": ("change_first", "change_third"),
                 "past": ("past_first", "past_third"), "neg": ("first_neg", "third_neg")}
        if speaker == ASSISTANT:
            name = "second" if x == USER else "third"
        else:
            name = forms[form][0 if x == USER else 1]
        return spec.forms[name].format(o=self.surface(spec.predicate, o), x=x)

    # -- world queries ---------------------------------------------------------------------------

    def current(self, x: str, p: str, endorsed: bool = True) -> list[str]:
        return [cid for cid, c in self.claims.items()
                if c.event.subject == x and c.event.predicate == p and not c.superseded
                and (c.endorsed or not endorsed) and c.event.end is None]

    def fresh_values(self, x: str, p: str, start: str | None = None,
                     end: str | None = None) -> list[str]:
        lexicon = self.family.lexicon_values()[p]
        used_now = {self.claims[c].event.object for c in self.current(x, p, endorsed=False)}
        return [o for o in lexicon if (x, p, o, None, start, end) not in self.propositions
                and o not in used_now]

    # -- event construction ----------------------------------------------------------------------

    def new_claim(self, events: list[Event], x: str, p: str, o: str, t: int, endorsed: bool,
                  start: str | None = None, end: str | None = None,
                  floor: str | None = None) -> str:
        cid = self._id("c")
        kind = self.family.datatype(p)
        e = NewClaim(cid, x, p, o, kind, start, end)
        events.append(e)
        self.claims[cid] = _Claim(e, t, self.episode_of[t], endorsed, floor=floor)
        self.propositions.add(e.proposition)
        return cid

    def stance(self, events: list[Event], cid: str, function: str, mode: str = "own",
               polarity: str = "positive", derived: bool = False) -> str:
        aid = self._id("a")
        events.append(Stance(aid, cid, function, mode, polarity, derived))
        return aid

    def supersede(self, events: list[Event], cid: str, kind: str, licence: str,
                  replacing: str | None = None) -> None:
        events.append(Supersede(self._id("s"), cid, kind, licence, replacing))
        self.claims[cid].superseded = True

    def emit(self, t: int, speaker: str, events: list[Event], name: str, focus: Binding | None,
             cue: dict[str, Any], intended: str | None = None) -> None:
        macro = None
        if events:
            intended = intended or self.g.macros[name]
            macro = Macro(self._id("mac"), name, intended, focus.binding_id)
        self.records.append(LogRecord(t, f"m{t:04d}", f"ep-{self.episode_of[t]}", speaker,
                                      self.date_of[t], tuple(events), macro, cue))

    # -- realisations ----------------------------------------------------------------------------
    # Each returns a closure that emits the macro at version t, or None if the precondition fails.

    def r_state_intro(self, t: int, x: str, spec: StatePredicate, skeleton: str, name: str,
                      intended: str, focus_template: str) -> Callable | None:
        if spec.exclusive and self.current(x, spec.predicate):
            return None
        values = self.fresh_values(x, spec.predicate)
        blocked = [cid for cid in self.current(x, spec.predicate, endorsed=False)
                   if not self.claims[cid].endorsed] if not spec.exclusive else []
        if not values and not blocked:
            return None

        def run():
            events: list[Event] = []
            use_blocked = blocked and (not values or self.rng.random() < 0.5)
            if use_blocked:
                cid = self.rng.choice(blocked)
                self.stance(events, cid, "inform")
                self.claims[cid].endorsed = True
                o = self.claims[cid].event.object
            else:
                o = self.rng.choice(values)
                cid = self.new_claim(events, x, spec.predicate, o, t, True)
                self.stance(events, cid, "inform")
            s = self.stmt(spec, x, o, "state")
            self.emit(t, USER, events, name, Binding(focus_template, x, spec.predicate),
                      self._cue(skeleton, events, stmt=s), intended)
        return run

    def r_change(self, t: int, x: str) -> Callable | None:
        spec = self.family.exclusive
        cur = self.current(x, spec.predicate)
        if not cur:
            return None
        old = self.claims[cur[0]]
        floor = _shift(max(self.date_of[old.version], old.event.start or ""), 1)
        dated_range = _dates_between(floor, self.date_of[t]) if floor <= self.date_of[t] else []

        def run():
            events: list[Event] = []
            start = self.rng.choice(dated_range) if dated_range and self.rng.random() < 0.5 \
                else None
            values = self.fresh_values(x, spec.predicate, start)
            if not values:
                return False
            o = self.rng.choice(values)
            cid = self.new_claim(events, x, spec.predicate, o, t, True, start=start, floor=floor)
            aid = self.stance(events, cid, "inform")
            self.supersede(events, cur[0], "change", aid, cid)
            s = self.stmt(spec, x, o, "change")
            skeleton = "change_dated" if start else "change"
            self.emit(t, USER, events, "m-change", Binding("V2", x, spec.predicate),
                      self._cue(skeleton, events, stmt=s, date=render_date(start) if start
                                else None, discourse="change"))
        return run

    def r_remove(self, t: int, x: str) -> Callable | None:
        spec = self.family.multi
        cur = self.current(x, spec.predicate)
        if not cur:
            return None

        def run():
            events: list[Event] = []
            cid = self.rng.choice(cur)
            aid = self.stance(events, cid, "inform", polarity="negative")
            self.supersede(events, cid, "change", aid)
            o = self.claims[cid].event.object
            self.emit(t, USER, events, "m-remove", Binding("V1", x, spec.predicate),
                      self._cue("remove", events, stmt=self.stmt(spec, x, o, "neg"),
                                discourse="change"))
        return run

    def r_correct(self, t: int, x: str, which: str) -> Callable | None:
        spec = self.family.exclusive if which != "multi" else self.family.multi
        cur = [c for c in self.current(x, spec.predicate)
               if self.claims[c].episode < self.episode_of[t]]
        if not cur:
            return None
        cid = self.rng.choice(cur)
        old = self.claims[cid]
        if which == "date":
            if old.event.start is None or old.floor is None:
                return None
            dates = [d for d in _dates_between(old.floor, self.date_of[t]) if d != old.event.start]
            if not dates:
                return None
        values = self.fresh_values(x, spec.predicate, old.event.start)
        if which == "value" and not values:
            return None

        def run():
            events: list[Event] = []
            o_old = old.event.object
            if which == "date":
                start = self.rng.choice(dates)
                new = self.new_claim(events, x, spec.predicate, o_old, t, True, start=start,
                                     floor=old.floor)
                aid = self.stance(events, new, "inform")
                self.supersede(events, cid, "correction", aid, new)
                cue = self._cue("correct_date", events,
                                stmt=self.stmt(spec, x, o_old, "change"),
                                date=render_date(start), old_date=render_date(old.event.start),
                                discourse="correction")
            elif which == "value":
                o = self.rng.choice(values)
                new = self.new_claim(events, x, spec.predicate, o, t, True,
                                     start=old.event.start, floor=old.floor)
                aid = self.stance(events, new, "inform")
                self.supersede(events, cid, "correction", aid, new)
                cue = self._cue("correct_value", events, stmt=self.stmt(spec, x, o, "state"),
                                old=self.surface(spec.predicate, o_old), discourse="correction")
            else:
                aid = self.stance(events, cid, "inform", polarity="negative")
                self.supersede(events, cid, "correction", aid)
                fresh = [v for v in values if v != o_old]
                if fresh and self.rng.random() < 0.5:
                    o = self.rng.choice(fresh)
                    new = self.new_claim(events, x, spec.predicate, o, t, True)
                    self.stance(events, new, "inform")
                    cue = self._cue("correct_value", events,
                                    stmt=self.stmt(spec, x, o, "state"),
                                    old=self.surface(spec.predicate, o_old),
                                    discourse="correction")
                else:
                    cue = self._cue("correct_remove", events,
                                    stmt=self.stmt(spec, x, o_old, "state"),
                                    discourse="correction")
            template = "V1" if which == "multi" else "V2"
            self.emit(t, USER, events, "m-correct", Binding(template, x, spec.predicate), cue)
        return run

    def r_mention(self, t: int) -> Callable | None:
        options = []
        for x in (USER, self.companion):
            for spec in self.family.state_predicates:
                for cid in self.current(x, spec.predicate):
                    options.append(("state", x, spec, cid))
        for task in self.tasks:
            choice = task.choice()
            if choice is not None:
                options.append(("choice", task.task_id, None, choice))
        if not options:
            return None

        def run():
            kind, x, spec, cid = self.rng.choice(options)
            events: list[Event] = []
            o = self.claims[cid].event.object
            if kind == "choice":
                self.stance(events, cid, "inform", derived=True)
                task = next(k for k in self.tasks if k.task_id == x)
                self.emit(t, ASSISTANT, events, "m-mention", Binding("V6", x),
                          self._cue("mention_choice", events,
                                    item=self.surface(self.g.choice_predicate, o),
                                    task=task.label))
                return
            focus = Binding("V2" if spec.exclusive else "V1", x, spec.predicate)
            how = self.rng.choice(["inform", "confirm", "derived"])
            if how == "derived":
                self.stance(events, cid, "inform", derived=True)
                self.emit(t, ASSISTANT, events, "m-mention", focus,
                          self._cue("mention_derived", events,
                                    stmt=self.stmt(spec, x, o, "state", ASSISTANT)))
            else:
                self.stance(events, cid, how)
                self.emit(t, USER, events, "m-mention", focus,
                          self._cue(f"mention_{how}", events,
                                    stmt=self.stmt(spec, x, o, "state")))
        return run

    def r_past(self, t: int, x: str) -> Callable | None:
        spec = self.family.exclusive
        current = {self.claims[c].event.object for c in self.current(x, spec.predicate)}
        recent = [d for d in _dates_between(self.date_of[1], self.date_of[t])]

        def run():
            events: list[Event] = []
            if len(recent) >= 3 and self.rng.random() < 0.5:
                start, end = sorted(self.rng.sample(recent, 2))
            else:
                year = int(self.date_of[1][:4]) - self.rng.randint(3, 15)
                start = f"{year}-{self.rng.randint(1, 12):02d}-01"
                end = f"{year + self.rng.randint(1, 5)}-{self.rng.randint(1, 12):02d}-01"
            values = [o for o in self.fresh_values(x, spec.predicate, start, end)
                      if o not in current]
            if not values:
                return False
            o = self.rng.choice(values)
            cid = self.new_claim(events, x, spec.predicate, o, t, True, start=start, end=end)
            self.stance(events, cid, "inform")
            self.emit(t, USER, events, "m-past", Binding("V2", x, spec.predicate),
                      self._cue("past", events, stmt=self.stmt(spec, x, o, "past"),
                                start=render_date(start), end=render_date(end)))
        return run

    def r_blocked(self, t: int, x: str, spec: StatePredicate) -> Callable | None:
        current = {self.claims[c].event.object for c in self.current(x, spec.predicate)}
        values = [o for o in self.fresh_values(x, spec.predicate) if o not in current]
        if not values:
            return None

        def run():
            events: list[Event] = []
            o = self.rng.choice(values)
            mode = self.rng.choice(["quote", "hypothetical"])
            cid = self.new_claim(events, x, spec.predicate, o, t, False)
            self.stance(events, cid, "inform", mode=mode)
            self.emit(t, USER, events, "m-blocked",
                      Binding("V2" if spec.exclusive else "V1", x, spec.predicate),
                      self._cue(f"blocked_{mode}", events, stmt=self.stmt(spec, x, o, "state")))
        return run

    def r_constraint(self, t: int, task: _Task, revise: bool) -> Callable | None:
        index = self.tasks.index(task)
        if index and not self.tasks[index - 1].constraints:
            return None                 # tasks are opened in order
        options = [c for c in self.family.task.constraints
                   if (c.predicate in task.constraints) == revise]
        if not options:
            return None

        def run():
            con = self.rng.choice(options)
            old = task.constraints.get(con.predicate)
            values = [v for v in self.fresh_values(task.task_id, con.predicate)]
            if not values:
                return False
            events: list[Event] = []
            v = self.rng.choice(values)
            cid = self.new_claim(events, task.task_id, con.predicate, v, t, True)
            aid = self.stance(events, cid, "request")
            if revise:
                self.supersede(events, old, "change", aid, cid)
            task.constraints[con.predicate] = cid
            request = con.request.format(v=self.surface(con.predicate, v))
            self.emit(t, USER, events, "m-constraint-revise" if revise else "m-constraint",
                      Binding("V4", task.task_id),
                      self._cue("constraint_revise" if revise else "constraint", events,
                                task=task.label, request=request,
                                discourse="change" if revise else None))
        return run

    def r_offer(self, t: int, task: _Task) -> Callable | None:
        if not task.constraints or len(task.offers) >= task.offers_max or not self.items:
            return None
        cat = self.family.task.catalogue

        def run():
            events: list[Event] = []
            item = self.items.pop()
            cid = self.new_claim(events, task.task_id, self.g.choice_predicate, item, t, False)
            self.stance(events, cid, "offer")
            v = self.rng.choice(cat.lexicon)
            d = self.new_claim(events, item, cat.predicate, v, t, True)
            self.stance(events, d, "inform")
            task.offers.append(cid)
            self.arr[item], self.item_of[cid] = d, item
            self.emit(t, ASSISTANT, events, "m-offer", Binding("V5", task.task_id),
                      self._cue("offer", events, task=task.label,
                                item=self.surface(self.g.choice_predicate, item),
                                cat=cat.phrase.format(v=self.surface(cat.predicate, v))))
        return run

    def r_accept(self, t: int, task: _Task, mode: str) -> Callable | None:
        """mode: `first` (V6 C2), `switch` (V6 C4) or `pending` (V5 C3)."""
        if task.no_accept or not task.pending():
            return None
        has_choice = task.choice() is not None
        if (mode == "first" and has_choice) or (mode == "switch" and not has_choice):
            return None

        def run():
            events: list[Event] = []
            cid = self.rng.choice(task.pending())
            self.stance(events, cid, "accept")
            task.accepted[cid] = t
            name, focus = {"first": ("m-accept-first", "V6"), "switch": ("m-accept-switch", "V6"),
                           "pending": ("m-accept", "V5")}[mode]
            self.emit(t, USER, events, name, Binding(focus, task.task_id),
                      self._cue("accept", events, task=task.label,
                                item=self.surface(self.g.choice_predicate, self.item_of[cid])))
        return run

    def r_reject(self, t: int, task: _Task) -> Callable | None:
        options = [(c, "V5") for c in task.pending()]
        choice = task.choice()
        if choice is not None and len(task.accepted_unrejected()) == 1:
            options.append((choice, "V6"))      # G8: no earlier choice to fall back to
        if not options:
            return None

        def run():
            cid, focus = self.rng.choice(options)
            events: list[Event] = []
            self.stance(events, cid, "reject")
            task.rejected.add(cid)
            self.emit(t, USER, events, "m-reject", Binding(focus, task.task_id),
                      self._cue("reject", events,
                                item=self.surface(self.g.choice_predicate, self.item_of[cid])))
        return run

    def r_catalogue_change(self, t: int, task: _Task) -> Callable | None:
        choice = task.choice()
        if choice is None:
            return None
        item = self.item_of[choice]
        cat = self.family.task.catalogue
        values = self.fresh_values(item, cat.predicate)
        if not values:
            return None

        def run():
            events: list[Event] = []
            v = self.rng.choice(values)
            d = self.new_claim(events, item, cat.predicate, v, t, True)
            aid = self.stance(events, d, "inform")
            self.supersede(events, self.arr[item], "change", aid, d)
            self.arr[item] = d
            self.emit(t, ASSISTANT, events, "m-catalogue-change", Binding("V6", task.task_id),
                      self._cue("catalogue_change", events,
                                item=self.surface(self.g.choice_predicate, item),
                                cat=cat.phrase.format(v=self.surface(cat.predicate, v)),
                                discourse="change"))
        return run

    def realisations(self, t: int, kind: str) -> list[tuple[str, Callable]]:
        """Feasible (realisation kind, closure) pairs for change type `kind` at version t."""
        people = (USER, self.companion)
        multi, excl = self.family.multi, self.family.exclusive
        groups: dict[str, list[Callable | None]] = {}
        if kind == "C1":
            groups["change"] = [self.r_change(t, x) for x in people]
            groups["remove"] = [self.r_remove(t, x) for x in people]
            groups["revise"] = [self.r_constraint(t, k, True) for k in self.tasks]
            groups["catalogue"] = [self.r_catalogue_change(t, k) for k in self.tasks]
        elif kind == "C2":
            groups["add"] = [self.r_state_intro(t, x, multi, "add", "m-add", "C2", "V1")
                             for x in people]
            groups["first"] = [self.r_state_intro(t, x, excl, "first", "m-first", "C2", "V2")
                               for x in people]
            groups["offer"] = [self.r_offer(t, k) for k in self.tasks]
            groups["constraint"] = [self.r_constraint(t, k, False) for k in self.tasks]
            groups["accept"] = [self.r_accept(t, k, "first") for k in self.tasks]
        elif kind == "C3":
            groups["accept"] = [self.r_accept(t, k, "pending") for k in self.tasks]
            groups["reject"] = [self.r_reject(t, k) for k in self.tasks]
        elif kind == "C4":
            groups["count"] = [self.r_state_intro(t, x, multi, "add", "m-add-count", "C4", "V3")
                               for x in people]
            groups["switch"] = [self.r_accept(t, k, "switch") for k in self.tasks]
        elif kind == "C5":
            groups["value"] = [self.r_correct(t, x, "value") for x in people]
            groups["date"] = [self.r_correct(t, x, "date") for x in people]
            groups["multi"] = [self.r_correct(t, x, "multi") for x in people]
        elif kind == "C6":
            groups["mention"] = [self.r_mention(t)]
        elif kind == "C7":
            groups["past"] = [self.r_past(t, x) for x in people]
            groups["blocked"] = [self.r_blocked(t, x, s) for x in people
                                 for s in (multi, excl)]
        return [(name, f) for name, fs in groups.items() for f in fs if f is not None]

    def realise(self, t: int, kind: str) -> bool:
        options = self.realisations(t, kind)
        by_kind: dict[str, list[Callable]] = {}
        for name, f in options:
            by_kind.setdefault(name, []).append(f)
        names = sorted(by_kind)
        self.rng.shuffle(names)
        if kind == "C2":
            # Negation hits (C3) and choice switches (C4) need pending offers, which only C2
            # creates: open tasks and make offers first while that demand is unmet.
            demand = self.queue.count("C3") + self.queue.count("C4") // 2
            pending = sum(len(k.pending()) for k in self.tasks)
            if demand > pending and self.rng.random() < 0.6:
                names.sort(key=lambda n: {"offer": 0, "constraint": 1}.get(n, 2))
        for name in names:
            fs = by_kind[name]
            self.rng.shuffle(fs)
            for f in fs:
                if f() is not False:
                    return True
        return False

    def filler(self, t: int) -> None:
        previous = self.records[-1].speaker if self.records else ASSISTANT
        speaker = USER if previous == ASSISTANT else ASSISTANT
        self.emit(t, speaker, [], "filler", None,
                  {"skeleton": "filler", "slots": {"index": self.rng.randrange(10**6)},
                   "discourse": None, "required": [], "allowed": []})

    def _cue(self, skeleton: str, events: list[Event], discourse: str | None = None,
             **slots: str | None) -> dict[str, Any]:
        """Render cue: skeleton, slot strings, the values the text must mention (objects of the
        claims the events state) and the values it may mention (objects of superseded claims)."""
        required, allowed = [], []
        for e in events:
            claim = self.claims[e.claim_id].event
            surface = self.surface(claim.predicate, claim.object)
            if isinstance(e, Supersede):
                allowed.append(surface)
            elif surface not in required:
                required.append(surface)
            if claim.predicate == self.g.choice_predicate:
                allowed.append(surface)
            if claim.predicate == self.family.task.catalogue.predicate:
                item = self.surface(self.g.choice_predicate, claim.subject)
                if item not in required:
                    required.append(item)
        allowed = [a for a in allowed if a not in required]
        return {"skeleton": skeleton, "slots": {k: v for k, v in slots.items() if v is not None},
                "discourse": discourse, "required": required, "allowed": sorted(set(allowed))}

    # -- the plan ---------------------------------------------------------------------------------

    def plan(self) -> PlannedSequence:
        # Setup episode: introduce the world on random slots of 1..L0; the rest are fillers.
        setup = [("intro", USER, self.family.exclusive), ("intro", USER, self.family.multi),
                 ("intro", self.companion, self.family.exclusive),
                 ("intro", self.companion, self.family.multi), ("constraint", None, None)]
        if self.rng.random() < 0.5:
            setup.append(("intro", USER, self.family.multi))
        slots = sorted(self.rng.sample(range(1, self.L0 + 1), len(setup)))
        self.rng.shuffle(setup)
        setup_at = dict(zip(slots, setup, strict=True))
        counts = self.cell.counts()
        planned = [k for k in (*BUDGETED, "C6", "C7") for _ in range(counts[k])]
        self.rng.shuffle(planned)
        span = list(range(self.L0 + 1, self.L + 1))
        if len(planned) > len(span):
            raise ValueError(f"{len(planned)} macros do not fit into {len(span)} messages")
        positions = set(self.rng.sample(span, len(planned)))
        self.queue = queue = list(planned)
        realised, unrealised = Counter(), Counter()
        for t in range(1, self.L + 1):
            if t in setup_at:
                kind, x, spec = setup_at[t]
                if kind == "constraint":
                    ok = self.r_constraint(t, self.tasks[0], False)()
                else:
                    template = "V2" if spec.exclusive else "V1"
                    name = "m-first" if spec.exclusive else "m-add"
                    f = self.r_state_intro(t, x, spec, "first", name, "C2", template)
                    ok = f() if f else False
                if ok is False:
                    self.filler(t)
                continue
            if t not in positions:
                self.filler(t)
                continue
            for i, kind in enumerate(queue):
                if self.realise(t, kind):
                    realised[kind] += 1
                    queue.pop(i)
                    break
            else:
                unrealised[queue.pop(0)] += 1
                self.filler(t)
        unrealised.update(queue)
        return PlannedSequence(
            sequence_id=self.sequence_id, family=self.family, cell=self.cell, seed=self.seed,
            log=self.records, companion=self.companion,
            tasks=[(k.task_id, k.label) for k in self.tasks], setup_length=self.L0,
            planned=dict(counts), realised=dict(realised), unrealised=dict(unrealised))


def plan_sequence(family: ScenarioFamily, cell: CellConfig, seed: int,
                  sequence_id: str) -> PlannedSequence:
    if family.family_id != cell.family:
        raise ValueError(f"cell is for {cell.family!r}, family is {family.family_id!r}")
    return _Planner(family, cell, seed, sequence_id).plan()
