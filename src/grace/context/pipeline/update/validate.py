"""Program checks of a claim patch (plan 5.1, write step 3; plan 5.2).

`resolve_patch` turns the writer's surface strings into graph terms, item by item. An item that
fails a check is dropped with a reason (`Dropped`); the rest of the patch stands. Checks:

- **Names.** A subject, entity object or speaker is matched to a known entity ID exactly, then
  case-insensitively with whitespace folded; otherwise the cleaned name becomes a new entity ID.
  Speakers are entities too, so a first-person subject written with the speaker's name is the
  speaker.
- **Predicates.** A name or alias of the vocabulary in force resolves to its predicate. Otherwise
  the name is reduced to lowerCamelCase and, under the `local` policy, added to a history-local
  extension of the vocabulary with the writer's exclusivity proposal (default multi-valued, the
  side that never supersedes); it is never redefined afterwards (plan 5.2: old definitions are
  kept). Under the `drop` policy the item is dropped. Vocabulary maintenance by an LLM call
  (aliases, splits; T032) is out of scope here.
- **Objects.** Literal objects must have the canonical lexical form of their datatype; a few
  unambiguous forms are normalised (`20:45` -> `20:45:00`, `+3` -> `3`, `True` -> `true`).
- **Valid time.** Bounds must be ISO dates or date-times of one datatype with start before end;
  otherwise the bounds are dropped and only the source phrase is kept (no date is invented).
- **Span anchors.** The quote is located in the message text (`history.spans.anchor_quote`); a
  quote that does not occur leaves a whole-message evidence link and is counted.
- **Claim references.** A stance names a handle `k<i>` of this call's known claims or a local ID
  `n<i>` of a claim of the same patch stated in the same or an earlier message.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from grace.context.api import Message
from grace.context.memory.graph.entries import (
    Certainty,
    CommunicativeFunction,
    Entity,
    EntryError,
    Polarity,
    ReportMode,
    Span,
    SupersessionKind,
    Term,
    ValidTime,
    Value,
)
from grace.context.memory.graph.store import GraphState
from grace.context.memory.graph.vocabulary import Vocabulary, VocabularyError
from grace.context.memory.history.spans import SpanError, anchor_quote
from grace.context.pipeline.update.patch import ClaimPatch, PatchClaim, PatchStance, StanceFields

POLICIES = ("local", "drop")


# ---------------------------------------------------------------------------------------------
# Vocabulary


def predicate_name(text: str) -> str | None:
    """lowerCamelCase predicate name of `text` (`lives in` -> `livesIn`), or None."""
    parts = re.findall(r"[A-Za-z0-9]+", text)
    if not parts:
        return None
    pieces: list[str] = []
    for part in parts:
        pieces += re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", part) or [part]
    name = pieces[0].lower() + "".join(w[:1].upper() + w[1:].lower() for w in pieces[1:])
    return name if name[0].isalpha() else "p" + name


class LocalVocabulary:
    """The seed vocabulary plus the predicates first used in this history.

    Every extension produces a new `Vocabulary` with the label `<seed>+<n>`; change sets record the
    label in force (contracts.md, "Claim graph": `vocabulary_version`), so that the engine can
    invalidate views when it changes (plan 3.2, 5.2).
    """

    def __init__(self, seed: Vocabulary, policy: str = "local"):
        if policy not in POLICIES:
            raise ValueError(f"unknown-predicate policy must be one of {POLICIES}")
        self.seed = seed
        self.policy = policy
        self.current = seed
        self.added: list[dict] = []          # {name, exclusive, version}
        self.uses: Counter = Counter()

    @property
    def version(self) -> str:
        return self.current.version

    def resolve(self, name: str) -> str | None:
        """The predicate `name` denotes in the vocabulary in force, or None."""
        try:
            return self.current.resolve(name)
        except VocabularyError:
            pass
        normalised = predicate_name(name)
        if normalised is not None and normalised in self.current:
            return normalised
        return None

    def add(self, name: str, exclusive: bool, version: int) -> str | None:
        """Add predicate `name` (normalised) under the local policy; None under `drop`."""
        normalised = predicate_name(name)
        if self.policy == "drop" or normalised is None:
            return None
        if normalised in self.current:
            return normalised
        label = f"{self.seed.version}+{len(self.added) + 1}"
        self.current = self.current.extend(label, predicates={normalised: bool(exclusive)})
        self.added.append({"name": normalised, "exclusive": bool(exclusive), "version": version,
                           "vocabulary_version": label})
        return normalised

    def is_exclusive(self, predicate: str) -> bool:
        return self.current.predicates[predicate].exclusive

    def to_record(self) -> dict:
        return {"seed": self.seed.version, "policy": self.policy, "added": list(self.added),
                "uses": dict(sorted(self.uses.items()))}

    @classmethod
    def from_record(cls, seed: Vocabulary, record: Mapping) -> LocalVocabulary:
        if record.get("seed") != seed.version:
            raise ValueError(f"local vocabulary was built on seed {record.get('seed')!r}, not "
                             f"{seed.version!r}")
        out = cls(seed, record.get("policy", "local"))
        for item in record.get("added", ()):
            out.current = out.current.extend(item["vocabulary_version"],
                                             predicates={item["name"]: item["exclusive"]})
            out.added.append(dict(item))
        out.uses.update(record.get("uses", {}))
        return out


# ---------------------------------------------------------------------------------------------
# Entities


def clean_name(text: str) -> str:
    return " ".join(text.split())


class EntityTable:
    """Entity IDs known at the writer's head, matched exactly or case-insensitively."""

    def __init__(self, known: Iterable[str] = ()):
        self._ids: set[str] = set()
        self._folded: dict[str, str] = {}
        for entity in known:
            self.add(entity)

    def add(self, entity: str) -> str:
        if entity not in self._ids:
            self._ids.add(entity)
            self._folded.setdefault(entity.casefold(), entity)
        return entity

    def resolve(self, name: str) -> str:
        """The ID `name` denotes; a new name becomes a new ID."""
        name = clean_name(name)
        if name in self._ids:
            return name
        folded = self._folded.get(name.casefold())
        return folded if folded is not None else self.add(name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and (name in self._ids
                                          or clean_name(name).casefold() in self._folded)

    @classmethod
    def from_state(cls, state: GraphState, speakers: Iterable[str] = ()) -> EntityTable:
        known: list[str] = list(speakers)
        for c in sorted(state.claims.values(), key=lambda c: (c.version, c.claim_id)):
            known.append(c.subject)
            if isinstance(c.object, Entity):
                known.append(c.object.id)
        for a in sorted(state.attributions.values(), key=lambda a: (a.version, a.attribution_id)):
            known.append(a.speaker)
        for q in state.equivalences.values():
            known += [q.entity_a, q.entity_b]
        return cls(known)


def speaker_of(message: Message) -> str:
    return clean_name(message.speaker or message.role)


# ---------------------------------------------------------------------------------------------
# Literals and valid time

_TIME_HM = re.compile(r"(\d{1,2}):(\d{2})")
_TIME_HMS = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")


def resolve_value(text: str, datatype: str) -> Value:
    """A canonical literal; raises EntryError when `text` has no canonical form."""
    raw = text.strip()
    if datatype == "time":
        if m := _TIME_HM.fullmatch(raw):
            raw = f"{int(m[1]):02d}:{m[2]}:00"
        elif m := _TIME_HMS.fullmatch(raw):
            raw = f"{int(m[1]):02d}:{m[2]}:{m[3]}"
    elif datatype == "integer":
        candidate = raw.replace(",", "").lstrip("+")
        if re.fullmatch(r"-?\d+", candidate):
            raw = str(int(candidate))
    elif datatype == "boolean":
        raw = raw.lower()
    elif datatype == "string":
        raw = clean_name(raw)
    return Value(raw, datatype)


def _bound(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    try:
        if "T" in value:
            _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            _dt.date.fromisoformat(value)
    except ValueError:
        raise EntryError(f"{value!r} is not an ISO date or date-time") from None
    return value


def resolve_valid_time(start: str | None, end: str | None,
                       expression: str | None) -> tuple[ValidTime, str | None]:
    """(valid time, note). Bad bounds are dropped; the phrase is kept, never a guessed date."""
    try:
        return ValidTime(_bound(start), _bound(end), expression), None
    except EntryError as exc:
        phrase = expression or " - ".join(x for x in (start, end) if x) or None
        return ValidTime(None, None, phrase), f"valid_time: {exc}"


# ---------------------------------------------------------------------------------------------
# Resolved items


@dataclass(frozen=True)
class Stance:
    function: CommunicativeFunction
    report_mode: ReportMode
    polarity: Polarity
    certainty: Certainty
    derived: bool

    @classmethod
    def of(cls, fields_: StanceFields) -> Stance:
        return cls(CommunicativeFunction(fields_.function), ReportMode(fields_.report_mode),
                   Polarity(fields_.polarity), Certainty(fields_.certainty), fields_.derived)


@dataclass(frozen=True)
class ResolvedClaim:
    message: Message
    speaker: str
    subject: str
    predicate: str
    object: Term
    scope: str | None
    valid_time: ValidTime
    stance: Stance
    exclusive: bool
    correction: bool
    local_id: str | None
    span: Span | None


@dataclass(frozen=True)
class ResolvedStance:
    message: Message
    speaker: str
    claim: str           # a claim ID (from a handle) or a local ID n<i> of this patch
    local: bool
    stance: Stance
    ends: SupersessionKind | None
    valid_end: str | None
    span: Span | None


@dataclass(frozen=True)
class ResolvedAlias:
    message: Message
    entity_a: str
    entity_b: str


@dataclass(frozen=True)
class Dropped:
    item: str            # claims[i], stances[i], same_as[i]
    reason: str
    detail: str = ""

    def to_record(self) -> dict:
        return {"item": self.item, "reason": self.reason, "detail": self.detail}


@dataclass
class Resolution:
    claims: list[ResolvedClaim] = field(default_factory=list)
    stances: list[ResolvedStance] = field(default_factory=list)
    aliases: list[ResolvedAlias] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    notes: Counter = field(default_factory=Counter)

    def for_message(self, version: int):
        return ([c for c in self.claims if c.message.version == version],
                [s for s in self.stances if s.message.version == version],
                [a for a in self.aliases if a.message.version == version])


def _span(message: Message, quote: str | None, notes: Counter) -> Span | None:
    if not quote:
        return None
    try:
        anchor = anchor_quote(message, quote)
    except SpanError:
        stripped = quote.strip().strip('"').strip()
        try:
            anchor = anchor_quote(message, stripped) if stripped else None
        except SpanError:
            anchor = None
    if anchor is None:
        notes["quote_not_found"] += 1
        return None
    return Span(anchor.start, anchor.end)


def resolve_patch(patch: ClaimPatch, messages: Sequence[Message], vocabulary: LocalVocabulary,
                  entities: EntityTable, handles: Mapping[str, str]) -> Resolution:
    """Resolve every item of `patch` against the unit `messages` (numbered from 1)."""
    out = Resolution()
    local_messages: dict[str, int] = {}
    for i, item in enumerate(patch.claims, start=1):
        where = f"claims[{i}]"
        resolved = _resolve_claim(item, where, messages, vocabulary, entities, out)
        if resolved is not None:
            out.claims.append(resolved)
            if item.local_id is not None:
                local_messages[item.local_id] = item.message
    for i, item in enumerate(patch.stances, start=1):
        where = f"stances[{i}]"
        resolved = _resolve_stance(item, where, messages, entities, handles, local_messages,
                                   out)
        if resolved is not None:
            out.stances.append(resolved)
    for i, item in enumerate(patch.aliases, start=1):
        a, b = entities.resolve(item.name), entities.resolve(item.same_as)
        if a == b:
            out.dropped.append(Dropped(f"same_as[{i}]", "same_entity", a))
            continue
        out.aliases.append(ResolvedAlias(messages[item.message - 1], a, b))
    return out


def _resolve_claim(item: PatchClaim, where: str, messages: Sequence[Message],
                   vocabulary: LocalVocabulary, entities: EntityTable,
                   out: Resolution) -> ResolvedClaim | None:
    message = messages[item.message - 1]
    try:
        if item.object_type == "entity":
            obj: Term = Entity(entities.resolve(item.object))
        else:
            obj = resolve_value(item.object, item.object_type)
    except EntryError as exc:
        out.dropped.append(Dropped(where, "bad_object", str(exc)))
        return None
    predicate = vocabulary.resolve(item.predicate)
    if predicate is None:   # only an item that passed every other check extends the vocabulary
        predicate = vocabulary.add(item.predicate, bool(item.exclusive), message.version)
        if predicate is None:
            out.dropped.append(Dropped(where, "unknown_predicate", item.predicate))
            return None
        out.notes["new_predicate"] += 1
    vocabulary.uses[predicate] += 1
    valid_time, note = resolve_valid_time(item.valid_from, item.valid_until,
                                          item.time_expression)
    if note:
        out.notes["bad_valid_time"] += 1
    stance = Stance.of(item.stance)
    return ResolvedClaim(message=message, speaker=entities.resolve(speaker_of(message)),
                         subject=entities.resolve(item.subject), predicate=predicate, object=obj,
                         scope=item.scope, valid_time=valid_time, stance=stance,
                         exclusive=vocabulary.is_exclusive(predicate),
                         correction=item.correction, local_id=item.local_id,
                         span=_span(message, item.quote, out.notes))


def _resolve_stance(item: PatchStance, where: str, messages: Sequence[Message],
                    entities: EntityTable,
                    handles: Mapping[str, str], local_messages: Mapping[str, int],
                    out: Resolution) -> ResolvedStance | None:
    message = messages[item.message - 1]
    if item.claim.startswith("k"):
        if item.claim not in handles:
            out.dropped.append(Dropped(where, "unknown_handle", item.claim))
            return None
        claim, local = handles[item.claim], False
    else:
        if item.claim not in local_messages:
            out.dropped.append(Dropped(where, "unknown_local_id", item.claim))
            return None
        if local_messages[item.claim] > item.message:
            out.dropped.append(Dropped(where, "stance_before_claim", item.claim))
            return None
        claim, local = item.claim, True
    valid_end = None
    if item.valid_until is not None:
        try:
            valid_end = _bound(item.valid_until)
        except EntryError:
            out.notes["bad_valid_time"] += 1
    speaker = entities.resolve(speaker_of(message))
    return ResolvedStance(message=message, speaker=speaker, claim=claim, local=local,
                          stance=Stance.of(item.stance),
                          ends=SupersessionKind(item.ends) if item.ends else None,
                          valid_end=valid_end, span=_span(message, item.quote, out.notes))
