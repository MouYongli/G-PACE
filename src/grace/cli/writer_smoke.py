"""T022 follow-up: a small real-model run of GRACE's writer on development data (stage `probe`).

    uv run python -m grace.cli.writer_smoke \\
        --config configs/experiments/T022-writer-smoke.yaml \\
        --writer-url http://127.0.0.1:<port>/v1 [--compute "<session> GPU <n> ports <p>"] \\
        [--limit 12] [--histories conv-26] [--workers 2]

Runs `grace.eval.runner.probes.writer_extract` over every history of the config's benchmarks
(development splits only; the driver refuses any other split kind) with the writer of
`configs/common/writer.yaml` and the model of `model_config`, and writes, in a new run directory
under `$PROJECT_ROOT/runs/T022/artifacts/manager/T022/<run-id>/`:

- `run.json`, `resolved-config.yaml`, `run.log`, `calls.jsonl` (contracts.md, Experiment run);
- `records/<benchmark>/` the checked benchmark records (the writer reads only the messages and
  history headers; `gold.jsonl` is written by the record writer and never read here);
- `updates.jsonl` one record per extraction unit (status, call IDs and statuses, entries,
  dropped items, conflicts, raw output);
- `graphs/<history_id>/` the claim store snapshot and the writer state of every history, read by
  `grace.cli.retrieval_recall` (`graph: extracted`);
- `metrics.json` unit, call and graph statistics (`grace.eval.analysis.metrics.writer`, from the
  files above) and `samples.json`, a seeded sample of units for a qualitative look.

`--limit n` writes only the first n messages of each history (a dry run). `n_records`: units.
This is a smoke run of the writer on development data, not E006 (graph quality) or E007 (writer
scale and granularity).
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

from grace.cli.retrieval_recall import benchmark_config
from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.context.pipeline.update.updater import WriterConfig, llm_writer
from grace.eval.analysis.metrics import writer as metric
from grace.eval.datasets.benchmarks.base import write_records
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.runner.harness import rundir
from grace.eval.runner.probes.writer_extract import drive_history
from grace.llm.client import ChatClient, Endpoint
from grace.llm.records import CallLedger
from grace.llm.tokens import HFTokenCounter, TokenizerPin, locate_snapshot

EXPERIMENT = "T022"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--writer-url", required=True)
    parser.add_argument("--compute", default=None, help="reservation copied into run.json")
    parser.add_argument("--limit", type=int, default=None,
                        help="write only the first n messages of each history (dry run)")
    parser.add_argument("--histories", nargs="*", default=None,
                        help="restrict to these history IDs (default: every history)")
    parser.add_argument("--workers", type=int, default=2, help="histories written in parallel")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    config_path = args.config if args.config.is_absolute() else REPO_ROOT / args.config
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["experiment"] != EXPERIMENT:
        parser.error(f"config is for {config['experiment']!r}, not {EXPERIMENT}")
    writer_config_path = REPO_ROOT / config["writer_config"]
    writer_config = WriterConfig.load(writer_config_path)
    entries = config["benchmarks"]
    configs = {e["slug"]: benchmark_config(e) for e in entries}

    run_parent = shared_dir("runs_root") / EXPERIMENT / "artifacts" / "manager"
    run_dir = rundir.create(run_parent, EXPERIMENT, args.run_id)
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
                "serving": {"writer_url": args.writer_url, "compute": args.compute or "none",
                            **config.get("serving", {})},
                "limit": args.limit, "histories": args.histories, "workers": args.workers}
    (run_dir / "resolved-config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False),
                                                  encoding="utf-8")
    code = rundir.code_state()
    root = project_root()
    data = [{"benchmark": slug, "version": bc.version, "manifest_sha256": bc.manifest_sha256,
             "split": e["split"], "path": bc.source_dir(root).as_posix()}
            for e, (slug, bc) in zip(entries, configs.items(), strict=True)]
    run = rundir.RunJson(run_dir, {
        "run_id": run_id, "experiment": EXPERIMENT, "stage": "probe", "upstream": [],
        "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": config_path.relative_to(REPO_ROOT).as_posix(),
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": data,
        "project_root": root.as_posix(), "seed": int(config["seed"]),
        "command": " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment("cpu (writer model on the serving endpoint)"),
        "compute": args.compute or "none", "held_out_access": "none"})
    n_units = 0
    try:
        ledger = CallLedger(run_dir / "calls.jsonl", run_id)
        pin = TokenizerPin.from_file(model_config)
        counter = HFTokenCounter(pin, locate_snapshot(pin))
        raw = yaml.safe_load(model_config.read_text(encoding="utf-8"))
        client = ChatClient(Endpoint.for_model(pin, args.writer_url, raw["served_name"],
                                               timeout_s=300.0), ledger, counter)
        updates_path = run_dir / "updates.jsonl"
        all_updates = []
        messages_by_key = {}
        for entry in entries:
            slug, bc = entry["slug"], configs[entry["slug"]]
            records = load_split(slug, entry["split"], config=bc)
            write_records(records, run_dir / "records" / slug)
            messages = defaultdict(list)
            for m in records.messages:
                messages[m.history_id].append(m)
                messages_by_key[(m.history_id, m.message_id)] = m.to_record()
            histories = [h for h in records.histories
                         if args.histories is None or h.history_id in args.histories]
            say(f"{slug}: {len(histories)} histories, "
                f"{sum(len(messages[h.history_id]) for h in histories)} messages, "
                f"limit={args.limit}, granularity={writer_config.granularity.name}")

            def one(history, messages=messages):
                writer = llm_writer(writer_config, client, history)
                updates = drive_history(history, messages[history.history_id], writer,
                                        writer_config, run_dir, limit=args.limit)
                say(f"  {history.history_id}: {len(updates)} unit records")
                return updates

            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
                results = list(pool.map(one, histories))
            for part in results:
                all_updates += part
        with updates_path.open("w", encoding="utf-8") as f:
            for u in all_updates:
                f.write(json.dumps(u, ensure_ascii=False, sort_keys=True) + "\n")
        n_units = len(all_updates)

        updates = metric.read_jsonl(updates_path)
        calls = metric.read_jsonl(run_dir / "calls.jsonl")
        per_history = defaultdict(list)
        for u in updates:
            per_history[u["history_id"]].append(u)
        changesets = {h: metric.read_jsonl(run_dir / "graphs" / h / "store" / "changesets.jsonl")
                      for h in per_history}
        metrics = {"units": metric.unit_stats(updates), "calls": metric.call_stats(calls),
                   "per_history": {h: metric.unit_stats(us) for h, us in per_history.items()},
                   "graph": metric.graph_stats([c for h in sorted(changesets)
                                                for c in changesets[h]]),
                   "model_calls": len(calls)}
        (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True)
                                              + "\n", encoding="utf-8")
        samples = metric.sample_units(updates, changesets, messages_by_key,
                                      int(config.get("samples", 30)), int(config["seed"]))
        (run_dir / "samples.json").write_text(json.dumps(samples, indent=2, ensure_ascii=False)
                                              + "\n", encoding="utf-8")
        say(json.dumps({"units": metrics["units"]["by_status"],
                        "calls": metrics["calls"]["by_status"]}, sort_keys=True))
        run.data["model_calls"] = len(calls)
        run.finish(n_units)
        say(f"run directory: {run_dir} status={run.data['status']}"
            + (f" failure={run.data['failure']}" if run.data["failure"] else ""))
    except BaseException as exc:
        say(traceback.format_exc())
        run.finish(n_units, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        log.close()
    return 0 if run.data["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
