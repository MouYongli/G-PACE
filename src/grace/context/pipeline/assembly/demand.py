"""The variables an answer needs, and which items support them (plan 5.5, steps 1 and 2).

The demand of a read is the list of variables the planner named (`Plan.variables` of
`pipeline/query/planner.py`, pairs `(?var, describes)`), for example "?deadline: the deadline",
"?train: the accepted train", "?arrival: its arrival time". The engine passes these pairs in; this
module does not import `query/`. When the planner named none (rule templates name none for some
tasks, and a fallback plan names none), the demand is one variable, `answer`, described by the
request itself.

Support is decided in two ways:

- **By program.** An item that binds a variable (a query answer binds its answer columns) lists
  it in `Item.covers`.
- **Lexically.** Otherwise an item supports a variable when its text contains at least
  `threshold` of the content terms of the variable's description (at least one term). Terms are
  lower-cased words of three or more characters outside a small stop list, compared on their
  first `stem` characters (default `STEM`). This is a deterministic stand-in for the
  verification call of plan 5.6, which is not implemented (T026 log); the threshold and the stem
  length are unfrozen placeholders (`configs/assembly/*.yaml`), to be fixed on development data
  before the configuration lock.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from grace.context.pipeline.assembly.items import Item

ANSWER = "answer"
STEM = 5
_WORD = re.compile(r"[a-z0-9]+")
STOP = frozenset("""
a an and are as at be been but by can could did do does for from had has have he her his how i
if in into is it its me my of on or our she so than that the their them then there these they
this to was we were what when where which who whom whose why will with would you your about
after before during ever just also any some all much many more most other such only own same
very s t don now get got go going went say said tell told think know one ones like
""".split())


@dataclass(frozen=True)
class Variable:
    """One variable the answer needs: its name (without `?`) and what it stands for."""

    name: str
    describes: str

    def __post_init__(self) -> None:
        name = self.name.lstrip("?")
        if not name:
            raise ValueError("variable name must be non-empty")
        object.__setattr__(self, "name", name)

    def to_record(self) -> dict[str, str]:
        return {"var": self.name, "describes": self.describes}


@dataclass(frozen=True)
class Demand:
    """The variables a read must fill, and the request they come from."""

    request: str
    variables: tuple[Variable, ...]

    def __post_init__(self) -> None:
        if not self.variables:
            raise ValueError("a demand lists at least one variable")
        names = [v.name for v in self.variables]
        if len(set(names)) != len(names):
            raise ValueError(f"variables named twice: {names}")

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(v.name for v in self.variables)

    def variable(self, name: str) -> Variable:
        for v in self.variables:
            if v.name == name:
                return v
        raise KeyError(name)

    def to_record(self) -> dict:
        return {"request": self.request, "variables": [v.to_record() for v in self.variables]}


def demand_of(request: str, variables: Iterable[tuple[str, str]] = ()) -> Demand:
    """The demand of a read: the planner's `(var, describes)` pairs, else one `answer` variable."""
    listed = tuple(Variable(name, describes) for name, describes in variables)
    return Demand(request, listed or (Variable(ANSWER, request),))


def terms(text: str, stem: int = STEM) -> frozenset[str]:
    """Content terms of `text`, stemmed to their first `stem` characters."""
    return frozenset(w[:stem] for w in _WORD.findall(text.lower())
                     if len(w) >= 3 and w not in STOP)


@dataclass(frozen=True)
class Support:
    """Decides which demand variables an item supports."""

    threshold: float = 0.5
    stem: int = STEM

    def __post_init__(self) -> None:
        if not 0 < self.threshold <= 1:
            raise ValueError("threshold must be in (0, 1]")
        if self.stem < 1:
            raise ValueError("stem must be >= 1")

    def covers(self, item: Item, variables: Sequence[Variable]) -> frozenset[str]:
        names = {v.name for v in variables}
        out = set(item.covers & names)
        have = terms(item.text, self.stem)
        for v in variables:
            if v.name in out:
                continue
            need = terms(v.describes, self.stem)
            if need and len(need & have) >= max(1, math.ceil(self.threshold * len(need))):
                out.add(v.name)
        return frozenset(out)
