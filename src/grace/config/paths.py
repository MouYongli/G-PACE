"""Resolve REPO_ROOT, PROJECT_ROOT and the shared directories of configs/common/paths.yaml.

See AGENTS.md, "Project root and paths".
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

# src/grace/config/paths.py -> the worktree that holds this file.
REPO_ROOT = Path(__file__).resolve().parents[3]
PATHS_CONFIG = REPO_ROOT / "configs" / "common" / "paths.yaml"


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
    config = yaml.safe_load(PATHS_CONFIG.read_text(encoding="utf-8"))
    if key not in config:
        raise KeyError(f"{key!r} is not defined in configs/common/paths.yaml")
    return project_root() / config[key]
