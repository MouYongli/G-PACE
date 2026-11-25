"""Fragment-coverage annotation (task T012): label files, coverage, Cohen's kappa, overlap choice.

Kappa values are hand-computed on small synthetic label sets. The last test checks the committed
sheet and the agent pre-annotation under docs/research/annotations/fragment-coverage/ against each
other; it reads no benchmark data.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from grace.eval.analysis.annotation.fragment import (
    LabelError,
    agreement,
    coverage,
    overlap_ids,
    read_labels,
    read_sheet,
    render_agreement,
    render_coverage,
    wilson,
)
from grace.eval.datasets.benchmarks.base import DataError, load_config
from grace.eval.datasets.benchmarks.locomo_annotation import (
    OVERLAP_SEED,
    SHEET_COLUMNS,
    fragment_sheet,
    select_overlap,
)

REPO = Path(__file__).resolve().parents[2]
ANNOTATIONS = REPO / "docs" / "research" / "annotations" / "fragment-coverage"
COLUMNS = ("question_id", "annotator", "label", "operations", "other_reason", "flags",
           "rationale")


def write_csv(directory: Path, name: str, rows: list[dict], columns=COLUMNS) -> Path:
    path = directory / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    return path


def labels(annotator: str, classes: list[str], extra: dict | None = None) -> list[dict]:
    rows = []
    for i, label in enumerate(classes):
        row = {"question_id": f"h:q{i}", "annotator": annotator, "label": label}
        if label == "other":
            row["other_reason"] = "image_only"
        row.update((extra or {}).get(i, {}))
        rows.append(row)
    return rows


class LabelFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_operations_flags_and_skips_unlabelled_rows(self):
        rows = labels("alice", ["in_fragment", "other"],
                      {0: {"operations": "join; filter", "flags": "relative_time"}})
        rows.append({"question_id": "h:q9", "annotator": "", "label": ""})
        result = read_labels(write_csv(self.dir, "a.csv", rows))
        self.assertEqual(result.annotator, "alice")
        self.assertEqual(result.kind, "human")
        self.assertEqual(result.unlabelled, 1)
        self.assertEqual(result.labels["h:q0"].operations, ("filter", "join"))
        self.assertEqual(result.labels["h:q0"].flags, ("relative_time",))
        self.assertEqual(result.labels["h:q1"].other_reason, "image_only")

    def test_agent_prefix_marks_a_pre_annotation(self):
        path = write_csv(self.dir, "a.csv", labels("agent-m01-T012", ["in_fragment"]))
        self.assertEqual(read_labels(path).kind, "agent")

    def test_rejects_malformed_rows(self):
        cases = {
            "unknown label": labels("a", ["maybe"]),
            "unknown operation": labels("a", ["in_fragment"], {0: {"operations": "union"}}),
            "provenance is implicit": labels("a", ["in_fragment"],
                                              {0: {"operations": "provenance"}}),
            "operations outside the fragment": labels("a", ["common_sense"],
                                                      {0: {"operations": "join"}}),
            "other without reason": labels("a", ["other"], {0: {"other_reason": ""}}),
            "reason without other": labels("a", ["open_reasoning"],
                                           {0: {"other_reason": "image_only"}}),
            "flag outside the fragment": labels("a", ["date_arithmetic"],
                                                {0: {"flags": "relative_time"}}),
            "unknown flag": labels("a", ["in_fragment"], {0: {"flags": "maybe"}}),
            "two annotators": labels("a", ["in_fragment"]) + [
                {"question_id": "h:q5", "annotator": "b", "label": "in_fragment"}],
            "duplicate question": labels("a", ["in_fragment"]) * 2,
            "empty annotator": [{"question_id": "h:q0", "annotator": "", "label": "other",
                                 "other_reason": "image_only"}],
            "no labelled rows": [{"question_id": "h:q0", "annotator": "a", "label": ""}],
        }
        for name, rows in cases.items():
            with self.subTest(name):
                with self.assertRaises(LabelError):
                    read_labels(write_csv(self.dir, "bad.csv", rows))

    def test_missing_column(self):
        path = write_csv(self.dir, "bad.csv", [{"question_id": "h:q0"}],
                         columns=("question_id", "label"))
        with self.assertRaises(LabelError):
            read_labels(path)


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        sheet_rows = [{"question_id": f"h:q{i}", "category": str(1 + i % 2),
                       "overlap": "yes" if i < 4 else "no"} for i in range(6)]
        self.sheet = read_sheet(write_csv(self.dir, "sheet.csv", sheet_rows,
                                          columns=("question_id", "category", "overlap")))

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_shares_and_categories(self):
        rows = labels("a", ["in_fragment", "in_fragment", "open_reasoning", "other",
                            "in_fragment"],
                      {0: {"operations": "count;filter"}, 1: {"flags": "partial_image"}})
        result = coverage(read_labels(write_csv(self.dir, "a.csv", rows)), self.sheet)
        self.assertEqual(result["n"], 5)
        self.assertEqual(result["missing_from_sheet"], 1)
        self.assertEqual(result["classes"]["in_fragment"], {"count": 3, "share": 0.6})
        self.assertEqual(result["classes"]["date_arithmetic"]["count"], 0)
        self.assertEqual(result["coverage"]["count"], 3)
        self.assertEqual(result["single_pattern"], 2)
        self.assertEqual(result["operations"]["count"], 1)
        self.assertEqual(result["other_reasons"]["image_only"], 1)
        self.assertEqual(result["flags"]["partial_image"], 1)
        self.assertEqual(result["coverage_without_flagged"]["count"], 2)
        # categories alternate 1, 2, 1, 2, 1 over q0..q4
        self.assertEqual(result["by_category"]["1"]["in_fragment"], 2)
        self.assertEqual(result["by_category"]["1"]["n"], 3)
        self.assertEqual(result["by_category"]["2"]["open_reasoning"], 0)
        self.assertEqual(result["by_category"]["2"]["other"], 1)
        self.assertIn("| in_fragment | 3 | 60.0% |", render_coverage(result))

    def test_rejects_questions_outside_the_sheet(self):
        rows = [{"question_id": "x:q1", "annotator": "a", "label": "in_fragment"}]
        with self.assertRaises(LabelError):
            coverage(read_labels(write_csv(self.dir, "a.csv", rows)), self.sheet)

    def test_wilson_interval(self):
        low, high = wilson(50, 100)
        self.assertAlmostEqual(low, 0.4038, places=4)
        self.assertAlmostEqual(high, 0.5962, places=4)
        low, high = wilson(0, 10)
        self.assertAlmostEqual(low, 0.0)
        self.assertAlmostEqual(high, 0.2775, places=4)

    def test_kappa_on_the_overlap_only(self):
        # Overlap q0..q3. a: in in out out; b: in out out out (q4, q5 outside the overlap differ
        # on purpose and must not count).
        a = labels("alice", ["in_fragment", "in_fragment", "open_reasoning", "common_sense",
                             "in_fragment", "in_fragment"])
        b = labels("bob", ["in_fragment", "open_reasoning", "open_reasoning", "common_sense",
                           "other", "other"])
        la = read_labels(write_csv(self.dir, "a.csv", a))
        lb = read_labels(write_csv(self.dir, "b.csv", b))
        result = agreement(la, lb, overlap_ids(self.sheet))
        # Five classes on 4 items: observed 3/4; marginals a = in 2, open 1, common 1;
        # b = in 1, open 2, common 1; expected = (2*1 + 1*2 + 1*1) / 16 = 5/16;
        # kappa = (3/4 - 5/16) / (1 - 5/16) = 7/11.
        self.assertEqual(result["classes"]["n"], 4)
        self.assertAlmostEqual(result["classes"]["observed"], 0.75)
        self.assertAlmostEqual(result["classes"]["kappa"], 7 / 11)
        # In/out: a = in in out out, b = in out out out; observed 3/4, expected (2*1+2*3)/16
        # = 1/2; kappa = 1/2.
        self.assertAlmostEqual(result["binary"]["kappa"], 0.5)
        self.assertEqual(result["disagreements"], ["h:q1"])
        self.assertEqual(result["confusion"]["in_fragment"]["open_reasoning"], 1)
        self.assertTrue(result["human_agreement"])
        # Without the restriction the two extra disagreements enter.
        self.assertEqual(agreement(la, lb)["classes"]["n"], 6)

    def test_agent_labels_are_not_reported_as_human_agreement(self):
        a = read_labels(write_csv(self.dir, "a.csv", labels("agent-x", ["in_fragment"] * 2)))
        b = read_labels(write_csv(self.dir, "b.csv", labels("bob", ["in_fragment", "other"])))
        result = agreement(a, b)
        self.assertFalse(result["human_agreement"])
        self.assertIn("not inter-annotator agreement", render_agreement(result))

    def test_kappa_undefined_when_both_use_one_class(self):
        a = read_labels(write_csv(self.dir, "a.csv", labels("a", ["in_fragment"] * 3)))
        b = read_labels(write_csv(self.dir, "b.csv", labels("b", ["in_fragment"] * 3)))
        result = agreement(a, b)
        self.assertIsNone(result["classes"]["kappa"])
        self.assertIn("undefined", render_agreement(result))

    def test_agreement_needs_two_annotators_and_shared_questions(self):
        a = read_labels(write_csv(self.dir, "a.csv", labels("a", ["in_fragment"])))
        with self.assertRaises(LabelError):
            agreement(a, a)
        b = read_labels(write_csv(self.dir, "b.csv", [
            {"question_id": "h:q5", "annotator": "b", "label": "in_fragment"}]))
        with self.assertRaises(LabelError):
            agreement(a, b)


class OverlapSelectionTest(unittest.TestCase):
    @staticmethod
    def rows(spec: dict[tuple[str, int], int]) -> list[dict]:
        return [{"question_id": f"{h}:q{c * 100 + i}", "history_id": h, "category": c}
                for (h, c), n in spec.items() for i in range(n)]

    def test_proportional_and_deterministic(self):
        rows = self.rows({("conv-26", 1): 32, ("conv-26", 2): 37, ("conv-26", 3): 13,
                          ("conv-26", 4): 70, ("conv-49", 1): 37, ("conv-49", 2): 33,
                          ("conv-49", 3): 13, ("conv-49", 4): 73})
        chosen = select_overlap(rows)
        self.assertEqual(len(chosen), 100)
        self.assertEqual(len(set(chosen)), 100)
        self.assertEqual(chosen, select_overlap(list(reversed(rows))))
        strata = Counter((q.split(":")[0], int(q.split(":q")[1]) // 100) for q in chosen)
        # 100 * n / 308, largest remainder: 10.4, 12.0, 4.2, 22.7, 12.0, 10.7, 4.2, 23.7
        self.assertEqual(strata, {("conv-26", 1): 10, ("conv-26", 2): 12, ("conv-26", 3): 4,
                                  ("conv-26", 4): 23, ("conv-49", 1): 12, ("conv-49", 2): 11,
                                  ("conv-49", 3): 4, ("conv-49", 4): 24})
        self.assertNotEqual(chosen, select_overlap(rows, seed=OVERLAP_SEED + "-other"))

    def test_size_bounds(self):
        rows = self.rows({("h", 1): 3})
        self.assertEqual(len(select_overlap(rows, size=3)), 3)
        for size in (0, 4):
            with self.assertRaises(ValueError):
                select_overlap(rows, size=size)

    def test_sheet_refuses_held_out_splits(self):
        with self.assertRaises(DataError):
            fragment_sheet("held-out", config=load_config("locomo"))


class CommittedAnnotationTest(unittest.TestCase):
    """The committed sheet and the agent pre-annotation agree with each other."""

    def test_sheet_and_agent_labels(self):
        sheet = read_sheet(ANNOTATIONS / "sheet.csv")
        with (ANNOTATIONS / "sheet.csv").open(encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle))
        self.assertEqual(tuple(header), SHEET_COLUMNS)
        self.assertEqual(len(sheet), 308)
        self.assertEqual({r["history_id"] for r in sheet.values()}, {"conv-26", "conv-49"})
        self.assertEqual({r["category"] for r in sheet.values()}, {"1", "2", "3", "4"})
        self.assertEqual(len(overlap_ids(sheet)), 100)
        self.assertTrue(all(not r["label"] for r in sheet.values()), "the sheet stays blank")
        agent = read_labels(ANNOTATIONS / "labels-agent-m01-T012.csv")
        self.assertEqual(agent.annotator, "agent-m01-T012")
        self.assertEqual(agent.kind, "agent")
        self.assertEqual(set(agent.labels), set(sheet))
        self.assertTrue(all(lab.rationale for lab in agent.labels.values()))


if __name__ == "__main__":
    unittest.main()
