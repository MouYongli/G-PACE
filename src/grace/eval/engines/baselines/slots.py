"""Fixed-schema slot table with speaker, communicative function and provenance (plan 7.2).

Standalone pilot version (T003). The slot inventory and the communicative functions come from the
engine config; the plan defines the slots on development data and then freezes them. Every message
is read by one extraction call (`extract` / trigger `write` / ledger `W`, pinned prompt
`resources/prompts/extract-slots/`, inventory first and the new message last) that returns entries
`{slot, value, function}`; the engine adds the speaker, the role and the provenance (message ID,
version, time). Rows are only appended: there is no attribution guard and no bitemporality, which
is what ablation B adds in the GRACE-assembly version of the slot table (T027; see the T003 Log).

At read time the newest rows that fit the budget are shown in chronological order, one fragment per
row citing its message. The row text is derived, so `source_ids` is empty: the raw message is not
in the context.
"""

from __future__ import annotations

from grace.eval.engines.baselines.base import BaselineEngine, CallTag, message_time, pinned_prompt
from grace.llm.structured import extract_json

NO_EARLIER = "(none)"
MAX_TOKENS = 512  # generated tokens of one extraction call


class SlotTable(BaselineEngine):
    kind = "slots"

    def __init__(self, model, *, slots: dict[str, str], functions: list[str],
                 context_messages: int = 1):
        super().__init__(model)
        if not slots or not functions:
            raise ValueError("slot table needs a non-empty slot inventory and function list")
        self.slots, self.functions = dict(slots), list(functions)
        self.context_messages = context_messages
        self.prompt = pinned_prompt("extract-slots")
        self.slot_text = "\n".join(f"- {k}: {v}" for k, v in self.slots.items())
        self.rows: list[dict] = []

    def _parse(self, text: str) -> list[dict]:
        data = extract_json(text)
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
        earlier = "\n".join(f"[{m.message_id}] {m.speaker or m.role}: {m.text}" for m in before)
        messages = self.prompt.render(
            slots=self.slot_text, functions=", ".join(self.functions),
            earlier=earlier or NO_EARLIER,
            message=f"[{message.message_id}] {message.speaker or message.role} "
                    f"({message.role}): {message.text}")
        tag = CallTag("extract", "write", message.history_id, message.version)
        result = self.model.chat(messages, tag, prompt_sha256=self.prompt.sha256,
                                 parse=self._parse, max_tokens=MAX_TOKENS)
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
