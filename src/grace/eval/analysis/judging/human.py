"""Agreement of a judge with human labels (T004 acceptance; protocol in the Evaluation section).

Human labels are JSON Lines, one record per read and annotator:
`read_id`, `task_id`, `annotation`, `annotator`, `verdict` (`correct` or `incorrect`). The
adjudicated label of a read has `annotator: adjudicated`. Negative controls, judge reruns and the
agreement between the blind and the official judge are calibration (T035).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

LABEL_FIELDS = ("read_id", "task_id", "annotation", "annotator", "verdict")
ADJUDICATED = "adjudicated"


@dataclass(frozen=True)
class Agreement:
    n: int
    observed: float  # share of reads with the same verdict
    kappa: float | None  # Cohen's kappa; None when chance agreement is 1


def read_labels(path: Path) -> dict[str, dict[str, str]]:
    """annotator -> read_id -> verdict; malformed or duplicate records abort."""
    labels: dict[str, dict[str, str]] = defaultdict(dict)
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        row = json.loads(line)
        if set(row) != set(LABEL_FIELDS):
            raise ValueError(f"{path}:{number}: fields must be exactly {LABEL_FIELDS}")
        if row["verdict"] not in ("correct", "incorrect"):
            raise ValueError(f"{path}:{number}: verdict must be correct or incorrect")
        if row["read_id"] in labels[row["annotator"]]:
            raise ValueError(f"{path}:{number}: duplicate label of {row['read_id']}")
        labels[row["annotator"]][row["read_id"]] = row["verdict"]
    return dict(labels)


def cohen_kappa(a: Mapping[str, str], b: Mapping[str, str]) -> Agreement:
    """Agreement on the reads both label sets cover; requires a non-empty overlap."""
    shared = sorted(a.keys() & b.keys())
    if not shared:
        raise ValueError("the two label sets share no read")
    n = len(shared)
    observed = sum(a[k] == b[k] for k in shared) / n
    classes = {a[k] for k in shared} | {b[k] for k in shared}
    expected = sum((sum(a[k] == c for k in shared) / n) * (sum(b[k] == c for k in shared) / n)
                   for c in classes)
    kappa = None if expected == 1.0 else (observed - expected) / (1.0 - expected)
    return Agreement(n=n, observed=observed, kappa=kappa)


def judge_agreement(verdicts: Mapping[str, str], labels: Mapping[str, Mapping[str, str]]) -> dict:
    """Judge vs adjudicated labels, and between the human annotators.

    Judge verdicts `invalid` are reported, not scored: they enter neither side of the kappa.
    """
    if ADJUDICATED not in labels:
        raise ValueError("no adjudicated labels")
    valid = {k: v for k, v in verdicts.items() if v != "invalid"}
    gold = labels[ADJUDICATED]
    missing = sorted(gold.keys() - verdicts.keys())
    if missing:
        raise ValueError(f"{len(missing)} labelled reads have no judgement, e.g. {missing[:5]}")
    annotators = sorted(k for k in labels if k != ADJUDICATED)
    report = {"judge_vs_adjudicated": cohen_kappa(valid, gold),
              "judge_invalid": sum(1 for k in gold if verdicts[k] == "invalid"),
              "annotators": annotators}
    if len(annotators) >= 2:
        report["between_annotators"] = cohen_kappa(labels[annotators[0]], labels[annotators[1]])
    return report
