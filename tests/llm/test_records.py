"""llm/records.py against the Cost ledger section and its fixture."""

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from grace.llm.records import (
    CallContext,
    CallLedger,
    CallRecord,
    CallRecordError,
    category_for,
    read_calls,
)
from tests.contracts.test_cost_ledger import CATEGORY

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "calls.jsonl"


class RecordsTest(unittest.TestCase):
    def test_fixture_loads_and_matches_the_ledger_totals(self):
        records = read_calls(FIXTURE)
        expected = json.loads((FIXTURE.parent / "ledger-expected.json").read_text("utf-8"))
        for category, totals in expected["categories"].items():
            rows = [r for r in records if r.category == category]
            self.assertEqual(sum(r.logical_tokens for r in rows), totals["logical"])
            self.assertEqual(sum(r.computed_tokens for r in rows), totals["computed"])

    def test_category_table_matches_the_contract_test(self):
        for call_type, category in CATEGORY.items():
            if isinstance(category, dict):
                for trigger, value in category.items():
                    self.assertEqual(category_for(call_type, trigger), value)
            else:
                trigger = "evaluation" if call_type == "judge" else "read"
                self.assertEqual(category_for(call_type, trigger), category)
        self.assertEqual(category_for("render", "read"), "W")  # lazy rebuild is W

    def test_invalid_records_are_refused(self):
        base = read_calls(FIXTURE)[0]
        bad = {
            "category": "U",
            "trigger": "evaluation",
            "cached_input_tokens": base.input_tokens + 1,
            "status": "retried",
            "attempt": 0,
            "read_id": "q@1",  # write-triggered call with a read_id
            "input_tokens": 1.5,
            "gpu_seconds": -1.0,
            "call_type": "rerank",
        }
        for field, value in bad.items():
            with self.subTest(field=field), self.assertRaises(CallRecordError):
                dataclasses.replace(base, **{field: value})
        with self.assertRaises(CallRecordError):
            CallContext("judge", "read")
        with self.assertRaises(CallRecordError):
            CallContext("extract", "write", read_id="q@1")

    def test_ledger_ids_are_unique_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calls.jsonl"
            ledger = CallLedger(path, "run-1")
            base = dataclasses.replace(read_calls(FIXTURE)[0], run_id="run-1")
            first = dataclasses.replace(base, call_id=ledger.new_call_id())
            ledger.write(first)
            with self.assertRaises(CallRecordError):
                ledger.write(first)
            with self.assertRaises(CallRecordError):
                ledger.write(dataclasses.replace(base, call_id="x", run_id="run-2"))
            resumed = CallLedger(path, "run-1")
            self.assertNotEqual(resumed.new_call_id(), first.call_id)
            with self.assertRaises(CallRecordError):
                CallLedger(path, "run-2")

    def test_unknown_field_in_file_is_refused(self):
        row = json.loads(FIXTURE.read_text("utf-8").splitlines()[0])
        row["extra"] = 1
        with self.assertRaises(CallRecordError):
            CallRecord.from_dict(row)


if __name__ == "__main__":
    unittest.main()
