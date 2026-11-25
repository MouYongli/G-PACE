"""Surface rendering of the change sequences (design docs/research/change-sequences.md, section 7).

**Status.** The paper's renderer is a model that no evaluated system uses (plan 6.4). D006 leaves
the choice open: it must come from outside the Qwen and Gemma families, differ from the blind judge
and therefore not be DeepSeek. Until the user chooses it, this module provides

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
grammar's limit is revised before the audit. No model is called by this module as committed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import yaml

from grace.eval.datasets.changeseq.events import LogRecord, NewClaim, Stance, Supersede
from grace.eval.datasets.changeseq.template_families import (
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


class Renderer(Protocol):
    name: str
    kind: str
    snapshot: str | None

    def render(self, request: RenderRequest, attempt: int) -> str: ...

    def question(self, spec: Mapping[str, Any]) -> str: ...


def _pattern(value: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)", re.IGNORECASE)


def check_output(text: str, request: RenderRequest) -> list[str]:
    """The program checks of section 7: required values present, no forbidden value, no
    meta-language, length within bounds. Returns the failures (empty when the text passes)."""
    g = grammar()
    failures = []
    for value in request.required:
        if not _pattern(value).search(text):
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


def render_messages(log: Sequence[LogRecord], family: ScenarioFamily, renderer: Renderer,
                    sequence_id: str, seed: int) -> RenderOutcome:
    """Render every message with checks, retries and the template fallback (section 7)."""
    g = grammar()
    values = surfaces(family)
    out = RenderOutcome()
    previous: list[str] = []
    for record in log:
        cue = record.cue
        required = tuple(cue.get("required", ()))
        allowed = set(cue.get("allowed", ()))
        request = RenderRequest(
            sequence_id=sequence_id, version=record.version, message_id=record.message_id,
            speaker=record.speaker, date=record.timestamp,
            events=tuple(_event_fields(e) for e in record.events),
            skeleton=cue["skeleton"], slots=dict(cue.get("slots", {})),
            discourse=cue.get("discourse"), required=required, allowed=tuple(sorted(allowed)),
            forbidden=tuple(v for v in values if v not in required and v not in allowed),
            previous=tuple(previous[-CONTEXT_MESSAGES:]),
            seed=seed * 100_003 + record.version,
            topic="small talk" if cue["skeleton"] == "filler" else None)
        attempts, text, failures = [], None, []
        for attempt in range(1, g.max_render_attempts + 1):
            candidate = renderer.render(request, attempt)
            failures = check_output(candidate, request)
            attempts.append({"attempt": attempt, "failures": failures})
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
        previous.append(text)
    return out
