"""LoCoMo evidence-anchored read points (task T007; plan 6.5). Model-free and deterministic.

Two stages, run in this order (the promotion threshold is fixed between them):

    dev  conv-26 and conv-49 only, loaded through `splits.load_split`; writes the read points,
         statistics and exclusions of the development histories.
    all  every history. Requires the committed promotion threshold in
         `configs/benchmarks/read-points/locomo.yaml`; evaluates it on the held-out histories.
         Held-out annotations are read through the same `load_split` with the preregistration
         guard overridden, and only with `--held-out-annotation-only`: no system and no model
         sees the data; only evidence IDs, session boundaries and message texts are counted.

Writes into a new directory under runs_root (never into `$PROJECT_ROOT/data`):

    uv run python -m grace.cli.data.locomo_read_points dev --out "$PROJECT_ROOT/runs/T007/..."
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.eval.datasets.benchmarks import locomo_read_points as rp
from grace.eval.datasets.benchmarks.base import Records, load_config, sha256_file
from grace.eval.datasets.benchmarks.splits import load_split

SLUG = "locomo"
READ_POINTS_CONFIG = REPO_ROOT / "configs" / "benchmarks" / "read-points" / "locomo.yaml"
MODEL_CONFIG = REPO_ROOT / "configs" / "models" / "qwen3-8b.yaml"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True,
                          text=True).stdout.strip()


def token_counter(kind: str) -> tuple[Callable[[str], int], dict[str, Any]]:
    if kind == "whitespace":
        return rp.whitespace_tokens, {"kind": "whitespace",
                                      "note": "whitespace-separated words, not model tokens"}
    from grace.llm.tokens import HFTokenCounter, TokenizerPin

    counter = HFTokenCounter.from_model_config(MODEL_CONFIG)
    pin = TokenizerPin.from_file(MODEL_CONFIG)
    return counter.count_text, {
        "kind": "hf-tokenizer", "name": counter.name,
        "model_config": str(MODEL_CONFIG.relative_to(REPO_ROOT)), "files": pin.files,
        "note": "count_text on the message text only: no speaker name, chat template or "
                "special tokens"}


def committed_threshold() -> tuple[rp.Threshold, dict[str, Any]]:
    """The promotion threshold from the read-points config; the file must be committed and
    unchanged, so the threshold provably predates the held-out statistics."""
    rel = str(READ_POINTS_CONFIG.relative_to(REPO_ROOT))
    if not READ_POINTS_CONFIG.is_file():
        raise SystemExit(f"{rel} is missing; run the dev stage and commit the threshold first")
    if git("status", "--porcelain", "--", rel):
        raise SystemExit(f"{rel} has uncommitted changes; commit the threshold first")
    config = yaml.safe_load(READ_POINTS_CONFIG.read_text(encoding="utf-8"))
    raw = config.get("promotion_threshold")
    if not raw:
        raise SystemExit(f"{rel} has no promotion_threshold")
    threshold = rp.Threshold.from_config(raw)
    commit = git("log", "-1", "--format=%H", "-S", "promotion_threshold", "--", rel)
    return threshold, {**raw, "config": rel, "first_commit": commit}


def load(stage: str, allow_held_out: bool) -> dict[str, Records]:
    loaded = {"dev": load_split(SLUG, "dev")}
    if stage == "all":
        if not allow_held_out:
            raise SystemExit("stage all reads held-out annotations; pass "
                             "--held-out-annotation-only to confirm that no system runs on them")
        loaded["held-out"] = load_split(SLUG, "held-out", tag_exists=lambda: True)
    return loaded


def source_order(source: Path) -> tuple[list[str], dict[str, str]]:
    samples = json.loads(source.read_text(encoding="utf-8"))
    return ([s["sample_id"] for s in samples],
            {f"{s['sample_id']}:q{i}": qa["question"] for s in samples
             for i, qa in enumerate(s["qa"])})


def read_points_yaml(points: list[rp.ReadPoint], stats: list[rp.HistoryStats],
                     indexes: dict[str, rp.HistoryIndex], provenance: dict[str, Any],
                     threshold: dict[str, Any] | None) -> dict[str, Any]:
    histories = {}
    for s in stats:
        mine = [p for p in points if p.history_id == s.history_id and p.v is not None]
        histories[s.history_id] = {
            "split": s.split, "n_messages": s.n_messages,
            "session_ends": [last for _, _, last in indexes[s.history_id].segments],
            "read_points": s.read_points,
            "v": {p.task_id: p.v for p in mine}}
    return {
        "benchmark": SLUG, **provenance,
        "definition": "v(q) = last version of the session holding the latest annotated "
                      "evidence turn; every question is also read at N (plan 6.5)",
        "promotion_threshold": threshold,
        "histories": histories,
        "excluded": {p.task_id: p.reason for p in points if p.status == rp.EXCLUDED},
        "reported_separately": {p.task_id: p.reason for p in points
                                if p.status == rp.SEPARATE},
    }


def streaming_tasks(records: Records, points: list[rp.ReadPoint]) -> list[dict[str, Any]]:
    """Read tasks of the `streaming` schedule (contracts.md, Read task): every question with a
    read point is asked at v(q) and at N; excluded questions are not in the schedule."""
    by_id = {t.task_id: t for t in records.read_tasks}
    rows = []
    for p in points:
        if p.v is None:
            continue
        task = by_id[p.task_id].to_record()
        for version in sorted({p.v, p.n_messages}):
            rows.append({**task, "read_id": f"{p.task_id}@{version}", "version": version})
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", choices=("dev", "all"))
    parser.add_argument("--out", type=Path, required=True,
                        help="new output directory; must lie under runs_root")
    parser.add_argument("--tokens", choices=("qwen3-8b", "whitespace"), default="qwen3-8b",
                        help="token counter (default: the pinned Qwen3-8B tokenizer)")
    parser.add_argument("--held-out-annotation-only", action="store_true",
                        help="stage all: confirm that held-out data is only counted, never run")
    args = parser.parse_args(argv)

    runs = shared_dir("runs_root").resolve()
    out = args.out.resolve()
    if runs not in out.parents:
        parser.error(f"--out must lie under {runs}")
    if out.exists():
        parser.error(f"{out} exists; every invocation writes a new directory")

    threshold, threshold_record = (committed_threshold() if args.stage == "all"
                                   else (None, None))
    count, counter_record = token_counter(args.tokens)
    config = load_config(SLUG)
    source_dir = config.source_dir(project_root())
    records_by_split = load(args.stage, args.held_out_annotation_only)

    sample_ids, questions = source_order(source_dir / "locomo10.json")
    included = {h.history_id for r in records_by_split.values() for h in r.histories}
    audit = rp.load_audit(source_dir / "audit", sample_ids, questions, include=included)

    points: list[rp.ReadPoint] = []
    stats: list[rp.HistoryStats] = []
    indexes: dict[str, rp.HistoryIndex] = {}
    streaming_rows: list[dict[str, Any]] = []
    for records in records_by_split.values():
        split_points = rp.compute_read_points(records, audit)
        split_indexes = rp.index_histories(records)
        points += split_points
        indexes.update(split_indexes)
        stats += [rp.history_stats(h, split_points, count) for h in split_indexes.values()]
        streaming_rows += streaming_tasks(records, split_points)

    summaries = {}
    for split in records_by_split:
        summaries[split] = rp.summarize([p for p in points if p.split == split],
                                        [s for s in stats if s.split == split])
    if args.stage == "all":
        summaries["all"] = rp.summarize(points, stats)

    code_sha = git("rev-parse", "HEAD")
    provenance = {
        "version": config.version, "manifest_sha256": config.manifest_sha256,
        "locomo10_sha256": sha256_file(source_dir / "locomo10.json"),
        "code_sha": code_sha, "stage": args.stage,
        "token_counter": counter_record.get("name", counter_record["kind"]),
    }
    out.mkdir(parents=True)
    write_jsonl(out / "read_points.jsonl", [p.to_record() for p in points])
    write_jsonl(out / "read_tasks.streaming.jsonl", streaming_rows)
    write_json(out / "histories.json", [s.__dict__ for s in stats])
    write_json(out / "summary.json", summaries)
    write_json(out / "exclusions.json", rp.exclusions(points))
    if threshold is not None:
        write_json(out / "threshold_evaluation.json",
                   {**rp.evaluate_threshold(summaries["held-out"], threshold),
                    "applied_to": "held-out", "committed_in": threshold_record})
    (out / "read_points.yaml").write_text(
        "# LoCoMo evidence-anchored read points (task T007; plan 6.5). Generated by\n"
        "# scripts/locomo_read_points.sh (grace.cli.data.locomo_read_points); report:\n"
        "# docs/work/tasks/T007-locomo-read-points.md. Only `promotion_threshold` is written by "
        "hand.\n"
        "# `histories.<id>.v` maps task ID -> v(q); questions without a read point are under "
        "`excluded`.\n"
        + yaml.safe_dump(read_points_yaml(points, stats, indexes, provenance, threshold_record),
                         sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8")
    write_json(out / "run.json", {
        "task": "T007", "stage": args.stage, "command": sys.argv, "code_sha": code_sha,
        "git_dirty": bool(git("status", "--porcelain")),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "project_root": str(project_root()), "out": str(out),
        "data": {"benchmark": SLUG, "version": config.version, "source_dir": str(source_dir),
                 "manifest_sha256": config.manifest_sha256,
                 "manifest_sha256_actual": sha256_file(source_dir / "MANIFEST.sha256"),
                 "locomo10_sha256": provenance["locomo10_sha256"]},
        "splits": {s: r.counts() for s, r in records_by_split.items()},
        "held_out_access": ("annotation statistics only, guard overridden by "
                            "--held-out-annotation-only" if args.stage == "all" else "none"),
        "token_counter": counter_record, "threshold": threshold_record,
        "python": platform.python_version(), "model_calls": 0, "compute": "CPU only"})
    for split, summary in summaries.items():
        s = summary["streaming"]
        print(f"{split}: {summary['questions']} questions, {s['questions']} streaming, "
              f"share before final {s['share_before_final']}, "
              f"status {summary['status_counts']}")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
