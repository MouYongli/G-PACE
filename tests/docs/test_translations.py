"""Check that the Chinese translation keeps the heading structure of the canonical English files."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAIRS = (("AGENTS.md", "AGENTS.zh-CN.md"),)


def heading_levels(path):
    levels, in_fence = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and (match := re.match(r"(#+)\s", line)):
            levels.append(len(match.group(1)))
    return levels


class TranslationTest(unittest.TestCase):
    def test_heading_structure_matches(self):
        for english, chinese in PAIRS:
            with self.subTest(file=english):
                self.assertEqual(heading_levels(ROOT / english), heading_levels(ROOT / chinese))


if __name__ == "__main__":
    unittest.main()
