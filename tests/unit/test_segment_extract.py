"""E006 segment probe: one sampled segment becomes a history of its own (no model calls)."""

import unittest

from grace.context.api import HistoryInfo, Message, Segment
from grace.eval.runner.probes.extract import graph_id, segment_history


def _message(n: int, session: str) -> Message:
    return Message(benchmark="locomo", split="dev", history_id="conv-x", version=n,
                   message_id=f"M{n}", segment_id=session, speaker="A" if n % 2 else "B",
                   role="peer", text=f"text {n}", timestamp=None, timestamp_raw=None)


class SegmentHistoryTest(unittest.TestCase):
    def setUp(self):
        self.messages = [_message(n, "s1" if n <= 5 else "s2") for n in range(1, 11)]
        self.history = HistoryInfo(
            benchmark="locomo", split="dev", history_id="conv-x", subset=None, n_messages=10,
            segments=(Segment("s1", 1, 5, "2023-01-01T10:00", "raw1"),
                      Segment("s2", 6, 10, "2023-01-02T10:00", "raw2")),
            metadata={"question": "never shown"})
        self.segment = {"key": "locomo:conv-x:s2:7-9", "context_ids": ["M4", "M5", "M6"],
                        "message_ids": ["M7", "M8", "M9"]}

    def test_renumbered_and_self_contained(self):
        info, sub = segment_history(self.history, self.messages, self.segment)
        self.assertEqual(graph_id(self.segment), "locomo__conv-x__s2__7-9")
        self.assertEqual(info.history_id, "locomo__conv-x__s2__7-9")
        self.assertEqual([m.version for m in sub], [1, 2, 3, 4, 5, 6])
        self.assertEqual([m.message_id for m in sub], ["M4", "M5", "M6", "M7", "M8", "M9"])
        self.assertTrue(all(m.history_id == info.history_id for m in sub))
        self.assertEqual(info.n_messages, 6)
        self.assertEqual([(s.segment_id, s.first_version, s.last_version, s.timestamp)
                          for s in info.segments],
                         [("s1", 1, 2, "2023-01-01T10:00"), ("s2", 3, 6, "2023-01-02T10:00")])
        self.assertEqual(dict(info.metadata), {})

    def test_missing_message_is_an_error(self):
        bad = dict(self.segment, message_ids=["M7", "M99"])
        with self.assertRaises(ValueError):
            segment_history(self.history, self.messages, bad)


if __name__ == "__main__":
    unittest.main()
