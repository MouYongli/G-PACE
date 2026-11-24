"""Paths moved by decision D013 (task T001) are named nowhere but in dated records."""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD = ("configs/paths.yaml", "grace/paths.py", "grace.paths ", "grace.paths\n", "from grace.paths")
NEW = ("configs/common/paths.yaml", "src/grace/config/paths.py")
# Decision and task files are dated records; they keep the paths valid when they were written.
HISTORICAL = ("docs/work/decisions/", "docs/work/tasks/")
SELF = Path(__file__).relative_to(ROOT).as_posix()


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                             capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise unittest.SkipTest(f"git ls-files unavailable: {exc}") from exc
    return [name for name in out.decode("utf-8").split("\0") if name]


class MovedPathsTest(unittest.TestCase):
    def test_new_locations_exist(self):
        for path in NEW:
            self.assertTrue((ROOT / path).is_file(), path)
        self.assertFalse((ROOT / "configs" / "paths.yaml").exists())
        self.assertFalse((ROOT / "src" / "grace" / "paths.py").exists())

    def test_old_paths_are_not_named(self):
        offenders = []
        for name in tracked_files():
            if name.startswith(HISTORICAL) or name == SELF or not (ROOT / name).is_file():
                continue
            try:
                text = (ROOT / name).read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            offenders += [f"{name}: {old.strip()}" for old in OLD if old in text]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
