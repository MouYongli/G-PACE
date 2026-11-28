"""Evidence-in-context metrics of E013 (`eval/analysis/metrics/evidence.py`)."""

from __future__ import annotations

import unittest

from grace.eval.analysis.metrics import evidence


class EvidenceTest(unittest.TestCase):
    def test_strict_lenient_hit_recall_and_unsupported(self):
        gold = {"evidence_ids": ["D1:3", "D2:1#char=0,5"]}
        trace = {"provenance": {"q1": ["D2:1"], "D1:3": ["D1:3"]}}
        pred = {"output": "answer", "context_ids": ["D1:3", "D4:4"]}
        v = evidence.read_values(pred, gold, trace)
        self.assertEqual(v, {"full_evidence_hit": 0.0, "full_evidence_lenient": 1.0,
                             "evidence_hit": 1.0, "evidence_recall": 0.5,
                             "unsupported_answer": 0.0})
        none = evidence.read_values({"output": "answer", "context_ids": ["D9:9"]}, gold, None)
        self.assertEqual((none["evidence_hit"], none["unsupported_answer"]), (0.0, 1.0))
        abstained = evidence.read_values({"output": "unknown", "context_ids": []}, gold, None)
        self.assertEqual(abstained["unsupported_answer"], 0.0)
        full = evidence.read_values({"output": "answer", "context_ids": ["D1:3", "D2:1"]},
                                    gold, None)
        self.assertEqual(full["full_evidence_hit"], 1.0)

    def test_reads_without_gold_evidence_are_not_scored(self):
        self.assertIsNone(evidence.read_values({"output": "answer", "context_ids": ["D1:1"]},
                                               {"evidence_ids": []}, None))
        self.assertIsNone(evidence.read_values({"output": "answer", "context_ids": []},
                                               {"evidence_ids": None}, None))

    def test_answer_prompt_tokens_take_the_last_successful_answer_call(self):
        calls = [{"call_type": "answer", "status": "invalid_output", "read_id": "r",
                  "input_tokens": 9},
                 {"call_type": "answer", "status": "ok", "read_id": "r", "input_tokens": 7},
                 {"call_type": "plan", "status": "ok", "read_id": "r", "input_tokens": 99}]
        self.assertEqual(evidence.answer_prompt_tokens(calls), {"r": 7})


if __name__ == "__main__":
    unittest.main()
