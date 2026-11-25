"""Fixed-schema slot table with speaker, communicative function and provenance (plan 7.2).

Standalone pilot version (T003). The slot inventory and the communicative functions come from the
engine config; the plan defines the slots on development data and then freezes them. Every message
is read by one extraction call (`extract` / trigger `write` / ledger `W`) that returns entries
`{slot, value, function}`; the engine adds the speaker, the role and the provenance (message ID,
version, time). Rows are only appended: there is no attribution guard and no bitemporality, which
is what ablation B adds in the GRACE-assembly version of the slot table (T027; see the T003 Log).

At read time the newest rows that fit the budget are shown in chronological order, one fragment per
row citing its message. The row text is derived, so `source_ids` is empty: the raw message is not
in the context.
"""

from __future__ import annotations

import hashlib
import json

from grace.eval.engines.baselines.base import BaselineEngine, CallTag, message_time

EXTRACT_INSTRUCTIONS = (
    "You fill a fixed-schema slot table from a conversation. Read the new message and output "
    "every value it states, requests, confirms, corrects or rejects for one of the allowed slots. "
    "Use only the allowed slot names and communicative functions. Copy values as short strings. "
    'Output JSON only: {"entries": [{"slot": "...", "value": "...", "function": "..."}]}; '
    'output {"entries": []} when the message fills no slot.'
)


class SlotTable(BaselineEngine):
    kind = "slots"

    def __init__(self, model, *, slots: dict[str, str], functions: list[str],
                 context_messages: int = 1):
        super().__init__(model)
        if not slots or not functions:
            raise ValueError("slot table needs a non-empty slot inventory and function list")
        self.slots, self.functions = dict(slots), list(functions)
        self.context_messages = context_messages
        schema = json.dumps({"slots": self.slots, "functions": self.functions}, sort_keys=True)
        self.prompt_sha256 = hashlib.sha256(
            (EXTRACT_INSTRUCTIONS + "\n" + schema).encode("utf-8")).hexdigest()
        self.system = (f"{EXTRACT_INSTRUCTIONS}\n\nAllowed slots (name: description):\n"
                       + "\n".join(f"- {k}: {v}" for k, v in self.slots.items())
                       + "\n\nAllowed communicative functions: " + ", ".join(self.functions))
        self.rows: list[dict] = []

    def _parse(self, text: str) -> list[dict]:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("no JSON object in the output")
        data = json.loads(text[start: end + 1])
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise ValueError("`entries` must be a list")
        out = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"slot", "value", "function"}:
                raise ValueError(f"bad entry {entry!r}")
            if entry["slot"] not in self.slots or entry["function"] not in self.functions:
                raise ValueError(f"slot or function outside the schema: {entry!r}")
            if not isinstance(entry["value"], str) or not entry["value"].strip():
                raise ValueError(f"empty value: {entry!r}")
            out.append(entry)
        return out

    def _on_write(self, message):
        history = self._history()
        before = self.messages[-1 - self.context_messages:-1] if self.context_messages else []
        lines = [f"[{m.message_id}] {m.speaker or m.role}: {m.text}" for m in before]
        user = ("Earlier messages:\n" + "\n".join(lines) + "\n\n" if lines else "") + (
            f"New message [{message.message_id}] {message.speaker or message.role} "
            f"({message.role}): {message.text}")
        tag = CallTag("extract", "write", message.history_id, message.version)
        result = self.model.chat([{"role": "system", "content": self.system},
                                  {"role": "user", "content": user}], tag,
                                 prompt_sha256=self.prompt_sha256, parse=self._parse)
        if result.ok:
            for entry in result.parsed:
                self.rows.append({**entry, "speaker": message.speaker, "role": message.role,
                                  "message_id": message.message_id, "version": message.version,
                                  "time": message_time(message, history)})
        return list(result.call_ids)

    @staticmethod
    def render_row(row: dict) -> str:
        stamp = f" ({row['time']})" if row["time"] else ""
        who = row["speaker"] or row["role"]
        return (f"[{row['message_id']}]{stamp} {row['slot']} = {row['value']} "
                f"(speaker: {who}, role: {row['role']}, function: {row['function']})")

    def _build(self, task, budget, request):
        packer = self._packer()
        fragments = [packer.fragment(f"row-{i}", "other", self.render_row(row),
                                     (row["message_id"],))
                     for i, row in enumerate(self.rows) if row["version"] <= task.version]
        index = {f.fragment_id: i for i, f in enumerate(fragments)}
        context = packer.pack(task, budget, list(reversed(fragments)),
                              order=lambda f: index[f.fragment_id])
        return context, [], []

    def _state(self):
        return {"rows": self.rows}

    def _load_state(self, state):
        self.rows = state["rows"]
