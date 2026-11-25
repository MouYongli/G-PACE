"""The metrics.json record of the Evaluation section and the denominator rules.

Per read a scorer yields a value in [0, 1] (accuracy, F1, JGA) or `None` when the read is not
scored by that metric. `aggregate` applies the registered invalid-output policy:

- `count_as_wrong`: an `invalid` prediction scores 0 and stays in the denominator;
- `exclude_and_report`: it leaves the denominator and is counted in `n_invalid`.

`unknown` predictions are scored by the scorer's abstention rule and always stay in the
denominator. A judgement whose own output was unparsable (`verdict: invalid`) leaves the
denominator and is counted in `n_judge_invalid`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

POLICIES = ("count_as_wrong", "exclude_and_report")
DIRECTIONS = ("higher", "lower")


@dataclass(frozen=True)
class MetricRecord:
    benchmark: str
    split: str
    schedule: str  # read-task file the run used, e.g. read_tasks.jsonl
    annotation: str
    metric: str
    direction: str
    stratum: str | None  # "<label>=<value>", or None for the whole population
    seed: int
    value: float | None  # None when the denominator is empty
    n_total: int  # reads in the registered population
    n_scored: int  # reads that entered the denominator
    n_invalid: int  # `invalid` predictions in the population
    n_unknown: int  # `unknown` predictions in the population
    n_judge_invalid: int  # reads excluded because the judge output was unparsable
    invalid_policy: str
    scorer: str  # registered scorer name in configs/common/scorers.yaml
    evaluator_version: str  # full code SHA of the scoring run

    def __post_init__(self):
        if self.invalid_policy not in POLICIES:
            raise ValueError(f"unknown invalid_policy {self.invalid_policy!r}")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"unknown direction {self.direction!r}")
        if not 0 <= self.n_scored <= self.n_total:
            raise ValueError("0 <= n_scored <= n_total violated")
        if (self.value is None) != (self.n_scored == 0):
            raise ValueError("value is null exactly when nothing was scored")


@dataclass(frozen=True)
class Tally:
    value: float | None
    n_total: int
    n_scored: int
    n_invalid: int
    n_unknown: int
    n_judge_invalid: int


def aggregate(values: Mapping[str, float | None], outputs: Mapping[str, str], policy: str,
              judge_invalid: frozenset[str] = frozenset()) -> Tally:
    """Mean over the denominator. `values` holds every read of the population; a value of None
    for a non-invalid read that is not judge-invalid is an error (a scorer must score it)."""
    if policy not in POLICIES:
        raise ValueError(f"unknown invalid_policy {policy!r}")
    total, scored, n_invalid, n_unknown, n_judge = 0.0, 0, 0, 0, 0
    for read_id, value in values.items():
        output = outputs[read_id]
        n_invalid += output == "invalid"
        n_unknown += output == "unknown"
        if output == "invalid":
            if policy == "count_as_wrong":
                scored += 1
            continue
        if read_id in judge_invalid:
            n_judge += 1
            continue
        if value is None or not 0.0 <= value <= 1.0:
            raise ValueError(f"read {read_id}: scorer returned {value!r}")
        total += value
        scored += 1
    return Tally(total / scored if scored else None, len(values), scored, n_invalid, n_unknown,
                 n_judge)


def write_metrics(path: Path, records: list[MetricRecord]) -> None:
    """Write metrics.json exclusively (an existing file is never overwritten)."""
    if not records:
        raise ValueError("no metric records to write")
    payload = {"metrics": [asdict(r) for r in records]}
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
