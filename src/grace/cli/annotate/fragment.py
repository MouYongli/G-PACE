"""Fragment-coverage annotation of LoCoMo (task T012; guideline docs/research/fragment-coverage.md).

Usage (normally through scripts/annotation/fragment-coverage.sh):

    python -m grace.cli.annotate.fragment sheet [--out CSV]
    python -m grace.cli.annotate.fragment coverage LABELS.csv [--sheet CSV] [--json OUT]
    python -m grace.cli.annotate.fragment agreement A.csv B.csv [--sheet CSV] [--all] [--json OUT]

`sheet` writes the annotation sheet of the development split (it refuses any other split).
`coverage` reports the classes of one label file. `agreement` reports Cohen's kappa between two
label files on the overlap questions of the sheet (`--all`: on every question both label).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from grace.config.paths import REPO_ROOT
from grace.eval.analysis.annotation import fragment
from grace.eval.datasets.benchmarks import locomo_annotation

ANNOTATION_DIR = REPO_ROOT / "docs" / "research" / "annotations" / "fragment-coverage"
SHEET = ANNOTATION_DIR / "sheet.csv"


def _emit(report: dict, text: str, out: Path | None) -> None:
    print(text)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_sheet = sub.add_parser("sheet", help="write the annotation sheet")
    p_sheet.add_argument("--out", type=Path, default=SHEET)
    p_sheet.add_argument("--split", default="dev")
    p_cov = sub.add_parser("coverage", help="coverage per class of one label file")
    p_cov.add_argument("labels", type=Path)
    p_cov.add_argument("--sheet", type=Path, default=SHEET)
    p_cov.add_argument("--json", type=Path)
    p_agr = sub.add_parser("agreement", help="Cohen's kappa between two label files")
    p_agr.add_argument("a", type=Path)
    p_agr.add_argument("b", type=Path)
    p_agr.add_argument("--sheet", type=Path, default=SHEET)
    p_agr.add_argument("--all", action="store_true",
                       help="use every question both files label, not only the overlap set")
    p_agr.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    if args.command == "sheet":
        rows = locomo_annotation.fragment_sheet(args.split)
        locomo_annotation.write_sheet(rows, args.out)
        chosen = sum(r["overlap"] == "yes" for r in rows)
        print(f"wrote {args.out}: {len(rows)} questions, {chosen} in the overlap set "
              f"(seed {locomo_annotation.OVERLAP_SEED!r})")
        return 0
    sheet = fragment.read_sheet(args.sheet)
    if args.command == "coverage":
        report = fragment.coverage(fragment.read_labels(args.labels), sheet)
        _emit(report, fragment.render_coverage(report), args.json)
        return 0
    restrict = None if args.all else fragment.overlap_ids(sheet)
    report = fragment.agreement(fragment.read_labels(args.a), fragment.read_labels(args.b),
                                restrict)
    _emit(report, fragment.render_agreement(report), args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
