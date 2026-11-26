"""Measure a system run with GPU seconds recorded per call (task T030, plan 8.1 and 8.2).

A `system` stage run of the harness (`grace.eval.runner.harness.drive`) against a local
OpenAI-compatible server, with `Endpoint.gpu_accounting = "wall_clock"`: every call record gets
`gpu_seconds = latency x GPUs of the server`. Calls are sent one at a time, so the wall clock of
a call is the GPU time it occupied; under concurrent load it is an upper bound.

This is how the cached full-history row is measured rather than estimated: run the
`full-history-cached` engine against a server started with prefix caching, and the
`full-history` engine against the same model started without it, on the same reads:

    GPUS=5 PORT=8108 scripts/serve-model.sh Qwen/Qwen3-8B --max-model-len 32768 \
        --enable-prompt-tokens-details [--no-enable-prefix-caching]
    uv run python -m grace.cli.cost.measure --engine configs/engines/full-history-cached.yaml \
        --benchmark locomo --split dev --base-url http://127.0.0.1:8108/v1 --gpus 1 \
        --server-caching on

`--server-caching` states how the server was started; it must agree with the engine config's
`prefix_caching`, and the run is checked afterwards against what the server reported (a server
started without caching reports no cached tokens).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shlex
import sys
from pathlib import Path

from grace.config.paths import shared_dir
from grace.eval.runner.harness.drive import (
    DEFAULT_MODEL,
    ClientSettings,
    load_engine_config,
    run_system,
)


def wall_clock_accounting(gpus: int):
    """`on_model` hook: switch the model's chat endpoint to wall-clock GPU accounting."""
    if gpus < 1:
        raise ValueError("--gpus must be >= 1")

    def hook(model) -> None:
        client = model.client
        client.endpoint = dataclasses.replace(client.endpoint, gpu_accounting="wall_clock",
                                              gpus=gpus)
    return hook


def cached_tokens(run_dir: Path) -> tuple[int, int]:
    """(calls, cached input tokens) in a run's calls.jsonl."""
    calls = cached = 0
    for line in (run_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        calls += 1
        cached += row["cached_input_tokens"]
    return calls, cached


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engine", type=Path, required=True, help="configs/engines/<name>.yaml")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--split", default="dev", help="development split (default: dev)")
    parser.add_argument("--schedule", default=None)
    parser.add_argument("--budget", default="full", help="memory budget in tokens, or 'full'")
    parser.add_argument("--history", action="append", default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--embed-url", default=None)
    parser.add_argument("--model-config", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--gpus", type=int, required=True, help="GPUs of the chat server")
    parser.add_argument("--server-caching", choices=["on", "off"], required=True,
                        help="whether the server was started with prefix caching")
    parser.add_argument("--experiment", default="T030")
    parser.add_argument("--run-root", type=Path, default=None,
                        help="default: runs/T030/artifacts/manager under PROJECT_ROOT")
    args = parser.parse_args(argv)
    config = load_engine_config(args.engine)
    if config["prefix_caching"] != (args.server_caching == "on"):
        parser.error(f"{args.engine} has prefix_caching {config['prefix_caching']}, but the "
                     f"server caching is {args.server_caching}")
    run_root = args.run_root or shared_dir("runs_root") / "T030" / "artifacts" / "manager"
    result = run_system(
        engine_config=args.engine, benchmark=args.benchmark, split=args.split,
        budget=None if args.budget == "full" else int(args.budget), experiment=args.experiment,
        run_root=run_root, schedule=args.schedule, seed=args.seed, history_ids=args.history,
        client=ClientSettings(args.base_url, args.model_config, args.embed_url),
        on_model=wall_clock_accounting(args.gpus),
        command=" ".join(shlex.quote(a) for a in [sys.executable, "-m",
                                                    "grace.cli.cost.measure", *sys.argv[1:]]))
    calls, cached = cached_tokens(result.run_dir)
    print(f"{result.run_id}: {result.status} ({result.n_reads} reads, {calls} calls, "
          f"{cached} cached input tokens) -> {result.run_dir}")
    if result.failure:
        print(f"failure: {result.failure}")
    if args.server_caching == "off" and cached:
        print("check failed: the server reported cached tokens although caching is off")
        return 1
    if args.server_caching == "on" and calls > 1 and not cached:
        print("check failed: the server reported no cached tokens although caching is on")
        return 1
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
