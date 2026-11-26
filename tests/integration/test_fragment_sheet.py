"""The committed fragment-coverage sheet (task T012) is reproduced from the LoCoMo store.

Skipped where the data is absent. Regenerates the sheet of the development split through
`load_split` (manifest and count checks) and compares it with
docs/research/annotations/fragment-coverage/sheet.csv byte for byte.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grace.config.paths import project_root
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.locomo_annotation import fragment_sheet, write_sheet

SHEET = (Path(__file__).resolve().parents[2] / "docs" / "research" / "annotations"
         / "fragment-coverage" / "sheet.csv")


def locomo_present() -> bool:
    try:
        config = load_config("locomo")
        return config.source_dir(project_root()).is_dir()
    except RuntimeError:
        return False


@unittest.skipUnless(locomo_present(), "no LoCoMo data under PROJECT_ROOT")
class FragmentSheetTest(unittest.TestCase):
    def test_sheet_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sheet.csv"
            write_sheet(fragment_sheet("dev"), out)
            self.assertEqual(out.read_bytes(), SHEET.read_bytes())


if __name__ == "__main__":
    unittest.main()
