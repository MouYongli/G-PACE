"""Resolve PROJECT_ROOT and the shared directories named in configs/paths.yaml (see AGENTS.md)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def project_root() -> Path:
    """Return PROJECT_ROOT: the exported variable if set, else the parent of the shared .git dir."""
    if env := os.environ.get("PROJECT_ROOT"):
        return Path(env).resolve()
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("cannot resolve PROJECT_ROOT; export PROJECT_ROOT") from exc
    return Path(common).parent


def shared_dir(key: str) -> Path:
    """Return a shared directory (for example `data_root`) as an absolute path."""
    config = yaml.safe_load((REPO_ROOT / "configs" / "paths.yaml").read_text(encoding="utf-8"))
    if key not in config:
        raise KeyError(f"{key!r} is not defined in configs/paths.yaml")
    return project_root() / config[key]
