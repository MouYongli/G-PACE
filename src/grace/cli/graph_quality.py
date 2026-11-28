"""E006 (graph quality): writer-only extraction of the annotated segments, and its scoring.

    uv run python -m grace.cli.graph_quality extract \\
        --config configs/experiments/E006-graph-quality.yaml \\
        --writer-url http://localhost:8252/v1 [--compute "<reservation>"] \\
        [--segments-only KEY ...] [--workers 4]
    uv run python -m grace.cli.graph_quality score WRITER_RUN_DIR \\
        --config configs/experiments/E006-graph-quality.yaml \\
        [--judge-url http://localhost:8252/v1] [--experiment E007 --run-parent DIR] \\
        [--gold FILE ...] [--label TEXT]

`extract` (stage `probe`) writes every segment of the T024 sample on its own, its context messages
first (`grace.eval.runner.probes.extract`), into a new run directory under
`$PROJECT_ROOT/runs/E006/artifacts/w01-E006/E006/<run-id>/`: `run.json`, `resolved-config.yaml`,
`run.log`, `calls.jsonl`, `updates.jsonl` (one record per extraction unit, with its `segment`) and
`graphs/<segment graph ID>/` (claim store and writer state). `n_records`: segments written.

`score` (stage `score`) reads one writer run directory, the gold label files and the segment texts,
and writes `metrics.json`, `claims.jsonl` (every writer claim occurrence on a segment message with
its match), `gold.jsonl` (every gold claim with its match) and `judgements.jsonl` (LLM judge calls
of the predicate and entailment checks) into a new score run directory. It accepts any writer run
with `updates.jsonl` and `graphs/<id>/store/changesets.jsonl` + `graphs/<id>/writer.json`: a
segment run of `extract` (graph per segment) or a full-history run of `grace.cli.writer_smoke`
(graph per history). The scoring logic is `grace.eval.analysis.metrics.graph` (files only).
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import traceback
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.eval.runner.harness import rundir

WORKER = "w01-E006"


def _load_config(path: Path) -> tuple[Path, dict]:
    path = path if path.is_absolute() else REPO_ROOT / path
    return path, yaml.safe_load(path.read_text(encoding="utf-8"))


def _client(model_config: Path, url: str, ledger_path: Path, run_id: str):
    from grace.llm.client import ChatClient, Endpoint
    from grace.llm.records import CallLedger
    from grace.llm.tokens import HFTokenCounter, TokenizerPin, locate_snapshot
    ledger = CallLedger(ledger_path, run_id)
    pin = TokenizerPin.from_file(model_config)
    counter = HFTokenCounter(pin, locate_snapshot(pin))
    raw = yaml.safe_load(model_config.read_text(encoding="utf-8"))
    return ChatClient(Endpoint.for_model(pin, url, raw["served_name"], timeout_s=300.0),
                      ledger, counter)


def extract(args: argparse.Namespace) -> int:
    from grace.cli.retrieval_recall import benchmark_config
    from grace.context.pipeline.update.updater import WriterConfig, llm_writer
    from grace.eval.datasets.benchmarks.splits import load_split
    from grace.eval.runner.probes.extract import drive_segment

    config_path, config = _load_config(args.config)
    if config["experiment"] != args.experiment:
        raise SystemExit(f"config is for {config['experiment']!r}, not {args.experiment}")
    writer_config_path = REPO_ROOT / config["writer_config"]
    writer_config = WriterConfig.load(writer_config_path)
    sample = json.loads((REPO_ROOT / config["sample"]).read_text(encoding="utf-8"))
    segments = [s for s in sample["segments"]
                if not args.segments_only or s["key"] in args.segments_only]
    entries = config["benchmarks"]
    configs = {e["slug"]: benchmark_config(e) for e in entries}

    run_parent = (args.run_parent or shared_dir("runs_root") / args.experiment / "artifacts"
                  / WORKER)
    run_dir = rundir.create(run_parent, args.experiment, args.run_id)
    run_id = run_dir.name
    log = (run_dir / "run.log").open("a", encoding="utf-8")

    def say(text: str) -> None:
        print(text, flush=True)
        log.write(text + "\n")
        log.flush()

    model_config = REPO_ROOT / config["model_config"]
    resolved = {"experiment": config,
                "writer": {"config": config["writer_config"],
                           "sha256": rundir.file_sha256(writer_config_path),
                           "values": yaml.safe_load(writer_config_path.read_text("utf-8"))},
                "sample": {"path": config["sample"],
                           "sha256": rundir.file_sha256(REPO_ROOT / config["sample"]),
                           "segments": [s["key"] for s in segments]},
                "serving": {"writer_url": args.writer_url, "compute": args.compute or "none",
                            **config.get("serving", {})},
                "workers": args.workers}
    (run_dir / "resolved-config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False),
                                                  encoding="utf-8")
    code = rundir.code_state()
    root = project_root()
    data = [{"benchmark": slug, "version": bc.version, "manifest_sha256": bc.manifest_sha256,
             "split": e["split"], "path": bc.source_dir(root).as_posix()}
            for e, (slug, bc) in zip(entries, configs.items(), strict=True)]
    run = rundir.RunJson(run_dir, {
        "run_id": run_id, "experiment": args.experiment, "stage": "probe", "upstream": [],
        "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": config_path.relative_to(REPO_ROOT).as_posix(),
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": data,
        "project_root": root.as_posix(), "seed": int(config["seed"]),
        "command": " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment("cpu (writer model on the serving endpoint)"),
        "compute": args.compute or "none", "held_out_access": "none",
        "segment_mode": config.get("segment_mode", "context+segment")})
    n_done = 0
    try:
        client = _client(model_config, args.writer_url, run_dir / "calls.jsonl", run_id)
        histories, messages = {}, defaultdict(list)
        for entry in entries:
            slug, bc = entry["slug"], configs[entry["slug"]]
            records = load_split(slug, entry["split"], config=bc)
            wanted = {s["history_id"] for s in segments if s["benchmark"] == slug}
            for h in records.histories:
                if h.history_id in wanted:
                    histories[(slug, h.history_id)] = h
            for m in records.messages:
                if m.history_id in wanted:
                    messages[(slug, m.history_id)].append(m)
            say(f"{slug}: {len(wanted)} histories for "
                f"{sum(1 for s in segments if s['benchmark'] == slug)} segments")

        def one(segment):
            key = (segment["benchmark"], segment["history_id"])
            updates = drive_segment(histories[key], messages[key], segment,
                                    lambda info: llm_writer(writer_config, client, info),
                                    writer_config, run_dir)
            say(f"  {segment['key']}: {len(updates)} unit records")
            return updates

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            results = list(pool.map(one, segments))
        all_updates = [u for part in results for u in part]
        with (run_dir / "updates.jsonl").open("w", encoding="utf-8") as f:
            for u in all_updates:
                f.write(json.dumps(u, ensure_ascii=False, sort_keys=True) + "\n")
        n_done = len(results)
        from grace.eval.analysis.metrics import writer as metric
        updates = metric.read_jsonl(run_dir / "updates.jsonl")
        calls = metric.read_jsonl(run_dir / "calls.jsonl")
        metrics = {"units": metric.unit_stats(updates), "calls": metric.call_stats(calls),
                   "model_calls": len(calls), "segments": n_done}
        (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True)
                                              + "\n", encoding="utf-8")
        say(json.dumps({"units": metrics["units"]["by_status"],
                        "calls": metrics["calls"]["by_status"]}, sort_keys=True))
        run.data["model_calls"] = len(calls)
        run.finish(n_done)
        say(f"run directory: {run_dir} status={run.data['status']}"
            + (f" failure={run.data['failure']}" if run.data["failure"] else ""))
    except BaseException as exc:
        say(traceback.format_exc())
        run.finish(n_done, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        log.close()
    return 0 if run.data["status"] == "completed" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_ext = sub.add_parser("extract", help="writer-only extraction of the sampled segments")
    p_ext.add_argument("--config", type=Path, required=True)
    p_ext.add_argument("--writer-url", required=True)
    p_ext.add_argument("--compute", default=None, help="reservation copied into run.json")
    p_ext.add_argument("--segments-only", nargs="*", default=None, help="segment keys")
    p_ext.add_argument("--workers", type=int, default=4, help="segments written in parallel")
    p_ext.add_argument("--experiment", default="E006")
    p_ext.add_argument("--run-parent", type=Path, default=None)
    p_ext.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    if args.command == "extract":
        return extract(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
