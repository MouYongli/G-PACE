"""Surface rendering of the change sequences (design docs/research/change-sequences.md, section 7).

**Status.** The paper's renderer is a model that no evaluated system uses (plan 6.4). D006 chose
Mistral-Small-3.2-24B-Instruct-2506 (outside the Qwen and Gemma families, not the DeepSeek judge);
it is implemented in `model_renderer.py`. This module provides

- the `Renderer` interface and the request a renderer receives (`RenderRequest`);
- the program checks every rendered message must pass (`check_output`) and the driver that
  retries and falls back (`render_messages`), with the render log;
- `TemplateRenderer`, a deterministic renderer that fills the generic skeletons of
  `resources/changeseq/grammar.yaml` with the family's sentences. **It is a development and test
  renderer only, not the paper's renderer**: its text is regular enough that a system could learn
  its phrasing, which is exactly what the outside renderer is there to prevent.

**Plug-in point for the model renderer.** A model renderer is a class with the same interface:

- `name` (for example `template-v1` or `<model>@<snapshot>`), `kind` (`template` or `model`) and
  `snapshot` (the exact model snapshot; recorded in `meta.json` and the dataset manifest);
- `render(request, attempt) -> str`: one message. A model renderer sends one chat call per attempt
  through `grace.llm` (every model call goes through `src/grace/llm/`, AGENTS.md), with the fixed
  seed `request.seed + attempt` and a prompt template under `resources/prompts/` whose hash is
  recorded with the dataset. The request carries everything section 7 lists: speaker, episode
  date, the previous six rendered messages (never later ones), the message's events as structured
  fields, required mentions and their allowed aliases, forbidden values, persona and register, and
  the discourse requirement for changes and corrections. Fillers get a topic that touches no
  family predicate;
- `question(spec) -> str`: the text of a read question (`schedule.py` builds the spec).

The driver accepts a message only if `check_output` passes; it re-renders with a new seed up to
`max_render_attempts` times and then falls back to the deterministic template sentence. Attempts,
check failures and fallbacks go to `render_log.jsonl`; a family whose fallback rate exceeds the
grammar's limit is revised before the audit. This module itself calls no model.

**Mentions.** Beyond the cue's required values (objects of the stated claims), the driver also
requires the dates of the message (`date`, `start`, `end` slots), the task label when the message
names a task, and the companion's name when a stated claim is about the companion; the other
companions of the family are forbidden. The template renderer always satisfies these; they keep a
model renderer from dropping or swapping who and when a statement is about, which the labels
depend on. Values are compared as normalised strings (Unicode NFKC, case, dashes, apostrophes,
whitespace; a leading zero of an hour is optional). The only aliases (design section 7, "a
listed alias") are dates: a required date in the year of the message's episode date may be written
without the year ("2 April" for "2 April 2026"); the main configuration has no entity aliases
(section 3.6).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import yaml

from grace.eval.datasets.changeseq.events import LogRecord, NewClaim, Stance, Supersede
from grace.eval.datasets.changeseq.generate import render_date
from grace.eval.datasets.changeseq.template_families import (
    ASSISTANT,
    RESOURCES,
    USER,
    ScenarioFamily,
    grammar,
)

FILLER_FILE = RESOURCES / "fillers.yaml"
CONTEXT_MESSAGES = 6


@lru_cache(maxsize=1)
def fillers() -> dict[str, tuple[str, ...]]:
    data = yaml.safe_load(FILLER_FILE.read_text(encoding="utf-8"))
    return {speaker: tuple(lines) for speaker, lines in data.items()}


@dataclass(frozen=True)
class RenderRequest:
    """What a renderer receives for one message (design section 7, "Input per message")."""

    sequence_id: str
    version: int
    message_id: str
    speaker: str
    date: str
    events: tuple[dict[str, Any], ...]
    skeleton: str
    slots: Mapping[str, Any]
    discourse: str | None
    required: tuple[str, ...]
    allowed: tuple[str, ...]
    forbidden: tuple[str, ...]
    previous: tuple[str, ...]
    seed: int
    persona: str = "a friendly adult user writing short chat messages"
    register: str = "informal"
    topic: str | None = None
    # The meaning as readable fact lines (claims resolved to labels), for a model renderer.
    facts: tuple[str, ...] = ()
    # Accepted alternatives of a required value (a date of the episode's year without the year).
    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


class Renderer(Protocol):
    name: str
    kind: str
    snapshot: str | None

    def render(self, request: RenderRequest, attempt: int) -> str: ...

    def question(self, spec: Mapping[str, Any]) -> str: ...


_FOLD = str.maketrans({"\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u201c": '"',
                       "\u201d": '"', "\u2010": "-", "\u2011": "-", "\u2012": "-",
                       "\u2013": "-", "\u2014": "-", "\u00a0": " "})
_HOUR = re.compile(r"0(\d:\d\d)")


def normalise(text: str) -> str:
    """Normalised string for mention checks: NFKC, folded dashes and quotes, single spaces."""
    text = unicodedata.normalize("NFKC", text).translate(_FOLD)
    return re.sub(r"\s+", " ", text).strip()


def _pattern(value: str) -> re.Pattern:
    value = normalise(value)
    body = re.escape(value)
    if (m := _HOUR.fullmatch(value)) is not None:   # 09:41 may be written 9:41
        body = "0?" + re.escape(m.group(1))
    return re.compile(r"(?<!\w)" + body + r"(?!\w)", re.IGNORECASE)


def check_output(text: str, request: RenderRequest) -> list[str]:
    """The program checks of section 7: required values present, no forbidden value, no
    meta-language, length within bounds. Returns the failures (empty when the text passes)."""
    g = grammar()
    failures = []
    text = normalise(text)
    for value in request.required:
        if not any(_pattern(v).search(text) for v in (value, *request.aliases.get(value, ()))):
            failures.append(f"missing required value {value!r}")
    for value in request.forbidden:
        if _pattern(value).search(text):
            failures.append(f"forbidden value {value!r}")
    lowered = text.casefold()
    for marker in g.meta_language:
        if marker.casefold() in lowered:
            failures.append(f"meta-language {marker!r}")
    lo, hi = g.length
    if not lo <= len(text) <= hi:
        failures.append(f"length {len(text)} outside [{lo}, {hi}]")
    return failures


def template_sentence(request: RenderRequest) -> str:
    """The deterministic template sentence of the family skeleton (also the fallback)."""
    if request.skeleton == "filler":
        lines = fillers()[request.speaker]
        return lines[int(request.slots["index"]) % len(lines)]
    text = grammar().skeletons[request.skeleton].format(**request.slots)
    return text[0].upper() + text[1:]


class TemplateRenderer:
    """Deterministic development and test renderer (not the paper's renderer)."""

    name = "template-v1"
    kind = "template"
    snapshot = None

    def render(self, request: RenderRequest, attempt: int) -> str:
        return template_sentence(request)

    def question(self, spec: Mapping[str, Any]) -> str:
        return question_text(spec)


def question_text(spec: Mapping[str, Any]) -> str:
    """Template text of a read question; `spec` comes from `schedule.py`."""
    g, family = grammar(), spec["family"]
    kind, x = spec["kind"], spec.get("subject")
    first = x == USER

    def poss() -> str:
        return "my" if first else f"{x}'s"

    if kind in ("presupposition", "known_then", "seen_from_now"):
        text = g.questions[kind].format(poss=poss(), noun=family.exclusive.noun,
                                        old=spec.get("old", ""), anchor=spec.get("anchor", ""))
    elif spec["template"] in ("V1", "V3"):
        name = ("ask" if spec["template"] == "V1" else "count") + ("_first" if first
                                                                    else "_third")
        text = family.multi.forms[name].format(x=x)
    elif spec["template"] == "V2":
        text = family.exclusive.forms["ask_first" if first else "ask_third"].format(x=x)
    else:
        text = g.questions[spec["template"]].format(task=spec["task_label"],
                                                    cat_noun=family.task.catalogue.noun)
    return text[0].upper() + text[1:]


def surfaces(family: ScenarioFamily) -> list[str]:
    """Every value surface of the family: lexicon values, rendered times and item labels."""
    out = []
    for predicate, lexicon in family.lexicon_values().items():
        kind = family.datatype(predicate)
        for value in lexicon:
            if kind == "time":
                out.append(value[:5])
            elif kind == "entity":
                out.append(family.task.item_label(value))
            else:
                out.append(value)
    return sorted(set(out))


@dataclass
class RenderedMessage:
    record: LogRecord
    text: str


@dataclass
class RenderOutcome:
    messages: list[RenderedMessage] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fallback_rate(self) -> float:
        n = len(self.log)
        return sum(1 for x in self.log if x["fallback"]) / n if n else 0.0

    @property
    def check_failures(self) -> int:
        return sum(1 for x in self.log if x["final_failures"])


def _event_fields(e) -> dict[str, Any]:
    kind = type(e).__name__
    if isinstance(e, NewClaim | Stance | Supersede):
        return {"type": kind, **e.__dict__}
    raise TypeError(kind)


PERSONAS = {
    USER: ("the user, an adult chatting with their personal assistant about {domain}",
           "informal, short chat messages"),
    ASSISTANT: ("the user's personal assistant, helpful and concise", "polite, plain"),
}
DATE_SLOTS = ("date", "start", "end")


def _surface(family: ScenarioFamily, predicate: str, value: str) -> str:
    kind = family.datatype(predicate)
    if kind == "time":
        return value[:5]
    if kind == "entity":
        return family.task.item_label(value)
    return value


def _who(family: ScenarioFamily, subject: str, tasks: Mapping[str, str]) -> str:
    if subject == USER:
        return "the user"
    if subject in tasks:
        return tasks[subject]
    if subject in dict(family.task.items):
        return family.task.item_label(subject)
    return subject


def fact_lines(events: Sequence, claims: Mapping[str, NewClaim], family: ScenarioFamily,
               tasks: Mapping[str, str]) -> tuple[str, ...]:
    """The message's events as readable lines for a model renderer (IDs resolved to labels)."""
    def text(claim: NewClaim) -> str:
        line = (f"{_who(family, claim.subject, tasks)} | {claim.predicate} | "
                f"{_surface(family, claim.predicate, claim.object)}")
        if claim.start or claim.end:
            line += (f" | from {render_date(claim.start) if claim.start else '?'} until "
                     f"{render_date(claim.end) if claim.end else '?'}")
        return line

    out = []
    for e in events:
        if isinstance(e, NewClaim):
            continue                      # stated through the stance that carries it
        claim = claims[e.claim_id]
        if isinstance(e, Stance):
            how = [e.function, f"{e.polarity} polarity"]
            if e.report_mode != "own":
                how.append(f"report mode {e.report_mode}")
            if e.derived:
                how.append("derived")
            out.append(f"statement ({', '.join(how)}): {text(claim)}")
        elif isinstance(e, Supersede):
            kind = "was wrong (corrected)" if e.kind == "correction" else "no longer holds"
            out.append(f"earlier statement {kind}: {text(claim)}")
    return tuple(out)


def date_aliases(required: Sequence[str], slots: Mapping[str, Any], timestamp: str
                 ) -> dict[str, tuple[str, ...]]:
    """Dates of the episode's year may be written without the year."""
    year = timestamp[:4]
    out = {}
    for k in DATE_SLOTS:
        value = slots.get(k)
        if value and value in required and str(value).endswith(f" {year}"):
            out[value] = (str(value).removesuffix(f" {year}"),)
    return out


def mentions(record: LogRecord, family: ScenarioFamily, claims: Mapping[str, NewClaim]
             ) -> tuple[list[str], list[str]]:
    """Extra required and forbidden mentions of a message (module docstring, "Mentions")."""
    cue = record.cue
    slots = cue.get("slots", {})
    required = [str(slots[k]) for k in DATE_SLOTS if slots.get(k)]
    task = slots.get("task")
    if task:
        required.append(task.removeprefix("the "))
    named = {claims[e.claim_id].subject for e in record.events if not isinstance(e, NewClaim)}
    named |= {e.subject for e in record.events if isinstance(e, NewClaim)}
    required += [x for x in family.companions if x in named]
    forbidden = [x for x in family.companions if x not in named]
    return required, forbidden


def render_messages(log: Sequence[LogRecord], family: ScenarioFamily, renderer: Renderer,
                    sequence_id: str, seed: int) -> RenderOutcome:
    """Render every message with checks, retries and the template fallback (section 7)."""
    g = grammar()
    values = surfaces(family)
    out = RenderOutcome()
    previous: list[str] = []
    claims: dict[str, NewClaim] = {}
    tasks: dict[str, str] = {}
    for record in log:
        cue = record.cue
        for e in record.events:
            if isinstance(e, NewClaim):
                claims[e.claim_id] = e
        if cue.get("slots", {}).get("task"):
            for e in record.events:
                claim = claims[e.claim_id]
                if claim.subject not in tasks and claim.predicate in (
                        g.choice_predicate, *(c.predicate for c in family.task.constraints)):
                    tasks[claim.subject] = cue["slots"]["task"]
        extra_required, extra_forbidden = mentions(record, family, claims)
        required = tuple(dict.fromkeys([*cue.get("required", ()), *extra_required]))
        allowed = set(cue.get("allowed", ()))
        if cue.get("slots", {}).get("old_date"):
            allowed.add(cue["slots"]["old_date"])
        persona, register = PERSONAS[record.speaker]
        speaker = "user" if record.speaker == USER else "assistant"
        request = RenderRequest(
            sequence_id=sequence_id, version=record.version, message_id=record.message_id,
            speaker=speaker, date=record.timestamp,
            events=tuple(_event_fields(e) for e in record.events),
            skeleton=cue["skeleton"], slots=dict(cue.get("slots", {})),
            discourse=cue.get("discourse"), required=required,
            allowed=tuple(sorted(a for a in allowed if a not in required)),
            forbidden=tuple([*(v for v in values if v not in required and v not in allowed),
                             *extra_forbidden]),
            previous=tuple(previous[-CONTEXT_MESSAGES:]),
            seed=seed * 100_003 + record.version,
            persona=persona.format(domain=family.title.lower()), register=register,
            topic="small talk" if cue["skeleton"] == "filler" else None,
            facts=fact_lines(record.events, claims, family, tasks),
            aliases=date_aliases(required, cue.get("slots", {}), record.timestamp))
        attempts, text, failures = [], None, []
        for attempt in range(1, g.max_render_attempts + 1):
            candidate = renderer.render(request, attempt)
            failures = check_output(candidate, request)
            attempts.append({"attempt": attempt, "failures": failures}
                            | ({"text": candidate} if failures and renderer.kind == "model"
                               else {}))
            if not failures:
                text = candidate
                break
            if renderer.kind == "template":
                break               # a deterministic renderer gives the same text again
        fallback = text is None
        if fallback:
            text = template_sentence(request)
            failures = check_output(text, request)
        out.log.append({"version": record.version, "message_id": record.message_id,
                        "renderer": renderer.name, "attempts": attempts, "fallback": fallback,
                        "final_failures": failures})
        out.messages.append(RenderedMessage(record, text))
        previous.append(f"{'user' if record.speaker == USER else 'assistant'}: {text}")
    return out
