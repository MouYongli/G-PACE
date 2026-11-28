"""ReacTOD reproduced on the primary model (plan 7.2, MultiWOZ baselines; arXiv 2605.19077).

ReacTOD casts state tracking as discrete tool calls inside a bounded ReAct loop whose every
proposed call is checked by a deterministic validator. The paper publishes no code and no prompt
text; this reproduction follows its method section, and every choice the paper leaves open is
named below (and in the T028 task file) so that the gap to the published number can be explained.

Per user turn t (the loop never reads a later turn and never sees gold):

- Inputs of every call: the intent list with definitions and the tool definitions (system
  prompt); the previous system utterance, the user utterance, the belief state B_{t-1}, the
  previous intent and the action-observation trace of this turn (user prompt). History is not
  shown unless the agent calls `get_history`.
- Tools: `classify_intent` (one or more domains, or `none`: the fallback for non-transactional
  turns, which ends the turn without an update) returns the slot definitions of those domains;
  `resolve_slots` proposes ΔB_t as (slot, raw value, normalised value) triples and ends the turn
  when it validates; `get_history` returns the last n turns (n <= 10).
- Update: B_t = B_{t-1} upserted with ΔB_t; the value `none` removes a slot. B is never changed
  during the loop, only after the validator accepts `resolve_slots`.
- Validator: action compliance (known tool, `classify_intent` before `resolve_slots`, no
  duplicate call in the turn); schema conformance (slot names of the classified domains, times as
  HH:MM, numbers as digits, categorical values in the 2.2 enumeration, `dontcare` everywhere);
  coreference consistency (a generic reference such as "the hotel" as a name, departure or
  destination is refused with the advice to call `get_history`). A refusal is returned to the
  agent as a structured error observation, e.g. "invalid format for slot taxi-arriveby: expected
  HH:MM".
- Bound: K_max = 6 model calls per turn. At the cap the turn falls back to B_{t-1} (no update,
  no further call). Unparsable output counts as one iteration and is answered with a format error.

Reproduction choices the paper leaves open (all fixed here, before any run): the prompt wording
(`resources/prompts/reactod/`); one JSON action per call in text form (Qwen3, thinking disabled,
temperature 0, as in the paper); `classify_intent` accepts several domains, because MultiWOZ user
turns can name two; the regular expressions and the enumerations (taken from the 2.2 schema);
the generic-reference list; the history window (agent's choice, at most 10 turns).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from grace.context import api
from grace.eval.engines.baselines.base import CallTag, ModelPort, pinned_prompt
from grace.eval.engines.baselines.multiwoz import SlotSpec, StateOutput, norm_value
from grace.llm.structured import extract_json

K_MAX = 6
MAX_HISTORY = 10
MAX_TOKENS = 512
REMOVE = "none"
TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
NUMBER = re.compile(r"^\d+$")
GENERIC = {"it", "that", "this", "there", "here", "same", "the same", "that one", "this one",
           "the one", "restaurant", "the restaurant", "hotel", "the hotel", "guesthouse",
           "the guesthouse", "attraction", "the attraction", "train", "the train", "taxi",
           "the taxi", "the place", "place", "the same place", "my hotel", "my restaurant",
           "the college", "the museum", "the station", "station"}
COREF_SLOTS = ("-name", "-departure", "-destination")
INTENTS = {
    "hotel": "find or book a place to stay (hotel or guesthouse)",
    "restaurant": "find or book a restaurant",
    "attraction": "find a place to visit (museum, college, park, theatre, ...)",
    "train": "find or book a train",
    "taxi": "book a taxi",
    "none": "no transactional request in this turn (greeting, thanks, goodbye, general talk)",
}
TOOLS = ("classify_intent", "resolve_slots", "get_history")


@dataclass
class TurnLog:
    """Trace of one turn: the actions, the validator verdicts and how the turn ended."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    end: str = "cap"  # resolved, fallback-intent, cap
    corrections: int = 0  # validator refusals and format errors in this turn


class ReacTOD:
    """One instance per dialogue. `observe` every message in order; `predict` at a user turn."""

    def __init__(self, model: ModelPort, specs: Sequence[SlotSpec], *, k_max: int = K_MAX):
        self.model, self.k_max = model, k_max
        self.specs = {s.name: s for s in specs}
        self.prompt = pinned_prompt("reactod")
        self.messages: list[api.Message] = []
        self.state: dict[str, str] = {}
        self.intent: list[str] = []
        self.turns: list[dict[str, Any]] = []

    # dialogue ---------------------------------------------------------------------------------
    def observe(self, message: api.Message) -> None:
        if self.messages and message.version != self.messages[-1].version + 1:
            raise ValueError("messages must be observed in version order")
        self.messages.append(message)

    def predict(self, task: api.ReadTask) -> StateOutput:
        if not self.messages or self.messages[-1].version != task.version:
            raise ValueError(f"read {task.read_id} is not at the last observed message")
        if self.messages[-1].role != "user":
            raise ValueError(f"read {task.read_id} does not follow a user turn")
        log, call_ids, raw = self._turn(task)
        self.turns.append({"read_id": task.read_id, "end": log.end,
                           "corrections": log.corrections, "steps": log.steps})
        choice = {d: self.state.get(f"{d}-name") for d in ("attraction", "hotel", "restaurant")}
        choice["train"] = None
        return StateOutput("state", dict(self.state), choice, raw, tuple(call_ids),
                           {"end": log.end, "corrections": log.corrections,
                            "calls": len(log.steps)})

    # one turn ---------------------------------------------------------------------------------
    def _turn(self, task: api.ReadTask) -> tuple[TurnLog, list[str], str | None]:
        log, call_ids, trace = TurnLog(), [], []
        intents: list[str] = []
        seen: set[str] = set()
        raw = None
        user = self.messages[-1]
        system = self.messages[-2].text if len(self.messages) > 1 else "(start of dialogue)"
        for step in range(1, self.k_max + 1):
            messages = self.prompt.render(
                intents="\n".join(f"- {k}: {v}" for k, v in INTENTS.items()),
                previous_intent=", ".join(self.intent) or "(none)",
                state=json.dumps(self.state, sort_keys=True) if self.state else "{}",
                system=system, user=user.text,
                trace="\n".join(trace) or "(no actions yet)")
            tag = CallTag("external", "read", task.history_id, task.version, task.read_id)
            result = self.model.chat(messages, tag, prompt_sha256=self.prompt.sha256,
                                     max_tokens=MAX_TOKENS)
            call_ids.extend(result.call_ids)
            raw = result.text
            action, error = self._parse(result.text if result.ok else None)
            key = json.dumps(action, sort_keys=True) if action else None
            if error is None:
                error = self._validate(action, intents, seen, key)
            entry = {"step": step, "action": action, "error": error}
            if error is not None:
                log.corrections += 1
                log.steps.append(entry)
                trace += [f"Action {step}: {key or (raw or '')[:300]}",
                          f"Observation {step}: ERROR: {error}"]
                continue
            seen.add(key)
            name = action["action"]
            if name == "classify_intent":
                intents = [d for d in action["intent"] if d != "none"]
                if not intents:
                    log.end, self.intent = "fallback-intent", []
                    log.steps.append(entry)
                    return log, call_ids, raw
                observation = self._slot_definitions(intents)
            elif name == "get_history":
                observation = self._history(int(action["n"]))
            else:  # resolve_slots, validated
                for update in action["updates"]:
                    value = norm_value(update["value"])
                    if value == REMOVE:
                        self.state.pop(update["slot"], None)
                    else:
                        self.state[update["slot"]] = value
                self.intent = intents
                log.end = "resolved"
                log.steps.append(entry)
                return log, call_ids, raw
            log.steps.append(entry)
            trace += [f"Action {step}: {key}", f"Observation {step}: {observation}"]
        return log, call_ids, raw   # cap reached: B_t = B_{t-1}

    # parsing and validation -------------------------------------------------------------------
    @staticmethod
    def _parse(text: str | None) -> tuple[dict[str, Any] | None, str | None]:
        if text is None:
            return None, "no output"
        try:
            data = extract_json(text)
        except (ValueError, TypeError) as exc:
            return None, f"output is not one JSON object ({exc})"
        if not isinstance(data, dict) or "action" not in data:
            return None, 'output must be one JSON object with a key "action"'
        data.pop("thought", None)
        return data, None

    def _validate(self, action: Mapping[str, Any], intents: list[str], seen: set[str],
                  key: str) -> str | None:
        name = action.get("action")
        if name not in TOOLS:
            return f"unknown action {name!r}; use one of {', '.join(TOOLS)}"
        if key in seen:
            return f"duplicate call of {name} in this turn; choose a different action"
        if name == "classify_intent":
            value = action.get("intent")
            value = [value] if isinstance(value, str) else value
            if (not isinstance(value, list) or not value
                    or any(v not in INTENTS for v in value)):
                return f"intent must be one or more of {', '.join(INTENTS)}"
            action["intent"] = value   # type: ignore[index]
            return None
        if name == "get_history":
            n = action.get("n")
            if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_HISTORY:
                return f"n must be an integer from 1 to {MAX_HISTORY}"
            return None
        # resolve_slots
        if not intents:
            return "call classify_intent before resolve_slots"
        updates = action.get("updates")
        if not isinstance(updates, list):
            return 'resolve_slots needs "updates": a list of {"slot", "raw", "value"}'
        errors = []
        for update in updates:
            if not isinstance(update, dict) or not isinstance(update.get("slot"), str) \
                    or not isinstance(update.get("value"), str):
                errors.append(f"bad update {update!r}: needs string slot and value")
                continue
            errors += self._check_slot(update["slot"], norm_value(update["value"]), intents)
        return "; ".join(errors) if errors else None

    def _check_slot(self, slot: str, value: str, intents: list[str]) -> list[str]:
        spec = self.specs.get(slot)
        if spec is None or slot.split("-", 1)[0] not in intents:
            return [f"unknown slot {slot} for intent {', '.join(intents)}"]
        if value in (REMOVE, "dontcare"):
            return []
        if spec.kind == "time" and not TIME.match(value):
            return [f"invalid format for slot {slot}: expected HH:MM"]
        if spec.kind == "number" and not NUMBER.match(value):
            return [f"invalid format for slot {slot}: expected a number"]
        if spec.kind == "categorical" and value not in spec.values:
            return [f"invalid value for slot {slot}: expected one of "
                    f"{', '.join((*spec.values, 'dontcare'))}"]
        if slot.endswith(COREF_SLOTS) and value in GENERIC:
            return [f"generic reference '{value}' for slot {slot}: call get_history to resolve "
                    "what it refers to"]
        return []

    # observations -----------------------------------------------------------------------------
    def _slot_definitions(self, intents: list[str]) -> str:
        lines = [s.line() for s in self.specs.values() if s.name.split("-", 1)[0] in intents]
        return "Slots of " + ", ".join(intents) + ":\n" + "\n".join(lines)

    def _history(self, n: int) -> str:
        shown = self.messages[-2 * n - 1:-1] if len(self.messages) > 1 else []
        if not shown:
            return "(no earlier turns)"
        return "\n".join(f"{'user' if m.role == 'user' else 'system'}: {m.text}" for m in shown)

