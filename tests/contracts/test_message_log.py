"""Contract tests for the message log and evidence spans (contracts.md, "Claim graph"; T014)."""

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from grace.context.api import Message
from grace.context.memory.history import spans
from grace.context.memory.history.log import LogConflict, LogError, MessageLog
from tests.contracts.test_claim_graph import FIXTURE, HISTORY, fixture_changesets


def fixture_messages() -> list[Message]:
    lines = (FIXTURE / "messages.jsonl").read_text(encoding="utf-8").splitlines()
    return [Message.from_record(json.loads(line)) for line in lines]


class MessageLogTest(unittest.TestCase):
    def setUp(self):
        self.messages = fixture_messages()
        self.log = MessageLog(HISTORY)
        for m in self.messages:
            self.assertEqual(self.log.append(m), m.version)

    def test_one_version_per_message_and_reads_at_a_cutoff(self):
        self.assertEqual(self.log.head, 10)
        self.assertEqual(self.log.next_version(), 11)
        for r in range(0, 11):
            self.assertEqual([m.version for m in self.log.messages(r)], list(range(1, r + 1)))
        self.assertEqual(self.log.by_id("m3").version, 3)
        with self.assertRaises(KeyError):
            self.log.by_id("m7", version=6)
        self.assertEqual(self.log.get(7).message_id, "m7")

    def test_idempotent_retry(self):
        for m in self.messages:
            self.assertEqual(self.log.append(m), m.version)
        self.assertEqual(self.log.head, 10)
        changed = dataclasses.replace(self.messages[2], text="Something else.")
        with self.assertRaises(LogConflict):
            self.log.append(changed)
        self.assertEqual(self.log.get(3), self.messages[2])

    def test_append_rules(self):
        last = self.messages[-1]
        cases = {
            "gap": dataclasses.replace(last, version=12, message_id="m12"),
            "reused id": dataclasses.replace(last, version=11),
            "other history": dataclasses.replace(last, history_id="other", version=11,
                                                 message_id="m11"),
        }
        for name, message in cases.items():
            with self.subTest(case=name), self.assertRaises(LogError):
                self.log.append(message)
        self.assertEqual(self.log.head, 10)

    def test_save_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.log.save(Path(tmp))
            restored = MessageLog.restore(Path(tmp), HISTORY)
            self.assertEqual(restored.messages(), self.log.messages())
            with self.assertRaises(FileExistsError):
                self.log.save(Path(tmp))


class SpanTest(unittest.TestCase):
    def setUp(self):
        self.messages = {m.message_id: m for m in fixture_messages()}

    def test_evidence_ids(self):
        whole = spans.SpanAnchor("m1")
        part = spans.SpanAnchor("m1", 10, 16)
        self.assertEqual(whole.evidence_id, "m1")
        self.assertEqual(part.evidence_id, "m1#char=10,16")
        for anchor in (whole, part, spans.SpanAnchor("D2:5", 0, 3)):
            self.assertEqual(spans.parse_evidence_id(anchor.evidence_id), anchor)
        self.assertEqual(spans.message_of("s1:3#char=0,4"), "s1:3")
        self.assertEqual(spans.message_of("a#b"), "a#b")

    def test_anchors_fit_their_message(self):
        m1 = self.messages["m1"]
        self.assertEqual(spans.SpanAnchor("m1", 10, 16).text(m1), "Munich")
        self.assertEqual(spans.anchor_quote(m1, "Munich"), spans.SpanAnchor("m1", 10, 16))
        for bad in (lambda: spans.SpanAnchor("m1", 10, 99).text(m1),
                    lambda: spans.SpanAnchor("m2", 0, 1).text(m1),
                    lambda: spans.anchor_quote(m1, "Berlin"),
                    lambda: spans.anchor_quote(m1, "Munich", occurrence=1),
                    lambda: spans.SpanAnchor("m1", 4, 4),
                    lambda: spans.SpanAnchor("m1", 4, None)):
            with self.assertRaises(spans.SpanError):
                bad()

    def test_fixture_evidence_spans_anchor_in_the_messages(self):
        for cs in fixture_changesets():
            for link in cs.evidence_links:
                message = self.messages[link.message_id]
                self.assertLessEqual(message.version, cs.version)
                if link.span:
                    anchor = spans.SpanAnchor(link.message_id, link.span.start, link.span.end)
                    self.assertTrue(anchor.text(message))


if __name__ == "__main__":
    unittest.main()
