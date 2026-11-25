"""MultiWOZ offer-turn census (task T006): deterministic, model-free, annotations only.

Usage (normally through scripts/multiwoz-offer-census.sh):

    python -m grace.cli.data.multiwoz_offers --split dev
    python -m grace.cli.data.multiwoz_offers --split held-out --allow-held-out-annotations

Verifies the manifests of MultiWOZ 2.4, 2.2 and 2.1 named in configs/benchmarks/multiwoz.yaml,
applies the offer rule of `grace.eval.datasets.benchmarks.multiwoz_offers` with both act sources
and writes one run directory under `$PROJECT_ROOT/runs/T006/artifacts/census/` with `run.json`,
`resolved-config.yaml`, `run.log`, `census.json`, `turns.jsonl` and `act_files.json`. On the
development split it also writes `check_sample.tsv`, a seeded sample of identified turns with
their context, for the manual precision check.

The held-out split is read directly from the annotation files, not through `load_split`: T006 is
a count of annotations that runs no model and writes no utterance text, and the task file names
the test set. The flag `--allow-held-out-annotations` makes that choice explicit on the command
line and in `run.json`; held-out outputs never contain utterance text.
"""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import sys
from pathlib import Path

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.eval.datasets.benchmarks import multiwoz_offers as mo
from grace.eval.datasets.benchmarks.base import (
    DataError,
    load_config,
    sha256_file,
    verify_manifest,
)
from grace.eval.runner.harness import rundir

EXPERIMENT = "T006"
CONFIG = REPO_ROOT / "configs" / "benchmarks" / "multiwoz.yaml"
SAMPLE_PER_LABEL = {"accept": 30, "reject": 30}


def _context(d: mo.DialogueInput, user_index: int) -> str:
    texts = d.texts or []
    lines = []
    for i in range(max(0, user_index - 2), user_index + 1):
        text = " ".join(texts[i].split())   # tabs and newlines would break the TSV
        lines.append(f"[{i}] {'USER' if i % 2 == 0 else 'SYSTEM'}: {text}")
    return " || ".join(lines)


def write_sample(path: Path, records: list[dict], dialogues: dict[str, mo.DialogueInput],
                 seed: int) -> int:
    rows = mo.sample(records, SAMPLE_PER_LABEL, seed)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["task_id", "label", "offer_kinds", "offered", "evidence", "context",
                         "verdict", "note"])
        for r in rows:
            evidence = {d: {k: v for k, v in info.items() if v}
                        for d, info in r["domains"].items() if info["label"] != "none"}
            writer.writerow([r["task_id"], r["label"], json.dumps(r["offer_kinds"]),
                             json.dumps(r["offered"]), json.dumps(evidence),
                             _context(dialogues[r["dialogue_id"]], r["turn_index"]), "", ""])
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--split", required=True, choices=["dev", "held-out"])
    parser.add_argument("--allow-held-out-annotations", action="store_true",
                        help="required for --split held-out (annotation count only, no model)")
    parser.add_argument("--seed", type=int, default=6, help="seed of the check sample")
    parser.add_argument("--out", type=Path, default=None,
                        help="parent of the run directory (default: runs/T006/artifacts/census)")
    args = parser.parse_args(argv)
    command = shlex.join([sys.executable, "-m", "grace.cli.data.multiwoz_offers",
                          *(argv if argv is not None else sys.argv[1:])])

    config = load_config("multiwoz")
    spec = config.splits[args.split]
    if spec.kind == "held-out" and not args.allow_held_out_annotations:
        parser.error("the held-out split needs --allow-held-out-annotations")
    runs = shared_dir("runs_root").resolve()
    parent = (args.out or runs / EXPERIMENT / "artifacts" / "census").resolve()
    if runs not in parent.parents:
        parser.error(f"--out must lie under {runs}")
    root = project_root()
    run_dir = rundir.create(parent.parent, parent.name, rundir.new_run_id(EXPERIMENT))
    log_lines: list[str] = []

    def log(message: str) -> None:
        print(message)
        log_lines.append(message)

    resolved = {"benchmark": config.benchmark, "split": args.split, "kind": spec.kind,
                "history_list_file": spec.history_list_file,
                "dir_22": config.options["split_dirs_22"][args.split],
                "act_sources": list(mo.ACT_SOURCES), "versions": list(mo.VERSIONS),
                "sample_per_label": SAMPLE_PER_LABEL if spec.kind != "held-out" else None,
                "seed": args.seed, "interval_accuracy": 0.7,
                "threshold_points": mo.THRESHOLD_POINTS,
                "held_out_annotations_only": spec.kind == "held-out"}
    (run_dir / "resolved-config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False),
                                                  encoding="utf-8")
    code = rundir.code_state()
    source_dirs = {v: config.source_dir(root, v) for v in config.manifests()}
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": EXPERIMENT, "stage": "probe", "upstream": [],
        "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": CONFIG.relative_to(REPO_ROOT).as_posix(),
        "config_sha256": sha256_file(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(),
        "data": [{"benchmark": "multiwoz", "version": v, "manifest_sha256": sha,
                  "split": args.split, "path": str(source_dirs[v])}
                 for v, sha in config.manifests().items()],
        "project_root": str(root), "seed": args.seed, "command": command,
        "environment": rundir.environment("cpu"),
        "notes": ("model-free count of annotations; held-out read with "
                  "--allow-held-out-annotations, no utterance text written")
        if spec.kind == "held-out" else "model-free count of annotations"})
    try:
        for version, expected in config.manifests().items():
            verify_manifest(source_dirs[version], expected, check_files=True)
            log(f"manifest {version} ok: {expected}")
        ids = mo.split_ids(source_dirs[config.version], spec.history_list_file)
        dialogues, presence = mo.load_dialogues(source_dirs, ids, resolved["dir_22"],
                                                keep_text=spec.kind != "held-out")
        n_user = sum(len(d.states["2.4"]) for d in dialogues)
        log(f"split {args.split}: {len(dialogues)} dialogues, {n_user} user turns")
        expected = spec.counts
        if (expected.get("histories"), expected.get("read_tasks")) != (len(dialogues), n_user):
            raise DataError(f"counts {len(dialogues)}/{n_user} differ from the config "
                                   f"{expected.get('histories')}/{expected.get('read_tasks')}")
        result = {"split": args.split, "run_id": run_dir.name, "code_sha": code.sha,
                  "act_files": presence, "by_act_source": {}}
        all_records = {}
        with (run_dir / "turns.jsonl").open("w", encoding="utf-8") as handle:
            for source in mo.ACT_SOURCES:
                records = [r for d in dialogues for r in mo.identify(d, source)]
                all_records[source] = records
                for r in records:
                    handle.write(json.dumps(r, sort_keys=True) + "\n")
                result["by_act_source"][source] = mo.census(records, len(dialogues), n_user)
                c = result["by_act_source"][source]
                log(f"act source {source}: offer turns {c['offer_turns']}, labels {c['labels']}, "
                    f"half-width {c['interval']['half_width_points']}")
        primary = result["by_act_source"]["2.1"]["interval"]
        smaller = min((result["by_act_source"][s]["interval"] for s in mo.ACT_SOURCES),
                      key=lambda i: i["n"])
        result["recommendation"] = {"primary_act_source": "2.1", **primary,
                                    "smallest_count_act_source": smaller}
        (run_dir / "census.json").write_text(json.dumps(result, indent=2) + "\n",
                                             encoding="utf-8")
        (run_dir / "act_files.json").write_text(json.dumps(presence, indent=2) + "\n",
                                                encoding="utf-8")
        if spec.kind != "held-out":
            n = write_sample(run_dir / "check_sample.tsv", all_records["2.1"],
                             {d.dialogue_id: d for d in dialogues}, args.seed)
            log(f"check sample: {n} turns")
        n_records = sum(len(r) for r in all_records.values())
        (run_dir / "run.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        run.finish(n_records)
    except Exception as exc:   # record the failure, keep the directory, re-raise
        (run_dir / "run.log").write_text("\n".join([*log_lines, repr(exc)]) + "\n",
                                         encoding="utf-8")
        run.finish(0, failure=repr(exc))
        raise
    print(run_dir)
    return 0 if run.data["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
