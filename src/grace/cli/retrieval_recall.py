"""T025: evidence recall of the retrieval channels, routing and fusion (stage `probe`).

    uv run python -m grace.cli.retrieval_recall \\
        --config configs/experiments/T025-retrieval-recall.yaml \\
        --embed-url http://127.0.0.1:<port>/v1 [--planner-url http://127.0.0.1:<port>/v1] \\
        [--compute "<session> GPU <n> ports <p>"] [--workers 4]

Runs `grace.eval.runner.probes.retrieval_recall` over every benchmark of the config (development
splits only) and writes, in a new run directory under
`$PROJECT_ROOT/runs/<experiment>/artifacts/manager/<experiment>/<run-id>/` (experiment T025, or
T022 for the graph channel on the graphs of a T022 writer run, `graph: extracted`):

- `run.json`, `resolved-config.yaml`, `run.log`, `calls.jsonl` (contracts.md, Experiment run);
- `records/<benchmark>/` the checked benchmark records (incl. `gold.jsonl`, scoring side only);
- `retrievals.jsonl` one record per read: channel rankings (to `depth`), the plan of the graph
  channel, and the fused evidence IDs of every condition at every cut-off;
- `recall.json` evidence recall per benchmark, condition and cut-off, overall and per stratum
  (`grace.eval.analysis.metrics.retrieval`, from the files above), with the planner's route
  counts for benchmarks with a graph.

Without `--planner-url` the planner runs its rule templates only (recorded in run.json).
`n_records`: reads.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import traceback
from collections import Counter, defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.context.pipeline.query.planner import Planner, PlannerConfig
from grace.context.pipeline.retrieval.retrieve import RetrievalConfig
from grace.eval.analysis.metrics import retrieval as metric
from grace.eval.datasets.benchmarks.base import BenchmarkConfig, load_config, write_records
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.runner.harness import rundir
from grace.eval.runner.probes import retrieval_recall as probe
from grace.llm.client import ChatClient, Endpoint
from grace.llm.embeddings import EmbeddingClient
from grace.llm.records import CallLedger
from grace.llm.tokens import HFTokenCounter, TokenizerPin, locate_snapshot

EXPERIMENTS = ("T025", "T022")   # T022: graph channel on graphs of a T022 writer run


def writer_run_dir(run_id: str) -> Path:
    """Directory of a T022 writer run (`grace.cli.writer_smoke`)."""
    return shared_dir("runs_root") / "T022" / "artifacts" / "manager" / "T022" / run_id


def check_writer_run(path: Path) -> dict[str, Any]:
    """The upstream record of a writer run whose graphs feed the graph channel; the run must be
    completed, at a clean SHA, and not cut short by `--limit` (contracts.md, Experiment run)."""
    run_json = path / "run.json"
    record = json.loads(run_json.read_text(encoding="utf-8"))
    resolved = yaml.safe_load((path / "resolved-config.yaml").read_text(encoding="utf-8"))
    if record["status"] != "completed" or record["code_dirty"]:
        raise ValueError(f"{path}: writer run is not completed at a clean SHA")
    if resolved.get("limit") is not None:
        raise ValueError(f"{path}: writer run was limited to {resolved['limit']} messages")
    return {"run_id": record["run_id"], "stage": record["stage"], "path": path.as_posix(),
            "run_json_sha256": rundir.file_sha256(run_json)}
PLANNER_CONFIG = REPO_ROOT / "configs" / "common" / "planner.yaml"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def benchmark_config(entry: dict[str, Any]) -> BenchmarkConfig:
    bc = (BenchmarkConfig.from_dict(entry["config"]) if "config" in entry
          else load_config(entry["slug"]))
    if bc.splits[entry["split"]].kind != "development":
        raise ValueError(f"{entry['slug']}/{entry['split']}: development splits only")
    return bc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--embed-url", default=None)
    parser.add_argument("--planner-url", default=None)
    parser.add_argument("--compute", default=None, help="reservation copied into run.json")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--benchmarks", nargs="*", default=None,
                        help="restrict to these benchmark slugs (default: all of the config)")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    config_path = args.config if args.config.is_absolute() else REPO_ROOT / args.config
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["experiment"] not in EXPERIMENTS:
        parser.error(f"config is for {config['experiment']!r}, not one of {EXPERIMENTS}")
    experiment = config["experiment"]
    base = RetrievalConfig.load(REPO_ROOT / config["retrieval_config"])
    conditions = [probe.Condition.from_dict(n, c) for n, c in config["conditions"].items()]
    cutoffs = [int(k) for k in config["cutoffs"]]
    depth = int(config["depth"])
    if depth < max(cutoffs):
        parser.error("depth must be >= the largest cut-off")
    entries = [e for e in config["benchmarks"]
               if args.benchmarks is None or e["slug"] in args.benchmarks]
    configs = {e["slug"]: benchmark_config(e) for e in entries}
    writer_runs = {e["slug"]: writer_run_dir(e["writer_run"]) for e in entries
                   if e.get("graph") == "extracted"}
    upstream = [check_writer_run(path) for path in writer_runs.values()]

    run_parent = shared_dir("runs_root") / experiment / "artifacts" / "manager"
    run_dir = rundir.create(run_parent, experiment, args.run_id)
    run_id = run_dir.name
    log = (run_dir / "run.log").open("a", encoding="utf-8")

    def say(text: str) -> None:
        print(text, flush=True)
        log.write(text + "\n")
        log.flush()

    model_config = REPO_ROOT / config["model_config"]
    resolved = {"experiment": config, "retrieval": base.to_record(),
                "planner": {"config": "configs/common/planner.yaml",
                            "llm": args.planner_url is not None},
                "serving": {"embed_url": args.embed_url, "planner_url": args.planner_url,
                            "compute": args.compute or "none"},
                "benchmarks_run": [e["slug"] for e in entries], "workers": args.workers}
    (run_dir / "resolved-config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False),
                                                  encoding="utf-8")
    code = rundir.code_state()
    root = project_root()
    data = [{"benchmark": slug, "version": bc.version, "manifest_sha256": bc.manifest_sha256,
             "split": e["split"], "path": bc.source_dir(root).as_posix()}
            for e, (slug, bc) in zip(entries, configs.items(), strict=True)]
    run = rundir.RunJson(run_dir, {
        "run_id": run_id, "experiment": experiment, "stage": "probe", "upstream": upstream,
        "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": config_path.relative_to(REPO_ROOT).as_posix(),
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": data,
        "project_root": root.as_posix(), "seed": int(config["seed"]),
        "command": " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment("cpu (models on the serving endpoints)"),
        "compute": args.compute or "none", "held_out_access": "none"})
    n_reads = 0
    try:
        ledger = CallLedger(run_dir / "calls.jsonl", run_id)
        pin = TokenizerPin.from_file(model_config)
        counter = HFTokenCounter(pin, locate_snapshot(pin))
        embed = None
        if args.embed_url:
            emb = base.dense
            embedder = EmbeddingClient(
                Endpoint(base_url=args.embed_url, served_model=emb["served_name"],
                         model_label=f"{emb['hf_repo']}@{emb['revision']}", timeout_s=300.0),
                ledger, counter.count_text)

            def embed(texts, context):
                return embedder.embed(texts, context).vectors
        client = None
        if args.planner_url:
            raw = yaml.safe_load(model_config.read_text(encoding="utf-8"))
            client = ChatClient(Endpoint.for_model(pin, args.planner_url, raw["served_name"],
                                                   timeout_s=120.0), ledger, counter)
        planner = Planner(PlannerConfig.load(PLANNER_CONFIG), client)

        out = (run_dir / "retrievals.jsonl").open("w", encoding="utf-8")
        recall: dict[str, Any] = {}
        for entry in entries:
            slug, bc = entry["slug"], configs[entry["slug"]]
            records = load_split(slug, entry["split"], config=bc)
            write_records(records, run_dir / "records" / slug)
            messages = defaultdict(list)
            for m in records.messages:
                messages[m.history_id].append(m)
            tasks = defaultdict(list)
            for t in records.read_tasks:
                tasks[t.history_id].append(t)
            history_ids = [h.history_id for h in records.histories]
            kind = entry.get("graph", "none")
            if kind == "gold":
                graphs = probe.load_gold_graphs(bc.source_dir(root), history_ids)
            elif kind == "extracted":
                graphs = probe.load_extracted_graphs(
                    writer_runs[slug], history_ids,
                    max_predicates=int(entry.get("fragment_predicates", 30)),
                    max_entities=int(entry.get("fragment_entities", 30)))
            elif kind == "none":
                graphs = {}
            else:
                raise ValueError(f"{slug}: unknown graph kind {kind!r}")
            say(f"{slug}: {len(history_ids)} histories, {len(records.read_tasks)} reads, "
                f"graph={entry.get('graph', 'none')}")

            def one(hid: str, slug=slug, messages=messages, tasks=tasks, graphs=graphs):
                rows = probe.probe_history(
                    hid, messages[hid], tasks[hid], base=base, conditions=conditions,
                    cutoffs=cutoffs, depth=depth, embed=embed,
                    embed_batch=int(config["embed_batch"]), graph=graphs.get(hid),
                    planner=planner if hid in graphs else None, benchmark=slug)
                say(f"  {slug} {hid}: {len(rows)} reads")
                return rows

            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
                results = list(pool.map(one, history_ids))
            rows = [r for part in results for r in part]
            for r in rows:
                out.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            out.flush()
            n_reads += len(rows)
            rec_dir = run_dir / "records" / slug
            gold = metric.gold_sets(_jsonl(rec_dir / "gold.jsonl"),
                                    _jsonl(rec_dir / "messages.jsonl"))
            recall[slug] = metric.score(_jsonl_rows(run_dir / "retrievals.jsonl", slug),
                                        gold, config.get("strata", {}).get(slug, ()))
            plans = [r["plan"] for r in rows if r["plan"] is not None]
            if plans:
                recall[slug]["planner"] = {
                    "reads": len(plans), "routes": dict(Counter(p["route"] for p in plans)),
                    "fallback_reasons": dict(Counter(p["failure"] for p in plans
                                                     if p["route"] == "fallback")),
                    "graph_available": sum(r["graph_available"] for r in rows),
                    "nonempty_answers": sum(1 for p in plans if p["answers"])}
            say(json.dumps({slug: recall[slug]["conditions"]}, sort_keys=True))
        out.close()
        recall["model_calls"] = len(ledger.records)
        (run_dir / "recall.json").write_text(json.dumps(recall, indent=2, sort_keys=True)
                                             + "\n", encoding="utf-8")
        run.data["model_calls"] = len(ledger.records)
        run.finish(n_reads)
        say(f"run directory: {run_dir} status={run.data['status']}"
            + (f" failure={run.data['failure']}" if run.data["failure"] else ""))
    except BaseException as exc:
        say(traceback.format_exc())
        run.finish(n_reads, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        log.close()
    return 0 if run.data["status"] == "completed" else 1


def _jsonl_rows(path: Path, benchmark: str) -> list[dict[str, Any]]:
    return [r for r in _jsonl(path) if r["benchmark"] == benchmark]


if __name__ == "__main__":
    sys.exit(main())
