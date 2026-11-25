"""Scenario families, the split and the controlled variables of a generation cell.

Design: docs/research/change-sequences.md, sections 2, 10 and 11. structure.md calls this file
`template_families.py`; the design calls the unit a **scenario family** (a domain micro-world:
entity types, predicates, a task type, value lexicons) to keep it apart from the six view
templates, and this module follows the design's term.

Resources (read from the current worktree, `REPO_ROOT`):

- `resources/changeseq/grammar.yaml`: macro inventory, assumptions, renderer skeletons;
- `resources/changeseq/families/<id>.yaml`: one scenario family each;
- `resources/changeseq/split.yaml`: the committed development / held-out split by domain group.

Every family has one multi-valued and one exclusive state predicate (authority speaker `user`, for
the user and for one named companion) and one task type with two exclusive constraint predicates,
the shared choice predicate and one exclusive catalogue predicate of the offered items (authority
speaker `assistant`). That makes all six view templates and all seven change types realisable in
every family (design section 2).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT

RESOURCES = REPO_ROOT / "resources" / "changeseq"
GRAMMAR_FILE = RESOURCES / "grammar.yaml"
FAMILY_DIR = RESOURCES / "families"
SPLIT_FILE = RESOURCES / "split.yaml"
DATATYPES = ("string", "time")
USER = "user"
ASSISTANT = "assistant"


class FamilyError(ValueError):
    """A family, grammar, split or cell config is malformed."""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FamilyError(f"file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FamilyError(f"{path}: expected a mapping")
    return data


def _keys(where: str, data: Mapping, required: set[str], optional: set[str] = frozenset()):
    if not isinstance(data, Mapping):
        raise FamilyError(f"{where}: expected a mapping, got {data!r}")
    if missing := sorted(required - set(data)):
        raise FamilyError(f"{where}: missing keys {missing}")
    if unknown := sorted(set(data) - required - optional):
        raise FamilyError(f"{where}: unknown keys {unknown}")


def _lexicon(where: str, values: Any, minimum: int) -> tuple[str, ...]:
    if not isinstance(values, list) or len(values) < minimum:
        raise FamilyError(f"{where}: expected a list of at least {minimum} values")
    out = tuple(str(v) for v in values)
    if len(set(out)) != len(out):
        raise FamilyError(f"{where}: duplicate values")
    return out


# ---------------------------------------------------------------------------------------------
# Family spec


@dataclass(frozen=True)
class StatePredicate:
    """A state predicate about a person; the authority speaker is the user (design section 2)."""

    predicate: str
    exclusive: bool
    noun: str
    lexicon: tuple[str, ...]
    forms: Mapping[str, str]
    authority: str = USER
    datatype: str = "string"

    def form(self, name: str, **values: str) -> str:
        return self.forms[name].format(**values)


@dataclass(frozen=True)
class Constraint:
    predicate: str
    datatype: str
    lexicon: tuple[str, ...]
    request: str


@dataclass(frozen=True)
class Catalogue:
    predicate: str
    datatype: str
    noun: str
    phrase: str
    lexicon: tuple[str, ...]
    authority: str = ASSISTANT


@dataclass(frozen=True)
class TaskType:
    noun: str
    constraints: tuple[Constraint, ...]
    catalogue: Catalogue
    items: tuple[tuple[str, str], ...]   # (entity ID, label)

    def item_label(self, item_id: str) -> str:
        return dict(self.items)[item_id]


_MULTI_FORMS = {"first", "second", "third", "first_neg", "third_neg", "ask_first", "ask_third",
                "count_first", "count_third"}
_EXCL_FORMS = {"first", "second", "third", "change_first", "change_third", "past_first",
               "past_third", "ask_first", "ask_third"}


@dataclass(frozen=True)
class ScenarioFamily:
    family_id: str
    group: str
    title: str
    companions: tuple[str, ...]
    multi: StatePredicate
    exclusive: StatePredicate
    task: TaskType
    source: str = ""

    @property
    def state_predicates(self) -> tuple[StatePredicate, ...]:
        return (self.multi, self.exclusive)

    def predicate_names(self) -> set[str]:
        return ({self.multi.predicate, self.exclusive.predicate, self.task.catalogue.predicate}
                | {c.predicate for c in self.task.constraints})

    def lexicon_values(self) -> dict[str, tuple[str, ...]]:
        """Predicate -> its value lexicon (the catalogue items under `selectedService`)."""
        out = {self.multi.predicate: self.multi.lexicon,
               self.exclusive.predicate: self.exclusive.lexicon,
               self.task.catalogue.predicate: self.task.catalogue.lexicon}
        out.update({c.predicate: c.lexicon for c in self.task.constraints})
        out[grammar().choice_predicate] = tuple(i for i, _ in self.task.items)
        return out

    def datatype(self, predicate: str) -> str:
        """`string`, `time` or `entity` (offered items are entities, the join subject of V6)."""
        if predicate == grammar().choice_predicate:
            return "entity"
        for p in (*self.state_predicates, self.task.catalogue, *self.task.constraints):
            if p.predicate == predicate:
                return p.datatype
        raise FamilyError(f"{self.family_id}: unknown predicate {predicate!r}")

    def authority(self, predicate: str) -> str:
        if predicate == self.task.catalogue.predicate:
            return ASSISTANT
        return USER

    def is_exclusive(self, predicate: str) -> bool:
        return predicate != self.multi.predicate and predicate != grammar().choice_predicate

    def domain_content(self) -> dict[str, set[str]]:
        """What must not be shared across the split (design section 11): non-core predicates,
        value lexicons (time literals excepted: they carry no domain), names and item IDs."""
        values = set()
        for predicate, lexicon in self.lexicon_values().items():
            if self.datatype(predicate) != "time":
                values.update(lexicon)
        values.update(label for _, label in self.task.items)
        return {"predicates": self.predicate_names() - set(grammar().core_predicates),
                "values": values, "names": set(self.companions),
                "nouns": {self.multi.noun, self.exclusive.noun, self.task.noun}}


def _state(where: str, raw: Mapping, exclusive: bool) -> StatePredicate:
    forms = _EXCL_FORMS if exclusive else _MULTI_FORMS
    _keys(where, raw, {"predicate", "noun", "lexicon", *forms})
    return StatePredicate(predicate=raw["predicate"], exclusive=exclusive, noun=raw["noun"],
                          lexicon=_lexicon(f"{where}.lexicon", raw["lexicon"], 8),
                          forms={k: raw[k] for k in forms})


def parse_family(raw: Mapping, source: str = "") -> ScenarioFamily:
    where = source or "family"
    _keys(where, raw, {"id", "group", "title", "companions", "multi", "exclusive", "task"})
    task = raw["task"]
    _keys(f"{where}.task", task, {"noun", "constraints", "catalogue", "items"})
    constraints = []
    if not isinstance(task["constraints"], list) or len(task["constraints"]) != 2:
        raise FamilyError(f"{where}.task.constraints: expected exactly two constraints")
    for i, c in enumerate(task["constraints"]):
        _keys(f"{where}.task.constraints[{i}]", c, {"predicate", "datatype", "lexicon", "request"})
        if c["datatype"] not in DATATYPES:
            raise FamilyError(f"{where}: constraint datatype {c['datatype']!r} not in {DATATYPES}")
        constraints.append(Constraint(c["predicate"], c["datatype"],
                                      _lexicon(f"{where}.constraint", c["lexicon"], 5),
                                      c["request"]))
    cat = task["catalogue"]
    _keys(f"{where}.task.catalogue", cat, {"predicate", "datatype", "noun", "phrase", "lexicon"})
    if cat["datatype"] not in DATATYPES:
        raise FamilyError(f"{where}: catalogue datatype {cat['datatype']!r} not in {DATATYPES}")
    items = []
    for i, item in enumerate(task["items"]):
        _keys(f"{where}.task.items[{i}]", item, {"id", "label"})
        items.append((str(item["id"]), str(item["label"])))
    if len(items) < 9 or len({i for i, _ in items}) != len(items):
        raise FamilyError(f"{where}.task.items: expected at least 9 items with unique IDs")
    family = ScenarioFamily(
        family_id=raw["id"], group=raw["group"], title=raw["title"],
        companions=_lexicon(f"{where}.companions", raw["companions"], 2),
        multi=_state(f"{where}.multi", raw["multi"], False),
        exclusive=_state(f"{where}.exclusive", raw["exclusive"], True),
        task=TaskType(task["noun"], tuple(constraints),
                      Catalogue(cat["predicate"], cat["datatype"], cat["noun"], cat["phrase"],
                                _lexicon(f"{where}.catalogue", cat["lexicon"], 8)),
                      tuple(items)),
        source=source)
    names = [p for p in (family.multi.predicate, family.exclusive.predicate,
                         family.task.catalogue.predicate,
                         *(c.predicate for c in family.task.constraints))]
    if len(set(names)) != len(names) or grammar().choice_predicate in names:
        raise FamilyError(f"{where}: predicates must be distinct and differ from the choice "
                          f"predicate: {names}")
    all_values = [v for p, lex in family.lexicon_values().items() for v in lex
                  if family.datatype(p) == "string"]
    if len(set(all_values)) != len(all_values):
        raise FamilyError(f"{where}: a string value appears in two lexicons of the family")
    return family


@cache
def load_family(family_id: str, directory: Path = FAMILY_DIR) -> ScenarioFamily:
    path = directory / f"{family_id}.yaml"
    family = parse_family(_load_yaml(path), source=path.name)
    if family.family_id != family_id:
        raise FamilyError(f"{path}: id {family.family_id!r} differs from the file name")
    return family


def family_ids(directory: Path = FAMILY_DIR) -> list[str]:
    return sorted(p.stem for p in directory.glob("*.yaml"))


# ---------------------------------------------------------------------------------------------
# Grammar constants


@dataclass(frozen=True)
class Grammar:
    version: str
    core_predicates: tuple[str, ...]
    choice_predicate: str
    macros: Mapping[str, str]
    offers_per_task: tuple[int, ...]
    p_no_accept: float
    questions_per_read: int
    special_slot_rotation: tuple[str, ...]
    setup_min: int
    setup_share: float
    episode_length: tuple[int, int]
    episode_gap_days: tuple[int, int]
    n_tasks: int
    fallback_rate_limit: float
    meta_language: tuple[str, ...]
    length: tuple[int, int]
    max_render_attempts: int
    skeletons: Mapping[str, str]
    questions: Mapping[str, str]
    task_letters: tuple[str, ...]

    def setup_length(self, history_length: int) -> int:
        """L_0 = max(10, 0.1 L) (design section 5)."""
        return max(self.setup_min, int(self.setup_share * history_length))


@cache
def grammar(path: Path = GRAMMAR_FILE) -> Grammar:
    raw = _load_yaml(path)
    return Grammar(
        version=raw["version"], core_predicates=tuple(raw["core_predicates"]),
        choice_predicate=raw["choice_predicate"], macros=dict(raw["macros"]),
        offers_per_task=tuple(raw["offers_per_task"]), p_no_accept=float(raw["p_no_accept"]),
        questions_per_read=int(raw["questions_per_read"]),
        special_slot_rotation=tuple(raw["special_slot_rotation"]),
        setup_min=int(raw["setup_length"]["min"]), setup_share=float(raw["setup_length"]["share"]),
        episode_length=(raw["episode_length"]["min"], raw["episode_length"]["max"]),
        episode_gap_days=(raw["episode_gap_days"]["min"], raw["episode_gap_days"]["max"]),
        n_tasks=int(raw["n_tasks"]), fallback_rate_limit=float(raw["fallback_rate_limit"]),
        meta_language=tuple(raw["meta_language"]),
        length=(raw["length"]["min_chars"], raw["length"]["max_chars"]),
        max_render_attempts=int(raw["max_render_attempts"]),
        skeletons=dict(raw["skeletons"]), questions=dict(raw["questions"]),
        task_letters=tuple(raw["task_letters"]))


# ---------------------------------------------------------------------------------------------
# Split


@dataclass(frozen=True)
class Split:
    seed: str
    groups: Mapping[str, tuple[str, ...]]
    development: tuple[str, ...]
    held_out: tuple[str, ...]

    def split_of(self, family_id: str) -> str:
        if family_id in self.development:
            return "development"
        if family_id in self.held_out:
            return "held-out"
        raise FamilyError(f"family {family_id!r} is in no split")


def compute_split(groups: Mapping[str, list[str]], seed: str, n_development: int) -> tuple[
        list[str], list[str]]:
    """Assign whole domain groups to development by a seeded permutation (design section 11).

    Groups are shuffled with `random.Random(int(sha256(seed)))`; groups are taken in that order
    while they fit into the remaining development quota, until it is exactly filled.
    """
    order = sorted(groups)
    random.Random(int(hashlib.sha256(seed.encode()).hexdigest(), 16)).shuffle(order)
    development, n = [], 0
    for group in order:
        if n + len(groups[group]) <= n_development:
            development.append(group)
            n += len(groups[group])
        if n == n_development:
            break
    if n != n_development:
        raise FamilyError(f"no group combination fills {n_development} development families")
    return sorted(development), sorted(g for g in groups if g not in development)


@cache
def load_split(path: Path = SPLIT_FILE) -> Split:
    raw = _load_yaml(path)
    _keys(str(path), raw, {"seed", "n_development", "groups", "development_groups",
                           "held_out_groups"})
    groups = {g: tuple(f) for g, f in raw["groups"].items()}
    dev_groups, held_groups = compute_split(raw["groups"], raw["seed"], raw["n_development"])
    if (sorted(raw["development_groups"]) != dev_groups
            or sorted(raw["held_out_groups"]) != held_groups):
        raise FamilyError(f"{path}: committed groups differ from the seeded permutation "
                          f"(development {dev_groups}, held-out {held_groups})")
    return Split(seed=raw["seed"], groups=groups,
                 development=tuple(f for g in dev_groups for f in groups[g]),
                 held_out=tuple(f for g in held_groups for f in groups[g]))


# ---------------------------------------------------------------------------------------------
# Controlled variables of one generation cell (design section 10)


CHANGE_TYPES = ("C1", "C2", "C3", "C4", "C5", "C6", "C7")
BUDGETED = CHANGE_TYPES[:5]


@dataclass(frozen=True)
class ScheduleSpec:
    """`U(M)`, `A(M, d)` or `P(I)` (design section 5); `name` labels the schedule file."""

    kind: str
    m: int | None = None
    d: int | None = None
    interval: float | None = None

    def __post_init__(self) -> None:
        ok = {"U": self.m is not None and self.m >= 1 and self.d is None,
              "A": self.m is not None and self.m >= 2 and self.d is not None and self.d >= 1,
              "P": self.interval is not None and self.interval >= 1}
        if not ok.get(self.kind, False):
            raise FamilyError(f"bad schedule spec {self!r}")

    @property
    def name(self) -> str:
        if self.kind == "U":
            return f"U{self.m}"
        if self.kind == "A":
            return f"A{self.m}d{self.d}"
        return f"P{self.interval:g}"

    @classmethod
    def parse(cls, text: str) -> ScheduleSpec:
        """`U10`, `A20d1`, `P10`."""
        try:
            if text.startswith("U"):
                return cls("U", m=int(text[1:]))
            if text.startswith("A"):
                m, d = text[1:].split("d")
                return cls("A", m=int(m), d=int(d))
            if text.startswith("P"):
                return cls("P", interval=float(text[1:]))
        except ValueError as exc:
            raise FamilyError(f"bad schedule name {text!r}") from exc
        raise FamilyError(f"bad schedule name {text!r}")


@dataclass(frozen=True)
class CellConfig:
    """Controlled variables of one sequence: change mix, revision density, nuisance rates,
    history length and the read schedules overlaid on it (design section 10)."""

    family: str
    length: int = 200
    density: float = 10.0                       # rho: C1-C5 macros per 100 messages after L_0
    mention_rate: float = 10.0                  # mu_6
    irrelevant_rate: float = 10.0               # mu_7
    mix: Mapping[str, float] = field(default_factory=lambda: {t: 0.2 for t in BUDGETED})
    schedules: tuple[ScheduleSpec, ...] = (ScheduleSpec("U", m=10),)
    primary_schedule: str | None = None

    def __post_init__(self) -> None:
        if self.length < 30:
            raise FamilyError(f"history length {self.length} < 30")
        if set(self.mix) != set(BUDGETED) or abs(sum(self.mix.values()) - 1) > 1e-9:
            raise FamilyError(f"mix must give shares of {BUDGETED} summing to 1: {self.mix}")
        if min(self.density, self.mention_rate, self.irrelevant_rate) < 0:
            raise FamilyError("rates must be non-negative")
        if not self.schedules:
            raise FamilyError("at least one schedule is required")
        names = [s.name for s in self.schedules]
        if len(set(names)) != len(names):
            raise FamilyError(f"duplicate schedules {names}")
        if self.primary_schedule is not None and self.primary_schedule not in names:
            raise FamilyError(f"primary schedule {self.primary_schedule} not in {names}")

    @property
    def primary(self) -> str:
        return self.primary_schedule or self.schedules[0].name

    def counts(self) -> dict[str, int]:
        """Macro counts per change type: budgeted C1-C5 by largest-remainder rounding of
        rho * (L - L_0) / 100 over the mix; C6 and C7 from their rates (design section 10)."""
        span = self.length - grammar().setup_length(self.length)
        total = round(self.density * span / 100)
        raw = {t: self.mix[t] * total for t in BUDGETED}
        counts = {t: int(v) for t, v in raw.items()}
        rest = total - sum(counts.values())
        for t in sorted(BUDGETED, key=lambda t: (-(raw[t] - counts[t]), t))[:rest]:
            counts[t] += 1
        counts["C6"] = round(self.mention_rate * span / 100)
        counts["C7"] = round(self.irrelevant_rate * span / 100)
        return counts

    def to_record(self) -> dict[str, Any]:
        return {"family": self.family, "length": self.length, "density": self.density,
                "mention_rate": self.mention_rate, "irrelevant_rate": self.irrelevant_rate,
                "mix": dict(self.mix), "schedules": [s.name for s in self.schedules],
                "primary_schedule": self.primary}

    @classmethod
    def from_record(cls, raw: Mapping[str, Any]) -> CellConfig:
        _keys("cell", raw, {"family"}, {"length", "density", "mention_rate", "irrelevant_rate",
                                        "mix", "schedules", "primary_schedule"})
        kwargs = dict(raw)
        if "schedules" in kwargs:
            kwargs["schedules"] = tuple(ScheduleSpec.parse(s) for s in kwargs["schedules"])
        return cls(**kwargs)
