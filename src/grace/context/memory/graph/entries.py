"""The four kinds of claim-graph entries (plan sections 3.2 and 5.2; contracts.md, "Claim graph").

- `Claim` (s, p, o, scope, valid time, knowledge version): the proposition, never who stated it.
- `Attribution` (speaker, claim, communicative function, report mode, polarity, certainty,
  knowledge version): one stance of one speaker on one claim.
- `EvidenceLink` (claim, message span, knowledge version).
- `Supersession` (claim, supersession version, kind): from that version on the claim is no longer
  currently accepted; kind `change` keeps it in the past state, `correction` removes it there too.

Every entry carries the version stamp of the commit that added it. Entries are frozen data classes
and carry no query logic, so the generator of the controlled change sequences can share them
(docs/research/change-sequences.md, section 6.4). `to_record` and `from_record` give the JSON form
stored in change sets; `from_record` rejects missing, unknown and mistyped fields.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any


class EntryError(ValueError):
    """An entry or a change set violates the claim-graph contract; the message names the field."""


class CommunicativeFunction(StrEnum):
    """Communicative-function axis of an attribution (plan 5.2; ISO 24617-2 correspondences in
    resources/rdf/functions.ttl)."""

    REQUEST = "request"
    OFFER = "offer"
    ACCEPT = "accept"
    REJECT = "reject"
    CONFIRM = "confirm"
    INFORM = "inform"
    COMMIT = "commit"
    QUESTION = "question"


class ReportMode(StrEnum):
    """Report-mode axis of an attribution: own statement, quoting another, hypothetical."""

    OWN = "own"
    QUOTE = "quote"
    HYPOTHETICAL = "hypothetical"


class Polarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class Certainty(StrEnum):
    """Certainty of a stance, following the GRaSP factuality values."""

    CERTAIN = "certain"
    PROBABLE = "probable"
    POSSIBLE = "possible"
    UNDERSPECIFIED = "underspecified"


class SupersessionKind(StrEnum):
    CHANGE = "change"
    CORRECTION = "correction"


# Datatypes an object literal may carry (XSD local names), with the canonical lexical form the
# store keeps unchanged. Non-canonical forms are rejected so that every serialisation round-trips.
_DATE = r"\d{4}-\d{2}-\d{2}"
_TIME = r"\d{2}:\d{2}:\d{2}"
_ZONE = r"(Z|[+-]\d{2}:\d{2})?"
_LEXICAL = {
    "string": None,
    "integer": re.compile(r"-?(0|[1-9]\d*)"),
    "boolean": re.compile(r"true|false"),
    "date": re.compile(_DATE),
    "dateTime": re.compile(_DATE + "T" + _TIME + _ZONE),
    "time": re.compile(_TIME),
}
DATATYPES = frozenset(_LEXICAL)
_ID = re.compile(r"\S(.*\S)?", re.DOTALL)


def _check_id(owner: str, name: str, value: Any) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise EntryError(f"{owner}.{name}: expected a non-empty string without surrounding "
                         f"whitespace, got {value!r}")


def _check_version(owner: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise EntryError(f"{owner}.version: expected an integer >= 1, got {value!r}")


def _check_enum(owner: str, name: str, value: Any, enum: type[StrEnum]) -> None:
    if not isinstance(value, enum):
        raise EntryError(f"{owner}.{name}: expected one of {[m.value for m in enum]}, "
                         f"got {value!r}")


def _check_lexical(owner: str, name: str, value: Any, datatype: str) -> None:
    if not isinstance(value, str):
        raise EntryError(f"{owner}.{name}: expected a string, got {value!r}")
    pattern = _LEXICAL[datatype]
    if pattern is not None and not pattern.fullmatch(value):
        raise EntryError(f"{owner}.{name}: {value!r} is not a canonical xsd:{datatype}")
    try:
        if datatype == "date":
            _dt.date.fromisoformat(value)
        elif datatype == "dateTime":
            _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif datatype == "time":
            _dt.time.fromisoformat(value)
    except ValueError as exc:
        raise EntryError(f"{owner}.{name}: {value!r} is not a valid xsd:{datatype}") from exc


def time_datatype(value: str) -> str:
    """`date` or `dateTime`: the XSD datatype of a valid-time bound."""
    return "dateTime" if "T" in value else "date"


# ---------------------------------------------------------------------------------------------
# Terms


@dataclass(frozen=True, order=True)
class Entity:
    """An entity (person, item, task, event) named by a history-local ID."""

    id: str

    def __post_init__(self) -> None:
        _check_id("Entity", "id", self.id)

    def to_record(self) -> dict[str, Any]:
        return {"entity": self.id}


@dataclass(frozen=True, order=True)
class Value:
    """A literal object: lexical form and XSD datatype local name (one of `DATATYPES`)."""

    lexical: str
    datatype: str = "string"

    def __post_init__(self) -> None:
        if self.datatype not in DATATYPES:
            raise EntryError(f"Value.datatype: {self.datatype!r} not in {sorted(DATATYPES)}")
        _check_lexical("Value", "lexical", self.lexical, self.datatype)

    def to_record(self) -> dict[str, Any]:
        return {"value": self.lexical, "datatype": self.datatype}


Term = Entity | Value


def term_from_record(record: Any, owner: str) -> Term:
    if isinstance(record, Mapping) and set(record) == {"entity"}:
        return Entity(record["entity"])
    if isinstance(record, Mapping) and set(record) == {"value", "datatype"}:
        return Value(record["value"], record["datatype"])
    raise EntryError(f"{owner}.object: expected {{entity}} or {{value, datatype}}, got {record!r}")


@dataclass(frozen=True)
class ValidTime:
    """Valid time [start, end) of a claim (OWL-Time interval, left-closed, right-open).

    `None` bounds are unknown (start) or open (end); no date is invented (plan 5.2). Bounds are
    canonical xsd:date or xsd:dateTime forms of the same datatype. `expression` keeps the source
    phrase ("last week") when the bounds could not be resolved, or alongside them.
    """

    start: str | None = None
    end: str | None = None
    expression: str | None = None

    def __post_init__(self) -> None:
        for name in ("start", "end"):
            value = getattr(self, name)
            if value is not None:
                _check_lexical("ValidTime", name, value, time_datatype(value))
        if self.start is not None and self.end is not None:
            if time_datatype(self.start) != time_datatype(self.end):
                raise EntryError("ValidTime: start and end must share one datatype")
            if not _as_datetime(self.start) < _as_datetime(self.end):
                raise EntryError(f"ValidTime: start {self.start} is not before end {self.end}")
        if self.expression is not None:
            _check_id("ValidTime", "expression", self.expression)

    @property
    def unknown(self) -> bool:
        return self.start is None and self.end is None and self.expression is None

    def to_record(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "expression": self.expression}


def _as_datetime(value: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _record(entry: Any) -> dict[str, Any]:
    out = {}
    for f in fields(entry):
        value = getattr(entry, f.name)
        if isinstance(value, (Entity, Value, ValidTime, Span)):
            value = value.to_record()
        elif isinstance(value, StrEnum):
            value = value.value
        out[f.name] = value
    return out


def _fields(cls: type, record: Any) -> dict[str, Any]:
    name = cls.__name__
    if not isinstance(record, Mapping):
        raise EntryError(f"{name}: expected an object, got {type(record).__name__}")
    expected = {f.name for f in fields(cls)}
    if unknown := sorted(record.keys() - expected):
        raise EntryError(f"{name}: unknown fields {unknown}")
    if missing := sorted(expected - record.keys()):
        raise EntryError(f"{name}: missing fields {missing}")
    return dict(record)


def _enum(cls: type, name: str, enum: type[StrEnum], value: Any) -> StrEnum:
    try:
        return enum(value)
    except ValueError as exc:
        raise EntryError(f"{cls.__name__}.{name}: {value!r} not in "
                         f"{[m.value for m in enum]}") from exc


# ---------------------------------------------------------------------------------------------
# The four entry kinds


@dataclass(frozen=True)
class Claim:
    """A proposition (s, p, o, scope, valid time) first produced at knowledge version `version`.

    `predicate` is a predicate name of the vocabulary; `scope` is `None` for the default scope.
    """

    claim_id: str
    subject: str
    predicate: str
    object: Term
    scope: str | None
    valid_time: ValidTime
    version: int

    def __post_init__(self) -> None:
        for name in ("claim_id", "subject", "predicate"):
            _check_id("Claim", name, getattr(self, name))
        if not isinstance(self.object, (Entity, Value)):
            raise EntryError(f"Claim.object: expected Entity or Value, got {self.object!r}")
        if self.scope is not None:
            _check_id("Claim", "scope", self.scope)
        if not isinstance(self.valid_time, ValidTime):
            raise EntryError(f"Claim.valid_time: expected ValidTime, got {self.valid_time!r}")
        _check_version("Claim", self.version)

    @property
    def entry_id(self) -> str:
        return self.claim_id

    @property
    def proposition(self) -> tuple:
        """The key (s, p, o, scope, valid time) that a repeated mention must not duplicate."""
        return (self.subject, self.predicate, self.object, self.scope, self.valid_time)

    def to_record(self) -> dict[str, Any]:
        return _record(self)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Claim:
        data = _fields(cls, record)
        data["object"] = term_from_record(data["object"], "Claim")
        valid = data["valid_time"]
        if not isinstance(valid, Mapping) or set(valid) != {"start", "end", "expression"}:
            raise EntryError("Claim.valid_time: expected {start, end, expression}, "
                             f"got {valid!r}")
        data["valid_time"] = ValidTime(**valid)
        return cls(**data)


@dataclass(frozen=True)
class Attribution:
    """One stance of `speaker` towards claim `claim_id`, expressed in message `message_id`.

    `derived` marks an assistant restatement, which is not independent support (plan 5.2).
    """

    attribution_id: str
    claim_id: str
    speaker: str
    function: CommunicativeFunction
    report_mode: ReportMode
    polarity: Polarity
    certainty: Certainty
    derived: bool
    message_id: str
    version: int

    def __post_init__(self) -> None:
        for name in ("attribution_id", "claim_id", "speaker", "message_id"):
            _check_id("Attribution", name, getattr(self, name))
        _check_enum("Attribution", "function", self.function, CommunicativeFunction)
        _check_enum("Attribution", "report_mode", self.report_mode, ReportMode)
        _check_enum("Attribution", "polarity", self.polarity, Polarity)
        _check_enum("Attribution", "certainty", self.certainty, Certainty)
        if not isinstance(self.derived, bool):
            raise EntryError(f"Attribution.derived: expected a boolean, got {self.derived!r}")
        _check_version("Attribution", self.version)

    @property
    def entry_id(self) -> str:
        return self.attribution_id

    def to_record(self) -> dict[str, Any]:
        return _record(self)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Attribution:
        data = _fields(cls, record)
        data["function"] = _enum(cls, "function", CommunicativeFunction, data["function"])
        data["report_mode"] = _enum(cls, "report_mode", ReportMode, data["report_mode"])
        data["polarity"] = _enum(cls, "polarity", Polarity, data["polarity"])
        data["certainty"] = _enum(cls, "certainty", Certainty, data["certainty"])
        return cls(**data)


@dataclass(frozen=True, order=True)
class Span:
    """Character range [start, end) of a message text (Web Annotation TextPositionSelector)."""

    start: int
    end: int

    def __post_init__(self) -> None:
        for name in ("start", "end"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise EntryError(f"Span.{name}: expected an integer >= 0, got {value!r}")
        if self.start >= self.end:
            raise EntryError(f"Span: start {self.start} is not before end {self.end}")

    def to_record(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end}


@dataclass(frozen=True)
class EvidenceLink:
    """Claim `claim_id` is supported by message `message_id` (optionally a span of it)."""

    evidence_id: str
    claim_id: str
    message_id: str
    span: Span | None
    version: int

    def __post_init__(self) -> None:
        for name in ("evidence_id", "claim_id", "message_id"):
            _check_id("EvidenceLink", name, getattr(self, name))
        if self.span is not None and not isinstance(self.span, Span):
            raise EntryError(f"EvidenceLink.span: expected Span or None, got {self.span!r}")
        _check_version("EvidenceLink", self.version)

    @property
    def entry_id(self) -> str:
        return self.evidence_id

    def to_record(self) -> dict[str, Any]:
        record = _record(self)
        record["span"] = self.span.to_record() if self.span else None
        return record

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> EvidenceLink:
        data = _fields(cls, record)
        span = data["span"]
        if span is not None:
            if not isinstance(span, Mapping) or set(span) != {"start", "end"}:
                raise EntryError(f"EvidenceLink.span: expected {{start, end}}, got {span!r}")
            data["span"] = Span(**span)
        return cls(**data)


@dataclass(frozen=True)
class Supersession:
    """From version `version` on, claim `claim_id` is no longer currently accepted.

    - `kind`: `change` (the world changed; the claim stays in the past state) or `correction`
      (the claim was mistaken; it leaves the past state as well).
    - `valid_end`: for a change only, the world time from which the claim no longer holds, when
      the source states it or the replacing claim has a start (contracts.md, "Claim graph",
      answer to T008 open question 2). `None` means unknown: at most the world time of the
      superseding message. A correction never carries one.
    - `replacing_claim_id`: the claim c' that replaces it, or `None` for a removal (G2(ii)).
    - `attribution_id`: the stance a' that licensed the supersession under the attribution guard.
    """

    supersession_id: str
    claim_id: str
    kind: SupersessionKind
    valid_end: str | None
    replacing_claim_id: str | None
    attribution_id: str
    version: int

    def __post_init__(self) -> None:
        for name in ("supersession_id", "claim_id", "attribution_id"):
            _check_id("Supersession", name, getattr(self, name))
        _check_enum("Supersession", "kind", self.kind, SupersessionKind)
        if self.replacing_claim_id is not None:
            _check_id("Supersession", "replacing_claim_id", self.replacing_claim_id)
            if self.replacing_claim_id == self.claim_id:
                raise EntryError("Supersession: a claim cannot replace itself")
        if self.valid_end is not None:
            if self.kind is SupersessionKind.CORRECTION:
                raise EntryError("Supersession.valid_end: a correction carries no valid end")
            _check_lexical("Supersession", "valid_end", self.valid_end,
                           time_datatype(self.valid_end))
        _check_version("Supersession", self.version)

    @property
    def entry_id(self) -> str:
        return self.supersession_id

    def to_record(self) -> dict[str, Any]:
        return _record(self)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Supersession:
        data = _fields(cls, record)
        data["kind"] = _enum(cls, "kind", SupersessionKind, data["kind"])
        return cls(**data)


Entry = Claim | Attribution | EvidenceLink | Supersession
ENTRY_KINDS: dict[str, type] = {
    "claims": Claim,
    "attributions": Attribution,
    "evidence_links": EvidenceLink,
    "supersessions": Supersession,
}
