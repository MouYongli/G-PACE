"""Offline tests for grace.cli.data.download, using file:// sources in a temporary directory."""

import hashlib
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from grace.cli.data import download as dl
from grace.paths import REPO_ROOT


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src, self.dest = root / "src", root / "dest"
        (self.src / "data").mkdir(parents=True)
        self.payload = b'{"q": 1}\n'
        (self.src / "data" / "a.json").write_bytes(self.payload)
        with zipfile.ZipFile(self.src / "data" / "b.zip", "w") as zf:
            zf.writestr("inner/c.txt", "c\n")
            zf.writestr("__MACOSX/inner/._c.txt", "junk")
            zf.writestr("inner/.DS_Store", "junk")

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self, **file_a):
        return {
            "version": "1",
            "license": "test",
            "sources": [
                {
                    "kind": "github",
                    "repo": "example/repo",
                    "revision": "0" * 40,
                    "url_template": self.src.as_uri() + "/{path}",
                    "strip": "data/",
                    "files": [
                        {"path": "data/a.json", **file_a},
                        {"path": "data/b.zip", "extract": True},
                    ],
                }
            ],
        }

    def test_download_unpack_manifest_and_rerun(self):
        entry = self.entry(sha256=sha(self.payload))
        self.assertEqual(dl.download_version("x", entry, self.dest), "downloaded")
        version = self.dest / "x" / "1"
        self.assertEqual((version / "a.json").read_bytes(), self.payload)
        self.assertEqual((version / "inner" / "c.txt").read_text(), "c\n")
        self.assertFalse((version / "__MACOSX").exists())
        self.assertFalse((version / "inner" / ".DS_Store").exists())
        manifest = (version / dl.MANIFEST).read_text()
        self.assertIn(f"{sha(self.payload)}  a.json", manifest)
        self.assertNotIn("SOURCE.json", manifest)  # keeps the manifest hash reproducible
        self.assertEqual(dl.verify_manifest(version), [])
        self.assertEqual(dl.download_version("x", entry, self.dest), "present")

    def test_tampered_file_is_reported(self):
        dl.download_version("x", self.entry(), self.dest)
        (self.dest / "x" / "1" / "a.json").write_bytes(b"changed")
        with self.assertRaises(dl.DownloadError):
            dl.download_version("x", self.entry(), self.dest)

    def test_checksum_mismatch_leaves_nothing_behind(self):
        with self.assertRaises(dl.DownloadError):
            dl.download_version("x", self.entry(sha256="0" * 64), self.dest)
        self.assertEqual([p.name for p in (self.dest / "x").iterdir()], [])

    def test_unexpected_manifest_hash_is_rejected(self):
        entry = {**self.entry(), "manifest_sha256": "0" * 64}
        with self.assertRaises(dl.DownloadError):
            dl.download_version("x", entry, self.dest)
        self.assertEqual([p.name for p in (self.dest / "x").iterdir()], [])

    def test_dry_run_writes_nothing(self):
        self.assertEqual(dl.download_version("x", self.entry(), self.dest, dry_run=True), "dry-run")
        self.assertFalse(self.dest.exists())

    def test_unsafe_paths_are_rejected(self):
        with self.assertRaises(dl.DownloadError):
            dl.target_path({"prefix": ".."}, "a.json")
        with zipfile.ZipFile(self.src / "evil.zip", "w") as zf:
            zf.writestr("../escape.txt", "x")
        with self.assertRaises(dl.DownloadError):
            dl.extract_zip(self.src / "evil.zip")


class SourcesTest(unittest.TestCase):
    def test_sources_match_scripts_and_pin_revisions(self):
        sources = dl.load_sources()
        scripts = sorted((REPO_ROOT / "scripts" / "data").glob("b[0-9]*_*.sh"))
        slugs = [re.match(r"b\d+_(.+)\.sh$", s.name).group(1) for s in scripts]
        self.assertEqual(sorted(slugs), sorted(sources))
        for slug, entries in sources.items():
            for entry in entries:
                for src in entry["sources"]:
                    with self.subTest(slug=slug, version=entry["version"], repo=src["repo"]):
                        self.assertRegex(entry["manifest_sha256"], r"^[0-9a-f]{64}$")
                        self.assertIn(src["kind"], dl.URL_TEMPLATES)
                        self.assertRegex(src["revision"], r"^[0-9a-f]{40}$")
                        self.assertTrue(src["files"])


if __name__ == "__main__":
    unittest.main()
