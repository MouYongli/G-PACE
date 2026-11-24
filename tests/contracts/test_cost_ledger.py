"""Contract tests for the Cost ledger section of docs/research/contracts.md."""

import copy
import json
import unittest
from collections import defaultdict
from pathlib import Path

from tests.contracts.records import ContractError, check_fields, read_jsonl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "runs"
NULL = type(None)
CALL = {"call_id": str, "run_id": str, "history_id": (str, NULL), "read_id": (str, NULL),
        "version": (int, NULL), "call_type": str, "trigger": str, "category": str, "model": str,
        "attempt": int, "status": str, "input_tokens": int, "output_tokens": int,
        "cached_input_tokens": int, "gpu_seconds": (int, float, NULL), "latency_ms": (int, float),
        "prompt_sha256": (str, NULL)}
# call_type -> category; for `external`, trigger -> category.
# Table "Which tokens are counted when" of the Cost ledger section.
CATEGORY = {"extract": "W", "vocabulary": "W", "render": "W", "summary": "W", "plan": "U",
            "repair": "U", "verify": "U", "answer": "A", "embed": "embedding",
            "judge": "evaluation", "external": {"write": "W", "read": "U"}}
TRIGGERS = {"write", "read", "evaluation"}
STATUSES = {"ok", "failed", "invalid_output"}


def check_calls(rows):
    check_fields(rows, CALL, "calls")
    problems = defaultdict(list)
    seen = set()
    for row in rows:
        cid = row["call_id"]
        if cid in seen:
            problems["duplicate_key"].append(cid)
        seen.add(cid)
        expected = CATEGORY.get(row["call_type"])
        if isinstance(expected, dict):
            expected = expected.get(row["trigger"])
        if row["category"] != expected:
            problems["wrong_category"].append(cid)
        if row["trigger"] not in TRIGGERS or (row["call_type"] == "judge") != (
            row["trigger"] == "evaluation"
        ):
            problems["bad_trigger"].append(cid)
        if row["trigger"] == "write" and row["read_id"] is not None:
            problems["bad_trigger"].append(cid)
        if row["status"] not in STATUSES or row["attempt"] < 1:
            problems["bad_value"].append(cid)
        if not 0 <= row["cached_input_tokens"] <= row["input_tokens"] or row["output_tokens"] < 0:
            problems["bad_tokens"].append(cid)
    if problems:
        raise ContractError(problems)


def ledgers(rows):
    """The three ledgers per category; failed and invalid attempts count in full."""
    out = defaultdict(lambda: {"logical": 0, "computed": 0, "gpu_seconds": 0.0, "gpu_null": 0})
    for row in rows:
        ledger = out[row["category"]]
        ledger["logical"] += row["input_tokens"] + row["output_tokens"]
        uncached = row["input_tokens"] - row["cached_input_tokens"]
        ledger["computed"] += uncached + row["output_tokens"]
        if row["gpu_seconds"] is None:
            ledger["gpu_null"] += 1
        else:
            ledger["gpu_seconds"] += row["gpu_seconds"]
    return out


def per_read(rows, reads):
    """Logical tokens per read: W charged before it (per turn, interleaved), U_i and A_i."""
    out, previous = {}, 0
    for read_id, version in sorted(reads.items(), key=lambda item: item[1]):
        def logical(rows_):
            return sum(r["input_tokens"] + r["output_tokens"] for r in rows_)

        writes = [r for r in rows if r["category"] == "W" and (
            previous < (r["version"] or 0) <= version or r["read_id"] == read_id)]
        out[read_id] = {
            "version": version,
            "W_before": logical(writes),
            "U": logical(r for r in rows if r["category"] == "U" and r["read_id"] == read_id),
            "A": logical(r for r in rows if r["category"] == "A" and r["read_id"] == read_id),
        }
        previous = version
    return out


class CostLedgerTest(unittest.TestCase):
    def setUp(self):
        self.rows = read_jsonl(FIXTURES / "calls.jsonl")
        self.expected = json.loads((FIXTURES / "ledger-expected.json").read_text("utf-8"))

    def test_fixture_follows_the_contract(self):
        check_calls(self.rows)

    def test_three_ledgers(self):
        got = ledgers(self.rows)
        for category, expected in self.expected["categories"].items():
            with self.subTest(category=category):
                self.assertEqual(got[category]["logical"], expected["logical"])
                self.assertEqual(got[category]["computed"], expected["computed"])
                self.assertAlmostEqual(got[category]["gpu_seconds"], expected["gpu_seconds"])
                self.assertEqual(got[category]["gpu_null"], expected["gpu_null"])

    def test_write_plan_render_and_read_time(self):
        reads = {rid: item["version"] for rid, item in self.expected["reads"].items()}
        self.assertEqual(per_read(self.rows, reads), self.expected["reads"])
        total_w = self.expected["categories"]["W"]["logical"]
        self.assertEqual(sum(r["W_before"] for r in self.expected["reads"].values()), total_w)

    def test_lazy_rebuild_at_read_time_is_W(self):
        lazy = [r for r in self.rows if r["call_type"] == "render" and r["trigger"] == "read"]
        self.assertTrue(lazy)
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if row["call_type"] == "render" and row["trigger"] == "read":
                row["category"] = "U"
        with self.assertRaises(ContractError) as caught:
            check_calls(rows)
        self.assertIn("wrong_category", caught.exception.problems)

    def test_failed_attempts_are_counted(self):
        failed = [r for r in self.rows if r["status"] != "ok"]
        self.assertTrue(failed)
        without = ledgers([r for r in self.rows if r["status"] == "ok"])
        full = ledgers(self.rows)
        self.assertGreater(full["W"]["logical"], without["W"]["logical"])
        self.assertGreater(full["A"]["logical"], without["A"]["logical"])

    def test_judge_and_embedding_are_not_system_cost(self):
        rows = copy.deepcopy(self.rows)
        judge = next(r for r in rows if r["call_type"] == "judge")
        judge["category"] = "A"
        with self.assertRaises(ContractError):
            check_calls(rows)
        system = sum(ledgers(self.rows)[c]["logical"] for c in ("W", "U", "A"))
        everything = sum(item["logical"] for item in ledgers(self.rows).values())
        self.assertEqual(everything - system, 40 + 203)

    def test_cached_tokens_cannot_exceed_input(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["cached_input_tokens"] = rows[0]["input_tokens"] + 1
        with self.assertRaises(ContractError) as caught:
            check_calls(rows)
        self.assertIn("bad_tokens", caught.exception.problems)


if __name__ == "__main__":
    unittest.main()
