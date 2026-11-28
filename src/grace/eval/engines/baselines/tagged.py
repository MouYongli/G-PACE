"""Hybrid retrieval over chunks tagged with speaker and dialogue act (plan 7.2; ablation B arm).

The RRF fusion of `retrieval.py` (BM25 + dense, same chunking, same `top_k`, same packing), with
a tag prepended to every chunk before it is indexed, embedded and shown:

    [speaker: Ana; acts: accept, request] Ana: Fine, I'll take TP1950. Please book it.

- **Speaker** comes from the message itself (the same field the writer attributes stances to).
- **Dialogue acts** are predicted by the writer model, with the writer's communicative-function
  labels (read from the writer's output schema, `resources/schemas/llm/extract-claims.json`), in
  one call of type `extract` per unit of the writer's granularity (`unit_size` consecutive
  messages, `context_messages` earlier ones shown for reference), pinned prompt
  `resources/prompts/tag-dialogue-acts/`, output constrained by
  `resources/schemas/llm/tag-dialogue-acts.json`. The calls are recorded in `calls.jsonl` and
  charged to W, so the tags' tokens are in the cost (plan 7.2: "their tokens counted in cost").
  The writer's decoding settings apply (temperature 0, seed, thinking off by the model config).
- A unit is tagged when it is full (trigger `write`); before a read, a partial unit is tagged and
  indexed (trigger `read`), as the writer flushes a partial unit before a read. Only tagged
  messages are indexed, so every chunk a read can retrieve carries its tag.
- A failed or invalid tagging call does not stop the run: the unit's messages get `acts: unknown`
  and are indexed with that tag; the call records say `failed` or `invalid_output`.

Why the call is not GRACE's writer itself: `eval/engines/baselines/` may import only `api.py` and
`memory/index/` from `context/` (structure.md), and the claim patch carries the functions per
claim, not per message. The tagging call uses the same model, label set, granularity, local
context and decoding as the writer; only the output is the per-message tag instead of a patch.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from grace.context import api
from grace.context.memory.index.chunking import Chunk, render_message
from grace.eval.engines.baselines.base import CallTag, Packer, message_time, pinned_prompt
from grace.eval.engines.baselines.retrieval import Retrieval
from grace.llm.structured import SCHEMAS_DIR, load_schema, parse

SCHEMA = "tag-dialogue-acts"
WRITER_SCHEMA = "extract-claims"
MAX_UNIT = 16           # the schema's bound on messages per unit
UNKNOWN = "unknown"     # acts of a message whose tagging call failed
NONE = "none"           # acts of a message that performs no tagged function


def writer_functions() -> tuple[str, ...]:
    """The writer's communicative-function labels, from its output schema."""
    schema = json.loads((SCHEMAS_DIR / f"{WRITER_SCHEMA}.json").read_text(encoding="utf-8"))
    return tuple(schema["properties"]["claims"]["items"]["properties"]["function"]["enum"])


def tag_prefix(speaker: str, acts: Sequence[str] | None) -> str:
    shown = UNKNOWN if acts is None else (", ".join(acts) or NONE)
    return f"[speaker: {speaker}; acts: {shown}]"


class TaggedRetrieval(Retrieval):
    kind = "tagged"

    def __init__(self, model, *, unit_size: int = 8, context_messages: int = 2,
                 max_tokens: int = 512, structured_output: str = "json_schema", **retrieval):
        super().__init__(model, **retrieval)
        if not 1 <= unit_size <= MAX_UNIT:
            raise ValueError(f"unit_size must be in 1..{MAX_UNIT}")
        if structured_output not in ("json_schema", "none"):
            raise ValueError("structured_output must be json_schema or none")
        self.unit_size, self.context_messages = unit_size, context_messages
        self.max_tokens, self.structured_output = max_tokens, structured_output
        self.prompt = pinned_prompt(SCHEMA)
        self.validator = load_schema(SCHEMA)
        allowed = set(self.validator.schema["properties"]["tags"]["items"]["properties"]
                      ["acts"]["items"]["enum"])
        if allowed != set(writer_functions()):
            raise ValueError("tag labels differ from the writer's communicative functions")
        self.tags: dict[str, list[str] | None] = {}   # message_id -> acts (None: unknown)
        self.pending: list[api.Message] = []
        self.indexed: list[str] = []                    # message IDs in indexing order
        self._vectors: dict[str, list[float]] = {}

    # tagging ----------------------------------------------------------------------------------
    def _speaker(self, message: api.Message) -> str:
        return message.speaker or message.role

    def _line(self, message: api.Message, number: int | None) -> str:
        when = message_time(message, self._history())
        stamp = f" ({when})" if when else ""
        head = f"[{number}] " if number is not None else ""
        return f"{head}{self._speaker(message)}{stamp}: {message.text}"

    def _parse(self, n: int):
        def check(text: str) -> dict[int, list[str]]:
            parsed = parse(text, self.validator)
            if not parsed.ok:
                raise ValueError(parsed.error)
            out: dict[int, list[str]] = {}
            for entry in parsed.value["tags"]:
                number = entry["message"]
                if number > n or number in out:
                    raise ValueError(f"message number {number} outside 1..{n} or repeated")
                out[number] = list(dict.fromkeys(entry["acts"]))  # repeated acts dropped
            return out
        return check

    def _decoding(self) -> dict:
        if self.structured_output != "json_schema":
            return {}
        return {"response_format": {"type": "json_schema",
                                    "json_schema": {"name": "dialogue_act_tags",
                                                    "schema": dict(self.validator.schema)}}}

    def _tag(self, unit: list[api.Message], trigger: str, read_id: str | None) -> list[str]:
        first = len(self.messages) - len(self.pending)  # index of unit[0] in the log
        earlier = self.messages[max(0, first - self.context_messages):first]
        messages = self.prompt.render(
            earlier="\n".join(self._line(m, None) for m in earlier) or "(none)",
            messages="\n".join(self._line(m, i) for i, m in enumerate(unit, start=1)))
        last = unit[-1]
        tag = CallTag("extract", trigger, last.history_id, last.version, read_id)
        result = self.model.chat(messages, tag, prompt_sha256=self.prompt.sha256,
                                 parse=self._parse(len(unit)), max_tokens=self.max_tokens,
                                 response_format=self._decoding().get("response_format"))
        for i, message in enumerate(unit, start=1):
            self.tags[message.message_id] = result.parsed.get(i, []) if result.ok else None
        return list(result.call_ids)

    def _chunk(self, message: api.Message) -> Chunk:
        text = f"{tag_prefix(self._speaker(message), self.tags[message.message_id])} " \
               f"{render_message(message)}"
        return Chunk(message.message_id, (message.message_id,), message.version, text)

    def _index(self, unit: list[api.Message], trigger: str, read_id: str | None) -> list[str]:
        chunks = [self._chunk(m) for m in unit]
        call_ids: list[str] = []
        if self.bm25:
            for chunk in chunks:
                self.bm25.add(chunk)
        if self.dense:
            last = unit[-1]
            tag = CallTag("embed", trigger, last.history_id, last.version, read_id)
            result = self.model.embed([c.text for c in chunks], tag)
            call_ids += result.call_ids
            for chunk, vector in zip(chunks, result.vectors, strict=True):
                self.dense.add(chunk, vector)
                self._vectors[chunk.chunk_id] = list(vector)
        self.indexed += [m.message_id for m in unit]
        return call_ids

    def _flush(self, trigger: str, read_id: str | None = None) -> list[str]:
        if not self.pending:
            return []
        unit = list(self.pending)
        call_ids = self._tag(unit, trigger, read_id)
        self.pending = []
        return call_ids + self._index(unit, trigger, read_id)

    # engine hooks -----------------------------------------------------------------------------
    def _on_write(self, message):
        self.pending.append(message)
        if len(self.pending) >= self.unit_size:
            return self._flush("write")
        return []

    def _build(self, task, budget, request):
        flushed = self._flush("read", task.read_id)
        context, candidates, call_ids = super()._build(task, budget, request)
        return context, candidates, flushed + call_ids

    def _message_fragment(self, packer: Packer, message: api.Message,
                          kind: str = "message") -> api.Fragment:
        """The baselines' message line with the tag after the citable ID and time."""
        when = message_time(message, self._history())
        stamp = f" ({when})" if when else ""
        speaker = self._speaker(message)
        prefix = tag_prefix(speaker, self.tags[message.message_id])
        return packer.fragment(message.message_id, kind,
                               f"[{message.message_id}]{stamp} {prefix} {speaker}: {message.text}",
                               (message.message_id,), (message.message_id,))

    def _state(self):
        return {"tags": self.tags, "pending": [m.message_id for m in self.pending],
                "indexed": self.indexed,
                "vectors": [self._vectors[i] for i in self.indexed] if self.dense else None}

    def _load_state(self, state):
        self.tags = dict(state["tags"])
        by_id = {m.message_id: m for m in self.messages}
        self.pending = [by_id[i] for i in state["pending"]]
        self.indexed = []
        vectors = state["vectors"]
        for n, message_id in enumerate(state["indexed"]):
            chunk = self._chunk(by_id[message_id])
            if self.bm25:
                self.bm25.add(chunk)
            if self.dense:
                self.dense.add(chunk, vectors[n])
                self._vectors[message_id] = vectors[n]
            self.indexed.append(message_id)
