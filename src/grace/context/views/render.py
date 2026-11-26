"""Template serialisation, LLM rendering, the rendering check and its fallback (plan 5.4).

Both renderers turn rendering units (`view.units`) into sentences labelled with the row IDs they
state; the caller attaches the evidence of those rows.

- `TemplateRenderer`: the family's sentence pattern filled with the row values (fact cards). No
  LLM call.
- `LLMRenderer`: one call per chunk of units through `grace.llm.client.ChatClient` (the only exit
  for model calls), call type `render`, prompt `render-view` pinned in configs/common/prompts.yaml,
  output checked against `resources/schemas/llm/render-view.json`. The LLM writes the rows as text
  and derives no content. Every sentence is checked (`check_sentence`): each value of its rows
  must appear in it, and so must the binding's subject (`RenderSpec.required_constants`), both
  compared as normalised strings; it must contain no entity name or number from outside its rows
  and the view's constants. A sentence that fails is replaced by the template serialisation of its
  units (`source: fallback`) and counted; so is every unit of a call that fails or returns output
  the schema rejects. Ledger category W for every render call, at write time and for a lazy
  rebuild at read time alike (contracts.md, "Cost ledger"); the trigger tells them apart.

Values are shown in a display form (`display`): entity IDs and string literals as they are, a
time with zero seconds without them (20:45:00 -> 20:45), predicate names split into words
(arriveBy -> arrive by).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from grace.context.memory.graph.entries import Entity, Value
from grace.context.pipeline.query.ir import Predicate
from grace.context.pipeline.query.result import AnswerValue
from grace.context.views.view import Row
from grace.llm.client import ChatResult, LLMCallFailed
from grace.llm.prompts import Prompt
from grace.llm.records import CallContext
from grace.llm.structured import load_schema, parse

PROMPT = "render-view"
SCHEMA = "render-view"
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NORM = re.compile(r"[^0-9a-z]+")
_DIGITS = re.compile(r"\d+")
_WORD_CHARS = re.compile(r"[A-Za-z0-9]")


# ---------------------------------------------------------------------------------------------
# Display and normalisation


def humanise(name: str) -> str:
    """`playsInstrument` -> `plays instrument`; `arriveBy` -> `arrive by`."""
    return " ".join(part.lower() if not part.isupper() else part
                    for part in _CAMEL.split(name.replace("_", " ")))


def display(value: AnswerValue | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Entity):
        return value.id
    if isinstance(value, Predicate):
        return humanise(value.name)
    if isinstance(value, Value) and value.datatype == "time" and value.lexical.endswith(":00") \
            and len(value.lexical) == 8:
        return value.lexical[:5]
    return value.lexical


def normalise(text: str) -> str:
    """Case-folded, with every character other than a-z and 0-9 removed."""
    return _NORM.sub("", text.casefold())


def check_sentence(text: str, required: Sequence[str], allowed: Sequence[str] = (),
                   others: Sequence[str] = (), binding: Sequence[str] = ()) -> str | None:
    """None if `text` passes the rendering check, else the reason.

    - `required`: display values that must each appear (normalised substring);
    - `binding`: binding constants that must each appear, matched like `required` (normalised
      substring of the normalised text): the binding's subject, see
      `RenderSpec.required_constants`;
    - `allowed`: further strings it may contain (member values, the view's constants);
    - `others`: display values of the view's other rows; none may appear unless it is part of an
      allowed, binding or required value. Every number in the text must occur in a required,
      binding or allowed value.
    """
    norm = normalise(text)
    if not norm:
        return "empty sentence"
    for value in required:
        if normalise(value) and normalise(value) not in norm:
            return f"value {value!r} is missing"
    for constant in binding:
        if normalise(constant) and normalise(constant) not in norm:
            return f"binding constant {constant!r} is missing"
    permitted = [normalise(v) for v in (*required, *binding, *allowed) if normalise(v)]
    for value in others:
        n = normalise(value)
        if n and n in norm and not any(n in p for p in permitted):
            return f"value {value!r} of another row appears"
    digits = {d for v in (*required, *binding, *allowed) for d in _DIGITS.findall(v)}
    for number in _DIGITS.findall(text):
        if not any(number in d for d in digits):
            return f"number {number} is not in its rows"
    return None


# ---------------------------------------------------------------------------------------------
# What a renderer is given and returns


@dataclass(frozen=True)
class RenderSpec:
    """What a view's rendering needs to know besides its rows."""

    title: str
    columns: tuple[str, ...]
    is_count: bool = False
    subject: str | None = None
    predicate: str | None = None
    sentence: str | None = None  # the family's sentence pattern; None: generic `col = value`

    def constants(self) -> tuple[str, ...]:
        """Strings an LLM sentence may contain besides its rows: title, subject, predicate."""
        out = [self.title]
        if self.subject:
            out.append(self.subject)
        if self.predicate:
            out += [self.predicate, humanise(self.predicate)]
        return tuple(out)

    def required_constants(self) -> tuple[str, ...]:
        """Binding constants every LLM sentence must contain: the binding's subject.

        The subject (the entity of an entity-predicate binding, the task of a task binding) is a
        name, like the row values, and is matched like them: its display string must be a
        normalised substring of the sentence (case and every character other than a-z and 0-9
        ignored, so "Train booking A," matches "train booking A"). Without it a sentence such as
        "The constraint is arrive by 12:00." no longer says which task or entity it is about, and
        several views of one history share predicates and values (E005, 2026-11-26). The
        predicate is not required: it is a relation name the renderer is asked to put into words
        ("speaksLanguage" -> "Jonas speaks Polish."), so a literal match would reject correct
        paraphrases; it stays allowed. The title is not required either. A view without a
        binding (no subject) requires nothing beyond its rows. Template sentences are not checked.
        """
        return (self.subject,) if self.subject else ()


@dataclass(frozen=True)
class RenderContext:
    """The ledger fields of a render call: write time, or a rebuild or temporary view at read."""

    trigger: str
    history_id: str
    version: int
    read_id: str | None = None

    def call_context(self) -> CallContext:
        return CallContext("render", self.trigger, self.history_id, self.read_id, self.version)


@dataclass(frozen=True)
class Rendered:
    """Sentences as (row IDs, text, source), the IDs of the calls made, and the check counts."""

    sentences: tuple[tuple[tuple[str, ...], str, str], ...]
    call_ids: tuple[str, ...] = ()
    llm_sentences: int = 0      # LLM sentences that passed the check
    failed_sentences: int = 0   # LLM sentences that failed the check or bound unknown rows
    fallback_units: int = 0     # units serialised by template after a failure


class Renderer(Protocol):
    mode: str

    def render(self, spec: RenderSpec, rows: Mapping[str, Row],
               todo: Sequence[tuple[str, ...]], context: RenderContext) -> Rendered: ...


def _columns(spec: RenderSpec, row: Row) -> dict[str, str]:
    values = {c: display(v) for c, v in zip(spec.columns, row.values, strict=True)}
    if spec.is_count:
        values["count"] = values[spec.columns[-1]]
    return values


def template_sentence(spec: RenderSpec, rows: Mapping[str, Row], unit: tuple[str, ...]) -> str:
    row = rows[unit[0]]
    values = _columns(spec, row)
    if spec.sentence is None:
        return "; ".join(f"{c} = {values[c]}" for c in spec.columns) + "."
    fill = {"subject": spec.subject or "", "predicate": humanise(spec.predicate or ""),
            **values}
    return spec.sentence.format(**fill)


class TemplateRenderer:
    """Template serialisation: no LLM call."""

    mode = "template"

    def render(self, spec, rows, todo, context) -> Rendered:
        return Rendered(tuple((u, template_sentence(spec, rows, u), "template") for u in todo))


# ---------------------------------------------------------------------------------------------
# LLM rendering


class ChatPort(Protocol):
    """What `LLMRenderer` needs of `grace.llm.client.ChatClient`."""

    def chat(self, messages, context: CallContext, *, prompt_sha256: str | None,
             decoding: Mapping | None = None,
             validate: Callable[[str], str | None] | None = None) -> ChatResult: ...


def row_lines(spec: RenderSpec, rows: Mapping[str, Row], todo: Sequence[tuple[str, ...]]
              ) -> str:
    """The `rows` variable of the prompt: one line per unit, members indented under a count."""
    lines = []
    for unit in todo:
        head = rows[unit[0]]
        values = _columns(spec, head)
        shown = {"count": values["count"]} if spec.is_count else values
        lines.append(f"[{head.row_id}] " + "; ".join(f"{k} = {v}" for k, v in shown.items()))
        for member in unit[1:]:
            mv = _columns(spec, rows[member]) if not spec.is_count else {
                c: display(v) for c, v in zip(spec.columns, rows[member].values, strict=True)}
            lines.append(f"  member [{member}] " + "; ".join(f"{k} = {v}" for k, v in mv.items()))
    return "\n".join(lines)


@dataclass
class LLMRenderer:
    """LLM rendering with the rendering check and template fallback (module docstring)."""

    client: ChatPort
    prompt: Prompt
    decoding: Mapping[str, Any] = field(default_factory=dict)
    max_rows_per_call: int = 16
    mode: str = "llm"

    def __post_init__(self) -> None:
        self._schema = load_schema(SCHEMA)

    def _validate(self, text: str) -> str | None:
        return parse(text, self._schema).error

    def render(self, spec, rows, todo, context) -> Rendered:
        out: list[tuple[tuple[str, ...], str, str]] = []
        call_ids: list[str] = []
        ok = failed = fallback = 0
        for chunk in _chunks(todo, self.max_rows_per_call):
            accepted, ids, n_ok, n_failed = self._call(spec, rows, chunk, context)
            call_ids += ids
            ok, failed = ok + n_ok, failed + n_failed
            covered = {rid for unit_ids, _, _ in accepted for rid in unit_ids}
            out += accepted
            for unit in chunk:
                if unit[0] not in covered:
                    out.append((unit, template_sentence(spec, rows, unit), "fallback"))
                    fallback += 1
        return Rendered(tuple(out), tuple(call_ids), ok, failed, fallback)

    def _call(self, spec, rows, chunk, context):
        messages = self.prompt.render(title=spec.title, rows=row_lines(spec, rows, chunk))
        try:
            result = self.client.chat(messages, context.call_context(),
                                      prompt_sha256=self.prompt.sha256, decoding=self.decoding,
                                      validate=self._validate)
        except LLMCallFailed as exc:
            return [], [r.call_id for r in exc.records], 0, 0
        ids = [r.call_id for r in result.records]
        if result.status != "ok":
            return [], ids, 0, 0
        parsed = parse(result.text, self._schema).value
        unit_of = {rid: unit for unit in chunk for rid in unit}
        heads = {unit[0] for unit in chunk}
        covered: set[str] = set()
        accepted, n_failed = [], 0
        for item in parsed["sentences"]:
            text, bound = item["text"].strip(), item["rows"]
            if any(r not in unit_of for r in bound):
                n_failed += 1
                continue
            stated = []
            for r in bound:  # close over units: an aggregate brings its members
                unit = unit_of[r]
                if unit[0] != r and unit[0] not in bound:
                    stated = None  # a member named without its aggregate
                    break
                if unit[0] == r and unit not in stated:
                    stated.append(unit)
            if not stated or any(u[0] in covered for u in stated):
                n_failed += 1
                continue
            reason = self._check(spec, rows, chunk, stated, text)
            if reason is not None:
                n_failed += 1
                continue
            ids_stated = tuple(rid for u in sorted(stated, key=chunk.index) for rid in u)
            covered |= {u[0] for u in stated}
            accepted.append((ids_stated, text, "llm"))
        assert covered <= heads
        return accepted, ids, len(accepted), n_failed

    @staticmethod
    def _check(spec, rows, chunk, stated, text) -> str | None:
        required, allowed = [], list(spec.constants())
        stated_ids = {rid for u in stated for rid in u}
        for unit in stated:
            head = rows[unit[0]]
            values = _columns(spec, head)
            if spec.is_count:
                required.append(values["count"])
                required += [values[c] for c in spec.columns[:-1]]
                for m in unit[1:]:
                    allowed += [display(v) for v in rows[m].values]
            else:
                required += list(values.values())
        others = [display(v) for rid, r in rows.items() if rid not in stated_ids
                  for v in r.values if _WORD_CHARS.search(display(v))]
        return check_sentence(text, required, allowed, others, spec.required_constants())


def _chunks(todo: Sequence[tuple[str, ...]], limit: int) -> list[list[tuple[str, ...]]]:
    out: list[list[tuple[str, ...]]] = []
    size = 0
    for unit in todo:
        if out and size + len(unit) <= limit:
            out[-1].append(unit)
            size += len(unit)
        else:
            out.append([unit])
            size = len(unit)
    return out
