"""Embedding calls over an OpenAI-compatible `/embeddings` API; every attempt becomes a record.

The embedding counterpart of `client.ChatClient` (D013: every model call goes through `llm/`).
Added by T003 for the dense and RRF retrieval baselines; strictly additive, it reuses the
`Endpoint`, `CallLedger` and `CallRecord` of this package unchanged.

Accounting (Cost ledger section): one record per attempt with `call_type` `embed`, category
`embedding` and `output_tokens` 0. `input_tokens` is the server's `usage.prompt_tokens` when it
reports it; otherwise, and for failed attempts, the caller's `count_text` over the inputs. Transport
failures and HTTP errors are retried up to `max_attempts`, each recorded with status `failed`.
"""

from __future__ import annotations

import time
import urllib.error
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from grace.llm.client import Endpoint, LLMCallFailed, Transport, http_post
from grace.llm.records import CallContext, CallLedger, CallRecord


@dataclass
class EmbedResult:
    vectors: list[list[float]]
    records: list[CallRecord] = field(default_factory=list)


class EmbeddingClient:
    def __init__(self, endpoint: Endpoint, ledger: CallLedger, count_text: Callable[[str], int],
                 *, max_attempts: int = 3, backoff_s: float = 1.0,
                 transport: Transport = http_post, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.endpoint, self.ledger, self.count_text = endpoint, ledger, count_text
        self.max_attempts, self.backoff_s = max_attempts, backoff_s
        self._transport, self._sleep, self._clock = transport, sleep, clock

    def _record(self, context: CallContext, attempt: int, status: str, input_tokens: int,
                latency_s: float) -> CallRecord:
        gpu = (latency_s * self.endpoint.gpus
               if self.endpoint.gpu_accounting == "wall_clock" else None)
        record = CallRecord(
            call_id=self.ledger.new_call_id(), run_id=self.ledger.run_id,
            history_id=context.history_id, read_id=context.read_id, version=context.version,
            call_type="embed", trigger=context.trigger, category=context.category,
            model=self.endpoint.model_label, attempt=attempt, status=status,
            input_tokens=input_tokens, output_tokens=0, cached_input_tokens=0, gpu_seconds=gpu,
            latency_ms=round(latency_s * 1000.0, 3), prompt_sha256=None)
        self.ledger.write(record)
        return record

    def embed(self, texts: Sequence[str], context: CallContext) -> EmbedResult:
        """Embed `texts` in one request; vectors come back in input order."""
        if context.call_type != "embed":
            raise ValueError("embedding calls need call_type 'embed'")
        texts = list(texts)
        local_tokens = sum(self.count_text(t) for t in texts)
        payload = {"model": self.endpoint.served_model, "input": texts}
        url = self.endpoint.base_url.rstrip("/") + "/embeddings"
        records: list[CallRecord] = []
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            start = self._clock()
            try:
                body = self._transport(url, payload, {}, self.endpoint.timeout_s)
                rows = sorted(body["data"], key=lambda row: row["index"])
                vectors = [[float(x) for x in row["embedding"]] for row in rows]
                if len(vectors) != len(texts):
                    raise ValueError(f"{len(vectors)} vectors for {len(texts)} inputs")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError,
                    IndexError, TypeError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                records.append(self._record(context, attempt, "failed", local_tokens,
                                            self._clock() - start))
                if attempt < self.max_attempts:
                    self._sleep(self.backoff_s * 2 ** (attempt - 1))
                continue
            reported = (body.get("usage") or {}).get("prompt_tokens")
            tokens = int(reported) if reported is not None else local_tokens
            records.append(self._record(context, attempt, "ok", tokens, self._clock() - start))
            return EmbedResult(vectors, records)
        raise LLMCallFailed(f"{self.max_attempts} attempts failed; last: {last_error}", records)
