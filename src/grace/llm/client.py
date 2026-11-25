"""Chat completion over an OpenAI-compatible HTTP API; every attempt becomes a call record.

This is the only exit for chat calls (D013). It speaks the plain `/chat/completions` protocol with
the standard library, so a local vLLM server (`scripts/serve-model.sh`) and a remote API look the
same, and tests can use a fake HTTP server.

Accounting (Cost ledger section; plan 8.1):

- `input_tokens` is counted locally with the pinned tokenizer and chat template of the model
  (`tokens.TokenCounter`), so it does not depend on what a server reports and failed attempts are
  counted in full. The server's own `prompt_tokens` is returned for cross-checking.
- `output_tokens` and `cached_input_tokens` come from the server's `usage`
  (`usage.prompt_tokens_details.cached_tokens`; 0 when the server does not report it, and the
  result says so in `cache_reported`).
- `gpu_seconds` follows `Endpoint.gpu_accounting`: `none` (null, the only honest value without a
  per-request GPU timer, and the value for remote APIs) or `wall_clock` (latency times the GPUs of
  the server; an upper bound under batching).
- Transport failures and HTTP errors are retried up to `max_attempts`, each attempt recorded with
  status `failed`. An answer that fails the caller's `validate` is recorded as `invalid_output`
  and handed back; repairing it is the caller's decision.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from grace.llm.records import CallContext, CallLedger, CallRecord
from grace.llm.tokens import Message, TokenCounter


class LLMCallFailed(RuntimeError):
    """Every attempt of a logical call failed; all attempts are already in the ledger."""

    def __init__(self, message: str, records: list[CallRecord]):
        super().__init__(message)
        self.records = records


@dataclass(frozen=True)
class Endpoint:
    """An OpenAI-compatible server and the model it serves."""

    base_url: str  # e.g. http://127.0.0.1:8000/v1
    served_model: str  # the `model` field sent to the server
    model_label: str  # recorded in `model`: served model and snapshot, e.g. repo@revision
    api_key_env: str | None = None  # name of the environment variable holding the key
    timeout_s: float = 600.0
    gpu_accounting: str = "none"  # "none" or "wall_clock"
    gpus: int = 0  # GPUs of the server, for wall_clock accounting

    def __post_init__(self):
        if self.gpu_accounting not in ("none", "wall_clock"):
            raise ValueError(f"unknown gpu_accounting {self.gpu_accounting!r}")
        if self.gpu_accounting == "wall_clock" and self.gpus < 1:
            raise ValueError("wall_clock GPU accounting needs gpus >= 1")


@dataclass
class ChatResult:
    text: str | None
    status: str  # ok or invalid_output
    error: str | None
    records: list[CallRecord] = field(default_factory=list)
    server_input_tokens: int | None = None
    cache_reported: bool = False

    @property
    def call_id(self) -> str:
        """Call ID of the attempt that produced `text` (the last one)."""
        return self.records[-1].call_id


Transport = Callable[[str, dict, dict, float], dict]


def http_post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **headers},
                                     method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


class ChatClient:
    def __init__(self, endpoint: Endpoint, ledger: CallLedger, counter: TokenCounter, *,
                 max_attempts: int = 3, backoff_s: float = 1.0,
                 transport: Transport = http_post, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.endpoint, self.ledger, self.counter = endpoint, ledger, counter
        self.max_attempts, self.backoff_s = max_attempts, backoff_s
        self._transport, self._sleep, self._clock = transport, sleep, clock

    def _headers(self) -> dict:
        if not self.endpoint.api_key_env:
            return {}
        key = os.environ.get(self.endpoint.api_key_env)
        if not key:
            raise RuntimeError(f"environment variable {self.endpoint.api_key_env} is not set")
        return {"Authorization": f"Bearer {key}"}

    def _record(self, context: CallContext, attempt: int, status: str, input_tokens: int,
                output_tokens: int, cached: int, latency_s: float,
                prompt_sha256: str | None) -> CallRecord:
        gpu = (latency_s * self.endpoint.gpus
               if self.endpoint.gpu_accounting == "wall_clock" else None)
        record = CallRecord(
            call_id=self.ledger.new_call_id(), run_id=self.ledger.run_id,
            history_id=context.history_id, read_id=context.read_id, version=context.version,
            call_type=context.call_type, trigger=context.trigger, category=context.category,
            model=self.endpoint.model_label, attempt=attempt, status=status,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cached_input_tokens=min(cached, input_tokens), gpu_seconds=gpu,
            latency_ms=round(latency_s * 1000.0, 3), prompt_sha256=prompt_sha256)
        self.ledger.write(record)
        return record

    def chat(self, messages: Sequence[Message], context: CallContext, *,
             prompt_sha256: str | None, decoding: Mapping | None = None,
             validate: Callable[[str], str | None] | None = None) -> ChatResult:
        """One logical call. `decoding` is passed through (temperature, max_tokens, seed, ...);
        `validate(text)` returns None or an error message."""
        if context.call_type == "embed":
            raise ValueError("embedding calls do not go through chat()")
        messages = [dict(m) for m in messages]
        input_tokens = self.counter.count_messages(messages)
        payload = {"model": self.endpoint.served_model, "messages": messages,
                   **dict(decoding or {})}
        url = self.endpoint.base_url.rstrip("/") + "/chat/completions"
        headers = self._headers()
        records: list[CallRecord] = []
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            start = self._clock()
            try:
                body = self._transport(url, payload, headers, self.endpoint.timeout_s)
                text = body["choices"][0]["message"]["content"]
                usage = body.get("usage") or {}
                output_tokens = int(usage["completion_tokens"])
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError,
                    IndexError, TypeError) as exc:
                latency = self._clock() - start
                last_error = f"{type(exc).__name__}: {exc}"
                records.append(self._record(context, attempt, "failed", input_tokens, 0, 0,
                                            latency, prompt_sha256))
                if attempt < self.max_attempts:
                    self._sleep(self.backoff_s * 2 ** (attempt - 1))
                continue
            latency = self._clock() - start
            details = usage.get("prompt_tokens_details") or {}
            cached = details.get("cached_tokens")
            error = validate(text or "") if validate is not None else None
            status = "ok" if error is None else "invalid_output"
            records.append(self._record(context, attempt, status, input_tokens, output_tokens,
                                        int(cached or 0), latency, prompt_sha256))
            server_input = usage.get("prompt_tokens")
            return ChatResult(text=text, status=status, error=error, records=records,
                              server_input_tokens=None if server_input is None
                              else int(server_input),
                              cache_reported=cached is not None)
        raise LLMCallFailed(f"{self.max_attempts} attempts failed; last: {last_error}", records)
