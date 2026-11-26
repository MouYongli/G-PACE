"""E002: one-off claim extraction for the rough natural staleness distribution (plan 6.5).

Phase 1 measures how often each change type occurs in natural dialogue "with a one-off extraction
prompt and hand-written queries" (plan 6.5); phase 3 repeats it with the final writer. This module
is that one-off extraction. It is experiment apparatus, not GRACE's writer (`pipeline/update/`,
T022), and it never sees views.

Per message one `extract` call (trigger `write`, ledger W) with the pinned prompt
`resources/prompts/extract-claims-rough/` returns claims, stances on known claims and known claims
that ended. `HistoryWriter.apply` turns that output into the change set of the message's version
with fixed rules (no model involved):

- **Names.** Subjects and entity objects are matched to known entities case-insensitively; the
  first spelling seen is kept. Predicates are reduced to `[A-Za-z][A-Za-z0-9_]*` lowerCamelCase.
- **Vocabulary.** A predicate keeps the exclusivity of the seed vocabulary
  (`resources/rdf/predicates.yaml`) or, when new, the `single_valued` flag of its first use; it is
  never redefined afterwards (plan 5.2). The per-history table is written to `vocabulary.json`.
- **Repeated mention.** A claim whose (subject, predicate, object) equals a currently accepted
  claim, compared case-insensitively, becomes a new attribution and evidence link on that claim
  (the claim graph forbids repeating a current proposition).
- **Stances.** A stance on a known claim ID becomes an attribution with that function and an
  evidence link.
- **Ended claims.** A known claim reported as no longer true (or wrong) is superseded with kind
  `change` (or `correction`), licensed by a negative-polarity `inform` attribution of the speaker
  on that claim.
- **Exclusivity rule.** A new `inform` claim of an exclusive predicate supersedes, with kind
  `change`, every currently accepted claim with the same subject and predicate and a different
  object, licensed by the new claim's attribution (the replacing claim).

Every attribution has report mode `own`, certainty `certain` and is not derived; every new claim or
attribution gets an evidence link to the whole message (no span). Valid times are left unknown.
Invalid model output gives an empty change set for that message and is counted.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entries import (
    Attribution,
    Certainty,
    Claim,
    CommunicativeFunction,
    Entity,
    EvidenceLink,
    Polarity,
    ReportMode,
    Supersession,
    SupersessionKind,
    ValidTime,
    Value,
)
from grace.context.memory.graph.vocabulary import Vocabulary
from grace.llm.structured import extract_json

CLAIM_FUNCTIONS = ("inform", "request", "offer", "accept", "reject", "confirm", "commit")
STANCE_FUNCTIONS = ("accept", "reject", "confirm")
END_KINDS = ("change", "correction")
OBJECT_KINDS = ("entity", "value")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("the and for with that this was are you your have has had not but from they "
                  "she her his him its our out all any can did does what when who how why "
                  "about just like really been will would there their them then than very".split())


class ExtractionError(ValueError):
    """The model output does not have the shape the prompt asks for."""


# ---------------------------------------------------------------------------------------------
# Parsing


@dataclass(frozen=True)
class NewClaim:
    subject: str
    predicate: str
    object: str
    object_kind: str
    function: str
    single_valued: bool


@dataclass(frozen=True)
class Extraction:
    claims: tuple[NewClaim, ...] = ()
    stances: tuple[tuple[str, str], ...] = ()     # (claim ID, function)
    ended: tuple[tuple[str, str], ...] = ()       # (claim ID, kind)


def _text(item: Mapping[str, Any], key: str) -> str:
    value = item.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not " ".join(value.split()):
        raise ExtractionError(f"{key} must be a non-empty string, got {value!r}")
    return " ".join(value.split())


def parse_output(text: str) -> Extraction:
    """The extraction in `text`; raises ExtractionError on any deviation from the asked shape.

    Items with an unknown function or kind are errors, not silently dropped, so that the invalid
    rate is honest.
    """
    try:
        data = extract_json(text)
    except ValueError as exc:
        raise ExtractionError(str(exc)) from exc
    if not isinstance(data, dict) or not set(data) <= {"claims", "stances", "ended"}:
        raise ExtractionError("expected an object with the keys claims, stances, ended")
    claims, stances, ended = [], [], []
    for item in data.get("claims") or []:
        if not isinstance(item, dict):
            raise ExtractionError(f"claim {item!r} is not an object")
        function = item.get("function", "inform")
        if function not in CLAIM_FUNCTIONS:
            raise ExtractionError(f"claim function {function!r} not in {CLAIM_FUNCTIONS}")
        kind = item.get("object_kind", "value")
        if kind not in OBJECT_KINDS:
            raise ExtractionError(f"object_kind {kind!r} not in {OBJECT_KINDS}")
        single = item.get("single_valued", False)
        if not isinstance(single, bool):
            raise ExtractionError(f"single_valued {single!r} is not a boolean")
        claims.append(NewClaim(_text(item, "subject"), _text(item, "predicate"),
                               _text(item, "object"), kind, function, single))
    for item in data.get("stances") or []:
        if not isinstance(item, dict) or item.get("function") not in STANCE_FUNCTIONS:
            raise ExtractionError(f"bad stance {item!r}")
        stances.append((_text(item, "claim"), item["function"]))
    for item in data.get("ended") or []:
        if not isinstance(item, dict) or item.get("kind") not in END_KINDS:
            raise ExtractionError(f"bad ended entry {item!r}")
        ended.append((_text(item, "claim"), item["kind"]))
    return Extraction(tuple(claims), tuple(stances), tuple(ended))


def predicate_name(text: str) -> str | None:
    """lowerCamelCase predicate name of `text`, or None if nothing usable is left."""
    parts = re.findall(r"[A-Za-z0-9]+", text)
    if not parts:
        return None
    words = []
    for part in parts:
        # keep inner capitals of camelCase input ("livesIn" stays "livesIn")
        words += re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", part) or [part]
    name = words[0].lower() + "".join(w[:1].upper() + w[1:].lower() for w in words[1:])
    if not name[0].isalpha():
        name = "p" + name
    return name


def tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP}


# ---------------------------------------------------------------------------------------------
# Per-history writer


@dataclass
class _Known:
    claim: Claim
    label: str                       # "subject | predicate | object"
    stances: list[str] = field(default_factory=list)   # "speaker function"
    last_version: int = 0
    current: bool = True


@dataclass
class ApplyNotes:
    claims_new: int = 0
    repeated: int = 0
    stances: int = 0
    ended: int = 0
    exclusive_supersessions: int = 0
    dropped: Counter = field(default_factory=Counter)

    def to_record(self) -> dict[str, Any]:
        return {"claims_new": self.claims_new, "repeated": self.repeated,
                "stances": self.stances, "ended": self.ended,
                "exclusive_supersessions": self.exclusive_supersessions,
                "dropped": dict(sorted(self.dropped.items()))}


class HistoryWriter:
    """Deterministic mapping from extractions to change sets for one history (module docstring)."""

    def __init__(self, history_id: str, seed: Vocabulary, *, max_claims: int = 40,
                 max_predicates: int = 60, recent_versions: int = 4):
        self.history_id = history_id
        self.seed = seed
        self.max_claims, self.max_predicates = max_claims, max_predicates
        self.recent_versions = recent_versions
        self.exclusive: dict[str, bool] = {}          # predicate -> exclusive (run-local table)
        self.first_use: dict[str, int] = {}
        self.predicate_uses: Counter = Counter()
        self.entities: dict[str, str] = {}            # casefold -> first spelling
        self.known: dict[str, _Known] = {}            # claim ID -> record
        self._by_key: dict[tuple[str, str, str], str] = {}   # current (s, p, o) casefold -> ID
        self._next = Counter()

    # -- IDs and names -------------------------------------------------------------------------

    def _id(self, kind: str) -> str:
        self._next[kind] += 1
        return f"{kind}{self._next[kind]}"

    def entity(self, name: str) -> str:
        return self.entities.setdefault(name.casefold(), name)

    def is_exclusive(self, predicate: str, proposed: bool, version: int) -> bool:
        if predicate not in self.exclusive:
            if predicate in self.seed:
                self.exclusive[predicate] = self.seed.is_exclusive(predicate)
            else:
                self.exclusive[predicate] = proposed
            self.first_use[predicate] = version
        return self.exclusive[predicate]

    def vocabulary_record(self) -> dict[str, Any]:
        return {p: {"exclusive": self.exclusive[p], "first_version": self.first_use[p],
                    "uses": self.predicate_uses[p]} for p in sorted(self.exclusive)}

    # -- prompt inputs -------------------------------------------------------------------------

    def predicate_lines(self) -> str:
        top = [p for p, _ in self.predicate_uses.most_common(self.max_predicates)]
        if not top:
            return "(none yet)"
        return "\n".join(f"{p}: {'single' if self.exclusive[p] else 'multi'}" for p in top)

    def claim_lines(self, text: str, version: int) -> str:
        """The known claims shown to the model: current claims ranked by word overlap with the
        message and its context, the claims touched in the last few versions first."""
        words = tokens(text)
        scored = []
        for cid, k in self.known.items():
            if not k.current:
                continue
            recent = k.last_version >= version - self.recent_versions
            overlap = len(words & tokens(k.label))
            if recent or overlap:
                scored.append((not recent, -overlap, -k.last_version, cid))
        chosen = sorted(scored)[:self.max_claims]
        if not chosen:
            return "(none)"
        lines = []
        for *_, cid in sorted(chosen, key=lambda s: int(s[3][1:])):
            k = self.known[cid]
            lines.append(f"{cid}: {k.label} | {', '.join(k.stances[-3:])}")
        return "\n".join(lines)

    # -- applying an extraction ----------------------------------------------------------------

    def _key(self, subject: str, predicate: str, obj: str) -> tuple[str, str, str]:
        return (subject.casefold(), predicate, obj.casefold())

    def apply(self, extraction: Extraction, *, version: int, message_id: str, speaker: str
              ) -> tuple[ChangeSet, ApplyNotes]:
        notes = ApplyNotes()
        claims: list[Claim] = []
        attributions: list[Attribution] = []
        evidence: list[EvidenceLink] = []
        supersessions: list[Supersession] = []
        touched: dict[str, str] = {}                    # claim ID -> stance text for _Known
        ending: dict[str, tuple[str, str | None, str]] = {}   # claim -> (kind, replacing, licence)
        attributed: set[tuple[str, str]] = set()        # (claim ID, function) this version

        def attribute(cid: str, function: str, polarity: Polarity = Polarity.POSITIVE) -> str:
            aid = self._id("a")
            attributions.append(Attribution(aid, cid, speaker, CommunicativeFunction(function),
                                            ReportMode.OWN, polarity, Certainty.CERTAIN, False,
                                            message_id, version))
            if not any(e.claim_id == cid for e in evidence):
                evidence.append(EvidenceLink(self._id("e"), cid, message_id, None, version))
            attributed.add((cid, function))
            sign = "" if polarity is Polarity.POSITIVE else "not "
            touched[cid] = f"{speaker} {sign}{function}"
            return aid

        for item in extraction.claims:
            predicate = predicate_name(item.predicate)
            if predicate is None:
                notes.dropped["bad_predicate"] += 1
                continue
            subject = self.entity(item.subject)
            obj = self.entity(item.object) if item.object_kind == "entity" else item.object
            exclusive = self.is_exclusive(predicate, item.single_valued, version)
            self.predicate_uses[predicate] += 1
            key = self._key(subject, predicate, obj)
            new_ids = {c.claim_id for c in claims}
            if key in self._by_key:                     # repeated mention of a current claim
                cid = self._by_key[key]
                if (cid, item.function) in attributed:
                    notes.dropped["duplicate_in_message"] += 1
                    continue
                if cid not in new_ids:
                    notes.repeated += 1
                attribute(cid, item.function)
                continue
            cid = self._id("c")
            term = Entity(obj) if item.object_kind == "entity" else Value(obj)
            claim = Claim(cid, subject, predicate, term, None, ValidTime(), version)
            claims.append(claim)
            self.known[cid] = _Known(claim, f"{subject} | {predicate} | {obj}")
            self._by_key[key] = cid
            notes.claims_new += 1
            aid = attribute(cid, item.function)
            if exclusive and item.function == "inform":
                for other_key, other in list(self._by_key.items()):
                    if (other_key[:2] == key[:2] and other_key != key
                            and other not in new_ids and other not in ending):
                        ending[other] = ("change", cid, aid)
                        notes.exclusive_supersessions += 1

        for cid, function in extraction.stances:
            k = self.known.get(cid)
            if k is None or not k.current:
                notes.dropped["stance_unknown_claim"] += 1
                continue
            if (cid, function) in attributed:
                notes.dropped["duplicate_in_message"] += 1
                continue
            attribute(cid, function)
            notes.stances += 1

        new_ids = {c.claim_id for c in claims}
        for cid, kind in extraction.ended:
            k = self.known.get(cid)
            if k is None or not k.current or cid in new_ids:
                notes.dropped["ended_unknown_claim"] += 1
                continue
            if cid in ending:                           # the exclusivity rule already ends it
                old_kind, replacing, licence = ending[cid]
                ending[cid] = (kind, replacing, licence)
                continue
            licence = attribute(cid, "inform", Polarity.NEGATIVE)
            ending[cid] = (kind, None, licence)
            notes.ended += 1

        for cid, (kind, replacing, licence) in ending.items():
            supersessions.append(Supersession(self._id("s"), cid, SupersessionKind(kind), None,
                                              replacing, licence, version))
            k = self.known[cid]
            k.current = False
            self._by_key.pop(self._key(k.claim.subject, k.claim.predicate,
                                       _object_text(k.claim)), None)
        for cid, stance in touched.items():
            k = self.known[cid]
            k.stances.append(stance)
            k.last_version = version

        cs = ChangeSet(self.history_id, version, tuple(claims), tuple(attributions),
                       tuple(evidence), tuple(supersessions))
        return cs, notes


def _object_text(claim: Claim) -> str:
    obj = claim.object
    return obj.id if isinstance(obj, Entity) else obj.lexical


# ---------------------------------------------------------------------------------------------
# Prompt values


def clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + " [...]", True


def prompt_values(writer: HistoryWriter, message, earlier: Sequence, participants: str,
                  date: str | None, *, message_chars: int, earlier_chars: int
                  ) -> tuple[dict[str, str], bool]:
    """Values of the prompt's placeholders, and whether the message was clipped."""
    text, clipped = clip(message.text, message_chars)
    earlier_lines = []
    for m in earlier:
        line, _ = clip(m.text, earlier_chars)
        earlier_lines.append(f"{m.speaker or m.role}: {line}")
    context = " ".join([text, *earlier_lines])
    values = {"participants": participants, "date": date or "unknown",
              "predicates": writer.predicate_lines(),
              "claims": writer.claim_lines(context, message.version),
              "earlier": "\n".join(earlier_lines) or "(none)",
              "speaker": message.speaker or message.role, "message": text}
    return values, clipped


def extraction_record(history_id: str, message, *, status: str, error: str | None,
                      raw: str | None, notes: ApplyNotes | None, call_ids: Sequence[str],
                      clipped: bool) -> dict[str, Any]:
    return {"history_id": history_id, "version": message.version,
            "message_id": message.message_id, "status": status, "error": error,
            "clipped": clipped, "call_ids": list(call_ids), "raw_output": raw,
            "notes": notes.to_record() if notes else None}


def dumps(record: Mapping[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------------------------
# Driver for one history


@dataclass(frozen=True)
class Settings:
    message_chars: int = 8000
    earlier_messages: int = 2
    earlier_chars: int = 600
    max_claims: int = 40
    max_predicates: int = 60
    recent_versions: int = 4


@dataclass
class HistoryExtraction:
    history_id: str
    changesets: list[ChangeSet] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)
    vocabulary: dict[str, Any] = field(default_factory=dict)
    status: Counter = field(default_factory=Counter)


def extract_history(history, messages: Sequence, chat, prompt, seed: Vocabulary, *,
                    participants: str, settings: Settings = Settings(),
                    on_message=None) -> HistoryExtraction:
    """Extract every message of one history in version order.

    `chat(rendered_messages, version) -> (text | None, status, error, call_ids)` makes one logical
    call through `grace.llm` (status `ok`, `invalid_output` or `failed`); `prompt` is the pinned
    `grace.llm.prompts.Prompt`. A failed call or invalid output leaves the version's change set
    empty; the record keeps the status and the raw output.
    """
    writer = HistoryWriter(history.history_id, seed, max_claims=settings.max_claims,
                           max_predicates=settings.max_predicates,
                           recent_versions=settings.recent_versions)
    for m in messages:
        if m.speaker:
            writer.entity(m.speaker)
    dates = {s.segment_id: s.timestamp for s in history.segments}
    out = HistoryExtraction(history.history_id)
    for i, message in enumerate(messages):
        start = time.perf_counter()
        earlier = messages[max(0, i - settings.earlier_messages):i]
        date = message.timestamp or dates.get(message.segment_id)
        values, clipped = prompt_values(writer, message, earlier, participants, date,
                                        message_chars=settings.message_chars,
                                        earlier_chars=settings.earlier_chars)
        text, status, error, call_ids = chat(prompt.render(**values), message.version)
        model_ms = (time.perf_counter() - start) * 1000
        extraction = Extraction()
        if status == "ok":
            try:
                extraction = parse_output(text or "")
            except ExtractionError as exc:
                status, error = "invalid_output", str(exc)
        cs, notes = writer.apply(extraction, version=message.version,
                                 message_id=message.message_id,
                                 speaker=message.speaker or message.role)
        out.changesets.append(cs)
        out.status[status] += 1
        out.records.append(extraction_record(history.history_id, message, status=status,
                                             error=error, raw=text, notes=notes,
                                             call_ids=call_ids, clipped=clipped))
        apply_ms = (time.perf_counter() - start) * 1000 - model_ms
        out.traces.append({"history_id": history.history_id, "version": message.version,
                           "message_ids": [message.message_id], "call_ids": list(call_ids),
                           "stale_marks": [],
                           "timings_ms": {"extract": round(model_ms, 3),
                                          "apply": round(apply_ms, 3)}})
        if on_message is not None:
            on_message(history.history_id, message.version, status)
    out.vocabulary = writer.vocabulary_record()
    return out
