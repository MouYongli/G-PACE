"""Sequence audit of the controlled change sequences (task T016; guideline
docs/research/sequence-audit.md).

Usage:

    python -m grace.cli.annotate.sequence sheet [--dataset DIR] [--out CSV] [--record JSON]
    python -m grace.cli.annotate.sequence mismatch LABELS.csv [--sheet CSV] [--json OUT]
    python -m grace.cli.annotate.sequence agreement A.csv B.csv [--sheet CSV] [--json OUT]

`sheet` draws the audit sample from a generated development dataset (default: the T015 run
named by `DEFAULT_DATASET_RUN` under the runs root) and writes the sheet and the sample record.
`mismatch` reports the mismatch rate per family of one label file and the families the decision
rule flags. `agreement` reports Cohen's kappa and the disagreement rate between two label files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from grace.config.paths import REPO_ROOT, shared_dir
from grace.eval.analysis.annotation import sequence, sequence_sheet

ANNOTATION_DIR = REPO_ROOT / "docs" / "research" / "annotations" / "sequence-audit"
SHEET = ANNOTATION_DIR / "sheet.csv"
RECORD = ANNOTATION_DIR / "sample.json"
DEFAULT_DATASET_RUN = ("T015", "T015-devmodel-20261125T192037Z")


def default_dataset() -> Path:
    task, run_id = DEFAULT_DATASET_RUN
    return shared_dir("runs_root") / task / "artifacts" / run_id / "dataset"


def _emit(report: dict, text: str, out: Path | None) -> None:
    print(text)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_sheet = sub.add_parser("sheet", help="draw the sample and write the annotation sheet")
    p_sheet.add_argument("--dataset", type=Path, help="generated dataset directory")
    p_sheet.add_argument("--out", type=Path, default=SHEET)
    p_sheet.add_argument("--record", type=Path, default=RECORD)
    p_mis = sub.add_parser("mismatch", help="mismatch rate per family of one label file")
    p_mis.add_argument("labels", type=Path)
    p_mis.add_argument("--sheet", type=Path, default=SHEET)
    p_mis.add_argument("--json", type=Path)
    p_agr = sub.add_parser("agreement", help="Cohen's kappa between two label files")
    p_agr.add_argument("a", type=Path)
    p_agr.add_argument("b", type=Path)
    p_agr.add_argument("--sheet", type=Path, default=SHEET)
    p_agr.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    if args.command == "sheet":
        dataset = args.dataset or default_dataset()
        data = sequence_sheet.load_dataset(dataset)
        rows, record = sequence_sheet.build_sheet(data)
        record["dataset_run"] = dataset.resolve().parent.name
        sequence_sheet.write_sheet(rows, args.out)
        sequence_sheet.write_record(record, args.record)
        print(f"wrote {args.out} and {args.record}: {record['counts']} "
              f"(seed {sequence_sheet.SAMPLE_SEED!r}, manifest {record['manifest_sha256']})")
        return 0
    sheet = sequence.read_sheet(args.sheet)
    if args.command == "mismatch":
        report = sequence.mismatch_report(sequence.read_labels(args.labels, sheet), sheet)
        _emit(report, sequence.render_mismatch(report), args.json)
        return 0
    report = sequence.agreement(sequence.read_labels(args.a, sheet),
                                sequence.read_labels(args.b, sheet), sheet)
    _emit(report, sequence.render_agreement(report), args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
