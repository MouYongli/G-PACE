"""Slot-table writer of ablation B (plan 7.3, B; T027): the writer step for the slot table.

Replaces the claim writer (`extract.py`) when the representation is the fixed slot table
(`memory/graph/slots.py`). One call of type `extract` per extraction unit (the writer's
granularity and local context, `configs/common/writer.yaml`), through
`grace.llm.client.ChatClient`, with the pinned prompt `extract-slots-attributed`; the inventory and
function list come first (stable prefix), the unit last. Output is constrained by
`resources/schemas/llm/extract-slots-attributed.json` when `structured_output` is `json_schema`.

The program, not the model, decides what enters the table: entries whose slot or function is
outside the frozen inventory, or whose message number is outside the unit, are dropped and
counted; malformed dates are dropped to null. The speaker of a row is the speaker of its message.
Supersession is decided by `SlotTable.state` (guard and time are factors of the table).
"""

from __future__ import annotations

import datetime as _dt
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grace.config.paths import REPO_ROOT
from grace.context.api import Message
from grace.context.memory.graph.slots import (
    DEFAULT_EXCLUSIVE,
    INVENTORY_FILE,
    SlotInventory,
    SlotRow,
    SlotTable,
    load_inventory,
)
from grace.context.pipeline.update.extract import (
    Extraction,
    Extractor,
    WriterInput,
    render_messages,
)
from grace.context.pipeline.update.patch import ClaimPatch
from grace.llm.client import ChatClient, LLMCallFailed
from grace.llm.prompts import Prompt, load_pinned
from grace.llm.records import CallContext
from grace.llm.structured import load_schema, parse

PROMPT = "extract-slots-attributed"
REGISTRY = REPO_ROOT / "configs" / "common" / "prompts.yaml"


@dataclass(frozen=True)
class SlotExtraction:
    status: str                                   # ok | invalid_output | failed
    rows: tuple[SlotRow, ...] = ()
    dropped: Mapping[str, int] = field(default_factory=dict)
    error: str | None = None
    call_ids: tuple[str, ...] = ()

    def by_version(self) -> list[list[SlotRow]]:
        """Rows grouped per version in version order, as `SlotTable.append` takes them."""
        groups: dict[int, list[SlotRow]] = {}
        for row in self.rows:
            groups.setdefault(row.version, []).append(row)
        return [groups[v] for v in sorted(groups)]


def _date_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return _dt.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        return None


def rows_from_entries(entries: Sequence[Mapping[str, Any]], unit: Sequence[Message],
                      inventory: SlotInventory) -> tuple[list[SlotRow], Counter]:
    """Slot rows of a parsed output; entries outside the schema's meaning are dropped."""
    rows: list[SlotRow] = []
    dropped: Counter = Counter()
    counters: Counter = Counter()
    for entry in entries:
        number = entry["message"]
        if not 1 <= number <= len(unit):
            dropped["message_number"] += 1
            continue
        if entry["slot"] not in inventory.slots:
            dropped["slot"] += 1
            continue
        if entry["function"] not in inventory.functions:
            dropped["function"] += 1
            continue
        message = unit[number - 1]
        start, end = (_date_or_none(entry.get("valid_from")),
                      _date_or_none(entry.get("valid_until")))
        if (entry.get("valid_from"), entry.get("valid_until")) != (start, end):
            dropped["date"] += 1
        if start and end and not start < end:
            start, end = start, None
            dropped["date"] += 1
        counters[message.message_id] += 1
        try:
            rows.append(SlotRow(
                f"{message.message_id}#s{counters[message.message_id]}", entry["slot"],
                entry["subject"].strip(), entry["value"].strip(),
                message.speaker or message.role, entry["function"],
                entry.get("report_mode", "own"), entry.get("polarity", "positive"),
                bool(entry.get("correction", False)), start, end, message.message_id,
                message.version))
        except ValueError:
            dropped["row"] += 1
    rows.sort(key=lambda r: r.version)
    return rows, dropped


@dataclass
class SlotWriter:
    """One `extract` call per unit producing attributed slot rows (module docstring)."""

    client: ChatClient
    inventory: SlotInventory
    prompt: Prompt = field(default_factory=lambda: load_pinned(PROMPT, REGISTRY))
    validator: Any = field(default_factory=lambda: load_schema(PROMPT))
    structured_output: str = "json_schema"
    decoding: Mapping[str, Any] = field(default_factory=dict)
    message_chars: int | None = 4000
    earlier_chars: int | None = 600
    dates: Mapping[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.structured_output not in ("json_schema", "none"):
            raise ValueError("structured_output must be json_schema or none")

    def messages(self, unit: Sequence[Message], earlier: Sequence[Message]
                 ) -> list[dict[str, str]]:
        return self.prompt.render(
            slots="\n".join(f"- {k}: {v}" for k, v in self.inventory.slots.items()),
            functions=", ".join(self.inventory.functions),
            earlier=render_messages(earlier, self.dates, numbered=False,
                                    chars=self.earlier_chars) or "(none)",
            messages=render_messages(unit, self.dates, numbered=True, chars=self.message_chars))

    def _decoding(self) -> dict[str, Any]:
        out = dict(self.decoding)
        if self.structured_output == "json_schema":
            out["response_format"] = {"type": "json_schema",
                                      "json_schema": {"name": "slot_entries",
                                                      "schema": dict(self.validator.schema)}}
        return out

    def extract(self, history_id: str, unit: Sequence[Message],
                earlier: Sequence[Message] = (), *, trigger: str = "write",
                read_id: str | None = None) -> SlotExtraction:
        if not unit:
            raise ValueError("empty extraction unit")
        context = CallContext(call_type="extract", trigger=trigger, history_id=history_id,
                              read_id=read_id, version=unit[-1].version)
        try:
            result = self.client.chat(self.messages(unit, earlier), context,
                                      prompt_sha256=self.prompt.sha256,
                                      decoding=self._decoding(),
                                      validate=lambda text: parse(text, self.validator).error)
        except LLMCallFailed as exc:
            return SlotExtraction("failed", error=str(exc),
                                  call_ids=tuple(r.call_id for r in exc.records))
        call_ids = tuple(r.call_id for r in result.records)
        parsed = parse(result.text, self.validator)
        if not parsed.ok:
            return SlotExtraction("invalid_output", error=parsed.error, call_ids=call_ids)
        rows, dropped = rows_from_entries(parsed.value["entries"], unit, self.inventory)
        return SlotExtraction("ok", tuple(rows), dict(dropped), call_ids=call_ids)


# ---------------------------------------------------------------------------------------------
# Engine component (ablation B, slot-table arm)


_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SlotFact:
    """A current slot value offered to the assembler as a state item (duck-typed by the engine:
    `item_id`, `text`, `evidence_ids`, `version`, `valid`)."""

    item_id: str
    text: str
    evidence_ids: tuple[str, ...]
    version: int
    valid: tuple[str | None, str | None] | None


class SlotExtractorAdapter(Extractor):
    """The updater's extractor for the slot arm: every unit goes to the slot writer, its rows to
    the slot table, and the claim graph receives an empty patch. Units, granularity, flushes
    before a read and retries stay the updater's."""

    name = "slots"

    def __init__(self, writer: SlotWriter | None, table: SlotTable):
        self.writer, self.table = writer, table

    def extract(self, request: WriterInput) -> Extraction:
        if self.writer is None:  # dry run without a chat client
            return Extraction("ok", ClaimPatch())
        result = self.writer.extract(request.history_id, request.messages, request.earlier,
                                     trigger=request.trigger, read_id=request.read_id)
        if result.status != "ok":
            return Extraction(result.status, error=result.error, call_ids=result.call_ids)
        for rows in result.by_version():
            self.table.append(rows)
        return Extraction("ok", ClaimPatch(), call_ids=result.call_ids,
                          statuses=("ok",) * len(result.call_ids))


class SlotMemory:
    """Per-history component of the slot-table arm (the engine's extension hook, see
    `context/engine.py`): the slot table replaces the claim graph as the store of state; at a
    read the current values (bitemporal: those not ended) are offered as state items, ranked by
    word overlap with the request, then by recency."""

    deferred = None

    def __init__(self, history_id: str, inventory: SlotInventory, writer: SlotWriter | None, *,
                 guard: bool, time: str):
        self.table = SlotTable(history_id, inventory, guard=guard, time=time)
        self.writer = writer

    def extractor(self, default: Extractor) -> Extractor:
        return SlotExtractorAdapter(self.writer, self.table)

    def read_graph(self, store, version: int):
        return store

    def state_facts(self, task, request: str) -> list[SlotFact]:
        words = set(_WORD.findall(request.lower()))
        values = self.table.state(task.version).current()

        def score(v):
            text = f"{v.first.subject} {v.first.slot} {v.value}".lower()
            return (-len(words & set(_WORD.findall(text))), -v.rows[-1].version)

        out = []
        for i, v in enumerate(sorted(values, key=score), start=1):
            first = v.first
            speakers = ", ".join(dict.fromkeys(f"{r.speaker} {r.function}" for r in v.rows))
            when = ""
            if v.valid_from or v.valid_until:
                when = f" (valid {v.valid_from or '?'} to {v.valid_until or 'open'})"
            text = f"{first.subject} | {first.slot} = {v.value}{when} [{speakers}]"
            valid = (v.valid_from, v.valid_until) if (v.valid_from or v.valid_until) else None
            out.append(SlotFact(f"{task.read_id}:slot{i}", text, v.evidence_ids,
                                max(r.version for r in v.rows), valid))
        return out

    def save(self, directory: Path) -> list[Path]:
        Path(directory).mkdir(parents=True, exist_ok=True)
        return self.table.save(directory)

    def restore(self, directory: Path) -> None:
        self.table = SlotTable.restore(directory, self.table.inventory)


def slot_table(*, writer, client=None, view_config=None, guard: bool = True,
               time: str = "bitemporal", inventory: str | None = None,
               exclusive: Sequence[str] | None = None):
    """Component factory (`config/registry.py`, name `slot-table`): one `SlotMemory` per
    history; the slot writer uses the writer config's decoding, context and clipping."""
    inv = load_inventory(REPO_ROOT / inventory if inventory else INVENTORY_FILE,
                         exclusive if exclusive is not None else DEFAULT_EXCLUSIVE)

    def make(history) -> SlotMemory:
        slot_writer = None
        if client is not None:
            slot_writer = SlotWriter(client, inv, structured_output=writer.structured_output,
                                     decoding=dict(writer.decoding),
                                     message_chars=writer.message_chars,
                                     earlier_chars=writer.earlier_chars,
                                     dates={s.segment_id: s.timestamp
                                            for s in history.segments})
        return SlotMemory(history.history_id, inv, slot_writer, guard=guard, time=time)
    return make
