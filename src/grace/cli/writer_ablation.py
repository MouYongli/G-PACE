"""E007 (ablation G): GRACE's writer under one arm (model, thinking, granularity) on one target.

    uv run python -m grace.cli.writer_ablation \\
        --config configs/experiments/E007-ablation-g-writer.yaml --arm <arm> --target <target> \\
        --writer-url http://127.0.0.1:<port>/v1 [--compute "<session> GPU <n> ports <p>"] \\
        [--limit n] [--histories ...] [--segments n] [--workers 4]

An arm fixes the writer model (`models` of the config), thinking on or off and the extraction
granularity, with optional decoding overrides (a larger `max_tokens` for session units or
thinking); everything else comes from `writer_config` and is the same for every arm: prompt,
schema, temperature, seed and the update rules. Thinking on sends `enable_thinking: true` as chat
template argument; the server must run a reasoning parser so that the thinking does not land in
`content` (the output tokens recorded include the thinking tokens).

Targets (development data only; the driver refuses any other split kind):

- `kind: histories`: every message of the listed histories, in order, as `grace.cli.writer_smoke`
  does (`writer_extract.drive_history`); graphs per history.
- `kind: segments`: the annotated segments of T024's graph-quality sample (`sample.json`, texts in
  `segments.jsonl`), each written from an empty graph (`writer_extract.drive_segment`); the data
  versions and manifests of the sample must equal those of the benchmark configs, and every
  segment text must equal the loaded message. Graphs per segment, named by the segment key.

Writes a new run directory `$PROJECT_ROOT/runs/E007/artifacts/<worker>/E007/<run-id>/` (stage
`probe`): `run.json`, `resolved-config.yaml`, `run.log`, `calls.jsonl`, `updates.jsonl` (one
record per unit, with `graph`), `graphs/<name>/` (store snapshot and writer state),
`changesets.jsonl` (every non-empty committed change set, with `graph`), `extractions.jsonl`
(every claim, stance and same_as item of the writer's raw output of each final `ok` unit, with its
message ID and speaker, before validation, for E006's scorer), `metrics.json`
(`grace.eval.analysis.metrics.writer`, overall and per graph group) and `samples.json`.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import shlex
import sys
import traceback
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml

from grace.cli.retrieval_recall import benchmark_config
from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.context.pipeline.update.segment import Granularity
from grace.context.pipeline.update.updater import WriterConfig, llm_writer
from grace.eval.analysis.metrics import writer as metric
from grace.eval.datasets.benchmarks.base import write_records
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.runner.harness import rundir
from grace.eval.runner.probes.writer_extract import drive_history, drive_segment
from grace.llm.client import ChatClient, Endpoint
from grace.llm.records import CallLedger
from grace.llm.tokens import HFTokenCounter, TokenizerPin, locate_snapshot

EXPERIMENT = "E007"
WORKER = "w01-E007"


def arm_writer_config(base: WriterConfig, arm: dict[str, Any]) -> WriterConfig:
    """The writer config of one arm: granularity and decoding overrides on the shared base."""
    if unknown := sorted(set(arm) - {"model", "thinking", "granularity", "decoding", "note"}):
        raise ValueError(f"arm: unknown keys {unknown}")
    return dataclasses.replace(
        base, granularity=Granularity.from_record(arm["granularity"]),
        decoding={**dict(base.decoding), **dict(arm.get("decoding") or {})})


def arm_pin(model_config: Path, thinking: bool) -> TokenizerPin:
    """The model's pin with thinking set as the arm says (template argument and flag agree)."""
    pin = TokenizerPin.from_file(model_config)
    return dataclasses.replace(pin, thinking=thinking,
                               template_kwargs={**pin.template_kwargs,
                                                "enable_thinking": thinking})


def graph_name(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", key)


def extraction_items(update: dict[str, Any], speakers: dict[str, str], graph: str,
                     segment: str | None) -> list[dict[str, Any]]:
    """Items of the raw output of one final `ok` unit, anchored to message IDs."""
    if update["status"] != "ok":
        return []
    patch = json.loads(update["raw_output"])
    ids = update["message_ids"]
    out = []
    for kind in ("claims", "stances", "same_as"):
        for i, item in enumerate(patch.get(kind) or []):
            mid = ids[item["message"] - 1]
            out.append({"graph": graph, "history_id": update["history_id"], "segment": segment,
                        "unit": [update["first_version"], update["last_version"]],
                        "kind": kind.rstrip("s") if kind != "same_as" else "same_as",
                        "index": i, "message_id": mid, "speaker": speakers[mid], **item})
    return out


def check_segments(target: dict[str, Any], configs: dict[str, Any], root: Path
                   ) -> tuple[list[dict[str, Any]], dict[str, str]]:
    sample_path = REPO_ROOT / target["sample"]
    seg_path = root / target["segments"]
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    for d in sample["data"]:
        bc = configs[d["benchmark"]]
        if (d["version"], d["manifest_sha256"]) != (bc.version, bc.manifest_sha256):
            raise ValueError(f"T024 sample data {d} differs from the benchmark config")
    segments = [json.loads(line) for line in seg_path.read_text("utf-8").splitlines() if line]
    if [s["key"] for s in segments] != [s["key"] for s in sample["segments"]]:
        raise ValueError("segments.jsonl keys differ from sample.json")
    digests = {"sample": hashlib.sha256(sample_path.read_bytes()).hexdigest(),
               "segments": hashlib.sha256(seg_path.read_bytes()).hexdigest()}
    return segments, digests


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--writer-url", required=True)
    parser.add_argument("--compute", default=None, help="reservation copied into run.json")
    parser.add_argument("--limit", type=int, default=None,
                        help="histories: write only the first n messages of each (dry run)")
    parser.add_argument("--histories", nargs="*", default=None,
                        help="restrict to these history IDs (default: the target's list)")
    parser.add_argument("--segments", type=int, default=None,
                        help="segments: only the first n segments of the sample (dry run)")
    parser.add_argument("--workers", type=int, default=4, help="graphs written in parallel")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    config_path = args.config if args.config.is_absolute() else REPO_ROOT / args.config
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["experiment"] != EXPERIMENT:
        parser.error(f"config is for {config['experiment']!r}, not {EXPERIMENT}")
    arm = config["arms"][args.arm]
    target = config["targets"][args.target]
    model = config["models"][arm["model"]]
    writer_config_path = REPO_ROOT / config["writer_config"]
    writer_config = arm_writer_config(WriterConfig.load(writer_config_path), arm)
    entries = target["benchmarks"]
    configs = {e["slug"]: benchmark_config(e) for e in entries}
    root = project_root()

    run_parent = shared_dir("runs_root") / EXPERIMENT / "artifacts" / WORKER
    run_dir = rundir.create(run_parent, EXPERIMENT, args.run_id)
    run_id = run_dir.name
    log = (run_dir / "run.log").open("a", encoding="utf-8")

    def say(text: str) -> None:
        print(text, flush=True)
        log.write(text + "\n")
        log.flush()

    model_config = REPO_ROOT / model["model_config"]
    resolved = {"experiment": EXPERIMENT, "arm": {"name": args.arm, **arm},
                "target": {"name": args.target, **target}, "model": model,
                "writer": {"config": config["writer_config"],
                           "sha256": rundir.file_sha256(writer_config_path),
                           "resolved": {**dataclasses.asdict(writer_config),
                                        "granularity": writer_config.granularity.name}},
                "serving": {"writer_url": args.writer_url, "compute": args.compute or "none"},
                "seed": config["seed"], "limit": args.limit, "histories": args.histories,
                "segments": args.segments, "workers": args.workers}
    segments: list[dict[str, Any]] = []
    if target["kind"] == "segments":
        segments, digests = check_segments(target, configs, root)
        if args.segments is not None:
            segments = segments[:args.segments]
        resolved["target"]["sha256"] = digests
    (run_dir / "resolved-config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False),
                                                  encoding="utf-8")
    code = rundir.code_state()
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
        pin = arm_pin(model_config, bool(arm["thinking"]))
        counter = HFTokenCounter(pin, locate_snapshot(pin))
        raw = yaml.safe_load(model_config.read_text(encoding="utf-8"))
        client = ChatClient(Endpoint.for_model(pin, args.writer_url, raw["served_name"],
                                               timeout_s=float(model.get("timeout_s", 600))),
                            ledger, counter)
        say(f"arm {args.arm}: {raw['served_name']} thinking={arm['thinking']} "
            f"granularity={writer_config.granularity.name} decoding={writer_config.decoding}")
        jobs = []          # (graph name, group, segment key, callable)
        speakers: dict[tuple[str, str], str] = {}
        messages_by_key: dict[tuple[str, str], dict] = {}
        histories_by_slug = {}
        for entry in entries:
            slug, bc = entry["slug"], configs[entry["slug"]]
            records = load_split(slug, entry["split"], config=bc)
            if target["kind"] == "histories":
                write_records(records, run_dir / "records" / slug)
            messages = defaultdict(list)
            for m in records.messages:
                messages[m.history_id].append(m)
            histories_by_slug[slug] = ({h.history_id: h for h in records.histories}, messages)
            if target["kind"] == "histories":
                wanted = args.histories or target.get("histories")
                histories = [h for h in records.histories
                             if wanted is None or h.history_id in wanted]
                for h in histories:
                    for m in messages[h.history_id]:
                        speakers[(h.history_id, m.message_id)] = m.speaker or m.role
                        messages_by_key[(h.history_id, m.message_id)] = m.to_record()
                say(f"{slug}: {len(histories)} histories, "
                    f"{sum(len(messages[h.history_id]) for h in histories)} messages, "
                    f"limit={args.limit}")

                for h in histories:
                    def job(history=h, msgs=messages):
                        writer = llm_writer(writer_config, client, history)
                        return drive_history(history, msgs[history.history_id], writer,
                                             writer_config, run_dir, limit=args.limit)
                    jobs.append((h.history_id, slug, None, job))
        if target["kind"] == "segments":
            for seg in segments:
                infos, messages = histories_by_slug[seg["benchmark"]]
                history = infos[seg["history_id"]]
                msgs = sorted(messages[seg["history_id"]], key=lambda m: m.version)
                for sm in seg["messages"]:
                    m = msgs[sm["version"] - 1]
                    if (m.message_id, m.text) != (sm["message_id"], sm["text"]):
                        raise ValueError(f"{seg['key']}: message {sm['message_id']} differs "
                                         "from the loaded record")
                for m in msgs[seg["first_version"] - 1:seg["last_version"]]:
                    speakers[(seg["key"], m.message_id)] = m.speaker or m.role
                    messages_by_key[(seg["key"], m.message_id)] = m.to_record()
                name = graph_name(seg["key"])

                def job(history=history, msgs=msgs, seg=seg, name=name):
                    writer = llm_writer(writer_config, client, history)
                    return drive_segment(history, msgs, seg["first_version"],
                                         seg["last_version"], writer, writer_config, run_dir,
                                         name)
                jobs.append((name, seg["benchmark"], seg["key"], job))
            say(f"segments: {len(jobs)} of the T024 sample, "
                f"{sum(s['last_version'] - s['first_version'] + 1 for s in segments)} messages")

        def run_job(item):
            name, group, key, job = item
            updates = job()
            say(f"  {name}: {len(updates)} unit records")
            return [{**u, "graph": name, "group": group, "segment": key} for u in updates]

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            results = list(pool.map(run_job, jobs))
        all_updates = [u for part in results for u in part]
        updates_path = run_dir / "updates.jsonl"
        with updates_path.open("w", encoding="utf-8") as f:
            for u in all_updates:
                f.write(json.dumps(u, ensure_ascii=False, sort_keys=True) + "\n")
        n_units = len(all_updates)

        with (run_dir / "extractions.jsonl").open("w", encoding="utf-8") as f:
            for u in all_updates:
                skey = u["segment"] or u["history_id"]
                spk = {mid: speakers[(skey, mid)] for mid in u["message_ids"]}
                for item in extraction_items(u, spk, u["graph"], u["segment"]):
                    f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        changesets = {name: metric.read_jsonl(run_dir / "graphs" / name / "store"
                                              / "changesets.jsonl")
                      for name, *_ in jobs}
        with (run_dir / "changesets.jsonl").open("w", encoding="utf-8") as f:
            for name in sorted(changesets):
                for cs in changesets[name]:
                    if any(cs["entries"].values()):
                        f.write(json.dumps({**cs, "graph": name}, ensure_ascii=False,
                                           sort_keys=True) + "\n")

        updates = metric.read_jsonl(updates_path)
        calls = metric.read_jsonl(run_dir / "calls.jsonl")
        groups = defaultdict(list)
        for u in updates:
            groups[u["group"]].append(u)
        metrics = {"arm": args.arm, "target": args.target,
                   "granularity": writer_config.granularity.name,
                   "thinking": bool(arm["thinking"]), "model": raw["served_name"],
                   "units": metric.unit_stats(updates), "calls": metric.call_stats(calls),
                   "per_group": {g: metric.unit_stats(us) for g, us in sorted(groups.items())},
                   "graph": metric.graph_stats([c for n in sorted(changesets)
                                                for c in changesets[n]]),
                   "model_calls": len(calls)}
        n_messages = metrics["units"]["messages"]
        tok = metrics["calls"]["tokens"].get("all", {})
        metrics["per_message"] = {
            k: (round(tok.get(k, 0) / n_messages, 2) if n_messages else None)
            for k in ("input_tokens", "output_tokens", "cached_input_tokens")}
        (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True)
                                              + "\n", encoding="utf-8")
        flat = [{**u, "history_id": u["segment"] or u["history_id"]} for u in updates]
        samples = metric.sample_units(
            flat, {(u["segment"] or u["history_id"]): changesets[u["graph"]] for u in updates},
            messages_by_key, int(config.get("samples", 30)), int(config["seed"]))
        (run_dir / "samples.json").write_text(json.dumps(samples, indent=2, ensure_ascii=False)
                                              + "\n", encoding="utf-8")
        say(json.dumps({"units": metrics["units"]["by_status"],
                        "empty_patches": metrics["units"]["empty_patches"],
                        "calls": metrics["calls"]["by_status"],
                        "tokens": tok}, sort_keys=True))
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
