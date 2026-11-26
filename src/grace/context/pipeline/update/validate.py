"""Program checks of a claim patch (plan 5.1, write step 3; plan 5.2).

`resolve_patch` turns the writer's surface strings into graph terms, item by item. An item that
fails a check is dropped with a reason (`Dropped`); the rest of the patch stands. Checks:

- **Names.** A subject, entity object or speaker is matched to a known entity ID exactly, then
  to the surface name of a known entity (its label) case-insensitively with whitespace and
  apostrophe variants folded, then to an ID case-insensitively; otherwise the name gets a new
  entity ID (`entity_id`): characters outside `[A-Za-z0-9_]` are removed (apostrophes,
  diacritics) or replaced by `_`, so that every ID is a bare name of the query IR grammar (T017,
  T023) and a safe IRI local name. A different surface name that normalises to a taken ID gets
  the suffix `_2`, `_3`, ... (deterministic in the order names first occur), so two names never
  share an ID by normalisation alone. The surface name is kept as the entity's label
  (`EntityTable.labels`, saved in the writer state). Speakers are entities too, so a
  first-person subject written with the speaker's name is the speaker.
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
- **Ending evidence.** A stance that ends a known claim must quote evidence that mentions that
  claim (`ending_evidence`); the updater drops it otherwise (user decision of 2026-11-26, an
  addition to the removal rule G2(ii) of the guard; decision D010).
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata
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


_APOSTROPHES = re.compile(r"['\u2018\u2019\u02bc`\u00b4]")
_NOT_NAME = re.compile(r"[^A-Za-z0-9_]+")
# Bare names the query IR grammar reads as something else (grammar._KEYWORDS, booleans), compared
# case-insensitively to be safe; pure numbers are read as numbers.
_RESERVED = frozenset({"true", "false", "default", "_", "r"})


def entity_id(name: str) -> str:
    """The base entity ID of a surface name: a bare name of the query IR grammar.

    `Caroline's mom` -> `Carolines_mom`, `José` -> `Jose`, `Rock & roll` -> `Rock_roll`. The
    result matches `[A-Za-z0-9_]+`, is not a pure number and not a reserved word (those get the
    prefix `e_`); a name with no letter or digit becomes `entity`."""
    text = unicodedata.normalize("NFKD", clean_name(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _APOSTROPHES.sub("", text)
    text = _NOT_NAME.sub("_", text).strip("_")
    text = re.sub(r"_+", "_", text) or "entity"
    if text.casefold() in _RESERVED or re.fullmatch(r"\d+", text):
        text = "e_" + text
    return text


def surface_key(name: str) -> str:
    """Key under which surface names are the same name: whitespace, case and apostrophe
    variants folded."""
    return _APOSTROPHES.sub("'", clean_name(name)).casefold()


class EntityTable:
    """Entity IDs known at the writer's head and the surface names (labels) they came from.

    `resolve` (module docstring, "Names") never creates an ID outside `[A-Za-z0-9_]+`. `labels`
    maps every ID the writer created from a different surface name to that name; `new_labels`
    holds the ones created by this table, for the writer state."""

    def __init__(self, known: Iterable[str] = (), labels: Mapping[str, str] | None = None):
        self._ids: set[str] = set()
        self._folded: dict[str, str] = {}     # casefolded ID -> ID
        self._by_key: dict[str, str] = {}     # surface key -> ID
        self.labels: dict[str, str] = {}
        self.new_labels: dict[str, str] = {}
        self.normalised = 0                   # new IDs that differ from their surface name
        for entity in known:
            self.add(entity)
        for entity, label in sorted((labels or {}).items()):
            self.add(entity)
            self.labels[entity] = label
            self._by_key.setdefault(surface_key(label), entity)

    def add(self, entity: str) -> str:
        if entity not in self._ids:
            self._ids.add(entity)
            self._folded.setdefault(entity.casefold(), entity)
            self._by_key.setdefault(surface_key(entity), entity)
        return entity

    def lookup(self, name: str) -> str | None:
        """The known ID `name` denotes, or None."""
        name = clean_name(name)
        if name in self._ids:
            return name
        hit = self._by_key.get(surface_key(name))
        if hit is not None:
            return hit
        return self._folded.get(name.casefold())

    def resolve(self, name: str) -> str:
        """The ID `name` denotes; a new name becomes a new, grammar-safe ID."""
        hit = self.lookup(name)
        if hit is not None:
            return hit
        surface = clean_name(name)
        base = entity_id(surface)
        candidate, n = base, 1
        while candidate.casefold() in self._folded:
            n += 1
            candidate = f"{base}_{n}"
        self.add(candidate)
        self._by_key[surface_key(surface)] = candidate
        if candidate != surface:
            self.labels[candidate] = surface
            self.new_labels[candidate] = surface
            self.normalised += 1
        return candidate

    def label(self, entity: str) -> str:
        return self.labels.get(entity, entity)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.lookup(name) is not None

    @classmethod
    def from_state(cls, state: GraphState, speakers: Iterable[str] = (),
                   labels: Mapping[str, str] | None = None) -> EntityTable:
        """The IDs of `state` with the saved `labels`; speakers are resolved like any name, so
        a speaker name outside the grammar gets a safe ID too."""
        known: list[str] = []
        for c in sorted(state.claims.values(), key=lambda c: (c.version, c.claim_id)):
            known.append(c.subject)
            if isinstance(c.object, Entity):
                known.append(c.object.id)
        for a in sorted(state.attributions.values(), key=lambda a: (a.version, a.attribution_id)):
            known.append(a.speaker)
        for q in state.equivalences.values():
            known += [q.entity_a, q.entity_b]
        table = cls(known, labels)
        for speaker in speakers:
            table.resolve(speaker)
        return table


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


# ---------------------------------------------------------------------------------------------
# Ending evidence (user decision of 2026-11-26; decision D010)

_CAMEL_WORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_ALNUM = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "the and for with that this was are you your have has had not but from they she her his him "
    "its our out all any can did does what when who how why about just like been will would "
    "there their them then than very which where whom into onto over some more most much many "
    "one get got make made thing things really still also even ever yes yeah well "
    # time words: they place a claim in time and name none
    "last next ago since time times day days week weeks month months year years today "
    "yesterday tomorrow now recently lately".split())
# Predicate words that name no particular claim (the catch-all predicates of the smoke run).
_GENERIC_PREDICATE_WORDS = frozenset(
    "is was be experienced experience memory plan intention feel feeling".split())


def _stem(word: str) -> str:
    """Crude stem: `-ing`, `-ed`, a plural `-s` and then a final `-e` removed while three letters
    remain (`hiking`, `hikes`, `hike` -> `hik`)."""
    for suffix in ("ing", "ed"):
        if len(word) >= len(suffix) + 3 and word.endswith(suffix):
            return word[:-len(suffix)]
    if len(word) >= 4 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) >= 4 and word.endswith("e"):
        word = word[:-1]
    return word


def content_words(text: str, *, camel: bool = False) -> set[str]:
    """Stemmed content words of `text`: lower-case runs of letters and digits, at least three
    characters (any number), stop words removed; `camel` splits lowerCamelCase first."""
    if camel:
        text = " ".join(_CAMEL_WORD.findall(text))
    text = text.replace("_", " ").lower()
    return {_stem(w) for w in _ALNUM.findall(text)
            if (len(w) >= 3 or w.isdigit()) and w not in _STOPWORDS}


def ending_evidence(predicate: str, claim_object: Term, quote: str | None,
                    object_label: str | None = None) -> str | None:
    """None when `quote` is evidence for ending the claim, else the reason it is not.

    The check (deliberately conservative; a legitimate ending that names neither is dropped):

    - the stance must carry a quote that was found in its message (`ended_without_quote`);
    - the quote must share a content word (`content_words`: stemmed, three or more letters or a
      number, no stop words) with the claim's object: the entity's label (or its ID with `_` as
      spaces) or the literal's lexical form;
    - only when the object has no content word at all (a boolean or a short literal), the
      predicate's words count instead (lowerCamelCase split, generic words such as `has`,
      `experienced`, `memory`, `plan` removed).

    The predicate alone never suffices when the object has content words, because one predicate
    is shared by many claims: in the smoke run `T022-20261126T184442Z-2a64` one message ended ten
    unrelated claims of its speaker under G2(ii)."""
    if not quote:
        return "ended_without_quote"
    said = content_words(quote)
    if isinstance(claim_object, Entity):
        surface = object_label or claim_object.id
    else:
        surface = "" if claim_object.datatype == "boolean" else claim_object.lexical
    wanted = content_words(surface)
    if not wanted:
        wanted = content_words(predicate, camel=True) - {_stem(w) for w in
                                                         _GENERIC_PREDICATE_WORDS}
    return None if said & wanted else "ended_without_evidence"
