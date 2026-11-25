"""E004 scale experiment: push, pull and hybrid staleness decisions on scaled synthetic graphs.

    uv run python -m grace.cli.scale plan --config configs/experiments/E004-scale-experiment.yaml
    uv run python -m grace.cli.scale run --config <config> --mix five --blocks 64 --seed 1 \\
        --views 48
    uv run python -m grace.cli.scale summary --config <config> --runs <run-id> <run-id>...

- `run` (stage `probe`, CPU only, no model): one run per (view mix, blocks, seed, standing
  views). Generates the blocks from the T015 generator (development families only), commits the
  prefix, times the queries of the first block's views (as compiled and with constants inlined),
  then measures every (read scope, writes per read) cell whose window is long enough, for every arm
  and repetition (`grace.eval.runner.probes.scale`). Writes `machine.json` (CPU model, cores, load
  average), `graph.json` (size, build time, skipped cells, query diagnostics),
  `measurements.jsonl` (one record per arm x cell x repetition) and `periods.jsonl` (one record
  per read period). `n_records` is the number of measurements.
- `plan`: the `run` invocations of the grid, one per line.
- `summary`: tables over an explicit list of completed run IDs (not a run;
  `grace.eval.analysis.metrics.scale`), written to `<out>/summary.json` with the checksum of every
  input run.json.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import sys
import time
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import project_root, shared_dir
from grace.eval.analysis.metrics import scale as analysis
from grace.eval.runner.harness import drive, rundir
from grace.eval.runner.probes import scale

EXPERIMENT = "E004"
WORKER = "manager"
KEYS = ("experiment", "version", "generator", "mixes", "graphs", "grid", "seeds",
        "repetitions", "reads", "arms", "diagnostics", "budget")


def load_experiment(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if missing := [k for k in KEYS if k not in config]:
        raise ValueError(f"{path}: missing keys {missing}")
    if config["experiment"] != EXPERIMENT:
        raise ValueError(f"{path}: experiment must be {EXPERIMENT}")
    gen = config["generator"]
    if gen["version"] != scale.GENERATOR_VERSION:
        raise ValueError(f"{path}: generator version {gen['version']} differs from the code's "
                         f"{scale.GENERATOR_VERSION}")
    for g in config["graphs"]:
        if g["mix"] not in config["mixes"]:
            raise ValueError(f"{path}: graph entry {g} names an unknown mix")
    scale.arm_strategies(config["arms"].values())
    return config


def run_root() -> Path:
    return shared_dir("runs_root") / EXPERIMENT / "artifacts" / WORKER


def runs(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every run of the design: one per (mix, blocks, seed, views), in config order; a number of
    views above the bindings the graph admits is left out."""
    def admits(mix: str, blocks: int) -> int:
        return blocks * sum(scale.BINDINGS_PER_BLOCK[f] for f in config["mixes"][mix])

    return [{"mix": g["mix"], "blocks": b, "seed": s, "views": n}
            for s in config["seeds"] for g in config["graphs"] for b in g["blocks"]
            for n in g["views"] if n <= admits(g["mix"], b)]


def cells(config: Mapping[str, Any], views: int, window: int) -> tuple[list[dict[str, Any]],
                                                                     list[dict[str, Any]]]:
    """The (read_scope, writes_per_read) cells of one run, and those skipped because the window
    is too short for `reads x writes_per_read` change sets."""
    grid, reads = config["grid"], int(config["reads"])
    out, skipped = [], []
    for scope in grid["read_scope"]:
        if scope != scale.ALL and scope > views:
            continue
        for w in grid["writes_per_read"]:
            cell = {"read_scope": scope, "writes_per_read": w}
            (out if reads * w <= window else skipped).append(cell)
    return out, skipped


def machine() -> dict[str, Any]:
    model = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    import pyoxigraph

    return {"cpu_model": model, "logical_cpus": os.cpu_count(),
            "affinity_cpus": len(os.sched_getaffinity(0)), "platform": platform.platform(),
            "python": platform.python_version(), "pyoxigraph": pyoxigraph.__version__,
            "load_average": list(os.getloadavg()),
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}


def write_jsonl(handle, record: Mapping[str, Any]) -> None:
    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    handle.flush()


def run_one(config_path: Path, mix: str, blocks: int, seed: int, views: int, *,
            root: Path | None = None, code: rundir.CodeState | None = None,
            command: str | None = None, config: Mapping[str, Any] | None = None
            ) -> tuple[Path, str]:
    """One `run` (one graph and one number of standing views); returns its directory and final
    status."""
    config = dict(config) if config is not None else load_experiment(config_path)
    key = {"mix": mix, "blocks": blocks, "seed": seed, "views": views}
    if key not in runs(config):
        raise ValueError(f"{key} is not a run of the design")
    code = code or rundir.code_state()
    run_dir = rundir.create(root or run_root(), EXPERIMENT)
    gen = config["generator"]
    resolved = {"stage": "probe", "experiment": EXPERIMENT,
                "config": drive.repo_relative(config_path), "run": key,
                **{k: config[k] for k in KEYS if k != "experiment"}}
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True), encoding="utf-8")
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": EXPERIMENT, "stage": "probe", "upstream": [],
        "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": drive.repo_relative(config_path),
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": [],
        "project_root": project_root().as_posix(), "seed": seed,
        "command": command or " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment("cpu")})
    (run_dir / "machine.json").write_text(json.dumps(machine(), indent=2) + "\n",
                                          encoding="utf-8")
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    n = 0
    try:
        start = time.perf_counter()
        made = [scale.generate_block(i, master_seed=seed, length=gen["block_length"],
                                     density=gen["density"], families=gen["families"])
                for i in range(blocks)]
        generate_s = time.perf_counter() - start
        graph = scale.build_graph(made, gen["prefix_length"], f"E004-b{blocks}-s{seed}")
        size = graph.size()
        families = config["mixes"][mix]
        admitted = scale.admitted(graph.bindings, families)
        diag = config["diagnostics"]
        compiled = [f for f in families
                    if f != "pending" or blocks <= diag["compiled_pending_max_blocks"]]
        diagnostics = scale.query_diagnostics(
            graph, scale.admitted(made[0].bindings, scale.FAMILY.values()),
            compiled_families=compiled, repeats=int(diag["repeats"]))
        window = len(graph.window)
        todo, skipped = cells(config, views, window)
        (run_dir / "graph.json").write_text(json.dumps(
            {**key, "generator_version": scale.GENERATOR_VERSION,
             "families": [b.family for b in made], "sequence_seeds": [b.seed for b in made],
             "view_families": list(families), "admitted_bindings": len(admitted),
             "generate_s": round(generate_s, 3), "prefix_build_s": round(graph.build_s, 3),
             "skipped_cells": skipped, "query_diagnostics": diagnostics, **size}, indent=2)
            + "\n", encoding="utf-8")
        log.write(f"graph: {size}, generated in {generate_s:.1f}s, prefix built in "
                  f"{graph.build_s:.1f}s; {len(todo)} cells, skipped {skipped}\n")
        log.flush()
        chosen = scale.choose_views(admitted, views, seed)
        arms = list(config["arms"].items())
        strategies = scale.arm_strategies(config["arms"].values())
        reads = int(config["reads"])
        deadline = start + float(config["budget"]["max_hours_per_run"]) * 3600
        with (run_dir / "measurements.jsonl").open("w", encoding="utf-8") as mfile, \
                (run_dir / "periods.jsonl").open("w", encoding="utf-8") as pfile:
            for cell in todo:
                sets = scale.read_sets([b.view_id for b in chosen], cell["read_scope"], reads,
                                       seed)
                for rep in range(int(config["repetitions"])):
                    k = rep % len(arms)
                    for position, (label, arm) in enumerate(arms[k:] + arms[:k]):
                        if time.perf_counter() > deadline:
                            raise TimeoutError(f"budget of {config['budget']['max_hours_per_run']}"
                                               f" h per run exceeded")
                        m = scale.measure(graph, chosen, arm,
                                          writes_per_read=cell["writes_per_read"], reads=reads,
                                          scope_sets=sets)
                        record_key = {**key, **cell, "repetition": rep, "arm": label,
                                      "strategy": strategies[arm]}
                        write_jsonl(mfile, {
                            **record_key, "position": position, "reads": reads,
                            "writes": reads * cell["writes_per_read"],
                            "setup_s": round(m.setup_s, 4), "wall_s": round(m.wall_s, 4),
                            "cpu_s": round(m.cpu_s, 4),
                            "load_before": [round(x, 2) for x in m.load_before],
                            "load_after": [round(x, 2) for x in m.load_after],
                            "repairs": scale.repair_signature(m.periods),
                            "actions": scale.action_counts(m.periods),
                            "strategy_summary": m.summary})
                        for p in m.periods:
                            write_jsonl(pfile, {**record_key, **p.to_record()})
                        n += 1
                log.write(f"cell {cell}: {int(config['repetitions'])} repetitions done "
                          f"({time.perf_counter() - start:.0f}s)\n")
                log.flush()
        expected = len(todo) * int(config["repetitions"]) * len(arms)
        if n != expected:
            raise RuntimeError(f"{n} measurements written, {expected} expected")
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        log.write(traceback.format_exc())
        log.close()
        run.finish(n, f"{type(exc).__name__}: {exc}")
        raise
    log.write(f"done: {n} measurements\n")
    log.close()
    run.finish(n)
    return run_dir, run.data["status"]


def plan_lines(config_path: Path) -> list[str]:
    config = load_experiment(config_path)
    rel = drive.repo_relative(config_path)
    return [f"uv run python -m grace.cli.scale run --config {rel} --mix {r['mix']} "
            f"--blocks {r['blocks']} --seed {r['seed']} --views {r['views']}"
            for r in runs(config)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="grace.cli.scale", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "summary"):
        p = sub.add_parser(name)
        p.add_argument("--config", type=Path, required=True)
        if name == "run":
            p.add_argument("--mix", required=True)
            p.add_argument("--blocks", type=int, required=True)
            p.add_argument("--seed", type=int, required=True)
            p.add_argument("--views", type=int, required=True)
        if name == "summary":
            p.add_argument("--runs", nargs="+", required=True)
            p.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "plan":
        print("\n".join(plan_lines(args.config)))
        return 0
    if args.command == "run":
        run_dir, status = run_one(args.config, args.mix, args.blocks, args.seed, args.views)
        print(f"{run_dir}: {status}")
        return 0 if status == "completed" else 1
    config = load_experiment(args.config)
    dirs = [run_root() / EXPERIMENT / r for r in args.runs]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%MZ")
    out = args.out or run_root() / f"{EXPERIMENT}-summary" / f"summary-{stamp}"
    path = analysis.write_summary(dirs, out, config)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
