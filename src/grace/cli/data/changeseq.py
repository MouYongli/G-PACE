"""Build controlled change sequences from a dataset config (task T015).

    uv run python -m grace.cli.data.changeseq configs/changeseq/dev-smoke.yaml \\
        --out "$PROJECT_ROOT/runs/T015/artifacts/<run-id>"

Writes into a new directory under runs_root (never into `$PROJECT_ROOT/data`): `run.json`
(status `running`, then `completed` or `failed`), `resolved-config.yaml`, and the dataset under
`dataset/` with `dataset.json` and `MANIFEST.sha256`. Refuses a dirty worktree unless
`--allow-dirty` is given (then `code_dirty: true` is recorded and the run is not formal), and
refuses held-out families unless the config sets `allow_held_out`.

Surface text comes from the renderer the config names: the deterministic template renderer
(`renderer: template-v1`, development and test renderer, no model calls) or the model renderer of
D006 (`renderer: {kind: model, ...}`, design section 7), which needs `--base-url` of the served
renderer model and writes every call to `calls.jsonl` of the run. run.json then records the model
calls, the renderer record, the fallback rate per family, the families over the limit and the
local-versus-server token-count check.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import traceback
from collections import Counter
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
    parser.add_argument("--base-url", help="OpenAI-compatible URL of the renderer model server "
                        "(model renderer only), e.g. http://127.0.0.1:8106/v1")
    parser.add_argument("--workers", type=int, default=None,
                        help="sequences rendered in parallel (default: the config's "
                        "renderer.workers, else 1)")
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
    if config.renderer_kind == "model" and not args.base_url:
        parser.error("the config uses the model renderer: pass --base-url")
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
        "base_url": args.base_url if config.renderer_kind == "model" else None,
        "held_out_access": "none" if not config.allow_held_out else "generation only",
    }

    def save() -> None:
        (out / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    save()
    renderer, ledger = None, None
    try:
        workers = 1
        if config.renderer_kind == "model":
            from grace.eval.datasets.changeseq.model_renderer import model_renderer
            from grace.llm.records import CallLedger

            ledger = CallLedger(out / "calls.jsonl", out.name)
            renderer = model_renderer(config.renderer, args.base_url, ledger)
            run["renderer"] = renderer.describe()
            workers = int(config.renderer.get("workers", 1))
        if args.workers is not None:
            workers = args.workers
        run["workers"] = workers
        save()
        dataset = build_dataset(config, out / "dataset", code.sha, renderer=renderer,
                                workers=workers)
    except Exception:
        run.update(status="failed", finished_at=utc_now(), error=traceback.format_exc())
        if ledger is not None:
            run["model_calls"] = len(ledger.records)
        save()
        raise
    run.update(status="completed", finished_at=utc_now(),
               n_records=sum(s["n_messages"] for s in dataset["sequences"]),
               n_sequences=len(dataset["sequences"]),
               render=dataset["render"],
               families_over_fallback_limit=sorted(f for f, x in dataset["render"].items()
                                                   if x["over_limit"]),
               manifest_sha256=file_sha256(out / "dataset" / "MANIFEST.sha256"))
    if ledger is not None:
        run["model_calls"] = len(ledger.records)
        run["calls_by_status"] = dict(sorted(Counter(r.status for r in ledger.records).items()))
        run["token_check"] = renderer.token_check()
    save()
    print(json.dumps({k: run[k] for k in ("run_id", "status", "n_sequences", "n_records",
                                          "model_calls", "families_over_fallback_limit",
                                          "manifest_sha256")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
