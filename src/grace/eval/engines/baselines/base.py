"""Shared machinery of the baselines: the model port, the message log and budget packing.

A baseline implements `grace.context.api.ContextEngine` and imports nothing from
`eval/datasets/` (structure.md). It receives everything through the interface: visible history
headers, messages and read tasks. Model calls go through a `ModelPort` handed in at construction;
the harness supplies one that records every call in `calls.jsonl` (contracts.md, "Cost ledger").
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from grace.config.paths import REPO_ROOT
from grace.context import api
from grace.llm.prompts import Prompt, load_pinned

# ---------------------------------------------------------------------------------------------
# Model port


@dataclass(frozen=True)
class CallTag:
    """What a model call serves; the recorder derives the ledger category from it."""

    call_type: str
    trigger: str
    history_id: str | None
    version: int | None
    read_id: str | None = None


@dataclass(frozen=True)
class ChatResult:
    """Final attempt of a logical chat call. `parsed` is the output of the caller's parser;
    `ok` is False when every attempt failed or produced invalid output."""

    text: str | None
    parsed: Any
    ok: bool
    call_ids: tuple[str, ...]
    input_tokens: int = 0


@dataclass(frozen=True)
class EmbedResult:
    vectors: tuple[tuple[float, ...], ...]
    call_ids: tuple[str, ...]


class ModelPort(Protocol):
    """The model access a baseline needs. Implemented by the harness (`harness/models.py`).

    `max_tokens` caps the generated tokens of the call (None: the backend's default)."""

    def chat(self, messages: Sequence[dict[str, str]], tag: CallTag, *,
             prompt_sha256: str | None = None,
             parse: Callable[[str], Any] | None = None,
             max_tokens: int | None = None) -> ChatResult: ...

    def embed(self, texts: Sequence[str], tag: CallTag) -> EmbedResult: ...

    def count_tokens(self, text: str) -> int: ...


# ---------------------------------------------------------------------------------------------
# Rendering and packing


EMPTY_CONTEXT = "[no memory]"


def message_time(message: api.Message, history: api.HistoryInfo) -> str | None:
    """The message's own time, else the time of its segment (contracts.md, "Message")."""
    if message.timestamp:
        return message.timestamp
    segment = history.segment(message.segment_id)
    return segment.timestamp if segment else None


def render_message(message: api.Message, history: api.HistoryInfo) -> str:
    """One message as it appears in a working context, with its citable ID first."""
    when = message_time(message, history)
    speaker = message.speaker or message.role
    stamp = f" ({when})" if when else ""
    return f"[{message.message_id}]{stamp} {speaker}: {message.text}"


@dataclass
class Packer:
    """Builds a working context within a token budget from fragments in priority order."""

    count: Callable[[str], int]
    separator: str = "\n"
    fragments: list[api.Fragment] = field(default_factory=list)

    def fragment(self, fragment_id: str, kind: str, text: str, evidence_ids: Iterable[str],
                 source_ids: Iterable[str] = ()) -> api.Fragment:
        return api.Fragment(fragment_id, kind, text, tuple(evidence_ids), tuple(source_ids),
                            self.count(text))

    def pack(self, task: api.ReadTask, budget: int | None,
             candidates: Sequence[api.Fragment],
             order: Callable[[api.Fragment], Any] | None = None) -> api.WorkingContext:
        """Take candidates in priority order while the context fits `budget`; then sort the kept
        fragments by `order` (default: priority order). A fragment that does not fit is skipped,
        and smaller ones after it may still be taken."""
        kept: list[api.Fragment] = []
        used = 0
        for fragment in candidates:
            extra = fragment.tokens + (1 if kept else 0)
            if budget is not None and used + extra > budget:
                continue
            kept.append(fragment)
            used += extra
        if order is not None:
            kept.sort(key=order)
        text = self.join(kept)
        while budget is not None and self.count(text) > budget and kept:
            kept.pop()  # the per-fragment estimate was short: drop from the end until it fits
            text = self.join(kept)
        return api.WorkingContext(task.read_id, task.history_id, task.version, budget,
                                  self.count(text), text, tuple(kept))

    def join(self, fragments: Sequence[api.Fragment]) -> str:
        """The context text; an explicit marker when nothing was selected, so that the answering
        model and contexts.jsonl both see the same non-empty text."""
        return self.separator.join(f.text for f in fragments) or EMPTY_CONTEXT


def truncate_to(text: str, budget: int, count: Callable[[str], int]) -> str:
    """The longest word prefix of `text` that fits `budget` tokens (binary search on words)."""
    if count(text) <= budget:
        return text
    words = text.split(" ")
    low, high = 0, len(words)
    while low < high:
        mid = (low + high + 1) // 2
        if count(" ".join(words[:mid])) <= budget:
            low = mid
        else:
            high = mid - 1
    return " ".join(words[:low])


PROMPT_REGISTRY = REPO_ROOT / "configs" / "common" / "prompts.yaml"


def pinned_prompt(name: str) -> Prompt:
    """A prompt of `resources/prompts/`, checked against its pin in the prompt registry."""
    return load_pinned(name, PROMPT_REGISTRY)


def query_text(task: api.ReadTask, messages: Sequence[api.Message]) -> str:
    """Retrieval query of a read: the question, or for a state read the latest message."""
    if task.question is not None:
        return task.question
    return messages[-1].text if messages else ""


# ---------------------------------------------------------------------------------------------
# Base engine


class BaselineEngine(api.ContextEngine):
    """Keeps the visible message log and implements the version checks, save and restore.

    Subclasses implement `_build` and may extend `_on_write`, `_state` and `_load_state`.
    """

    kind = "baseline"

    def __init__(self, model: ModelPort, **params: Any):
        if params:
            raise TypeError(f"{type(self).__name__}: unknown parameters {sorted(params)}")
        self.model = model
        self.history: api.HistoryInfo | None = None
        self.messages: list[api.Message] = []

    # life cycle -------------------------------------------------------------------------------
    def open(self, history: api.HistoryInfo) -> None:
        if self.history is not None:
            raise RuntimeError("engine already holds a history; use one instance per history")
        self.history = history

    @property
    def version(self) -> int:
        return len(self.messages)

    def write(self, message: api.Message) -> api.WriteResult:
        history = self._history()
        if message.history_id != history.history_id:
            raise ValueError(f"message of history {message.history_id!r} written to "
                             f"{history.history_id!r}")
        if message.version != self.version + 1:
            raise ValueError(f"expected version {self.version + 1}, got {message.version}")
        start = time.perf_counter()
        self.messages.append(message)
        call_ids = self._on_write(message)
        timings = {"write": (time.perf_counter() - start) * 1000}
        return api.WriteResult(api.WriteTrace(history.history_id, message.version,
                                              (message.message_id,), tuple(call_ids),
                                              timings_ms=timings))

    def read(self, task: api.ReadTask, budget_tokens: int | None) -> api.ReadResult:
        return self._read(task, budget_tokens, None)

    def further_retrieval(self, task: api.ReadTask, request: str,
                          budget_tokens: int | None) -> api.ReadResult:
        return self._read(task, budget_tokens, request)

    def _read(self, task, budget, request) -> api.ReadResult:
        history = self._history()
        if task.history_id != history.history_id:
            raise ValueError(f"read of history {task.history_id!r} sent to "
                             f"{history.history_id!r}")
        api.check_read(self, task)
        start = time.perf_counter()
        context, candidates, call_ids = self._build(task, budget, request)
        timings = {"read": (time.perf_counter() - start) * 1000}
        trace = api.read_trace(context, candidates=candidates, call_ids=call_ids,
                               further_retrieval=request is not None, timings_ms=timings)
        return api.ReadResult(context, trace)

    # hooks ------------------------------------------------------------------------------------
    def _on_write(self, message: api.Message) -> list[str]:
        """Update derived state after `message` was appended; return the call IDs made."""
        return []

    def _build(self, task: api.ReadTask, budget: int | None, request: str | None,
               ) -> tuple[api.WorkingContext, list[api.Candidate], list[str]]:
        raise NotImplementedError

    def _state(self) -> dict[str, Any]:
        return {}

    def _load_state(self, state: dict[str, Any]) -> None:
        """Restore derived state; the default rebuilds it by replaying `_on_write`-free state."""

    # persistence ------------------------------------------------------------------------------
    def save(self, directory: Path) -> list[Path]:
        history = self._history()
        path = Path(directory) / "state.json"
        state = {"kind": self.kind, "history": history.to_record(),
                 "messages": [m.to_record() for m in self.messages], "state": self._state()}
        path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return [path]

    def restore(self, directory: Path) -> None:
        if self.history is not None:
            raise RuntimeError("restore needs a fresh engine")
        state = json.loads((Path(directory) / "state.json").read_text(encoding="utf-8"))
        if state["kind"] != self.kind:
            raise ValueError(f"snapshot of {state['kind']!r} cannot restore {self.kind!r}")
        self.history = api.HistoryInfo.from_record(state["history"])
        self.messages = [api.Message.from_record(m) for m in state["messages"]]
        self._load_state(state["state"])

    # helpers ----------------------------------------------------------------------------------
    def _history(self) -> api.HistoryInfo:
        if self.history is None:
            raise RuntimeError("open() or restore() first")
        return self.history

    def _packer(self) -> Packer:
        return Packer(self.model.count_tokens)

    def _message_fragment(self, packer: Packer, message: api.Message,
                          kind: str = "message") -> api.Fragment:
        return packer.fragment(message.message_id, kind,
                               render_message(message, self._history()),
                               (message.message_id,), (message.message_id,))
