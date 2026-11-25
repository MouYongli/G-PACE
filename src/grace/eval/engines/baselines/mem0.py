"""Mem0 baseline (plan 7.2, "External systems"): the open-source `mem0ai` library, pinned in
pyproject.toml (`MEM0_VERSION`), run under this project's protocol.

Mem0 keeps its own algorithm. On every `add` it embeds the new messages, searches its vector store
for related memories, makes one LLM extraction call (its ADD-only "additive extraction" prompt with
the last ten messages, the related memories and the new messages), embeds the extracted memories
and stores the ones whose hash is new. `search` embeds the query and ranks memories with its own
scoring. This module is the adapter patch; it changes only where Mem0 sends its calls, what it is
told about time, and where it keeps its state:

1. **Model calls.** Mem0's LLM and embedder are replaced by `_PortLLM` and `_PortEmbedder`, which
   send every request through the harness's `ModelPort` (and so through `grace.llm` and the run's
   cost ledger). Extraction calls are `external` with trigger `write` (ledger `W`); embeddings are
   `embed` (ledger `embedding`) with the trigger of the phase. Mem0's own provider clients are
   never constructed, so it cannot reach a hosted API. Decoding is the model config's
   (temperature 0); `max_tokens` defaults to Mem0's 2,000. Mem0 asks for
   `response_format: json_object`; the port has no such option, so it is dropped and the output is
   checked with Mem0's own parsing. Unparsable output is retried once by the port
   (`invalid_output` records), as for every engine of this project; if the final output is still
   unparsable, Mem0 stores nothing for that message, as upstream does.
2. **Time.** Upstream fills the extraction prompt's "Observation Date" and "Current Date" with the
   wall-clock date (its `timestamp` argument is platform-only). The adapter fills both with the
   time of the message being written (`message_time`), so relative dates resolve against the
   conversation's own calendar.
3. **Telemetry and notices** are off: `MEM0_TELEMETRY=False` is set before the import and the
   imported flag is forced to False; `MEM0_DIR` (Mem0's config directory) defaults to a temporary
   directory instead of `~/.mem0`.
4. **Storage** is in process: an in-memory Qdrant client (`qdrant-client` local mode) and an
   in-memory SQLite history, one pair per engine, that is per history. No server is started.

Message mapping: one Mem0 scope per history, one `add` per message, so a read after message r sees
exactly the memories extracted from messages 1..r. A message is passed as
`{"role": "user" | "assistant", "content": "<speaker>: <text>"}`: assistant turns are `assistant`,
every other role (LoCoMo peers, users) is `user`. Mem0's own LoCoMo script keeps one scope per
speaker and adds messages in pairs; that doubles the write calls and is not used here.

Evidence set shown to the answering LLM: the memories Mem0's `search` returns for the question
(`top_k`, Mem0's score `threshold`), in Mem0's ranking, packed into the read's budget. Each memory
is one fragment `[<message ids>] (<time>) <memory text>`: the IDs are the messages whose `add`
produced the memory (one message per add here) and the time is that message's time. A
further-retrieval request is searched the same way; its new memories follow the original ones.

Mem0 features that need optional packages stay off, as in a plain `pip install mem0ai==2.2.1`: no
spaCy (no entity boost, no lemmatised keyword text) and no fastembed (no BM25 keyword channel), so
search is Mem0's semantic scoring. The engine refuses to start when either package is importable,
because its saved state does not cover the entity store they enable.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import importlib.util
import json
import logging
import os
import tempfile
import warnings
from collections.abc import Iterator, Sequence
from types import SimpleNamespace
from typing import Any

from grace.context import api
from grace.eval.engines.baselines.base import BaselineEngine, CallTag, message_time, query_text

MEM0_VERSION = "2.2.1"
SCOPE_KEY = "run_id"  # Mem0 session scope: one per history
COLLECTION = "mem0"
OPTIONAL_PACKAGES = ("spacy", "fastembed")

_MEM0: SimpleNamespace | None = None
_OBSERVED_AT: list[str | None] = [None]  # time of the message being written (single-threaded)


def features() -> dict[str, Any]:
    """The Mem0 version and which optional packages are importable."""
    return {"mem0ai": importlib.metadata.version("mem0ai"),
            **{name: importlib.util.find_spec(name) is not None for name in OPTIONAL_PACKAGES}}


def _mem0() -> SimpleNamespace:
    """Import Mem0 once, with telemetry off and the extraction prompt's dates patched."""
    global _MEM0
    if _MEM0 is not None:
        return _MEM0
    os.environ["MEM0_TELEMETRY"] = "False"
    os.environ.setdefault("MEM0_DIR", os.path.join(tempfile.gettempdir(), "grace-mem0"))
    from mem0.configs.base import MemoryConfig
    from mem0.exceptions import LLMError
    from mem0.memory import main, telemetry
    from mem0.memory import utils as mem0_utils

    version = importlib.metadata.version("mem0ai")
    if version != MEM0_VERSION:
        raise RuntimeError(f"mem0ai {version} installed, the adapter is written for "
                           f"{MEM0_VERSION}")
    telemetry.MEM0_TELEMETRY = False  # read by capture_event and the notices at call time
    main.MEM0_TELEMETRY = False
    upstream = main.generate_additive_extraction_prompt

    def dated_prompt(*args, **kwargs):
        when = _OBSERVED_AT[0]
        if when is not None:
            kwargs["current_date"], kwargs["timestamp"] = when, when
        return upstream(*args, **kwargs)

    main.generate_additive_extraction_prompt = dated_prompt
    # Expected with the plain install: missing optional packages, and Qdrant's note that payload
    # indexes do nothing in local mode. Parse errors and failures stay visible.
    for name in ("mem0.utils.spacy_models", "mem0.vector_stores.qdrant"):
        logging.getLogger(name).setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message="Payload indexes have no effect in the local Qdrant")
    _MEM0 = SimpleNamespace(main=main, utils=mem0_utils, MemoryConfig=MemoryConfig,
                            LLMError=LLMError)
    return _MEM0


def parse_extraction(text: str) -> list:
    """Mem0's parsing of an extraction reply (`Memory._add_to_vector_store`); raises ValueError
    where Mem0 would log a parse error and store nothing."""
    utils = _mem0().utils
    cleaned = utils.remove_code_blocks(text)
    if not cleaned or not cleaned.strip():
        return []
    try:
        data = json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        data = json.loads(utils.extract_json(cleaned), strict=False)
    if not isinstance(data, dict) or not isinstance(data.get("memory", []), list):
        raise ValueError("extraction reply is not an object with a 'memory' list")
    return data.get("memory", [])


def mem0_message(message: api.Message) -> dict[str, str]:
    role = "assistant" if message.role == "assistant" else "user"
    content = f"{message.speaker}: {message.text}" if message.speaker else message.text
    return {"role": role, "content": content}


# ---------------------------------------------------------------------------------------------
# Mem0's LLM and embedder, sent through the model port


class _PortLLM:
    """Stands in for a `mem0.llms` provider."""

    def __init__(self, engine: Mem0):
        self.engine = engine

    def generate_response(self, messages, response_format=None, tools=None, tool_choice="auto",
                          **kwargs):
        if tools:
            raise NotImplementedError("Mem0 tool calls are not used by the add pipeline")
        engine = self.engine
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        result = engine.model.chat(list(messages), engine.tag("external"),
                                   prompt_sha256=hashlib.sha256(system.encode()).hexdigest(),
                                   parse=parse_extraction, max_tokens=engine.max_tokens)
        engine.call_ids += result.call_ids
        if result.text is None:
            raise RuntimeError("extraction call failed on every attempt")
        return result.text


class _PortEmbedder:
    """Stands in for a `mem0.embeddings` provider. A query embedded at read time gets the
    configured instruction; one primed vector serves the first call of the first `add`."""

    def __init__(self, engine: Mem0):
        self.engine = engine
        self.primed: tuple[str, list[float]] | None = None

    def embed(self, text, memory_action=None):
        if self.primed is not None and self.primed[0] == text:
            vector, self.primed = self.primed[1], None
            return vector
        return self.embed_batch([text], memory_action)[0]

    def embed_batch(self, texts, memory_action="add"):
        engine = self.engine
        if engine.trigger == "read" and memory_action == "search" and engine.query_instruction:
            texts = [f"Instruct: {engine.query_instruction}\nQuery: {t}" for t in texts]
        result = engine.model.embed(list(texts), engine.tag("embed"))
        engine.call_ids += result.call_ids
        return [list(v) for v in result.vectors]


class _Fixed:
    """A factory that returns one prepared object (replaces Mem0's provider factories)."""

    def __init__(self, obj):
        self.obj = obj

    def create(self, *args, **kwargs):
        return self.obj


# ---------------------------------------------------------------------------------------------
# Engine


class Mem0(BaselineEngine):
    kind = "mem0"

    def __init__(self, model, *, top_k: int = 20, threshold: float = 0.1,
                 max_tokens: int = 2000, query_instruction: str | None = None):
        super().__init__(model)
        if top_k < 1 or max_tokens < 1 or not 0 <= threshold <= 1:
            raise ValueError("top_k >= 1, max_tokens >= 1 and 0 <= threshold <= 1")
        active = [name for name in OPTIONAL_PACKAGES if features()[name]]
        if active:
            raise RuntimeError(f"optional Mem0 packages installed ({', '.join(active)}); the "
                               "adapter pins the plain install")
        _mem0()
        self.top_k, self.threshold, self.max_tokens = top_k, threshold, max_tokens
        self.query_instruction = query_instruction
        self.memory = None
        self.llm, self.embedder = _PortLLM(self), _PortEmbedder(self)
        self.records: dict[str, dict[str, Any]] = {}  # Mem0 ID -> local ID, evidence, time
        # phase of the calls Mem0 makes now
        self.trigger, self.version_now, self.read_id = "write", None, None
        self.call_ids: list[str] = []

    # model port ---------------------------------------------------------------------------
    def tag(self, call_type: str) -> CallTag:
        return CallTag(call_type, self.trigger, self._history().history_id, self.version_now,
                       self.read_id)

    @contextlib.contextmanager
    def phase(self, trigger: str, version: int, read_id: str | None = None,
              observed_at: str | None = None) -> Iterator[None]:
        self.trigger, self.version_now, self.read_id = trigger, version, read_id
        _OBSERVED_AT[0] = observed_at
        try:
            yield
        finally:
            self.trigger, self.version_now, self.read_id = "write", None, None
            _OBSERVED_AT[0] = None

    # Mem0 instance ------------------------------------------------------------------------
    @property
    def scope(self) -> dict[str, str]:
        return {SCOPE_KEY: self._history().history_id}

    def _build_memory(self, dims: int) -> None:
        from qdrant_client import QdrantClient

        mem0 = _mem0()
        config = mem0.MemoryConfig(
            vector_store={"provider": "qdrant", "config": {
                "collection_name": COLLECTION, "embedding_model_dims": dims,
                "client": QdrantClient(location=":memory:"), "path": ":memory:"}},
            history_db_path=":memory:")
        main = mem0.main
        saved = main.LlmFactory, main.EmbedderFactory
        main.LlmFactory, main.EmbedderFactory = _Fixed(self.llm), _Fixed(self.embedder)
        try:
            self.memory = main.Memory(config)
        finally:
            main.LlmFactory, main.EmbedderFactory = saved

    def _session_scope(self) -> str:
        return _mem0().main._build_session_scope(self.scope)

    # write --------------------------------------------------------------------------------
    def _on_write(self, message):
        self.call_ids = []
        item = mem0_message(message)
        when = message_time(message, self._history())
        with self.phase("write", message.version, observed_at=when):
            if self.memory is None:
                # Mem0 embeds the parsed messages first; embed them here to learn the dimension
                # and hand the vector to that first call, so no call is duplicated.
                text = _mem0().utils.parse_messages([item])
                vector = self.embedder.embed_batch([text], "search")[0]
                self._build_memory(len(vector))
                self.embedder.primed = (text, vector)
            try:
                added = self.memory.add([item], **self.scope)["results"]
            except _mem0().LLMError:
                added = []  # the failed call is in the ledger; Mem0 stored nothing
            finally:
                self.embedder.primed = None
        for i, row in enumerate(r for r in added if r.get("event") == "ADD"):
            self.records[str(row["id"])] = {"local_id": f"m{message.version}.{i}",
                                            "evidence_ids": [message.message_id], "time": when}
        return list(self.call_ids)

    # read ---------------------------------------------------------------------------------
    def _search(self, query: str, task: api.ReadTask) -> list[dict[str, Any]]:
        if self.memory is None or not query.strip():
            return []
        with self.phase("read", task.version, task.read_id):
            return self.memory.search(query, top_k=self.top_k, filters=self.scope,
                                      threshold=self.threshold)["results"]

    def _build(self, task, budget, request):
        self.call_ids = []
        ranked = self._search(query_text(task, self.messages), task)
        if request is not None:
            seen = {r["id"] for r in ranked}
            ranked += [r for r in self._search(request, task) if r["id"] not in seen]
        packer = self._packer()
        fragments, candidates = [], []
        for row in ranked:
            record = self.records[str(row["id"])]
            stamp = f" ({record['time']})" if record["time"] else ""
            text = f"[{', '.join(record['evidence_ids'])}]{stamp} {row['memory']}"
            fragments.append(packer.fragment(record["local_id"], "retrieved", text,
                                             record["evidence_ids"], record["evidence_ids"]))
            candidates.append(api.Candidate(record["local_id"], "mem0", float(row["score"])))
        return packer.pack(task, budget, fragments), candidates, list(self.call_ids)

    # persistence --------------------------------------------------------------------------
    def _points(self) -> list[dict[str, Any]]:
        store = self.memory.vector_store
        points, offset = [], None
        while True:
            batch, offset = store.client.scroll(store.collection_name, limit=256, offset=offset,
                                                with_payload=True, with_vectors=True)
            for point in batch:
                vector = point.vector.get("") if isinstance(point.vector, dict) else point.vector
                points.append({"id": str(point.id), "vector": list(vector),
                               "payload": point.payload})
            if offset is None:
                break
        return sorted(points, key=lambda p: self.records[p["id"]]["local_id"])

    def _state(self):
        if self.memory is None:
            return {"dims": None, "points": [], "records": self.records, "last_messages": []}
        last = self.memory.db.get_last_messages(self._session_scope(), limit=10)
        return {"dims": self.memory.vector_store.embedding_model_dims,
                "points": self._points(), "records": self.records,
                "last_messages": [{"role": m["role"], "content": m["content"],
                                   "name": m["name"]} for m in last]}

    def _load_state(self, state):
        self.records = state["records"]
        if state["dims"] is None:
            return
        self._build_memory(state["dims"])
        points: Sequence[dict[str, Any]] = state["points"]
        if points:
            self.memory.vector_store.insert(vectors=[p["vector"] for p in points],
                                            payloads=[p["payload"] for p in points],
                                            ids=[p["id"] for p in points])
        db, scope = self.memory.db, self._session_scope()
        with db._lock:  # Mem0 orders its last messages by created_at; keep the saved order
            for i, m in enumerate(state["last_messages"]):
                db.connection.execute(
                    "INSERT INTO messages (id, session_scope, role, content, name, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f"restored-{i}", scope, m["role"], m["content"], m["name"],
                     f"0000-01-01T00:00:00.{i:06d}+00:00"))
            db.connection.commit()
