"""E001 pilot measurements: probe, system cells and summary tables (development data only).

    uv run python -m grace.cli.pilot probe --config configs/experiments/E001-pilot-measurements.yaml
    uv run python -m grace.cli.pilot plan --config <config> --cell full-cached
    uv run python -m grace.cli.pilot system --config <config> --cell full-cached \\
        --engine configs/engines/full-history-cached.yaml --benchmark multiwoz --shard 0/8 \\
        --base-url http://127.0.0.1:8100/v1 --embed-url http://127.0.0.1:8101/v1
    uv run python -m grace.cli.pilot summary --config <config> --probe <run-id> <run-id>...

- `probe` (stage `probe`, no model): loads every development split of the config through
  `load_split`, writes its record files under `records/<slug>/` (gold included: the analysis reads
  gold only as run files), counts every history and the full-history answer prompt of every read
  with the primary model's pinned tokenizer and chat template, exactly as the raw-text engine and
  the harness render them, and writes `pilot-probe.json` (lengths, full-history cost, update
  density, the prompt-reserve rule). `n_records` is the number of reads.
- `system`: one harness `system` run of one engine of a cell on one benchmark (and shard), with
  the server condition of the cell recorded in `resolved-config.yaml`.
- `plan`: the `system` invocations of a cell, one per line (for a parallel launcher).
- `summary`: tables over an explicit list of run IDs (not a run): per-run cost and cache ratio, the
  compute ratio of cached input, and the judging estimate. Written to `<out>/summary.json` with the
  checksums of every input run.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
import traceback
from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.eval.analysis.metrics import pilot
from grace.eval.datasets.benchmarks.base import BenchmarkConfig, Records, load_config, write_records
from grace.eval.datasets.benchmarks.splits import load_split
from grace.eval.engines.baselines.base import EMPTY_CONTEXT, message_time, render_message
from grace.eval.runner.harness import drive, rundir
from grace.eval.runner.harness.answer import messages_for
from grace.llm.prompts import load_pinned
from grace.llm.tokens import HFTokenCounter, TokenCounter

PROMPT_REGISTRY = REPO_ROOT / "configs" / "common" / "prompts.yaml"
STALE_LABELS = "stale_labels.jsonl"


# ---------------------------------------------------------------------------------------------
# Config


def load_experiment(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for key in ("experiment", "model_config", "benchmarks", "cells", "probe", "serving"):
        if key not in config:
            raise ValueError(f"{path}: missing {key!r}")
    return config


def benchmark_config(spec: Mapping[str, Any]) -> BenchmarkConfig | None:
    """The inline benchmark config of a benchmark entry, if it has one."""
    return BenchmarkConfig.from_dict(spec["config"]) if spec.get("config") else None


def resolved_benchmark(slug: str, spec: Mapping[str, Any]) -> BenchmarkConfig:
    return benchmark_config(spec) or load_config(slug)


def sample(history_ids: list[str], n: int | str, prefix: str) -> list[str]:
    """The n histories with the smallest sha256("<prefix>:<id>"), in that order; `all` keeps
    every history in the same order (so smaller samples are prefixes of larger ones)."""
    ordered = sorted(history_ids,
                     key=lambda h: hashlib.sha256(f"{prefix}:{h}".encode()).hexdigest())
    return ordered if n == "all" else ordered[:int(n)]


def load_records(slug: str, spec: Mapping[str, Any], data_root: Path | None = None) -> Records:
    """A development split through `load_split`; for change-seq also the generator's staleness
    labels (rows with answer_stale or citation_stale set) as a scoring file."""
    config = resolved_benchmark(slug, spec)
    if config.splits[spec["split"]].kind != "development":
        raise ValueError(f"{slug}/{spec['split']}: E001 reads development splits only")
    records = load_split(slug, spec["split"], config=config, data_root=data_root)
    if slug == "change-seq":
        source = config.source_dir(data_root if data_root is not None else project_root())
        dataset = json.loads((source / "dataset.json").read_text(encoding="utf-8"))
        paths = {s["sequence_id"]: s["path"] for s in dataset["sequences"]}
        rows = []
        for history in records.histories:
            for label in pilot.read_jsonl(source / paths[history.history_id] / "labels.jsonl"):
                if label["answer_stale"] or label["citation_stale"]:
                    rows.append({"history_id": history.history_id, **label})
        records.scoring[STALE_LABELS] = rows
    return records


# ---------------------------------------------------------------------------------------------
# Probe


def count_lengths(records: Records, counter: TokenCounter
                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per history and per read of the native schedule: token counts of the full history and of
    the full-history answer prompt, rendered as the raw-text engine and the harness render them."""
    messages = defaultdict(list)
    for message in records.messages:
        messages[message.history_id].append(message)
    reads = defaultdict(list)
    for task in records.read_tasks:
        reads[task.history_id].append(task)
    history_rows, read_rows = [], []
    for history in records.histories:
        items = sorted(messages[history.history_id], key=lambda m: m.version)
        rendered = [render_message(m, history) for m in items]
        tokens = [counter.count_text(t) for t in rendered]
        history_rows.append({
            "history_id": history.history_id, "n_messages": len(items),
            "history_tokens": counter.count_text("\n".join(rendered)),
            "message_tokens_sum": sum(tokens),
            "mean_message_tokens": round(sum(tokens) / len(tokens), 3) if tokens else 0,
            "n_reads": len(reads[history.history_id])})
        contexts: dict[int, tuple[str, int]] = {}
        for task in sorted(reads[history.history_id], key=lambda t: (t.version, t.read_id)):
            if task.version not in contexts:
                text = "\n".join(rendered[:task.version]) or EMPTY_CONTEXT
                contexts[task.version] = (text, counter.count_text(text))
            text, context_tokens = contexts[task.version]
            prompt = messages_for(text, task, message_time(items[task.version - 1], history))
            read_rows.append({"read_id": task.read_id, "task_id": task.task_id,
                              "history_id": task.history_id, "version": task.version,
                              "kind": task.kind, "context_tokens": context_tokens,
                              "prompt_tokens": counter.count_messages(prompt)})
    return history_rows, read_rows


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def probe_tables(run_dir: Path, slugs: list[str], probe: Mapping[str, Any],
                 output_reserve: int) -> dict[str, Any]:
    """`pilot-probe.json` from the probe's own files."""
    tables, fixed_max = {}, 0
    for slug in slugs:
        histories = pilot.read_jsonl(run_dir / "lengths" / f"{slug}.histories.jsonl")
        reads = pilot.read_jsonl(run_dir / "lengths" / f"{slug}.reads.jsonl")
        tables[slug] = {
            "lengths": pilot.length_tables(histories, reads,
                                           window_tokens=int(probe["window_tokens"]),
                                           output_reserve_tokens=output_reserve),
            "update_density": pilot.update_density(slug, run_dir / "records" / slug)}
        fixed = tables[slug]["lengths"]["fixed_prompt_tokens"]["max"]
        fixed_max = max(fixed_max, int(fixed or 0))
    reserve = pilot.prompt_reserve(fixed_max, output_reserve, int(probe["reserve_margin_tokens"]),
                                   int(probe["reserve_round_tokens"]))
    return {"benchmarks": tables,
            "prompt_reserve": {"fixed_prompt_tokens_max": fixed_max,
                               "output_reserve_tokens": output_reserve,
                               "margin_tokens": int(probe["reserve_margin_tokens"]),
                               "prompt_reserve_tokens": reserve,
                               "context_window_tokens": int(probe["window_tokens"]) - reserve}}


def data_entries(slug: str, spec: Mapping[str, Any], data_root: Path | None) -> list[dict]:
    config = resolved_benchmark(slug, spec)
    root = data_root if data_root is not None else project_root()
    return [{"benchmark": slug, "version": version, "manifest_sha256": sha,
             "split": spec["split"], "path": config.source_dir(root, version).resolve().as_posix()}
            for version, sha in config.manifests().items()]


def run_probe(config_path: Path, run_root: Path, *, counter: TokenCounter | None = None,
              loader: Callable[[str, Mapping[str, Any]], Records] | None = None,
              data_root: Path | None = None, code: rundir.CodeState | None = None,
              command: str | None = None) -> tuple[Path, str]:
    """The probe run; returns its directory and final status."""
    exp = load_experiment(config_path)
    code = code or rundir.code_state()
    run_dir = rundir.create(run_root, exp["experiment"])
    output_reserve = int(drive.budgets()["answer"]["output_reserve_tokens"])
    resolved = {"stage": "probe", "experiment": exp["experiment"],
                "config": drive.repo_relative(config_path), "model_config": exp["model_config"],
                "benchmarks": exp["benchmarks"], "probe": exp["probe"],
                "output_reserve_tokens": output_reserve}
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True), encoding="utf-8")
    data = [entry for slug, spec in exp["benchmarks"].items()
            for entry in data_entries(slug, spec, data_root)]
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": exp["experiment"], "stage": "probe",
        "upstream": [], "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": drive.repo_relative(config_path),
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": data,
        "project_root": project_root().as_posix(), "seed": int(exp.get("seed", 0)),
        "command": command or " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment("cpu")})
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    n_reads = 0
    try:
        counter = counter or HFTokenCounter.from_model_config(REPO_ROOT / exp["model_config"])
        load = loader or (lambda slug, spec: load_records(slug, spec, data_root))
        for slug, spec in exp["benchmarks"].items():
            records = load(slug, spec)
            write_records(records, run_dir / "records" / slug)
            histories, reads = count_lengths(records, counter)
            write_jsonl(run_dir / "lengths" / f"{slug}.histories.jsonl", histories)
            write_jsonl(run_dir / "lengths" / f"{slug}.reads.jsonl", reads)
            n_reads += len(reads)
            log.write(f"{slug}: {records.counts()}\n")
            log.flush()
        tables = probe_tables(run_dir, list(exp["benchmarks"]), exp["probe"], output_reserve)
        (run_dir / "pilot-probe.json").write_text(json.dumps(tables, indent=2) + "\n",
                                                  encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure, then re-raised
        log.write(traceback.format_exc())
        log.close()
        run.finish(n_reads, f"{type(exc).__name__}: {exc}")
        raise
    log.write(f"done: {n_reads} reads\n")
    log.close()
    run.finish(n_reads)
    return run_dir, run.data["status"]


# ---------------------------------------------------------------------------------------------
# System cells


def cell_runs(exp: Mapping[str, Any], cell: str,
              history_ids: Callable[[str], list[str]]) -> list[dict[str, Any]]:
    """Every (engine, benchmark, shard) run of a cell, with its histories."""
    spec = exp["cells"][cell]
    runs = []
    for slug in exp["benchmarks"]:
        n = spec["histories"] if spec["histories"] == "all" else spec["histories"].get(slug)
        if n is None:
            continue
        chosen = sample(history_ids(slug), n, exp["sample_prefix"])
        shards = int((spec.get("shards") or {}).get(slug, 1))
        for engine in spec["engines"]:
            for index in range(shards):
                runs.append({"cell": cell, "engine": engine, "benchmark": slug,
                             "shard": f"{index}/{shards}", "histories": chosen[index::shards]})
    return runs


def split_history_ids(exp: Mapping[str, Any], data_root: Path | None = None
                      ) -> Callable[[str], list[str]]:
    def ids(slug: str) -> list[str]:
        spec = exp["benchmarks"][slug]
        records = load_split(slug, spec["split"], config=resolved_benchmark(slug, spec),
                             data_root=data_root)
        return [h.history_id for h in records.histories]
    return ids


def serving_record(exp: Mapping[str, Any], cell: str) -> dict[str, Any]:
    condition = exp["cells"][cell]["condition"]
    serving = exp["serving"]
    return {"cell": cell, "condition": condition,
            "prefix_caching": bool(serving["conditions"][condition]["prefix_caching"]),
            "chat_args": [*serving["chat"]["args"], *serving["conditions"][condition]["args"]],
            "embed_args": list(serving["embed"]["args"]), "gpu": serving["gpu"]}


def run_cell(exp: Mapping[str, Any], cell: str, engine: str, benchmark: str, shard: str,
             history_ids: list[str], run_root: Path, client: drive.ClientSettings | None = None,
             **kwargs) -> drive.SystemRun:
    spec = exp["cells"][cell]
    budget = None if spec["budget"] == "full" else int(spec["budget"])
    bench = exp["benchmarks"][benchmark]
    return drive.run_system(engine_config=REPO_ROOT / engine, benchmark=benchmark,
                            split=bench["split"], budget=budget, experiment=exp["experiment"],
                            run_root=run_root, seed=int(exp.get("seed", 0)),
                            history_ids=history_ids, client=client,
                            benchmark_config=benchmark_config(bench), **kwargs)


# ---------------------------------------------------------------------------------------------
# Summary


def run_condition(table: Mapping[str, Any]) -> str | None:
    return (table.get("serving") or {}).get("condition")


def summarise(exp: Mapping[str, Any], run_dirs: list[Path], probe_dir: Path,
              counter: TokenCounter | None = None) -> dict[str, Any]:
    loaded = [pilot.read_run(d) for d in run_dirs]
    tables = [pilot.run_tables(item) for item in loaded]
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for i, table in enumerate(tables):
        cell = (table.get("serving") or {}).get("cell", "?")
        groups[(cell, str(table["engine_config"]), str(table["benchmark"]))].append(i)
    cells = []
    for (cell, engine, benchmark), members in sorted(groups.items()):
        calls = [c for i in members for c in loaded[i]["calls"]]
        answer = [c for c in calls if c["call_type"] == "answer"]
        outputs: dict[str, int] = defaultdict(int)
        for i in members:
            for key, value in tables[i]["outputs"].items():
                outputs[key] += value
        categories = defaultdict(list)
        for c in calls:
            categories[c["category"]].append(c)
        cells.append({"cell": cell, "engine_config": engine, "benchmark": benchmark,
                      "runs": [tables[i]["run_id"] for i in members],
                      "statuses": sorted({tables[i]["status"] for i in members}),
                      "condition": run_condition(tables[members[0]]),
                      "histories": sum(tables[i]["histories"] for i in members),
                      "reads": sum(tables[i]["n_records"] for i in members),
                      "outputs": dict(sorted(outputs.items())),
                      "answer_calls": pilot.call_sums(answer),
                      "by_category": {k: pilot.call_sums(v)
                                      for k, v in sorted(categories.items())}})
    fit_types = set((exp.get("summary") or {}).get("fit_call_types", ["answer"]))
    fit = {}
    full = [i for i, t in enumerate(tables)
            if (t.get("serving") or {}).get("cell") in ("full-cached", "full-uncached")
            and t["status"] == "completed"]
    fit_calls = [c for i in full for c in loaded[i]["calls"] if c["call_type"] in fit_types]
    fit["all"] = pilot.compute_ratio(fit_calls)
    for benchmark in sorted({tables[i]["benchmark"] for i in full}):
        fit[benchmark] = pilot.compute_ratio(
            [c for i in full if tables[i]["benchmark"] == benchmark
             for c in loaded[i]["calls"] if c["call_type"] in fit_types])
    anomalies = [t["run_id"] for t in tables if run_condition(t) == "apc-off"
                 and (t["answer_calls"]["cached_input_tokens"] or 0) > 0]
    judging = judge_estimate(exp, loaded, tables, probe_dir, counter)
    return {"runs": tables, "cells": cells, "compute_ratio": fit,
            "apc_off_runs_with_cached_tokens": anomalies, "judging_estimate": judging}


def judge_estimate(exp, loaded, tables, probe_dir: Path, counter: TokenCounter | None):
    spec = exp.get("judging") or {}
    wanted = set(spec.get("cells") or [])
    reads, gold = {}, {}
    for slug in exp["benchmarks"]:
        records = probe_dir / "records" / slug
        reads.update({r["read_id"]: r for r in pilot.read_jsonl(records / "read_tasks.jsonl")})
        for g in pilot.read_jsonl(records / "gold.jsonl"):
            gold.setdefault(g["task_id"], g)  # first annotation; the judge is per annotation
    prompt = load_pinned("judge", PROMPT_REGISTRY)
    out_tokens = int(drive.budgets()["judge"]["max_tokens"])
    per_benchmark = {}
    for slug in exp["benchmarks"]:
        predictions = [p for item, table in zip(loaded, tables, strict=True)
                       if (table.get("serving") or {}).get("cell") in wanted
                       and table["benchmark"] == slug for p in item["predictions"]]
        judged = [p for p in predictions if p["output"] == "answer"
                  and reads.get(p["read_id"], {}).get("kind") == "question"]
        tokens = []
        if counter is not None:
            for p in judged:
                task = reads[p["read_id"]]
                rendered = prompt.render(question=task["question"],
                                         reference=_text(gold[p["task_id"]]["reference"]),
                                         response=_text(p["prediction"]))
                tokens.append(counter.count_messages(rendered))
        per_benchmark[slug] = {"predictions": len(predictions), **pilot.judge_estimate(
            judged, tokens, spec.get("secondary_price_usd_per_mtok",
                                     {"input": 0.0, "output": 0.0}), out_tokens)}
    total = {k: sum(v[k] for v in per_benchmark.values())
             for k in ("predictions", "judgeable_predictions", "judge_input_tokens",
                       "judge_output_tokens_max")}
    total["secondary_usd_estimate"] = round(sum(v["secondary_usd_estimate"]
                                                for v in per_benchmark.values()), 4)
    return {"cells": sorted(wanted), "by_benchmark": per_benchmark, "total": total,
            "note": "judge prompt tokens counted with the primary model's tokenizer as a proxy; "
                    "the hosted judge counts with its own tokenizer"}


def _text(value) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value)


# ---------------------------------------------------------------------------------------------
# Command line


def default_run_root() -> Path:
    return shared_dir("runs_root") / "E001" / "artifacts" / "manager"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "plan", "system", "summary"):
        p = sub.add_parser(name)
        p.add_argument("--config", type=Path, required=True)
        p.add_argument("--run-root", type=Path, default=None,
                       help="parent of E001/<run-id>/ (default: runs/E001/artifacts/manager)")
        if name in ("plan", "system"):
            p.add_argument("--cell", required=True)
        if name == "system":
            p.add_argument("--engine", required=True)
            p.add_argument("--benchmark", required=True)
            p.add_argument("--shard", default="0/1")
            p.add_argument("--base-url", required=True)
            p.add_argument("--embed-url", default=None)
        if name == "summary":
            p.add_argument("--probe", required=True, help="run ID of the probe run")
            p.add_argument("--out", type=Path, required=True)
            p.add_argument("runs", nargs="+", help="run IDs of system runs")
    args = parser.parse_args(argv)
    exp = load_experiment(args.config)
    run_root = args.run_root or default_run_root()
    if args.command == "probe":
        run_dir, status = run_probe(args.config, run_root)
        print(f"{run_dir.name}: {status} -> {run_dir}")
        return 0 if status == "completed" else 1
    if args.command == "plan":
        for item in cell_runs(exp, args.cell, split_history_ids(exp)):
            print(f"--cell {item['cell']} --engine {item['engine']} "
                  f"--benchmark {item['benchmark']} --shard {item['shard']} "
                  f"# {len(item['histories'])} histories")
        return 0
    if args.command == "system":
        index, total = (int(x) for x in args.shard.split("/"))
        match = [r for r in cell_runs(exp, args.cell, split_history_ids(exp))
                 if r["engine"] == args.engine and r["benchmark"] == args.benchmark
                 and r["shard"] == f"{index}/{total}"]
        if len(match) != 1:
            parser.error("no such engine / benchmark / shard in this cell")
        client = drive.ClientSettings(args.base_url, REPO_ROOT / exp["model_config"],
                                      args.embed_url, serving_record(exp, args.cell))
        result = run_cell(exp, args.cell, args.engine, args.benchmark, args.shard,
                          match[0]["histories"], run_root, client,
                          command=" ".join(shlex.quote(a) for a in sys.argv))
        print(f"{result.run_id}: {result.status} ({result.n_reads} reads) -> {result.run_dir}")
        if result.failure:
            print(f"failure: {result.failure}")
        return 0 if result.status == "completed" else 1
    base = run_root / exp["experiment"]
    counter = HFTokenCounter.from_model_config(REPO_ROOT / exp["model_config"])
    dirs = [base / run_id for run_id in args.runs]
    summary = summarise(exp, dirs, base / args.probe, counter)
    inputs = [{"run_id": d.name, "run_json_sha256": rundir.file_sha256(d / "run.json")}
              for d in [base / args.probe, *dirs]]
    code = rundir.code_state()
    out = args.out
    out.mkdir(parents=True, exist_ok=False)
    payload = {"experiment": exp["experiment"], "code_sha": code.sha, "code_dirty": code.dirty,
               "config_path": drive.repo_relative(args.config),
               "command": " ".join(shlex.quote(a) for a in sys.argv), "created_at":
               rundir.utc_now(), "probe": args.probe, "inputs": inputs,
               "probe_tables": json.loads((base / args.probe / "pilot-probe.json")
                                          .read_text(encoding="utf-8")), **summary}
    (out / "summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(out / "summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
