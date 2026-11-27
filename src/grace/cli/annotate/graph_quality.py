"""Graph-quality annotation (task T024; guideline docs/research/graph-quality-annotation.md).

Usage:

    python -m grace.cli.annotate.graph_quality sample [--record JSON] [--segments JSONL]
    python -m grace.cli.annotate.graph_quality validate LABELS.jsonl [--segments JSONL]
    python -m grace.cli.annotate.graph_quality agreement A.jsonl B.jsonl [--segments JSONL]
        [--json OUT]
    python -m grace.cli.annotate.graph_quality merge A.jsonl B.jsonl --out MERGED.jsonl
        [--segments JSONL]

`sample` draws the 40 segments from the development records, writes the sample record (IDs only,
tracked) and the segments with their text into the T024 run directory. `validate` checks a label
file; `agreement` reports claim-level agreement of two label files; `merge` writes the merged
review file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from grace.config.paths import REPO_ROOT, shared_dir
from grace.eval.analysis.annotation import graph_quality as gq

RECORD = REPO_ROOT / "docs" / "research" / "annotations" / "graph-quality" / "sample.json"


def default_segments() -> Path:
    return shared_dir("runs_root") / "T024" / "artifacts" / "sample" / "segments.jsonl"


def _name(path: Path) -> str:
    stem = path.stem
    return stem[len("labels-"):] if stem.startswith("labels-") else stem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_sample = sub.add_parser("sample", help="draw the segments")
    p_sample.add_argument("--record", type=Path, default=RECORD)
    p_sample.add_argument("--segments", type=Path)
    p_val = sub.add_parser("validate", help="check one label file")
    p_val.add_argument("labels", type=Path)
    p_val.add_argument("--segments", type=Path)
    p_agr = sub.add_parser("agreement", help="claim-level agreement of two label files")
    p_agr.add_argument("a", type=Path)
    p_agr.add_argument("b", type=Path)
    p_agr.add_argument("--segments", type=Path)
    p_agr.add_argument("--json", type=Path)
    p_mer = sub.add_parser("merge", help="merged review file of two label files")
    p_mer.add_argument("a", type=Path)
    p_mer.add_argument("b", type=Path)
    p_mer.add_argument("--out", type=Path, required=True)
    p_mer.add_argument("--segments", type=Path)
    args = parser.parse_args(argv)
    segments_path = args.segments or default_segments()

    if args.command == "sample":
        from grace.eval.datasets.benchmarks import graph_quality_sample as sample
        record, rows = sample.draw()
        sample.write(record, rows, args.record, segments_path)
        print(f"wrote {args.record} and {segments_path}: {record['n_segments']} segments, "
              f"{record['n_messages']} messages")
        return 0

    segments = gq.read_segments(segments_path)
    if args.command == "validate":
        labels = gq.read_jsonl(args.labels)
        problems = gq.check(labels, segments)
        for p in problems:
            print(p)
        print(json.dumps(gq.counts(labels, segments), indent=2))
        print(f"{len(problems)} problems")
        return 1 if problems else 0
    a, b = gq.read_jsonl(args.a), gq.read_jsonl(args.b)
    for path, labels in ((args.a, a), (args.b, b)):
        problems = gq.check(labels, segments)
        if problems:
            print(f"{path}: {len(problems)} problems; first: {problems[0]}", file=sys.stderr)
            return 1
    if args.command == "agreement":
        report = {"a": str(args.a), "b": str(args.b), "segments": str(segments_path),
                  "agreement": gq.agreement(a, b, segments)}
        text = json.dumps(report, indent=2)
        print(text)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(text + "\n", encoding="utf-8")
        return 0
    merged = gq.merge(a, b, segments, _name(args.a), _name(args.b))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in merged:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}: {len(merged)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
