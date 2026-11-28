"""Slot-table writer of ablation B (T027): one extract call per unit, rows checked by program."""

import json
import tempfile
import unittest
from pathlib import Path

from grace.context.api import Message
from grace.context.memory.graph.slots import SlotTable, load_inventory
from grace.context.pipeline.update.slots import SlotWriter
from grace.llm.client import ChatClient, Endpoint
from grace.llm.records import CallLedger
from tests.llm.fakes import WordCounter, completion


class Transport:
    def __init__(self, reply):
        self.reply, self.requests = reply, []

    def __call__(self, url, payload, headers, timeout):
        self.requests.append(payload)
        return completion(self.reply if isinstance(self.reply, str) else json.dumps(self.reply))


def message(version, speaker, text):
    return Message("fixture", "fixture", "h", version, f"m{version}", "s1", speaker, "user", text,
                   "2024-04-20", None)


UNIT = [message(1, "Ana", "I live in Lisbon."),
        message(2, "agent", "There is flight TP1950."),
        message(3, "Ana", "Sorry, I meant Porto, not Lisbon.")]
ENTRIES = {"entries": [
    {"message": 1, "slot": "person.location", "subject": "Ana", "value": "Lisbon",
     "function": "inform"},
    {"message": 2, "slot": "item.choice", "subject": "Ana's flight booking", "value": "TP1950",
     "function": "offer"},
    {"message": 3, "slot": "person.location", "subject": "Ana", "value": "Porto",
     "function": "correct", "correction": True, "valid_from": "not a date"},
    {"message": 3, "slot": "no.such.slot", "subject": "Ana", "value": "x", "function": "inform"},
    {"message": 7, "slot": "person.location", "subject": "Ana", "value": "y",
     "function": "inform"}]}


class SlotWriterTest(unittest.TestCase):
    def writer(self, reply, structured="json_schema"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = CallLedger(Path(tmp.name) / "calls.jsonl", "T027-20261128T000000Z-0000")
        self.transport = Transport(reply)
        client = ChatClient(Endpoint("http://fake.invalid/v1", "fake", "fake@T027"), self.ledger,
                            WordCounter(), max_attempts=1, transport=self.transport,
                            sleep=lambda s: None)
        return SlotWriter(client, load_inventory(), structured_output=structured,
                          decoding={"temperature": 0.0})

    def test_rows_are_checked_and_attributed_to_the_message_speaker(self):
        writer = self.writer(ENTRIES)
        result = writer.extract("h", UNIT)
        self.assertEqual(result.status, "ok")
        self.assertEqual([(r.slot, r.value, r.speaker, r.version) for r in result.rows],
                         [("person.location", "Lisbon", "Ana", 1),
                          ("item.choice", "TP1950", "agent", 2),
                          ("person.location", "Porto", "Ana", 3)])
        self.assertEqual(result.dropped, {"slot": 1, "message_number": 1, "date": 1})
        record = self.ledger.records[0]
        self.assertEqual((record.call_type, record.category, record.version), ("extract", "W", 3))
        payload = self.transport.requests[0]
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertIn("person.location: where a person lives", payload["messages"][-1]["content"])
        table = SlotTable("h", load_inventory())
        for rows in result.by_version():
            table.append(rows)
        current = sorted(v.value for v in table.state().current())
        self.assertEqual(current, ["Porto", "TP1950"])

    def test_invalid_output(self):
        writer = self.writer("not json", structured="none")
        result = writer.extract("h", UNIT[:1])
        self.assertEqual(result.status, "invalid_output")
        self.assertNotIn("response_format", self.transport.requests[0])
        self.assertEqual(self.ledger.records[0].status, "invalid_output")


if __name__ == "__main__":
    unittest.main()
