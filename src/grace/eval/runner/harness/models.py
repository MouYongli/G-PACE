"""Model access for engines and the answering step: a recording wrapper around a backend.

`RecordingModel` implements the `ModelPort` of the baselines. It sends each call to a `Backend`,
retries invalid output up to `max_attempts`, and writes one cost-ledger record per attempt.

Backends:

- `FakeBackend`: deterministic, CPU-only, no network. It counts whitespace tokens, simulates prefix
  caching by the longest common prefix with earlier prompts, and answers through a responder
  function. For tests and dry runs only; its model name says so, and no score from it is real.
- A backend for the OpenAI-compatible serving endpoint comes from `llm/client.py` (T004). Model
  client libraries may be imported only by `llm/` (import rules), so it is not written here.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from grace.eval.engines.baselines.base import CallTag, ChatResult, EmbedResult
from grace.eval.runner.harness.ledger import CallLedger, CallRecord, category


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
    """`ModelPort` that records every attempt in the run's cost ledger."""

    def __init__(self, backend: Backend, ledger: CallLedger, *, max_attempts: int = 2):
        if max_attempts < 1:
            raise ValueError("max_attempts >= 1")
        self.backend, self.ledger, self.max_attempts = backend, ledger, max_attempts
        self.observed: list[str] = []  # every text sent to the backend (inputs seen by models)

    def count_tokens(self, text: str) -> int:
        return self.backend.count_tokens(text)

    def _record(self, tag: CallTag, attempt: int, status: str, completion: Completion | None,
                input_tokens: int, latency_ms: float, prompt_sha256: str | None) -> str:
        call_id = self.ledger.new_id()
        self.ledger.append(CallRecord(
            call_id=call_id, run_id=self.ledger.run_id, history_id=tag.history_id,
            read_id=tag.read_id, version=tag.version, call_type=tag.call_type,
            trigger=tag.trigger, category=category(tag.call_type, tag.trigger),
            model=self.backend.model, attempt=attempt, status=status,
            input_tokens=completion.input_tokens if completion else input_tokens,
            output_tokens=completion.output_tokens if completion else 0,
            cached_input_tokens=completion.cached_input_tokens if completion else 0,
            gpu_seconds=completion.gpu_seconds if completion else None,
            latency_ms=latency_ms, prompt_sha256=prompt_sha256))
        return call_id

    def chat(self, messages, tag: CallTag, *, prompt_sha256: str | None = None,
             parse: Callable[[str], Any] | None = None) -> ChatResult:
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
            except (ValueError, KeyError, TypeError):
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


# ---------------------------------------------------------------------------------------------
# Deterministic fake backend

_WORD = re.compile(r"\S+")
_ID = re.compile(r"^\[([^\]]+)\]")


def fake_responder(messages: Sequence[dict[str, str]]) -> str:
    """Deterministic stand-in outputs for the call types of T003, recognised by their prompts."""
    system, user = messages[0]["content"], messages[-1]["content"]
    if "running summary" in system:
        words = _WORD.findall(user.split("\n", 1)[-1])
        return " ".join(words[:40]) or "nothing"
    if "slot table" in system:
        return '{"entries": []}'
    if "OUTPUT CONTRACT" in system:
        context = user.split("Context:\n", 1)[-1].split("\n\nTask:", 1)[0]
        first = next((line for line in context.splitlines() if _ID.match(line)), None)
        if "state request" in user:
            return json.dumps({"output": "state", "state": {}, "cited_ids": []})
        if first is None:
            return json.dumps({"output": "unknown"})
        return json.dumps({"output": "answer", "answer": first.split(": ", 1)[-1],
                           "cited_ids": [_ID.match(first).group(1)]})
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
