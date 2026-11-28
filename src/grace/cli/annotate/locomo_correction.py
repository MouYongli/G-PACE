"""Manual correction of the LoCoMo development extraction (E009 preparation).

Usage:

    python -m grace.cli.annotate.locomo_correction bundle [--ingest RUN_DIR] [--proposals JSONL]
        [--out JSON]
    python -m grace.cli.annotate.locomo_correction summary JSONL [JSONL ...]
    python -m grace.cli.annotate.locomo_correction apply [--corrections JSONL ...]
        [--ingest RUN_DIR] [--fallback-proposals JSONL] [--require-complete] [--no-validate]
        [--run-root DIR]

`bundle` writes the data file of the review page `web/human-reviewer/locomo/correction/`
(dialogue text, extracted items and the agent proposals); it holds development dialogue text, so
its default place is under `$PROJECT_ROOT/runs/E009/`, never the repository. `summary` counts the
decisions of correction files (an export of the page, or the agent proposals). `apply` replays the
ingest with the corrections and writes a run directory (stage `probe`, upstream: the ingest) with
the corrected `changesets.jsonl` and `snapshot/` in the ingest's format, `corrections.jsonl` (the
decisions applied) and `correction-report.json`. Items without a decision keep the writer's
extraction, unless `--fallback-proposals` fills them with the agent proposals; the run records
which. Development data only.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections import Counter
from pathlib import Path

import yaml

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.eval.runner.harness import rundir
from grace.eval.runner.probes import extraction_correction as xc

EXPERIMENT = "E009"
# The shared LoCoMo dev ingest of the final writer (relative to runs_root).
DEFAULT_INGEST = Path("E007/artifacts/w03-E007/E007/E007-20261128T174115Z-1b02")
PROPOSALS = (REPO_ROOT / "docs" / "research" / "annotations" / "locomo-correction"
             / "proposals-agent-w01.jsonl")


def default_ingest() -> Path:
    return shared_dir("runs_root") / DEFAULT_INGEST


def default_run_root() -> Path:
    return shared_dir("runs_root") / EXPERIMENT / "artifacts" / "correction"


def summarise(records: list[dict]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter] = {}
    for r in records:
        c = out.setdefault(r["history_id"], Counter())
        c[r["decision"]] += 1
        if r.get("change_event"):
            c["change_event"] += 1
    return {h: dict(sorted(c.items())) for h, c in sorted(out.items())}


def cmd_bundle(args) -> int:
    proposals = xc.read_records([args.proposals]) if args.proposals else []
    bundle = xc.build_bundle(args.ingest, proposals)
    out = args.out or (default_run_root() / f"bundle-{bundle['source']['run_id']}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False) + "\n", encoding="utf-8")
    for h in bundle["histories"]:
        kinds = Counter(i["kind"] for i in h["items"])
        print(f"{h['history_id']}: {len(h['messages'])} messages, {len(h['items'])} items "
              f"({', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))})")
    print(f"{len(proposals)} agent proposals; wrote {out}")
    return 0


def cmd_summary(args) -> int:
    print(json.dumps(summarise(xc.read_records(args.files)), indent=2))
    return 0


def cmd_apply(args) -> int:
    if not args.corrections and not args.fallback_proposals:
        print("give --corrections and/or --fallback-proposals", file=sys.stderr)
        return 2
    ingest = Path(args.ingest).resolve()
    histories = xc.load_ingest(ingest)
    human = xc.read_records(args.corrections)
    fallback = xc.read_records([args.fallback_proposals]) if args.fallback_proposals else []
    decisions = xc.merge_decisions(human, fallback)
    human_keys = {xc.key_of(r) for r in human}
    undecided, no_human = {}, {}
    for hid, h in histories.items():
        ids = [i["item_id"] for i in xc.history_items(h)]
        undecided[hid] = sum((hid, i) not in decisions for i in ids)
        no_human[hid] = sum((hid, i) not in human_keys for i in ids)
    if args.require_complete and any(undecided.values()):
        print(f"undecided items: {undecided}", file=sys.stderr)
        return 2

    up = json.loads((ingest / "run.json").read_text(encoding="utf-8"))
    code = rundir.code_state()
    run_dir = rundir.create(args.run_root or default_run_root(), EXPERIMENT)
    inputs = [{"path": Path(p).resolve().as_posix(), "sha256": rundir.file_sha256(Path(p))}
              for p in args.corrections]
    resolved = {
        "purpose": "LoCoMo development extraction with manual corrections (E009 input)",
        "ingest_run_id": up["run_id"],
        "corrections": inputs,
        "fallback_proposals": ({"path": Path(args.fallback_proposals).resolve().as_posix(),
                                "sha256": rundir.file_sha256(Path(args.fallback_proposals))}
                               if args.fallback_proposals else None),
        "undecided_items_policy": "agent proposal" if args.fallback_proposals
        else "writer extraction kept",
        "shacl_validation": not args.no_validate,
    }
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=True, allow_unicode=True), encoding="utf-8")
    run = rundir.RunJson(run_dir, {
        "run_id": run_dir.name, "experiment": EXPERIMENT, "stage": "probe",
        "upstream": [{"run_id": up["run_id"], "stage": up.get("stage", "ingest"),
                      "path": ingest.as_posix(),
                      "run_json_sha256": rundir.file_sha256(ingest / "run.json")}],
        "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": "src/grace/cli/annotate/locomo_correction.py",
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": up.get("data", []),
        "project_root": project_root().as_posix(), "seed": 0,
        "command": " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment("cpu")})
    log = (run_dir / "run.log").open("w", encoding="utf-8")
    (run_dir / "calls.jsonl").write_text("", encoding="utf-8")
    report = xc.Report()
    n = 0
    try:
        manifest = []
        with (run_dir / "changesets.jsonl").open("w", encoding="utf-8") as handle:
            for hid, h in histories.items():
                changesets, store = xc.apply_corrections(h, decisions, report,
                                                         validate=not args.no_validate)
                for cs in changesets:
                    handle.write(cs.to_json() + "\n")
                n += len(changesets)
                files = store.save(run_dir / "snapshot" / hid / "store")
                log_dir = run_dir / "snapshot" / hid / "log"
                log_dir.mkdir(parents=True)
                source = ingest / "snapshot" / hid / "log" / "messages.jsonl"
                (log_dir / "messages.jsonl").write_bytes(source.read_bytes())
                files.append(log_dir / "messages.jsonl")
                manifest.append({"history_id": hid, "version": store.head, "files": [
                    {"path": Path(f).relative_to(run_dir / "snapshot").as_posix(),
                     "sha256": rundir.file_sha256(f)} for f in files]})
                print(f"{hid}: {len(changesets)} change sets, {no_human[hid]} items without a "
                      f"human decision, {undecided[hid]} without any", file=log, flush=True)
        (run_dir / "snapshot" / "manifest.json").write_text(
            json.dumps({"histories": manifest}, indent=2) + "\n", encoding="utf-8")
        applied = [{k: v for k, v in d.items() if k != "_source"} | {"applied_from": d["_source"]}
                   for _, d in sorted(decisions.items())]
        (run_dir / "corrections.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in applied), encoding="utf-8")
        (run_dir / "correction-report.json").write_text(json.dumps(
            {"items_without_human_decision": no_human, "items_without_any_decision": undecided,
             **report.to_record()}, indent=2, ensure_ascii=False)
            + "\n", encoding="utf-8")
    except Exception as error:  # the run is recorded as failed, with the cause
        print(f"failed: {error!r}", file=log, flush=True)
        run.finish(n, failure=f"{type(error).__name__}: {error}")
        raise
    finally:
        log.close()
    run.finish(n)
    print(json.dumps(dict(sorted(report.counts.items())), indent=2))
    print(f"{run.data['status']}: {run_dir}")
    return 0 if run.data["status"] == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_b = sub.add_parser("bundle", help="write the review page's data file")
    p_b.add_argument("--ingest", type=Path, default=None)
    p_b.add_argument("--proposals", type=Path, default=PROPOSALS)
    p_b.add_argument("--out", type=Path)
    p_s = sub.add_parser("summary", help="count the decisions of correction files")
    p_s.add_argument("files", type=Path, nargs="+")
    p_a = sub.add_parser("apply", help="write the corrected extraction to a run directory")
    p_a.add_argument("--ingest", type=Path, default=None)
    p_a.add_argument("--corrections", type=Path, nargs="*", default=[])
    p_a.add_argument("--fallback-proposals", type=Path)
    p_a.add_argument("--require-complete", action="store_true",
                     help="fail when an item has no decision")
    p_a.add_argument("--no-validate", action="store_true", help="skip SHACL validation")
    p_a.add_argument("--run-root", type=Path)
    args = parser.parse_args(argv)
    if getattr(args, "ingest", "unset") is None:
        args.ingest = default_ingest()
    return {"bundle": cmd_bundle, "summary": cmd_summary, "apply": cmd_apply}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
