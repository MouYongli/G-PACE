"""Extractor interface and the LLM writer (plan 5.1, write step 2; plan 5.6, "Writing and entity
alignment").

An `Extractor` turns one extraction unit into a `ClaimPatch`. It is a replaceable step
(structure.md: gold graphs enter through this interface, `eval/engines/oracles/`). `LLMWriter` is
GRACE's writer:

- one call of type `extract` per unit, through `grace.llm.client.ChatClient`, with the pinned
  prompt `extract-claims` (`resources/prompts/extract-claims/`); the fixed instructions, output
  schema and examples are the system message, so every call of a history shares that prefix
  (plan 5.6, "Prompt assembly"; plan 8.1, stable content first);
- the output is constrained by the JSON schema `resources/schemas/llm/extract-claims.json`, sent
  as `response_format` (`json_schema`) when `structured_output` is `json_schema`;
- the client's `validate` is `patch.parse_patch`, the same check the updater applies, so a call
  record says `ok` exactly when a usable patch came out of it, and `invalid_output` otherwise
  (E002 once recorded unusable outputs as `ok`);
- transport failures and HTTP errors are retried by the client, every attempt recorded as
  `failed`; when all attempts fail the result has status `failed` and carries every call ID.

What to do with an invalid output (split the unit, give up) is the updater's decision.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from grace.context.api import Message
from grace.context.pipeline.update.candidates import Candidates
from grace.context.pipeline.update.patch import ClaimPatch, parse_patch
from grace.llm.client import ChatClient, LLMCallFailed
from grace.llm.prompts import Prompt
from grace.llm.records import CallContext

STATUSES = ("ok", "invalid_output", "failed")


@dataclass(frozen=True)
class WriterInput:
    """Everything one writer call may see: the unit, its local context and the candidates."""

    history_id: str
    messages: tuple[Message, ...]          # the unit, in version order
    earlier: tuple[Message, ...]           # local context before the unit, not extracted
    candidates: Candidates
    participants: tuple[str, ...]
    trigger: str = "write"                 # `read` for a partial unit flushed before a read
    read_id: str | None = None

    @property
    def version(self) -> int:
        """The version being written: the last message of the unit (Cost ledger)."""
        return self.messages[-1].version


@dataclass(frozen=True)
class Extraction:
    """Result of one extractor call on one unit."""

    status: str                            # ok, invalid_output or failed
    patch: ClaimPatch | None = None
    error: str | None = None
    raw: str | None = None
    call_ids: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()         # status of every call record, in order

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown extraction status {self.status!r}")
        if (self.status == "ok") != (self.patch is not None):
            raise ValueError("an extraction has a patch iff its status is ok")


class Extractor(abc.ABC):
    """One extraction unit in, one patch (or a failure) out."""

    name: str = "extractor"

    @abc.abstractmethod
    def extract(self, request: WriterInput) -> Extraction: ...


class NullExtractor(Extractor):
    """Extracts nothing; every unit gives an empty patch (a graph-free variant)."""

    name = "none"

    def extract(self, request: WriterInput) -> Extraction:
        return Extraction("ok", ClaimPatch())


def _clip(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return text[:limit] + " [...]"


def _date(message: Message, dates: Mapping[str, str | None]) -> str | None:
    stamp = message.timestamp or dates.get(message.segment_id or "")
    return stamp[:10] if stamp else None


def render_messages(messages: Sequence[Message], dates: Mapping[str, str | None], *,
                    numbered: bool, chars: int | None) -> str:
    lines = []
    for i, m in enumerate(messages, start=1):
        date = _date(m, dates)
        head = f"[{i}] " if numbered else ""
        who = m.speaker or m.role
        lines.append(f"{head}{who}" + (f" ({date})" if date else "") + f": {_clip(m.text, chars)}")
    return "\n".join(lines)


@dataclass
class LLMWriter(Extractor):
    """GRACE's writer: one `extract` call per unit (module docstring)."""

    client: ChatClient
    prompt: Prompt
    validator: Any                          # jsonschema validator of the output schema
    schema: Mapping[str, Any] | None = None  # the schema itself, for response_format
    structured_output: str = "json_schema"  # json_schema or none
    decoding: Mapping[str, Any] = field(default_factory=dict)
    message_chars: int | None = 4000
    earlier_chars: int | None = 600
    dates: Mapping[str, str | None] = field(default_factory=dict)
    name: str = "llm"

    def __post_init__(self) -> None:
        if self.structured_output not in ("json_schema", "none"):
            raise ValueError("structured_output must be json_schema or none")
        if self.structured_output == "json_schema" and self.schema is None:
            raise ValueError("json_schema structured output needs the schema")

    def messages(self, request: WriterInput) -> list[dict[str, str]]:
        return self.prompt.render(
            predicates=request.candidates.predicate_lines(),
            participants=", ".join(request.participants) or "(unknown)",
            entities=request.candidates.entity_lines(),
            claims=request.candidates.claim_lines(),
            earlier=render_messages(request.earlier, self.dates, numbered=False,
                                    chars=self.earlier_chars) or "(none)",
            messages=render_messages(request.messages, self.dates, numbered=True,
                                     chars=self.message_chars))

    def _decoding(self) -> dict[str, Any]:
        out = dict(self.decoding)
        if self.structured_output == "json_schema":
            out["response_format"] = {"type": "json_schema",
                                      "json_schema": {"name": "claim_patch",
                                                      "schema": dict(self.schema)}}
        return out

    def extract(self, request: WriterInput) -> Extraction:
        n = len(request.messages)
        context = CallContext(call_type="extract", trigger=request.trigger,
                              history_id=request.history_id, read_id=request.read_id,
                              version=request.version)
        try:
            result = self.client.chat(
                self.messages(request), context, prompt_sha256=self.prompt.sha256,
                decoding=self._decoding(),
                validate=lambda text: parse_patch(text, self.validator, n)[1])
        except LLMCallFailed as exc:
            return Extraction("failed", error=str(exc),
                              call_ids=tuple(r.call_id for r in exc.records),
                              statuses=tuple(r.status for r in exc.records))
        call_ids = tuple(r.call_id for r in result.records)
        statuses = tuple(r.status for r in result.records)
        patch, error = parse_patch(result.text, self.validator, n)
        if patch is None:
            return Extraction("invalid_output", error=error, raw=result.text, call_ids=call_ids,
                              statuses=statuses)
        return Extraction("ok", patch, raw=result.text, call_ids=call_ids, statuses=statuses)
