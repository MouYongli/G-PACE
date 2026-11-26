"""Run directories and the `run.json` life cycle (contracts.md, "Experiment run", version 0.2)."""

from __future__ import annotations

import hashlib
import json
import platform
import secrets
import socket
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from grace.config.paths import REPO_ROOT


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id(experiment: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{experiment}-{stamp}-{secrets.token_hex(2)}"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resources_sha256(directory: Path = REPO_ROOT / "resources") -> str:
    """Checksum of resources/ exactly as the contract defines it."""
    lines = []
    if directory.exists():
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"symbolic link under resources/: {path}")
            if path.is_file():
                relative = path.relative_to(directory).as_posix().encode("utf-8")
                lines.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    text = b"".join(f"{digest}  ".encode() + rel + b"\n" for rel, digest in sorted(lines))
    return hashlib.sha256(text).hexdigest()


@dataclass(frozen=True)
class CodeState:
    sha: str
    dirty: bool


def code_state(root: Path = REPO_ROOT) -> CodeState:
    """Full commit SHA of the worktree and whether it has uncommitted changes."""
    def run(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                              text=True).stdout.strip()
    return CodeState(run("rev-parse", "HEAD"), bool(run("status", "--porcelain")))


def environment(device: str) -> dict[str, Any]:
    lock = REPO_ROOT / "uv.lock"
    return {"python": platform.python_version(),
            "lock_sha256": file_sha256(lock) if lock.exists() else "none",
            "host": socket.gethostname(), "device": device}


def create(parent: Path, experiment: str, run_id: str | None = None) -> Path:
    """Create `<parent>/<experiment>/<run_id>/` exclusively. A given `run_id` that exists is an
    error; a generated one that collides is drawn again (never reusing a directory)."""
    (Path(parent) / experiment).mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        path = Path(parent) / experiment / (run_id or new_run_id(experiment))
        try:
            path.mkdir()
            return path
        except FileExistsError:
            if run_id:
                raise
    raise RuntimeError("could not draw a free run ID")


class RunJson:
    """Writes run.json with status `running`, then exactly once `completed` or `failed`."""

    def __init__(self, run_dir: Path, fields: dict[str, Any]):
        self.path = Path(run_dir) / "run.json"
        self.data = {**fields, "status": "running", "started_at": utc_now(),
                     "finished_at": None, "n_records": 0, "failure": None}
        self._write()

    def _write(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")

    def finish(self, n_records: int, failure: str | None = None) -> None:
        if self.data["status"] != "running":
            raise RuntimeError("run.json is already final")
        if failure is None and self.data["code_dirty"]:
            failure = "code_dirty: uncommitted changes; not a formal run"
        self.data.update(status="failed" if failure else "completed", finished_at=utc_now(),
                         n_records=n_records, failure=failure)
        self._write()
