"""Download benchmark data at pinned revisions into $PROJECT_ROOT/data/<slug>/<version>/.

Usage (normally through scripts/data/*.sh):

    python -m grace.cli.data.download [SLUG ...] [--dest DIR] [--dry-run]

Sources are listed in configs/data/sources.yaml. Each version is downloaded into a temporary
directory next to its target, checked against any registered SHA-256, unpacked where requested,
described by SOURCE.json and MANIFEST.sha256 (data files only), and only then renamed into
place. An existing version is never overwritten; its manifest is verified instead.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

import yaml

from grace.paths import REPO_ROOT, shared_dir

SOURCES = REPO_ROOT / "configs" / "data" / "sources.yaml"
MANIFEST = "MANIFEST.sha256"
SOURCE_INFO = "SOURCE.json"
USER_AGENT = "grace-data-download"
CHUNK = 1 << 20
RETRIES = 3

URL_TEMPLATES = {
    "github": "https://raw.githubusercontent.com/{repo}/{revision}/{path}",
    "huggingface": "https://huggingface.co/datasets/{repo}/resolve/{revision}/{path}",
}


class DownloadError(RuntimeError):
    pass


def load_sources(path: Path = SOURCES) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["benchmarks"]


def file_url(source: dict, path: str) -> str:
    if "url_template" in source:  # used by tests to point at local files
        return source["url_template"].format(path=path)
    return URL_TEMPLATES[source["kind"]].format(
        repo=source["repo"], revision=source["revision"], path=path
    )


def target_path(source: dict, path: str) -> PurePosixPath:
    """Relative location of a file inside the version directory; rejects escaping paths."""
    strip = source.get("strip", "")
    rel = path[len(strip) :] if strip and path.startswith(strip) else path
    out = PurePosixPath(source.get("prefix", "")) / rel
    if out.is_absolute() or ".." in out.parts:
        raise DownloadError(f"unsafe target path {out}")
    return out


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as resp, dest.open("wb") as out:
                shutil.copyfileobj(resp, out, CHUNK)
            return
        except OSError as exc:
            if attempt == RETRIES:
                raise DownloadError(f"failed to download {url}: {exc}") from exc
            time.sleep(2 * attempt)


def is_os_junk(member: str) -> bool:
    """macOS archive metadata (__MACOSX/, ._* resource forks, .DS_Store)."""
    parts = PurePosixPath(member).parts
    return "__MACOSX" in parts or parts[-1] == ".DS_Store" or parts[-1].startswith("._")


def extract_zip(archive: Path) -> None:
    """Unpack into the archive's directory, skipping macOS metadata and refusing unsafe members.

    The archives carry their own top-level folder (for example MultiWOZ_2.1/), so they are not
    wrapped in another one.
    """
    out = archive.parent
    root = out.resolve()
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.namelist() if not is_os_junk(m)]
        for member in members:
            if not (out / member).resolve().is_relative_to(root):
                raise DownloadError(f"unsafe member {member!r} in {archive.name}")
        zf.extractall(out, members)


def write_manifest(version_dir: Path) -> str:
    """Write MANIFEST.sha256 (sha256sum format) and return the SHA-256 of the manifest file.

    SOURCE.json is left out because it records the retrieval time; the manifest, and so the
    `manifest_sha256` in configs/benchmarks/, depends only on the data files.
    """
    lines = []
    for path in sorted(p for p in version_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(version_dir).as_posix()
        if rel not in (MANIFEST, SOURCE_INFO):
            lines.append(f"{sha256_of(path)}  {rel}\n")
    manifest = version_dir / MANIFEST
    manifest.write_text("".join(lines), encoding="utf-8")
    return sha256_of(manifest)


def verify_manifest(version_dir: Path) -> list[str]:
    """Return the files whose hash no longer matches the manifest (missing files included)."""
    bad = []
    for line in (version_dir / MANIFEST).read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        path = version_dir / rel
        if not path.is_file() or sha256_of(path) != digest:
            bad.append(rel)
    return bad


def download_version(slug: str, entry: dict, dest_root: Path, dry_run: bool = False) -> str:
    version = str(entry["version"])
    target = dest_root / slug / version
    label = f"{slug}/{version}"

    if (target / MANIFEST).is_file():
        bad = verify_manifest(target)
        if bad:
            raise DownloadError(f"{label}: manifest mismatch in {', '.join(bad)}")
        manifest_sha = sha256_of(target / MANIFEST)
        expected = entry.get("manifest_sha256")
        if expected and manifest_sha != expected:
            raise DownloadError(f"{label}: manifest_sha256 {manifest_sha}, expected {expected}")
        print(f"{label}: present, manifest verified ({manifest_sha})")
        return "present"
    if target.exists():
        raise DownloadError(f"{label}: {target} exists without {MANIFEST}; remove it and retry")

    files = [(src, f) for src in entry["sources"] for f in src["files"]]
    if dry_run:
        for src, f in files:
            print(f"{label}: {file_url(src, f['path'])} -> {target / target_path(src, f['path'])}")
        return "dry-run"

    partial = target.parent / f".{version}.partial"
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    try:
        record = []
        for src, f in files:
            url = file_url(src, f["path"])
            out = partial / target_path(src, f["path"])
            print(f"{label}: {url}")
            fetch(url, out)
            digest = sha256_of(out)
            if f.get("sha256") and digest != f["sha256"]:
                raise DownloadError(f"{label}: SHA-256 mismatch for {f['path']}: {digest}")
            if f.get("extract"):
                extract_zip(out)
            record.append({"path": f["path"], "url": url, "sha256": digest})
        info = {
            "benchmark": slug,
            "version": version,
            "license": entry.get("license"),
            "sources": [
                {k: src[k] for k in ("kind", "repo", "revision") if k in src}
                for src in entry["sources"]
            ],
            "files": record,
            "retrieved_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        }
        (partial / SOURCE_INFO).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        manifest_sha = write_manifest(partial)
        expected = entry.get("manifest_sha256")
        if expected and manifest_sha != expected:
            raise DownloadError(f"{label}: manifest_sha256 {manifest_sha}, expected {expected}")
        partial.rename(target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    print(f"{label}: done; manifest_sha256 {manifest_sha}")
    return "downloaded"


def main(argv: list[str] | None = None) -> int:
    sources = load_sources()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slugs", nargs="*", metavar="SLUG", help=f"any of: {', '.join(sources)}")
    parser.add_argument("--dest", type=Path, help="data root (default: data_root of paths.yaml)")
    parser.add_argument("--dry-run", action="store_true", help="print URLs and targets only")
    args = parser.parse_args(argv)

    unknown = sorted(set(args.slugs) - set(sources))
    if unknown:
        parser.error(f"unknown benchmark(s): {', '.join(unknown)}")
    dest_root = (args.dest or shared_dir("data_root")).resolve()

    failed = False
    for slug in args.slugs or list(sources):
        for entry in sources[slug]:
            try:
                download_version(slug, entry, dest_root, args.dry_run)
            except DownloadError as exc:
                print(f"error: {exc}", file=sys.stderr)
                failed = True
    if failed:
        return 1
    if not args.dry_run:
        print(f"Next: check the files, then make them read-only: chmod -R a-w {dest_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
