"""Fragment coverage of LoCoMo questions: label files, coverage per class and Cohen's kappa.

Task T012, plan 6.5; the guideline is docs/research/fragment-coverage.md. Reads files only (the
annotation sheet and label files), as every module under `eval/analysis/` does.

A label file is a CSV with the columns `question_id`, `annotator`, `label` and optionally
`operations`, `other_reason`, `flags` and `rationale`; other columns (for example those of the
sheet) are ignored, so an annotator can fill a copy of the sheet and save it as their label
file. Rows with an empty `label` are unlabelled and skipped. One file holds one annotator. An
annotator whose name starts with `agent-` is a model pre-annotation, never a human annotator.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grace.eval.analysis.judging.human import Agreement, cohen_kappa

IN_FRAGMENT = "in_fragment"
LABELS = (IN_FRAGMENT, "open_reasoning", "date_arithmetic", "common_sense", "other")
# Operations an annotator lists beyond a single claim pattern. Provenance expansion, the sixth
# operation of plan 3.3, belongs to every in-fragment query and is therefore never listed; the
# built-in "currently accepted" negation is not listed as `negation` either.
OPERATIONS = ("filter", "join", "negation", "count", "latest")
OTHER_REASONS = ("image_only", "annotation_error", "beyond_fragment")
FLAGS = ("relative_time", "partial_image")
REQUIRED_COLUMNS = ("question_id", "annotator", "label")
AGENT_PREFIX = "agent-"


class LabelError(ValueError):
    """A label file or sheet violates the format of the guideline."""


@dataclass(frozen=True)
class Label:
    question_id: str
    label: str
    operations: tuple[str, ...] = ()
    other_reason: str = ""
    flags: tuple[str, ...] = ()
    rationale: str = ""


@dataclass
class LabelSet:
    annotator: str
    labels: dict[str, Label] = field(default_factory=dict)
    unlabelled: int = 0
    path: str = ""

    @property
    def kind(self) -> str:
        return "agent" if self.annotator.startswith(AGENT_PREFIX) else "human"

    def classes(self) -> dict[str, str]:
        return {q: lab.label for q, lab in self.labels.items()}

    def binary(self) -> dict[str, str]:
        return {q: ("in" if lab.label == IN_FRAGMENT else "out") for q, lab in self.labels.items()}


def _split(value: str) -> tuple[str, ...]:
    return tuple(t.strip() for t in value.replace(",", ";").split(";") if t.strip())


def parse_label(row: Mapping[str, str], where: str) -> Label:
    qid = (row.get("question_id") or "").strip()
    label = (row.get("label") or "").strip()
    if not qid:
        raise LabelError(f"{where}: empty question_id")
    if label not in LABELS:
        raise LabelError(f"{where}: label {label!r} not in {LABELS}")
    operations = _split(row.get("operations") or "")
    unknown = sorted(set(operations) - set(OPERATIONS))
    if unknown:
        raise LabelError(f"{where}: unknown operations {unknown}; allowed {OPERATIONS}")
    if len(set(operations)) != len(operations):
        raise LabelError(f"{where}: repeated operation in {operations}")
    if operations and label != IN_FRAGMENT:
        raise LabelError(f"{where}: operations are given only for {IN_FRAGMENT}")
    reason = (row.get("other_reason") or "").strip()
    if label == "other" and reason not in OTHER_REASONS:
        raise LabelError(f"{where}: label other needs other_reason in {OTHER_REASONS}")
    if label != "other" and reason:
        raise LabelError(f"{where}: other_reason is given only for label other")
    flags = _split(row.get("flags") or "")
    bad_flags = sorted(set(flags) - set(FLAGS))
    if bad_flags:
        raise LabelError(f"{where}: unknown flags {bad_flags}; allowed {FLAGS}")
    if flags and label != IN_FRAGMENT:
        raise LabelError(f"{where}: flags are given only for {IN_FRAGMENT}")
    ordered = tuple(op for op in OPERATIONS if op in operations)
    return Label(qid, label, ordered, reason, tuple(f for f in FLAGS if f in flags),
                 (row.get("rationale") or "").strip())


def read_labels(path: Path) -> LabelSet:
    """Read and check one label file; duplicate questions or several annotators abort."""
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or ())]
        if missing:
            raise LabelError(f"{path}: missing columns {missing}")
        annotators: set[str] = set()
        result = LabelSet(annotator="", path=str(path))
        for number, row in enumerate(reader, start=2):
            where = f"{path}:{number}"
            if not (row.get("label") or "").strip():
                result.unlabelled += 1
                continue
            annotator = (row.get("annotator") or "").strip()
            if not annotator:
                raise LabelError(f"{where}: empty annotator")
            annotators.add(annotator)
            label = parse_label(row, where)
            if label.question_id in result.labels:
                raise LabelError(f"{where}: duplicate label of {label.question_id}")
            result.labels[label.question_id] = label
    if len(annotators) > 1:
        raise LabelError(f"{path}: one annotator per file, found {sorted(annotators)}")
    if not annotators:
        raise LabelError(f"{path}: no labelled rows")
    result.annotator = annotators.pop()
    return result


def read_sheet(path: Path) -> dict[str, dict[str, str]]:
    """question_id -> sheet row (needs `question_id`, `category` and `overlap`)."""
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for column in ("question_id", "category", "overlap"):
        if rows and column not in rows[0]:
            raise LabelError(f"{path}: missing column {column}")
    sheet = {r["question_id"]: r for r in rows}
    if len(sheet) != len(rows):
        raise LabelError(f"{path}: duplicate question_id")
    return sheet


def overlap_ids(sheet: Mapping[str, Mapping[str, str]]) -> set[str]:
    return {q for q, row in sheet.items() if row.get("overlap") == "yes"}


def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval of a proportion (95 % by default)."""
    if n == 0:
        raise ValueError("empty sample")
    p = successes / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    denominator = 1 + z * z / n
    return (centre - half) / denominator, (centre + half) / denominator


def _check_against_sheet(labels: LabelSet, sheet: Mapping[str, Any] | None) -> list[str]:
    if sheet is None:
        return []
    unknown = sorted(set(labels.labels) - set(sheet))
    if unknown:
        raise LabelError(f"{labels.path}: questions not in the sheet: {unknown[:5]}")
    return sorted(set(sheet) - set(labels.labels))


def coverage(labels: LabelSet, sheet: Mapping[str, Mapping[str, str]] | None = None) -> dict:
    """Counts and shares per class, the in-fragment share with its Wilson interval, the split by
    category (when a sheet is given), operation counts and the reasons of `other`."""
    missing = _check_against_sheet(labels, sheet)
    n = len(labels.labels)
    if n == 0:
        raise LabelError("no labels")
    counts = Counter(lab.label for lab in labels.labels.values())
    covered = counts[IN_FRAGMENT]
    low, high = wilson(covered, n)
    report: dict[str, Any] = {
        "annotator": labels.annotator, "annotator_kind": labels.kind, "n": n,
        "missing_from_sheet": len(missing), "unlabelled_rows": labels.unlabelled,
        "classes": {c: {"count": counts[c], "share": counts[c] / n} for c in LABELS},
        "coverage": {"count": covered, "share": covered / n, "wilson95": [low, high]},
        "operations": {op: sum(op in lab.operations for lab in labels.labels.values())
                       for op in OPERATIONS},
        "single_pattern": sum(1 for lab in labels.labels.values()
                              if lab.label == IN_FRAGMENT and not lab.operations),
        "other_reasons": {r: sum(lab.other_reason == r for lab in labels.labels.values())
                          for r in OTHER_REASONS},
        "flags": {f: sum(f in lab.flags for lab in labels.labels.values()) for f in FLAGS},
    }
    strict = sum(1 for lab in labels.labels.values() if lab.label == IN_FRAGMENT and not lab.flags)
    report["coverage_without_flagged"] = {"count": strict, "share": strict / n}
    if sheet is not None:
        by_category: dict[str, Counter] = {}
        for qid, lab in labels.labels.items():
            by_category.setdefault(str(sheet[qid]["category"]), Counter())[lab.label] += 1
        report["by_category"] = {k: {c: v[c] for c in LABELS} | {"n": sum(v.values())}
                                 for k, v in sorted(by_category.items())}
    return report


def _confusion(a: Mapping[str, str], b: Mapping[str, str], keys: Iterable[str]) -> dict:
    table: dict[str, Counter] = {c: Counter() for c in LABELS}
    for k in keys:
        table[a[k]][b[k]] += 1
    return {row: {col: table[row][col] for col in LABELS} for row in LABELS}


def _agreement_dict(agreement: Agreement) -> dict:
    return {"n": agreement.n, "observed": agreement.observed, "kappa": agreement.kappa}


def agreement(a: LabelSet, b: LabelSet, restrict_to: set[str] | None = None) -> dict:
    """Cohen's kappa between two label sets on the questions both label (optionally only those in
    `restrict_to`, normally the overlap set of the sheet): over the five classes and in/out."""
    if a.annotator == b.annotator:
        raise LabelError(f"both label sets are by {a.annotator!r}")
    shared = set(a.labels) & set(b.labels)
    if restrict_to is not None:
        missing = {"a": sorted(restrict_to - set(a.labels)),
                   "b": sorted(restrict_to - set(b.labels))}
        shared &= restrict_to
    else:
        missing = {"a": [], "b": []}
    if not shared:
        raise LabelError("the two label sets share no question")
    ca = {k: v for k, v in a.classes().items() if k in shared}
    cb = {k: v for k, v in b.classes().items() if k in shared}
    ba = {k: v for k, v in a.binary().items() if k in shared}
    bb = {k: v for k, v in b.binary().items() if k in shared}
    human = a.kind == "human" and b.kind == "human"
    return {
        "annotators": [a.annotator, b.annotator], "kinds": [a.kind, b.kind],
        "human_agreement": human,
        "classes": _agreement_dict(cohen_kappa(ca, cb)),
        "binary": _agreement_dict(cohen_kappa(ba, bb)),
        "confusion": _confusion(ca, cb, sorted(shared)),
        "missing_from_overlap": {k: len(v) for k, v in missing.items()},
        "disagreements": sorted(k for k in shared if ca[k] != cb[k]),
    }


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render_coverage(report: Mapping[str, Any]) -> str:
    lines = [f"Annotator: {report['annotator']} ({report['annotator_kind']}); "
             f"{report['n']} labelled questions",
             "", "| Class | Count | Share |", "| --- | ---: | ---: |"]
    for c in LABELS:
        row = report["classes"][c]
        lines.append(f"| {c} | {row['count']} | {_pct(row['share'])} |")
    cov = report["coverage"]
    low, high = cov["wilson95"]
    lines += ["", f"Coverage: {cov['count']}/{report['n']} = {_pct(cov['share'])} "
                  f"(Wilson 95% {_pct(low)} to {_pct(high)})",
              f"In-fragment single claim pattern (no further operation): "
              f"{report['single_pattern']}",
              "Operations among in-fragment questions: "
              + ", ".join(f"{k} {v}" for k, v in report["operations"].items()),
              "Reasons of other: " + ", ".join(f"{k} {v}" for k, v in
                                               report["other_reasons"].items()),
              "Flagged in-fragment questions: " + ", ".join(f"{k} {v}" for k, v in
                                                            report["flags"].items()),
              f"Coverage counting flagged questions as out: "
              f"{report['coverage_without_flagged']['count']}/{report['n']} = "
              f"{_pct(report['coverage_without_flagged']['share'])}"]
    if "by_category" in report:
        lines += ["", "| Category | n | " + " | ".join(LABELS) + " |",
                  "| --- | ---: | " + " | ".join("---:" for _ in LABELS) + " |"]
        for cat, row in report["by_category"].items():
            lines.append(f"| {cat} | {row['n']} | " + " | ".join(str(row[c]) for c in LABELS)
                         + " |")
    if report["missing_from_sheet"]:
        lines.append(f"\nUnlabelled sheet questions: {report['missing_from_sheet']}")
    return "\n".join(lines)


def render_agreement(report: Mapping[str, Any]) -> str:
    def fmt(k: float | None) -> str:
        return "undefined" if k is None else f"{k:.3f}"

    cls, binary = report["classes"], report["binary"]
    lines = [f"Annotators: {report['annotators'][0]} ({report['kinds'][0]}) vs "
             f"{report['annotators'][1]} ({report['kinds'][1]})"]
    if not report["human_agreement"]:
        lines.append("NOTE: at least one label set is an agent pre-annotation; this is not "
                     "inter-annotator agreement between humans.")
    lines += [f"Five classes: n={cls['n']}, observed {_pct(cls['observed'])}, "
              f"Cohen's kappa {fmt(cls['kappa'])}",
              f"In/out: n={binary['n']}, observed {_pct(binary['observed'])}, "
              f"Cohen's kappa {fmt(binary['kappa'])}",
              f"Overlap questions without a label: {report['missing_from_overlap']}",
              "", "| a \\ b | " + " | ".join(LABELS) + " |",
              "| --- | " + " | ".join("---:" for _ in LABELS) + " |"]
    for row in LABELS:
        lines.append(f"| {row} | " + " | ".join(str(report["confusion"][row][c])
                                                 for c in LABELS) + " |")
    return "\n".join(lines)
