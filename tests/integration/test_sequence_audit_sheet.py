"""The committed sequence-audit sheet (task T016) is reproduced from the T015 dataset run.

Skipped where the run directory is absent. Redraws the sample from
`$PROJECT_ROOT/runs/T015/artifacts/T015-devmodel-20261125T192037Z/dataset` (manifest checked) and
compares sheet and sample record with docs/research/annotations/sequence-audit/ byte for byte.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grace.cli.annotate.sequence import RECORD, SHEET, default_dataset, main


def dataset_present() -> bool:
    try:
        return (default_dataset() / "MANIFEST.sha256").is_file()
    except RuntimeError:
        return False


@unittest.skipUnless(dataset_present(), "no T015 dataset run under PROJECT_ROOT")
class SequenceAuditSheetTest(unittest.TestCase):
    def test_sheet_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet, record = Path(tmp) / "sheet.csv", Path(tmp) / "sample.json"
            self.assertEqual(main(["sheet", "--out", str(sheet), "--record", str(record)]), 0)
            self.assertEqual(sheet.read_bytes(), SHEET.read_bytes())
            self.assertEqual(record.read_bytes(), RECORD.read_bytes())


if __name__ == "__main__":
    unittest.main()
