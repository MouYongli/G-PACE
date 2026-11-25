"""Read schedules, questions, gold answers and witnesses (design sections 3.4, 3.5 and 5).

A read point is a version r > L_0. Three schedule types, each determined by the sequence seed and
the schedule name: uniform `U(M)`, anchored `A(M, d)` (half uniform, half d messages after randomly
chosen focus macros of types C1-C5) and Poisson `P(I)` (geometric gaps with mean I). Reads never
write to the history, so several schedules are overlaid on the same messages; each has its own
question records.

At each read point the harness asks q = 3 questions: one binding whose answer changed since the
previous read point (a uniform binding if none changed), one binding drawn uniformly, and one
special slot rotating over a presupposition question, a known-then / seen-from-now pair (both
members asked at r, a fourth question) and an abstention question. If the slot's kind is not
available at r, the next kind in the rotation is tried; if none is, the slot is skipped and
counted.

Every question carries its gold answer set, witnesses and evidence (from `invalidation.py`), the
outdated values, `premise_outdated`, `expected_abstention`, pair fields and the question-level
change-type label: `change_types` (the types C1-C7 of the target binding at the messages of the
interval (r_{j-1}, r_j], the first interval starting at L_0) and `change_type` (the single member,
`none` or `mixed`).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from grace.eval.datasets.changeseq.generate import PlannedSequence, sub_rng
from grace.eval.datasets.changeseq.invalidation import (
    Binding,
    DerivedState,
    GoldStaleness,
    Indeterminate,
    hist_determinate,
    hist_witness,
)
from grace.eval.datasets.changeseq.template_families import (
    BUDGETED,
    ScheduleSpec,
    grammar,
)

ACCEPT_MACROS = {"m-accept", "m-accept-first", "m-accept-switch"}


def read_points(spec: ScheduleSpec, plan: PlannedSequence) -> list[int]:
    L, L0 = plan.cell.length, plan.setup_length
    rng = sub_rng(plan.seed, f"schedule:{spec.name}")

    def uniform(m: int) -> list[int]:
        return sorted({L0 + round(j * (L - L0) / m) for j in range(1, m + 1)})

    if spec.kind == "U":
        return uniform(spec.m)
    if spec.kind == "P":
        points, r = [], L0
        p = 1 / spec.interval
        while True:
            gap = 1
            while rng.random() >= p:
                gap += 1
            r += gap
            if r > L:
                return points
            points.append(r)
    half = spec.m // 2
    points = set(uniform(half))
    focus = [rec.version + spec.d for rec in plan.log
             if rec.macro and rec.macro.intended_type in BUDGETED
             and L0 < rec.version + spec.d <= L]
    rng.shuffle(focus)
    for r in focus:
        if len(points) >= spec.m:
            break
        points.add(r)
    free = [r for r in range(L0 + 1, L + 1) if r not in points]
    rng.shuffle(free)
    while len(points) < spec.m and free:
        points.add(free.pop())
    return sorted(points)


def _flatten(values: Sequence[dict[str, Any]]) -> list[Any]:
    seen, out = set(), []
    for v in values:
        for a in v["ans"]:
            key = json.dumps(a, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append(a)
    return out


@dataclass
class Schedule:
    name: str
    points: list[int]
    questions: list[dict[str, Any]] = field(default_factory=list)
    skipped_special: int = 0

    def counts(self) -> dict[str, Any]:
        return {"read_points": len(self.points), "questions": len(self.questions),
                "by_type": dict(Counter(q["type"] for q in self.questions)),
                "pairs": dict(Counter(q["pair_kind"] for q in self.questions
                                      if q["pair_role"] == "known-then")),
                "skipped_special": self.skipped_special}


class _Builder:
    def __init__(self, plan: PlannedSequence, gold: GoldStaleness, S: DerivedState, renderer):
        self.plan, self.gold, self.S, self.renderer = plan, gold, S, renderer
        self.family = plan.family
        self.bindings = plan.bindings()
        self.by_id = {b.binding_id: b for b in self.bindings}
        self.types = {(x["version"], x["binding_id"]): x["change_type"] for x in gold.labels}
        self.tasks = dict(plan.tasks)
        self.dates = {r.version: r.timestamp for r in plan.log}
        self.anchors = []                            # (version, phrase)
        g = grammar()
        for rec in plan.log:
            if rec.macro and (rec.macro.name == "m-offer" or rec.macro.name in ACCEPT_MACROS):
                slots = rec.cue["slots"]
                key = "anchor_offer" if rec.macro.name == "m-offer" else "anchor_accept"
                self.anchors.append((rec.version, g.questions[key].format(
                    item=slots["item"], task=slots["task"])))

    def surface(self, b: Binding, answer: Any) -> Any:
        """Surface form of one canonical answer: item labels, HH:MM times, counts as strings;
        V4 answers stay [predicate, value] pairs and V6 answers [item, catalogue value]."""
        fam = self.family

        def one(predicate: str, value: str) -> str:
            kind = fam.datatype(predicate)
            if kind == "time":
                return value[:5]
            return fam.task.item_label(value) if kind == "entity" else value

        if b.template == "V3":
            return str(answer)
        if b.template == "V4":
            return [answer[0], one(answer[0], answer[1])]
        if b.template == "V5":
            return one(self.plan.world.choice_predicate, answer)
        if b.template == "V6":
            return [one(self.plan.world.choice_predicate, answer[0]),
                    one(self.plan.world.catalogue_predicate, answer[1])]
        return one(b.predicate, answer)

    def interval_types(self, binding_id: str, lo: int, hi: int) -> list[str]:
        kinds = {self.types[(t, binding_id)] for t in range(lo + 1, hi + 1)}
        return sorted(kinds - {"untouched"})

    def spec(self, b: Binding, kind: str = "view", **extra) -> dict[str, Any]:
        return {"family": self.family, "kind": kind, "template": b.template,
                "subject": b.subject, "task_label": self.tasks.get(b.subject), **extra}

    def question(self, sched: Schedule, j: int, r: int, prev: int, qtype: str, b: Binding,
                 *, text_kind: str = "view", answer=None, witnesses=None, evidence=None,
                 tau=None, kappa=None, outdated=None, premise=False, pair=None,
                 extra=None) -> None:
        value = self.gold.value(b.binding_id, r)
        if answer is None:
            answer, witnesses, evidence = value["ans"], value["wit"], value["ev"]
        if outdated is None:
            current = {json.dumps(a, sort_keys=True) for a in answer}
            outdated = [a for a in _flatten(self.gold.values[b.binding_id][1:r])
                        if json.dumps(a, sort_keys=True) not in current]
        types = self.interval_types(b.binding_id, prev, r)
        n = sum(1 for q in sched.questions if q["read_version"] == r)
        qid = f"{sched.name}:r{j:02d}:q{n + 1}"
        spec = self.spec(b, text_kind, **(extra or {}))
        sched.questions.append({
            "question_id": qid, "schedule": sched.name, "read_index": j, "read_version": r,
            "asked_at": self.dates[r], "type": qtype, "binding_id": b.binding_id,
            "template": b.template, "text": self.renderer.question(spec),
            "answer": answer, "answer_text": [self.surface(b, a) for a in answer],
            "witnesses": witnesses, "evidence": evidence,
            "tau": tau, "kappa": kappa, "outdated_values": outdated,
            "outdated_text": [self.surface(b, a) for a in outdated],
            "premise_outdated": premise, "expected_abstention": not answer,
            "pair_id": pair[0] if pair else None, "pair_role": pair[1] if pair else None,
            "pair_kind": pair[2] if pair else None,
            "change_types": types,
            "change_type": types[0] if len(types) == 1 else ("none" if not types else "mixed")})

    # -- the special slot -------------------------------------------------------------------------

    def presupposition(self, sched, j, r, prev, rng) -> bool:
        options = []
        for b in self.bindings:
            if b.template != "V2":
                continue
            now = self.gold.value(b.binding_id, r)["ans"]
            if not now:
                continue
            earlier = [a for a in _flatten(self.gold.values[b.binding_id][1:r]) if a not in now]
            if earlier:
                options.append((b, earlier[-1]))
        if not options:
            return False
        b, old = rng.choice(options)
        self.question(sched, j, r, prev, "presupposition", b, text_kind="presupposition",
                      outdated=[old], premise=True, extra={"old": old})
        return True

    def pair(self, sched, j, r, prev, rng) -> bool:
        differing, control = [], []
        for k, phrase in self.anchors:
            if k >= r:
                continue
            tau = self.dates[k]
            for b in self.bindings:
                if b.template != "V2":
                    continue
                try:
                    then = hist_determinate(self.S, b.subject, b.predicate, tau, k)
                    now = hist_determinate(self.S, b.subject, b.predicate, tau, r)
                except Indeterminate:
                    continue
                if then is None or now is None:
                    continue
                (differing if then != now else control).append((b, k, tau, phrase, then, now))
        n_diff = sum(1 for q in sched.questions if q["pair_role"] == "known-then"
                     and q["pair_kind"] == "differing")
        n_ctrl = sum(1 for q in sched.questions if q["pair_role"] == "known-then"
                     and q["pair_kind"] == "control")
        first, second = ((differing, "differing"), (control, "control"))
        if n_diff > n_ctrl:
            first, second = second, first
        pool, kind = first if first[0] else second
        if not pool:
            return False
        b, k, tau, phrase, then, now = rng.choice(pool)
        pair_id = f"{sched.name}:r{j:02d}:pair"
        for role, kappa, answer, qtype in (("known-then", k, then, "known_then"),
                                           ("seen-from-now", r, now, "seen_from_now")):
            wit, ev = hist_witness(self.S, b.subject, b.predicate, tau, kappa)
            self.question(sched, j, r, prev, qtype, b, text_kind=qtype, answer=[answer],
                          witnesses=[[answer, wit]], evidence=ev, tau=tau, kappa=kappa,
                          outdated=[], pair=(pair_id, role, kind), extra={"anchor": phrase})
        return True

    def abstention(self, sched, j, r, prev, rng) -> bool:
        options = [b for b in self.bindings if not self.gold.value(b.binding_id, r)["ans"]]
        if not options:
            return False
        self.question(sched, j, r, prev, "abstention", rng.choice(options))
        return True

    def build(self, spec: ScheduleSpec) -> Schedule:
        g = grammar()
        rng = sub_rng(self.plan.seed, f"questions:{spec.name}")
        sched = Schedule(spec.name, read_points(spec, self.plan))
        prev = self.plan.setup_length
        for j, r in enumerate(sched.points, start=1):
            changed = [b for b in self.bindings
                       if self.gold.value(b.binding_id, prev)["ans"]
                       != self.gold.value(b.binding_id, r)["ans"]]
            first = rng.choice(changed) if changed else rng.choice(self.bindings)
            self.question(sched, j, r, prev, "changed" if changed else "uniform", first)
            second = rng.choice([b for b in self.bindings if b is not first])
            self.question(sched, j, r, prev, "uniform", second)
            rotation = g.special_slot_rotation
            start = (j - 1) % len(rotation)
            for kind in rotation[start:] + rotation[:start]:
                if getattr(self, kind)(sched, j, r, prev, rng):
                    break
            else:
                sched.skipped_special += 1
            prev = r
        return sched


def build_schedules(plan: PlannedSequence, gold: GoldStaleness, S: DerivedState,
                    renderer) -> list[Schedule]:
    builder = _Builder(plan, gold, S, renderer)
    return [builder.build(spec) for spec in plan.cell.schedules]
