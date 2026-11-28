"""Snapshots restore messages whose text holds Unicode line separators (E013: two LongMemEval-S
histories failed to restore because str.splitlines() split a JSON Lines record at U+2028)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grace.context import api
from grace.context.memory.history.log import MessageLog


class JsonLinesRestoreTest(unittest.TestCase):
    def test_message_text_with_line_separators_round_trips(self):
        log = MessageLog("h")
        texts = ["plain", "line separator", "next\x85line", "para graph\x1cfs"]
        for i, text in enumerate(texts, start=1):
            log.append(api.Message("locomo", "dev", "h", i, f"D1:{i}", "S1", "A", "user",
                                   text, "2023-05-01", None))
        with tempfile.TemporaryDirectory() as tmp:
            log.save(Path(tmp))
            back = MessageLog.restore(Path(tmp), "h")
        self.assertEqual([m.text for m in back.messages()], texts)


if __name__ == "__main__":
    unittest.main()
