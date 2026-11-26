"""Claim patch: what the writer proposes for one extraction unit (plan 5.1, write step 2).

A patch is the writer's output before any program check. It names messages by their position in
the unit (1..n, as the prompt numbers them), claims by surface strings, and earlier claims by the
handles the prompt lists (`k1`, `k2`, ...) or by the local IDs of claims of the same patch (`n1`,
...). Span anchors are quotes; the program locates them (`history/spans.anchor_quote`). Nothing in
a patch is trusted: `validate.py` resolves it against the unit, the vocabulary and the graph, and
`guard.py` decides what it may supersede.

The JSON form is `resources/schemas/llm/extract-claims.json`. `parse_patch` is the single check
that decides whether a writer output is usable; the LLM client uses it as `validate`, so the call
record's status (`ok` or `invalid_output`) is exactly whether a patch came out of it.

An extractor that does not use an LLM (for example a gold-graph oracle in `eval/engines/oracles/`)
may build a `ClaimPatch` directly.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from grace.llm.structured import parse as parse_json

OBJECT_TYPES = ("entity", "string", "integer", "boolean", "date", "dateTime", "time")
END_KINDS = ("change", "correction")
_LOCAL_ID = re.compile(r"n[1-9][0-9]*")
_HANDLE = re.compile(r"[kn][1-9][0-9]*")


class PatchError(ValueError):
    """A writer output is not a usable claim patch."""


@dataclass(frozen=True)
class StanceFields:
    """The attribution axes of a proposed stance (plan 5.2, "Attributions have two axes")."""

    function: str = "inform"
    report_mode: str = "own"
    polarity: str = "positive"
    certainty: str = "certain"
    derived: bool = False


@dataclass(frozen=True)
class PatchClaim:
    """A proposed claim with the stance of the speaker of message `message` on it.

    A claim that repeats a currently accepted proposition becomes an attribution and an evidence
    link on that claim (`validate.py`); it is never a second claim.
    """

    message: int
    subject: str
    predicate: str
    object: str
    object_type: str = "entity"
    stance: StanceFields = StanceFields()
    local_id: str | None = None
    exclusive: bool | None = None   # the writer's proposal; used only for a new local predicate
    correction: bool = False        # replaces an earlier value that was wrong (kind correction)
    scope: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    time_expression: str | None = None
    quote: str | None = None


@dataclass(frozen=True)
class PatchStance:
    """A stance of the speaker of message `message` on an earlier claim (`k<i>` or `n<i>`).

    `ends` asks to supersede that claim without a replacing claim (a removal or the correction of
    a multi-valued claim); the guard allows it only for a negative own stance of a speaker who
    took the same function on it before (contracts.md, "Claim graph", G2(ii)).
    """

    message: int
    claim: str
    stance: StanceFields
    ends: str | None = None
    valid_until: str | None = None
    quote: str | None = None


@dataclass(frozen=True)
class PatchAlias:
    """Entity alignment: `name` and `same_as` denote the same entity (plan 5.2)."""

    message: int
    name: str
    same_as: str


@dataclass(frozen=True)
class ClaimPatch:
    claims: tuple[PatchClaim, ...] = ()
    stances: tuple[PatchStance, ...] = ()
    aliases: tuple[PatchAlias, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.claims or self.stances or self.aliases)

    def to_record(self) -> dict[str, Any]:
        def claim(c: PatchClaim) -> dict[str, Any]:
            return {"id": c.local_id, "message": c.message, "subject": c.subject,
                    "predicate": c.predicate, "object": c.object, "object_type": c.object_type,
                    **_stance_record(c.stance), "exclusive": c.exclusive,
                    "correction": c.correction, "scope": c.scope, "valid_from": c.valid_from,
                    "valid_until": c.valid_until, "time_expression": c.time_expression,
                    "quote": c.quote}

        def stance(s: PatchStance) -> dict[str, Any]:
            return {"message": s.message, "claim": s.claim, **_stance_record(s.stance),
                    "ends": s.ends, "valid_until": s.valid_until, "quote": s.quote}

        return {"claims": [claim(c) for c in self.claims],
                "stances": [stance(s) for s in self.stances],
                "same_as": [{"message": a.message, "name": a.name, "same_as": a.same_as}
                            for a in self.aliases]}


def _stance_record(s: StanceFields) -> dict[str, Any]:
    return {"function": s.function, "report_mode": s.report_mode, "polarity": s.polarity,
            "certainty": s.certainty, "derived": s.derived}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _stance(item: Mapping[str, Any]) -> StanceFields:
    return StanceFields(function=item.get("function", "inform"),
                        report_mode=item.get("report_mode", "own"),
                        polarity=item.get("polarity", "positive"),
                        certainty=item.get("certainty", "certain"),
                        derived=bool(item.get("derived", False)))


def patch_from_value(value: Mapping[str, Any], n_messages: int) -> ClaimPatch:
    """The patch in a schema-valid writer output; raises PatchError on a structural fault.

    Structural faults make the whole output unusable: a message number outside 1..n, a malformed
    or duplicate local ID, a malformed claim reference, or an empty string field. Item-level
    problems that depend on the graph (an unknown handle, a quote that does not occur) are not
    faults here; `validate.py` drops those items and says why.
    """
    def message(item: Mapping[str, Any], where: str) -> int:
        number = item["message"]
        if not 1 <= number <= n_messages:
            raise PatchError(f"{where}: message {number} is outside 1..{n_messages}")
        return number

    def text(item: Mapping[str, Any], key: str, where: str) -> str:
        out = _clean(item.get(key))
        if out is None:
            raise PatchError(f"{where}: {key} is empty")
        return out

    claims, local_ids = [], set()
    for i, item in enumerate(value.get("claims") or [], start=1):
        where = f"claims[{i}]"
        local = item.get("id")
        if local is not None:
            if not _LOCAL_ID.fullmatch(local):
                raise PatchError(f"{where}: id {local!r} is not of the form n<number>")
            if local in local_ids:
                raise PatchError(f"{where}: duplicate id {local}")
            local_ids.add(local)
        claims.append(PatchClaim(
            message=message(item, where), subject=text(item, "subject", where),
            predicate=text(item, "predicate", where), object=text(item, "object", where),
            object_type=item.get("object_type", "entity"), stance=_stance(item),
            local_id=local, exclusive=item.get("exclusive"),
            correction=bool(item.get("correction", False)), scope=_clean(item.get("scope")),
            valid_from=_clean(item.get("valid_from")), valid_until=_clean(item.get("valid_until")),
            time_expression=_clean(item.get("time_expression")), quote=item.get("quote") or None))
    stances = []
    for i, item in enumerate(value.get("stances") or [], start=1):
        where = f"stances[{i}]"
        ref = item["claim"].strip()
        if not _HANDLE.fullmatch(ref):
            raise PatchError(f"{where}: claim {ref!r} is neither a known handle k<number> nor a "
                             "local id n<number>")
        stances.append(PatchStance(message=message(item, where), claim=ref, stance=_stance(item),
                                   ends=item.get("ends"),
                                   valid_until=_clean(item.get("valid_until")),
                                   quote=item.get("quote") or None))
    aliases = []
    for i, item in enumerate(value.get("same_as") or [], start=1):
        where = f"same_as[{i}]"
        aliases.append(PatchAlias(message(item, where), text(item, "name", where),
                                  text(item, "same_as", where)))
    return ClaimPatch(tuple(claims), tuple(stances), tuple(aliases))


def parse_patch(text: str | None, validator: Draft202012Validator,
                n_messages: int) -> tuple[ClaimPatch | None, str | None]:
    """(patch, None) for a usable writer output, else (None, the reason)."""
    parsed = parse_json(text, validator)
    if not parsed.ok:
        return None, parsed.error
    try:
        return patch_from_value(parsed.value, n_messages), None
    except PatchError as exc:
        return None, str(exc)
