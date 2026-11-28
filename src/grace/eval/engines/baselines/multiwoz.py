"""MultiWOZ state prediction: the slot projection and the deterministic baselines (plan 6.5, 7.2).

Everything here predicts the cumulative MultiWOZ state after a user turn from visible messages
only: no later turn is read and no gold state is ever fed back (task T028).

**Slot rows.** Every structured internal state is first reduced to slot rows: one row per stance on
an official slot value, with the speaker's role, the communicative function, the version of the
message that expressed it and whether the underlying claim is still currently accepted. Two sources
produce rows:

- `SlotRowExtractor`: one LLM extraction call per message over the 30 official slots, with the
  pinned `extract-slots` prompt of the pilot slot table (T003). It is the shared input of the two
  deterministic baselines below.
- `rows_from_graph`: the claim graph of GRACE at a cut-off version (contracts.md, "Claim graph"),
  through a configurable predicate -> slot mapping. This is "the projection from the claim graph to
  the official slots" (plan 6.5): the same `project` step then serves every system with a
  structured internal state.

**Projection policies** (`project`), each a pure function of the rows with `version <= r`:

- `overwrite` (deterministic overwrite on official slots): every new value of a slot replaces the
  old one, whoever said it; only rejected values are not written.
- `user-only` (the rule that never writes system values): the same, restricted to rows of the
  user. It agrees with the 2.4 convention on offered values by construction and cannot answer
  the "current choice" (plan 6.5).
- `guard` (the attribution guard as a projection): user stances write constraints; a value the
  agent offered enters the state only after the user accepts the offer, and then only into slots
  the user has not constrained; the accepted entity (name, train ID) is the current choice of its
  domain until the user rejects it. Only currently accepted claims count.

The prediction carries the official state; the current choice per domain goes into
`metadata.current_choice` (train IDs are not an official slot).

This module imports nothing from `eval/datasets/` (structure.md): the slot inventory and the
schema are handed in by the caller.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from grace.context import api
from grace.eval.engines.baselines.base import CallTag, ModelPort, pinned_prompt
from grace.llm.structured import extract_json

DOMAINS = ("attraction", "hotel", "restaurant", "taxi", "train")
# Entity slot per domain: the "current choice" of plan 6.5. Train IDs are not an official slot.
ENTITY = {"attraction": "name", "hotel": "name", "restaurant": "name", "train": "trainid"}
FUNCTIONS = ("inform", "request", "confirm", "correct", "offer", "accept", "reject", "other")
NULL_VALUES = {"", "?", "none", "not mentioned", "null"}
DONTCARE = {"dontcare", "dont care", "don't care", "do not care", "do n't care", "any",
            "doesn't matter", "does not matter", "no preference"}
POLICIES = ("overwrite", "user-only", "guard")
USER_WRITES = {"inform", "request", "confirm", "correct", "accept"}
AGENT_PROPOSES = {"offer", "inform", "confirm"}


def norm_value(value: Any) -> str:
    """Stored form of a predicted value: lower case, collapsed spaces, `dontcare` unified."""
    text = re.sub(r"\s+", " ", str(value).strip().lower())
    return "dontcare" if text in DONTCARE else text


def domain_of(slot: str) -> str:
    return slot.split("-", 1)[0]


@dataclass(frozen=True)
class SlotSpec:
    """One official slot as the trackers see it (from the MultiWOZ 2.2 schema)."""

    name: str
    description: str
    kind: str  # categorical, time, number, text
    values: tuple[str, ...] = ()

    def line(self) -> str:
        if self.kind == "categorical":
            allowed = ", ".join((*self.values, "dontcare"))
            return f"- {self.name}: {self.description} (one of: {allowed})"
        form = {"time": "time as HH:MM, 24-hour", "number": "a number"}.get(self.kind, "free text")
        return f"- {self.name}: {self.description} ({form}, or dontcare)"


# ---------------------------------------------------------------------------------------------
# Slot rows and projection


@dataclass(frozen=True)
class SlotRow:
    slot: str  # official slot (`hotel-area`) or a domain's entity slot (`train-trainid`)
    value: str
    role: str  # user or agent
    function: str
    version: int
    message_id: str
    current: bool = True  # the underlying claim is currently accepted (graph rows)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Projection:
    state: dict[str, str]
    current_choice: dict[str, str | None]


def project(rows: Iterable[SlotRow], version: int, policy: str,
            slots: frozenset[str]) -> Projection:
    """The state after the rows with `version <= version` under `policy` (module docstring)."""
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}; one of {POLICIES}")
    rows = sorted((r for r in rows if r.version <= version and r.current),
                  key=lambda r: r.version)
    rows = [r for r in rows if norm_value(r.value) not in NULL_VALUES]
    if policy == "guard":
        return _guard(rows, slots)
    state: dict[str, str] = {}
    for row in rows:
        if row.function == "reject" or (policy == "user-only" and row.role != "user"):
            continue
        if row.slot in slots:
            state[row.slot] = norm_value(row.value)
    choice = {d: state.get(f"{d}-{s}") for d, s in ENTITY.items() if f"{d}-{s}" in slots}
    return Projection(state, choice)


def _guard(rows: Sequence[SlotRow], slots: frozenset[str]) -> Projection:
    state: dict[str, str] = {}
    by_user: set[str] = set()  # slots whose value the user stated
    pending: dict[str, dict[str, str]] = {}  # domain -> slot -> offered value (latest offer turn)
    pending_version: dict[str, int] = {}
    choice: dict[str, str | None] = {d: None for d in ENTITY}

    def accept(domain: str) -> None:
        for slot, value in pending.pop(domain, {}).items():
            entity = ENTITY.get(domain)
            if entity and slot == f"{domain}-{entity}":
                choice[domain] = value
            if slot in slots and slot not in by_user:
                state[slot] = value

    for row in rows:
        domain, value = domain_of(row.slot), norm_value(row.value)
        if row.role != "user":
            if row.function in AGENT_PROPOSES:
                if pending_version.get(domain) != row.version:
                    pending[domain], pending_version[domain] = {}, row.version
                pending[domain][row.slot] = value
            continue
        offered = pending.get(domain, {})
        if row.function == "reject":
            entity = ENTITY.get(domain)
            if entity and row.slot == f"{domain}-{entity}" and choice.get(domain) == value:
                choice[domain] = None
            if offered.get(row.slot) == value:
                pending.pop(domain, None)
            if state.get(row.slot) == value:
                del state[row.slot]
                by_user.discard(row.slot)
            continue
        if row.function in USER_WRITES:
            if offered.get(row.slot) == value or row.function == "accept":
                accept(domain)
            if row.slot in slots:
                state[row.slot] = value
                by_user.add(row.slot)
            entity = ENTITY.get(domain)
            if entity and row.slot == f"{domain}-{entity}":
                choice[domain] = value
    return Projection(state, {d: c for d, c in choice.items()})


# ---------------------------------------------------------------------------------------------
# Claim graph -> slot rows


@dataclass(frozen=True)
class GraphMapping:
    """How claims map to slots: predicate (case-insensitive, separators ignored) -> slot suffix,
    and the predicates that type a subject with its domain (`isA hotel`)."""

    predicates: Mapping[str, str]
    domain_predicates: tuple[str, ...] = ("isa", "type", "domain", "category")

    @staticmethod
    def key(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", name.lower())


def rows_from_graph(state: Any, mapping: GraphMapping, roles: Mapping[str, str]) -> list[SlotRow]:
    """Slot rows of a claim-graph state (`GraphState` at a cut-off; duck-typed so that this module
    needs no import of `context/memory/graph/`).

    The domain of a claim is read from its subject: a domain-typing claim on the subject whose
    object names a domain, else a domain name inside the subject's ID or label. Each attribution
    with report mode `own` gives one row; a negative stance becomes `reject`. `roles` maps a
    speaker as written in attributions to `user` or `agent`."""
    preds = {GraphMapping.key(k): v for k, v in mapping.predicates.items()}
    typing = {GraphMapping.key(p) for p in mapping.domain_predicates}
    domains: dict[str, str] = {}
    for claim in state.claims.values():
        if GraphMapping.key(claim.predicate) in typing:
            name = _object_text(state, claim.object).lower()
            hit = next((d for d in DOMAINS if d in name), None)
            if hit:
                domains.setdefault(claim.subject, hit)
    rows = []
    for claim in sorted(state.claims.values(), key=lambda c: (c.version, c.claim_id)):
        suffix = preds.get(GraphMapping.key(claim.predicate))
        if suffix is None:
            continue
        domain = domains.get(claim.subject) or _domain_in(claim.subject, state)
        if domain is None:
            continue
        value = _object_text(state, claim.object)
        current = state.is_current(claim.claim_id)
        for att in state.attributions_on(claim.claim_id):
            if str(att.report_mode) != "own":
                continue
            function = "reject" if str(att.polarity) == "negative" else str(att.function)
            role = roles.get(att.speaker, "agent")
            rows.append(SlotRow(f"{domain}-{suffix}", value, role, function, att.version,
                                att.message_id, current))
    return rows


def _object_text(state: Any, term: Any) -> str:
    if hasattr(term, "lexical"):
        return term.lexical
    entity = getattr(term, "id", str(term))
    return state.display_name(entity) if hasattr(state, "display_name") else entity


def _domain_in(subject: str, state: Any) -> str | None:
    texts = [subject.lower()]
    if hasattr(state, "display_name"):
        texts.append(state.display_name(subject).lower())
    return next((d for d in DOMAINS for t in texts if d in t), None)


# ---------------------------------------------------------------------------------------------
# Trackers


@dataclass(frozen=True)
class StateOutput:
    """What a tracker returns for one state read (the Prediction fields it decides)."""

    output: str  # state or invalid
    state: dict[str, str] | None
    current_choice: dict[str, str | None]
    raw_output: str | None
    call_ids: tuple[str, ...] = ()
    trace: Mapping[str, Any] | None = None


class SlotRowExtractor:
    """One extraction call per message over the official slots (pinned prompt `extract-slots`).

    Rows of a failed call are lost and counted (`failed_messages`); the run reports them."""

    def __init__(self, model: ModelPort, specs: Sequence[SlotSpec], *,
                 context_messages: int = 1, max_tokens: int = 512):
        self.model, self.context_messages, self.max_tokens = model, context_messages, max_tokens
        self.slots = {s.name: s for s in specs}
        for domain, entity in ENTITY.items():   # entity slots that are not official slots
            name = f"{domain}-{entity}"
            self.slots.setdefault(name, SlotSpec(name, f"the {domain} the user chooses or is "
                                                 "offered, by its ID", "text"))
        self.prompt = pinned_prompt("extract-slots")
        self.slot_text = "\n".join(s.line() for s in self.slots.values())
        self.messages: list[api.Message] = []
        self.rows: list[SlotRow] = []
        self.failed_messages: list[str] = []

    def _parse(self, text: str) -> list[dict[str, str]]:
        data = extract_json(text)
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise ValueError("`entries` must be a list")
        out = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"slot", "value", "function"}:
                raise ValueError(f"bad entry {entry!r}")
            if entry["slot"] not in self.slots or entry["function"] not in FUNCTIONS:
                raise ValueError(f"slot or function outside the schema: {entry!r}")
            if not isinstance(entry["value"], str) or not entry["value"].strip():
                raise ValueError(f"empty value: {entry!r}")
            out.append(entry)
        return out

    def observe(self, message: api.Message) -> tuple[list[SlotRow], list[str]]:
        before = self.messages[-self.context_messages:] if self.context_messages else []
        self.messages.append(message)
        earlier = "\n".join(f"[{m.message_id}] {m.speaker or m.role}: {m.text}" for m in before)
        prompt = self.prompt.render(
            slots=self.slot_text, functions=", ".join(FUNCTIONS), earlier=earlier or "(none)",
            message=f"[{message.message_id}] {message.speaker or message.role} "
                    f"({message.role}): {message.text}")
        tag = CallTag("extract", "write", message.history_id, message.version)
        result = self.model.chat(prompt, tag, prompt_sha256=self.prompt.sha256,
                                 parse=self._parse, max_tokens=self.max_tokens)
        rows = []
        if result.ok:
            role = "user" if message.role == "user" else "agent"
            rows = [SlotRow(e["slot"], e["value"], role, e["function"], message.version,
                            message.message_id) for e in result.parsed]
            self.rows.extend(rows)
        else:
            self.failed_messages.append(message.message_id)
        return rows, list(result.call_ids)


def predict_from_rows(rows: Sequence[SlotRow], task: api.ReadTask, policy: str,
                      slots: frozenset[str]) -> StateOutput:
    """A state read answered by projecting slot rows (no model call)."""
    projection = project(rows, task.version, policy, slots)
    return StateOutput("state", projection.state, projection.current_choice, None, (),
                       {"policy": policy, "rows": sum(r.version <= task.version for r in rows)})


def slot_kinds(schema: Iterable[Mapping[str, Any]], slots: Iterable[str],
               time_slots: Callable[[str], bool] | None = None) -> list[SlotSpec]:
    """`SlotSpec`s of `slots` from MultiWOZ 2.2 `schema.json` services (description and the
    possible values of categorical slots); times and numbers recognised by name."""
    wanted = set(slots)
    is_time = time_slots or (lambda n: n.endswith(("-leaveat", "-arriveby", "-booktime")))
    specs = {}
    for service in schema:
        for slot in service.get("slots", []):
            name = slot["name"]
            if name not in wanted:
                continue
            values = tuple(slot.get("possible_values") or ())
            if is_time(name):
                kind = "time"
            elif slot.get("is_categorical") and values:
                kind = "categorical"
            elif name.endswith(("-bookpeople", "-bookstay", "-stars")):
                kind = "number"
            else:
                kind = "text"
            specs[name] = SlotSpec(name, slot.get("description", name), kind, values)
    missing = wanted - specs.keys()
    if missing:
        raise ValueError(f"schema lacks slots {sorted(missing)}")
    return [specs[n] for n in sorted(specs)]
