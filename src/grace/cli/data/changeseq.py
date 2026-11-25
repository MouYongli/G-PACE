"""Build controlled change sequences from a dataset config (task T015). Model-free.

    uv run python -m grace.cli.data.changeseq configs/changeseq/dev-smoke.yaml \\
        --out "$PROJECT_ROOT/runs/T015/artifacts/<run-id>"

Writes into a new directory under runs_root (never into `$PROJECT_ROOT/data`): `run.json`
(status `running`, then `completed` or `failed`), `resolved-config.yaml`, and the dataset under
`dataset/` with `dataset.json` and `MANIFEST.sha256`. Refuses a dirty worktree unless
`--allow-dirty` is given (then `code_dirty: true` is recorded and the run is not formal), and
refuses held-out families unless the config sets `allow_held_out`.

Surface text comes from the deterministic template renderer (development and test renderer; the
paper's renderer waits for the model choice of D006).
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import traceback
from pathlib import Path

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.eval.datasets.changeseq.build import DatasetConfig, build_dataset
from grace.eval.runner.harness.rundir import (
    code_state,
    environment,
    file_sha256,
    resources_sha256,
    utc_now,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("config", type=Path, help="dataset config under configs/changeseq/")
    parser.add_argument("--out", type=Path, required=True, help="new directory under runs_root")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    runs = shared_dir("runs_root").resolve()
    out = args.out.resolve()
    if runs not in out.parents:
        parser.error(f"--out must lie under {runs}")
    if out.exists():
        parser.error(f"{out} exists; a run directory is created exclusively")
    code = code_state()
    if code.dirty and not args.allow_dirty:
        parser.error("the worktree has uncommitted changes; commit first or pass --allow-dirty")
    config_path = args.config.resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = DatasetConfig.from_dict(raw)
    out.mkdir(parents=True)
    resolved = out / "resolved-config.yaml"
    resolved.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    try:
        config_rel = config_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        config_rel = str(config_path)
    run = {
        "run_id": out.name, "task": "T015", "stage": "data", "upstream": [],
        "status": "running", "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": config_rel, "config_sha256": file_sha256(resolved),
        "resources_sha256": resources_sha256(), "data": [],
        "project_root": str(project_root()), "seed": config.seed,
        "command": shlex.join([sys.executable, "-m", "grace.cli.data.changeseq",
                               *(argv if argv is not None else sys.argv[1:])]),
        "environment": environment("cpu"), "started_at": utc_now(), "finished_at": None,
        "n_records": 0, "model_calls": 0, "renderer": "template-v1",
        "held_out_access": "none" if not config.allow_held_out else "generation only",
    }

    def save() -> None:
        (out / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    save()
    try:
        dataset = build_dataset(config, out / "dataset", code.sha)
    except Exception:
        run.update(status="failed", finished_at=utc_now(), error=traceback.format_exc())
        save()
        raise
    run.update(status="completed", finished_at=utc_now(),
               n_records=sum(s["n_messages"] for s in dataset["sequences"]),
               n_sequences=len(dataset["sequences"]),
               manifest_sha256=file_sha256(out / "dataset" / "MANIFEST.sha256"))
    save()
    print(json.dumps({k: run[k] for k in ("run_id", "status", "n_sequences", "n_records",
                                          "manifest_sha256")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
