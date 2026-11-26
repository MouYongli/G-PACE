"""Model access for engines and the answering step: the `ModelPort` implementations.

Both implementations write one Cost-ledger record per attempt into the run's `calls.jsonl`
through `grace.llm.records.CallLedger`, and retry output the caller's parser rejects up to
`max_attempts` logical calls.

- `ClientModel`: the real path. Chat calls go through `grace.llm.client.ChatClient` (the
  OpenAI-compatible serving endpoint, local token counting with the model's pinned tokenizer and
  chat template), embedding calls through `grace.llm.embeddings.EmbeddingClient`. Transport
  failures are retried inside the client; a call whose transport attempts all fail returns
  `ok=False` (chat) or fails the run (embedding, since the index cannot be built without vectors).
  A retry after invalid output is a new logical call of the client, so its `attempt` restarts at 1.
- `RecordingModel` with `FakeBackend`: deterministic, CPU-only, no network, for tests and CI. It
  counts whitespace tokens, simulates prefix caching by the longest common prefix with earlier
  prompts, and answers through a responder function. Its model name says so; no score from it is
  real.
- `EngineLLMModel`: an engine's own chat calls on a second model (T034, Graphiti's native-backbone
  row: Graphiti's internal LLM on Azure gpt-4.1-mini), while its embeddings and token counting,
  and the answering step, stay on the run's model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from grace.eval.engines.baselines.base import CallTag, ChatResult, EmbedResult
from grace.eval.runner.harness.answer import FURTHER_HEADING, is_answer_call
from grace.llm.client import ChatClient, LLMCallFailed
from grace.llm.embeddings import EmbeddingClient
from grace.llm.records import CallContext, CallLedger, CallRecord, category_for
from grace.llm.tokens import TokenCounter

PARSE_ERRORS = (ValueError, KeyError, TypeError)
LOG = logging.getLogger("grace.harness.models")


def call_context(tag: CallTag) -> CallContext:
    return CallContext(tag.call_type, tag.trigger, tag.history_id, tag.read_id, tag.version)


# ---------------------------------------------------------------------------------------------
# Real model client


class ClientModel:
    """`ModelPort` over `grace.llm` clients (see the module docstring)."""

    def __init__(self, client: ChatClient, counter: TokenCounter, *,
                 decoding: Mapping[str, Any] | None = None,
                 embedder: EmbeddingClient | None = None, max_attempts: int = 2):
        if max_attempts < 1:
            raise ValueError("max_attempts >= 1")
        self.client, self.counter, self.embedder = client, counter, embedder
        self.decoding = dict(decoding or {})
        self.max_attempts = max_attempts
        self.observed: list[str] = []  # every text sent to a model (inputs seen by models)

    @property
    def model(self) -> str:
        return self.client.endpoint.model_label

    def count_tokens(self, text: str) -> int:
        return self.counter.count_text(text)

    def chat(self, messages, tag: CallTag, *, prompt_sha256: str | None = None,
             parse: Callable[[str], Any] | None = None,
             max_tokens: int | None = None,
             response_format: Mapping[str, Any] | None = None) -> ChatResult:
        self.observed.extend(m["content"] for m in messages)
        context = call_context(tag)
        decoding = {**self.decoding, **({"max_tokens": max_tokens} if max_tokens else {})}
        if response_format is not None:  # structured output (T034, Graphiti): sent as given
            decoding["response_format"] = dict(response_format)
        parsed: dict[str, Any] = {}

        def validate(text: str) -> str | None:
            try:
                parsed["value"] = parse(text) if parse else text
            except PARSE_ERRORS as exc:
                return f"{type(exc).__name__}: {exc}"
            return None

        call_ids: list[str] = []
        text, input_tokens = None, 0
        for _ in range(self.max_attempts):
            parsed.clear()
            try:
                result = self.client.chat(messages, context, prompt_sha256=prompt_sha256,
                                          decoding=decoding, validate=validate)
            except LLMCallFailed as exc:
                LOG.warning("%s: %s", self.model, exc)  # the transport error, for the run log
                call_ids += [r.call_id for r in exc.records]
                input_tokens = exc.records[-1].input_tokens if exc.records else input_tokens
                break
            call_ids += [r.call_id for r in result.records]
            text, input_tokens = result.text, result.records[-1].input_tokens
            if result.status == "ok":
                return ChatResult(text, parsed["value"], True, tuple(call_ids), input_tokens)
        return ChatResult(text, None, False, tuple(call_ids), input_tokens)

    def embed(self, texts, tag: CallTag) -> EmbedResult:
        if self.embedder is None:
            raise RuntimeError("this engine embeds, but no embedding endpoint was configured")
        self.observed.extend(texts)
        result = self.embedder.embed(texts, call_context(tag))
        return EmbedResult(tuple(tuple(v) for v in result.vectors),
                           tuple(r.call_id for r in result.records))


class EngineLLMModel:
    """`ModelPort` for an engine whose own chat calls go to `llm` (a second `ClientModel`, with
    its own endpoint and model label in every call record) while `embed` and `count_tokens` stay
    on `base`, the run's model: the engine packs contexts in the answering model's tokens. The
    answering step keeps `base`; only the engine is built with this port."""

    def __init__(self, llm, base):
        self.llm, self.base = llm, base

    @property
    def model(self) -> str:
        return self.llm.model

    @property
    def observed(self) -> list[str]:
        return [*self.llm.observed, *self.base.observed]

    def chat(self, messages, tag: CallTag, **kwargs) -> ChatResult:
        return self.llm.chat(messages, tag, **kwargs)

    def embed(self, texts, tag: CallTag) -> EmbedResult:
        return self.base.embed(texts, tag)

    def count_tokens(self, text: str) -> int:
        return self.base.count_tokens(text)


# ---------------------------------------------------------------------------------------------
# Deterministic fake backend


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    gpu_seconds: float | None = None


class Backend(Protocol):
    model: str
    device: str

    def complete(self, messages: Sequence[dict[str, str]]) -> Completion: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def count_tokens(self, text: str) -> int: ...


def prompt_text(messages: Sequence[dict[str, str]]) -> str:
    """The serialised prompt the fake backend counts (a stand-in for the chat template)."""
    return "\n".join(f"<{m['role']}>\n{m['content']}" for m in messages)


class RecordingModel:
    """`ModelPort` over a `Backend` that records every attempt in the run's cost ledger."""

    def __init__(self, backend: Backend, ledger: CallLedger, *, max_attempts: int = 2):
        if max_attempts < 1:
            raise ValueError("max_attempts >= 1")
        self.backend, self.ledger, self.max_attempts = backend, ledger, max_attempts
        self.observed: list[str] = []  # every text sent to the backend (inputs seen by models)

    @property
    def model(self) -> str:
        return self.backend.model

    def count_tokens(self, text: str) -> int:
        return self.backend.count_tokens(text)

    def _record(self, tag: CallTag, attempt: int, status: str, completion: Completion | None,
                input_tokens: int, latency_ms: float, prompt_sha256: str | None) -> str:
        call_id = self.ledger.new_id()
        self.ledger.append(CallRecord(
            call_id=call_id, run_id=self.ledger.run_id, history_id=tag.history_id,
            read_id=tag.read_id, version=tag.version, call_type=tag.call_type,
            trigger=tag.trigger, category=category_for(tag.call_type, tag.trigger),
            model=self.backend.model, attempt=attempt, status=status,
            input_tokens=completion.input_tokens if completion else input_tokens,
            output_tokens=completion.output_tokens if completion else 0,
            cached_input_tokens=completion.cached_input_tokens if completion else 0,
            gpu_seconds=completion.gpu_seconds if completion else None,
            latency_ms=latency_ms, prompt_sha256=prompt_sha256))
        return call_id

    def chat(self, messages, tag: CallTag, *, prompt_sha256: str | None = None,
             parse: Callable[[str], Any] | None = None,
             max_tokens: int | None = None,
             response_format: Mapping[str, Any] | None = None) -> ChatResult:
        """`response_format` is accepted for parity with `ClientModel` and not enforced: the
        responder decides the output."""
        category_for(tag.call_type, tag.trigger)  # refuse a bad tag before any attempt
        self.observed.extend(m["content"] for m in messages)
        call_ids: list[str] = []
        text, input_tokens = None, self.backend.count_tokens(prompt_text(messages))
        for attempt in range(1, self.max_attempts + 1):
            start = time.perf_counter()
            try:
                completion = self.backend.complete(messages)
            except Exception:  # noqa: BLE001 - a failed attempt is recorded, then retried
                latency = (time.perf_counter() - start) * 1000
                call_ids.append(self._record(tag, attempt, "failed", None, input_tokens,
                                             latency, prompt_sha256))
                continue
            latency = (time.perf_counter() - start) * 1000
            text = completion.text
            try:
                parsed = parse(text) if parse else text
            except PARSE_ERRORS:
                call_ids.append(self._record(tag, attempt, "invalid_output", completion,
                                             input_tokens, latency, prompt_sha256))
                continue
            call_ids.append(self._record(tag, attempt, "ok", completion, input_tokens, latency,
                                         prompt_sha256))
            return ChatResult(text, parsed, True, tuple(call_ids), completion.input_tokens)
        return ChatResult(text, None, False, tuple(call_ids), input_tokens)

    def embed(self, texts, tag: CallTag) -> EmbedResult:
        self.observed.extend(texts)
        start = time.perf_counter()
        vectors = self.backend.embed(texts)
        latency = (time.perf_counter() - start) * 1000
        tokens = sum(self.backend.count_tokens(t) for t in texts)
        call_id = self._record(tag, 1, "ok", Completion("", tokens, 0), tokens, latency, None)
        return EmbedResult(tuple(tuple(v) for v in vectors), (call_id,))


_WORD = re.compile(r"\S+")
_ID = re.compile(r"^\[([^\]]+)\]")


def fake_responder(messages: Sequence[dict[str, str]]) -> str:
    """Deterministic stand-in outputs for the call types of T003, recognised by their prompts."""
    system, user = messages[0]["content"], messages[-1]["content"]
    if "running summary" in system:
        words = _WORD.findall(user.split("New messages:\n", 1)[-1])
        return " ".join(words[:40]) or "nothing"
    if "slot table" in system:
        return '{"entries": []}'
    if "## New Messages\n" in user:  # Mem0's extraction call: one memory, the new message's words
        new = user.split("## New Messages\n", 1)[1].split("\n\n## ", 1)[0]
        words = _WORD.findall(new.split(": ", 2)[-1])
        return json.dumps({"memory": [{"id": "0", "text": " ".join(words[:40])}]} if words
                          else {"memory": []})
    if is_answer_call(messages):
        context = user.split("Context:\n", 1)[-1].split("\n\nCurrent date:", 1)[0]
        context = context.split(f"\n\n{FURTHER_HEADING}:\n", 1)[0]
        first = next((line for line in context.splitlines() if _ID.match(line)), None)
        if "State request" in user:
            return json.dumps({"output": "state", "state": {}, "cited_ids": []})
        if first is None:
            return json.dumps({"output": "unknown", "cited_ids": []})
        cited = _ID.match(first).group(1).split(", ")[0]
        return json.dumps({"output": "answer", "answer": first.split(": ", 1)[-1],
                           "cited_ids": [cited]})
    return "ok"


class FakeBackend:
    """Deterministic backend for tests and dry runs (see the module docstring)."""

    device = "cpu"

    def __init__(self, responder: Callable[[Sequence[dict[str, str]]], str] = fake_responder,
                 *, prefix_caching: bool = False, dim: int = 64, model: str = "fake@T003"):
        self.responder, self.prefix_caching, self.dim, self.model = (
            responder, prefix_caching, dim, model)
        self._prompts: list[list[str]] = []

    def count_tokens(self, text: str) -> int:
        return len(_WORD.findall(text))

    def complete(self, messages) -> Completion:
        tokens = _WORD.findall(prompt_text(messages))
        cached = 0
        if self.prefix_caching:
            for earlier in self._prompts:
                n = 0
                for a, b in zip(earlier, tokens, strict=False):
                    if a != b:
                        break
                    n += 1
                cached = max(cached, n)
            self._prompts = [*self._prompts[-63:], tokens]
        text = self.responder(messages)
        return Completion(text, len(tokens), self.count_tokens(text), min(cached, len(tokens)))

    def embed(self, texts) -> list[list[float]]:
        out = []
        for text in texts:
            vector = [0.0] * self.dim
            for word in re.findall(r"\w+", text.lower()):
                digest = hashlib.sha256(word.encode("utf-8")).digest()
                vector[digest[0] % self.dim] += 1.0
            out.append(vector)
        return out
