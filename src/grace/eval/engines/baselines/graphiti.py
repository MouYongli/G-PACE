"""Graphiti baseline (plan 7.2, "External systems"): the open-source `graphiti-core` library,
pinned in its own environment (`envs/graphiti`, `GRAPHITI_VERSION`), run under this project's
protocol (plan recorded in the T034 log).

Graphiti keeps its own algorithm. Each `add_episode` extracts entities from the new episode (with
the previous episodes as context), resolves them against the graph (embedding and full-text
candidates, then an LLM deduplication call when needed), extracts fact edges between them,
resolves those against existing facts (duplicates and contradictions, which set `invalid_at` on
the old edge), extracts temporal bounds and entity summaries, embeds names and facts, and saves
the episode. `search` is Graphiti's hybrid edge search: BM25 and cosine similarity over the facts,
fused by reciprocal rank (its `EDGE_HYBRID_SEARCH_RRF` recipe, the one `Graphiti.search` uses).
This module is the adapter patch; it changes only where Graphiti sends its calls and where it
keeps its graph:

1. **Model calls.** Graphiti's LLM, embedder and cross-encoder clients are replaced by
   `PortLLM`, `PortEmbedder` and `PortReranker`, which send every request through the
   harness's `ModelPort` (and so through `grace.llm` and the run's cost ledger). Graphiti's own
   provider clients are never constructed, so it cannot reach a hosted API. LLM calls are
   `external` with the trigger of the phase (ingestion: `write`, ledger `W`); embeddings are
   `embed`. Decoding is the model config's (temperature 0). The engine's `max_tokens` caps every
   call, including the ones where Graphiti sets its own limit (edge extraction asks for 16,384).
   The ledger's `prompt_sha256` of an LLM call is
   `prompt_hash(<prompt name>, <structured-output mode>)`: Graphiti's template is code, identified
   by its name in the pinned version, and the mode is part of how it is sent, so every call record
   says which template and whether constrained decoding was used (`prompt_names_by_hash`), and
   calls can be counted by type from `calls.jsonl` alone.
2. **Structured output.** `PortLLM` is upstream's `OpenAIGenericClient` (Graphiti's client for
   OpenAI-compatible servers such as vLLM) with only the transport replaced. In its default mode,
   `json_schema` (`structured_output: json_schema`), the response model's JSON schema is sent as
   `response_format`, which vLLM enforces by constrained decoding; this is the only engine of the
   project that uses constrained decoding, because Graphiti's own default does. In `json_object`
   mode the schema is appended to the prompt instead (upstream's fallback). Without constrained
   decoding Qwen3-8B often echoes the schema instead of an instance (T034 log: 6 of the first 8
   conv-26 episodes failed). The reply is parsed as JSON and validated
   against the response model; output that does not parse or validate is retried once by the port
   (`invalid_output` records), as for every engine of this project, and then by Graphiti's own
   retry policy (4 attempts on JSON errors and empty replies). The policy is upstream's except
   that it does not sleep between attempts (its back-off waits for rate limits of a hosted API).
   A call that fails after all retries raises in Graphiti, so its episode fails.
3. **Failed episodes** are skipped and counted, never fixed by hand: `add_episode` raising
   leaves the graph without that episode, the message stays in the visible log, and the engine
   logs one line `GRAPHITI_EPISODE {json}` per episode (logger `grace.graphiti`, level INFO for
   `ok`, WARNING for `failed`) with the version, message ID, outcome, error and number of LLM
   calls. The logger writes to stderr unless configured otherwise. The failure rate (T034 log) is
   computed from these lines and `calls.jsonl`.
4. **Graph store.** The embedded Kuzu backend (`KuzuDriver`), one on-disk database in a temporary
   directory per engine, that is per history; no server is started. `save` checkpoints and copies
   the database file next to `state.json`. The driver's `_database` is set to the group ID:
   `KuzuDriver` of the pinned version never sets it, and `add_episode` with a `group_id` reads it.
   The full-text indexes are created through the driver's graph operations, since
   `Graphiti.build_indices_and_constraints` does nothing on Kuzu in the pinned version.
5. **Telemetry and `.env`** are off: `GRAPHITI_TELEMETRY_ENABLED=false` is set before the import,
   and `dotenv.load_dotenv` (called by Graphiti at import) is replaced by a no-op, so no `.env`
   file is read.

Message mapping: one Graphiti group per history (`group_id` = history ID, or a hash of it when it
has characters Graphiti refuses), one episode per message, written in version order: name = the
message ID, body `<speaker>: <text>`, source `message`, reference time = the message's time, else
its segment's time (`message_time`), else `UNKNOWN_TIME` (no invented date: every such episode
gets the same constant). The previous episodes Graphiti shows the extractor are passed explicitly
as the last `RELEVANT_SCHEMA_LIMIT` (10, upstream's window) episodes written, so that messages that
share a segment time keep their order (upstream picks them by `valid_at`, where ties are
unordered).

Evidence set shown to the answering LLM: the edges Graphiti's `search` returns for the question
(`top_k`, upstream's default 10), in its ranking, packed into the read's budget. Each edge is one
fragment `[<message ids>] (valid <valid_at> to <invalid_at>) <fact>`: the IDs are the messages of
the episodes the edge cites, and the bounds are the edge's own (`unknown` when not set; the
parenthesis is left out when neither is). A further-retrieval request is searched the same way;
its new edges follow the original ones.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import importlib.metadata
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import weakref
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from grace.context import api
from grace.eval.engines.baselines.base import BaselineEngine, CallTag, message_time, query_text

GRAPHITI_VERSION = "0.31.2"
RELEVANT_SCHEMA_LIMIT = 10  # graphiti_core.search.search_utils.RELEVANT_SCHEMA_LIMIT
UNKNOWN_TIME = datetime(1970, 1, 1, tzinfo=UTC)
LLM_ATTEMPTS = 4  # Graphiti's LLMClient._generate_response_with_retry: stop_after_attempt(4)
DB_FILE = "graph.kuzu"
PROMPT_NAMES = (  # graphiti_core.prompts.names.PromptName of the pinned version
    "extract_nodes.extract_message", "extract_nodes.extract_json", "extract_nodes.extract_text",
    "extract_nodes.classify_nodes", "extract_nodes.extract_attributes",
    "extract_nodes.extract_summary", "extract_nodes.extract_summaries_batch",
    "extract_nodes.extract_entity_summaries_from_episodes", "dedupe_nodes.node",
    "dedupe_nodes.node_list", "dedupe_nodes.nodes", "extract_edges.edge",
    "extract_edges.extract_attributes", "extract_edges.extract_timestamps",
    "extract_edges.extract_timestamps_batch", "extract_nodes_and_edges.extract_message",
    "dedupe_edges.resolve_edge", "summarize_nodes.summarize_pair",
    "summarize_nodes.summarize_context", "summarize_nodes.summary_description",
    "summarize_sagas.summarize_saga", "eval.query_expansion", "eval.qa_prompt",
    "eval.eval_prompt", "eval.eval_add_episode_results")
UNNAMED_PROMPT = "unnamed"

LOG = logging.getLogger("grace.graphiti")
if not LOG.handlers:  # the episode lines are run evidence: on stderr even when nothing is set up
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    LOG.addHandler(_handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False
_PROMPT: contextvars.ContextVar[str] = contextvars.ContextVar("graphiti_prompt",
                                                              default=UNNAMED_PROMPT)
_GROUP_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*[ \t]*\r?\n?|\r?\n?```[ \t]*$")
_G: SimpleNamespace | None = None
_NO_CLIENT = object()


STRUCTURED_OUTPUT = ("json_schema", "json_object")  # OpenAIGenericClient's modes


def prompt_hash(name: str, mode: str) -> str:
    """The ledger's `prompt_sha256` of a Graphiti call: its template named in the pinned version,
    and the structured-output mode it was sent with."""
    return hashlib.sha256(f"graphiti-core=={GRAPHITI_VERSION}:{name}:{mode}".encode()).hexdigest()


def prompt_names_by_hash() -> dict[str, tuple[str, str]]:
    """`prompt_sha256` -> (prompt name, structured-output mode)."""
    return {prompt_hash(name, mode): (name, mode)
            for name in (*PROMPT_NAMES, UNNAMED_PROMPT) for mode in STRUCTURED_OUTPUT}


def response_format(response_model: Any, mode: str) -> dict[str, Any]:
    """`OpenAIGenericClient._build_response_format` of the pinned version."""
    if response_model is None or mode == "json_object":
        return {"type": "json_object"}
    return {"type": "json_schema",
            "json_schema": {"name": getattr(response_model, "__name__", "structured_response"),
                            "schema": response_model.model_json_schema()}}


def group_id(history_id: str) -> str:
    """Graphiti's partition of a history: its ID, or a hash when Graphiti would refuse the ID."""
    if _GROUP_ID.match(history_id):
        return history_id
    return "h" + hashlib.sha256(history_id.encode()).hexdigest()[:16]


def reference_time(when: str | None) -> datetime:
    """An ISO 8601 message time as an aware datetime (UTC when it has no zone)."""
    if not when:
        return UNKNOWN_TIME
    value = datetime.fromisoformat(when)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def episode_body(message: api.Message) -> str:
    return f"{message.speaker}: {message.text}" if message.speaker else message.text


def parse_structured(text: str, response_model: Any = None) -> dict[str, Any]:
    """Graphiti's parsing of a reply (fence stripped, JSON object), plus validation against the
    response model; raises ValueError where the reply would not serve Graphiti."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    if not cleaned:
        raise ValueError("empty reply")
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    if response_model is not None:
        try:
            response_model.model_validate(data)
        except Exception as exc:  # pydantic.ValidationError is not a ValueError subclass here
            raise ValueError(f"reply does not match {response_model.__name__}: {exc}") from exc
    return data


def render_bound(value: datetime | None) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M") if value else "unknown"


def render_edge(fact: str, evidence_ids: Sequence[str], valid_at: datetime | None,
                invalid_at: datetime | None) -> str:
    ids = f"[{', '.join(evidence_ids)}] " if evidence_ids else ""
    stamp = ""
    if valid_at or invalid_at:
        stamp = f"(valid {render_bound(valid_at)} to {render_bound(invalid_at)}) "
    return f"{ids}{stamp}{fact}"


def features() -> dict[str, Any]:
    """The Graphiti and Kuzu versions installed, or None when the package is missing."""
    out = {}
    for name in ("graphiti-core", "kuzu"):
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = None
    return out


# ---------------------------------------------------------------------------------------------
# Graphiti, imported lazily (only the envs/graphiti environment has it)


def _graphiti() -> SimpleNamespace:
    global _G
    if _G is not None:
        return _G
    version = features()["graphiti-core"]
    if version != GRAPHITI_VERSION:
        raise RuntimeError(f"graphiti-core {version} installed, the adapter is written for "
                           f"{GRAPHITI_VERSION}; use the envs/graphiti environment")
    os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False  # Graphiti calls it at import
    import warnings

    from graphiti_core import Graphiti
    from graphiti_core.cross_encoder.client import CrossEncoderClient
    from graphiti_core.driver.kuzu_driver import KuzuDriver
    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.llm_client.client import is_server_or_retry_error
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.errors import EmptyResponseError
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
    from graphiti_core.nodes import EpisodeType
    from graphiti_core.search import search_utils

    if search_utils.RELEVANT_SCHEMA_LIMIT != RELEVANT_SCHEMA_LIMIT:
        raise RuntimeError("RELEVANT_SCHEMA_LIMIT differs from the pinned version")
    warnings.filterwarnings("ignore", message="The Kuzu backend is deprecated")

    class InvalidStructuredOutput(json.JSONDecodeError):
        """Final output of the port did not parse or validate; Graphiti retries it."""

        def __init__(self, reason: str):
            super().__init__(reason, "", 0)

    class PortLLM(OpenAIGenericClient):
        """Upstream's client for OpenAI-compatible servers, sending through the model port. The
        `client` argument keeps upstream from constructing an OpenAI client; it is never used."""

        def __init__(self, engine: GraphitiEngine, max_tokens: int, mode: str):
            super().__init__(LLMConfig(api_key="unused", model=engine.model.model,
                                       temperature=0), cache=False, client=_NO_CLIENT,
                             max_tokens=max_tokens, structured_output_mode=mode)
            self.engine = engine

        async def generate_response(self, *args, **kwargs):
            # upstream signature: (messages, response_model, max_tokens, model_size, group_id,
            # prompt_name, *, attribute_extraction, model); the name is kept per asyncio task
            name = kwargs.get("prompt_name") or (args[5] if len(args) > 5 else None)
            _PROMPT.set(name or UNNAMED_PROMPT)
            return await super().generate_response(*args, **kwargs)

        async def _generate_response_with_retry(self, messages, response_model=None,
                                                max_tokens=None, model_size=None, *,
                                                model=None):
            for attempt in range(1, LLM_ATTEMPTS + 1):
                try:
                    return await self._generate_response(messages, response_model, max_tokens)
                except Exception as exc:
                    if attempt == LLM_ATTEMPTS or not is_server_or_retry_error(exc):
                        raise
            raise AssertionError("unreachable")

        async def _generate_response(self, messages, response_model=None, max_tokens=None,
                                     model_size=None, *, model=None):
            engine = self.engine
            chat = []
            for m in messages:  # as upstream: input cleaned, system and user turns only
                m.content = self._clean_input(m.content)
                if m.role in ("system", "user"):
                    chat.append({"role": m.role, "content": m.content})
            name, mode = _PROMPT.get(), self.structured_output_mode

            def parse(text):
                return parse_structured(text, response_model)

            result = await asyncio.to_thread(
                engine.model.chat, chat, engine.tag("external"),
                prompt_sha256=prompt_hash(name, mode), parse=parse,
                max_tokens=min(max_tokens or self.max_tokens, self.max_tokens),
                response_format=response_format(response_model, mode))
            engine.note_call(name, result)
            if result.ok:
                return result.parsed
            if result.text is None:
                raise RuntimeError(f"{name}: every transport attempt failed")
            if not result.text.strip():
                raise EmptyResponseError(f"{name}: empty reply")
            raise InvalidStructuredOutput(f"{name}: reply does not parse or validate")

    class PortEmbedder(EmbedderClient):
        """Stands in for a `graphiti_core.embedder` provider. Texts embedded at read time (the
        query) get the configured instruction."""

        def __init__(self, engine: GraphitiEngine):
            self.engine = engine

        async def create(self, input_data):
            if isinstance(input_data, str):
                return (await self.create_batch([input_data]))[0]
            items = list(input_data)
            if not all(isinstance(t, str) for t in items):
                raise TypeError("token-ID input is not supported by the embedding port")
            return (await self.create_batch(items))[0]

        async def create_batch(self, input_data_list):
            engine = self.engine
            texts = list(input_data_list)
            if engine.trigger == "read" and engine.query_instruction:
                texts = [f"Instruct: {engine.query_instruction}\nQuery: {t}" for t in texts]
            result = await asyncio.to_thread(engine.model.embed, texts, engine.tag("embed"))
            engine.call_ids.extend(result.call_ids)
            return [list(v) for v in result.vectors]

    class PortReranker(CrossEncoderClient):
        """Stands in for a `graphiti_core.cross_encoder` provider. The search recipe used here
        (RRF) does not rerank with a cross-encoder; a call means the recipe changed."""

        async def rank(self, query, passages):
            raise RuntimeError("cross-encoder reranking is not part of the configured search")

    _G = SimpleNamespace(Graphiti=Graphiti, KuzuDriver=KuzuDriver, EpisodeType=EpisodeType,
                         PortLLM=PortLLM, PortEmbedder=PortEmbedder, PortReranker=PortReranker)
    return _G


# ---------------------------------------------------------------------------------------------
# Engine


class GraphitiEngine(BaselineEngine):
    kind = "graphiti"

    def __init__(self, model, *, top_k: int = 10, max_tokens: int = 16384,
                 query_instruction: str | None = None, max_coroutines: int | None = None,
                 structured_output: str = "json_schema"):
        super().__init__(model)
        if top_k < 1 or max_tokens < 1 or (max_coroutines is not None and max_coroutines < 1):
            raise ValueError("top_k >= 1, max_tokens >= 1 and max_coroutines >= 1 or null")
        if structured_output not in STRUCTURED_OUTPUT:
            raise ValueError(f"structured_output is one of {STRUCTURED_OUTPUT}")
        self.structured_output = structured_output
        _graphiti()
        self.top_k, self.max_tokens, self.max_coroutines = top_k, max_tokens, max_coroutines
        self.query_instruction = query_instruction
        self.loop = asyncio.new_event_loop()
        self.workdir = Path(tempfile.mkdtemp(prefix="grace-graphiti-"))
        weakref.finalize(self, _cleanup, self.loop, self.workdir)
        self.client = None
        self.episodes: dict[str, str] = {}  # Graphiti episode UUID -> message ID
        self.recent: list[str] = []  # UUIDs of the last episodes written, oldest first
        self.outcomes: list[dict[str, Any]] = []  # one per message written
        self.trigger, self.version_now, self.read_id = "write", None, None
        self.call_ids: list[str] = []
        self.call_names: list[str] = []  # prompt name per logical LLM call of the current write
        self.call_failures = 0

    # model port ---------------------------------------------------------------------------
    def tag(self, call_type: str) -> CallTag:
        return CallTag(call_type, self.trigger, self._history().history_id, self.version_now,
                       self.read_id)

    def note_call(self, name: str, result) -> None:
        self.call_ids.extend(result.call_ids)
        self.call_names.append(name)
        if not result.ok:
            self.call_failures += 1

    # Graphiti instance --------------------------------------------------------------------
    def _connect(self, db_path: Path, fresh: bool) -> None:
        g = _graphiti()
        driver = g.KuzuDriver(db=str(db_path))
        # KuzuDriver never sets `_database`, which add_episode compares with the group ID; Kuzu
        # has one database per file, so the group is its database.
        driver._database = self.group
        llm = g.PortLLM(self, self.max_tokens, self.structured_output)
        self.client = g.Graphiti(graph_driver=driver, llm_client=llm,
                                 embedder=g.PortEmbedder(self), cross_encoder=g.PortReranker(),
                                 max_coroutines=self.max_coroutines)
        if fresh:
            # Graphiti.build_indices_and_constraints is a no-op on Kuzu in the pinned version;
            # the full-text indexes its BM25 search needs are created by the driver's graph ops.
            self.loop.run_until_complete(driver.graph_ops.build_indices_and_constraints(driver))

    @property
    def group(self) -> str:
        return group_id(self._history().history_id)

    # write --------------------------------------------------------------------------------
    def _on_write(self, message):
        self.call_ids, self.call_names, self.call_failures = [], [], 0
        if self.client is None:
            self._connect(self.workdir / DB_FILE, fresh=True)
        when = message_time(message, self._history())
        self.trigger, self.version_now = "write", message.version
        outcome: dict[str, Any] = {"version": message.version, "message_id": message.message_id}
        try:
            result = self.loop.run_until_complete(self.client.add_episode(
                name=message.message_id, episode_body=episode_body(message),
                source_description=f"{self._history().benchmark} conversation message",
                reference_time=reference_time(when), source=_graphiti().EpisodeType.message,
                group_id=self.group, previous_episode_uuids=list(self.recent)))
        except Exception as exc:  # noqa: BLE001 - a failed episode is skipped and counted
            outcome.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
        else:
            uuid = result.episode.uuid
            self.episodes[uuid] = message.message_id
            self.recent = [*self.recent, uuid][-RELEVANT_SCHEMA_LIMIT:]
            outcome.update(status="ok", nodes=len(result.nodes), edges=len(result.edges))
        finally:
            self.version_now = None
        outcome.update(llm_calls=len(self.call_names), llm_calls_failed=self.call_failures,
                       prompts=self.call_names)
        self.outcomes.append(outcome)
        level = logging.INFO if outcome["status"] == "ok" else logging.WARNING
        LOG.log(level, "GRAPHITI_EPISODE %s", json.dumps(
            {"history_id": self._history().history_id, **outcome}, sort_keys=True))
        return list(self.call_ids)

    # read ---------------------------------------------------------------------------------
    def _search(self, query: str, task: api.ReadTask) -> list[Any]:
        if self.client is None or not self.episodes or not query.strip():
            return []
        self.trigger, self.version_now, self.read_id = "read", task.version, task.read_id
        try:
            return self.loop.run_until_complete(self.client.search(
                query, group_ids=[self.group], num_results=self.top_k))
        finally:
            self.trigger, self.version_now, self.read_id = "write", None, None

    def _build(self, task, budget, request):
        self.call_ids = []
        ranked = self._search(query_text(task, self.messages), task)
        if request is not None:
            seen = {e.uuid for e in ranked}
            ranked += [e for e in self._search(request, task) if e.uuid not in seen]
        packer = self._packer()
        fragments, candidates = [], []
        for rank, edge in enumerate(ranked):
            evidence = [self.episodes[u] for u in edge.episodes if u in self.episodes]
            text = render_edge(edge.fact, evidence, edge.valid_at, edge.invalid_at)
            fragments.append(packer.fragment(edge.uuid, "retrieved", text, evidence, evidence))
            candidates.append(api.Candidate(edge.uuid, "graphiti", 1.0 / (rank + 1)))
        return packer.pack(task, budget, fragments), candidates, list(self.call_ids)

    # persistence --------------------------------------------------------------------------
    def save(self, directory: Path) -> list[Path]:
        files = super().save(directory)
        if self.client is not None:
            conn = self.client.driver.client
            self.loop.run_until_complete(conn.execute("CHECKPOINT;"))
            target = Path(directory) / DB_FILE
            shutil.copyfile(self.workdir / DB_FILE, target)
            files.append(target)
        return files

    def restore(self, directory: Path) -> None:
        self._restore_from = Path(directory)
        super().restore(directory)

    def _state(self):
        return {"episodes": self.episodes, "recent": self.recent, "outcomes": self.outcomes,
                "graph": self.client is not None}

    def _load_state(self, state):
        self.episodes, self.recent = state["episodes"], state["recent"]
        self.outcomes = state["outcomes"]
        if state["graph"]:
            shutil.copyfile(self._restore_from / DB_FILE, self.workdir / DB_FILE)
            self._connect(self.workdir / DB_FILE, fresh=False)


def _cleanup(loop: asyncio.AbstractEventLoop, workdir: Path) -> None:
    if not loop.is_closed() and not loop.is_running():
        loop.close()
    shutil.rmtree(workdir, ignore_errors=True)
