"""Align predictions with read tasks and gold; the evaluator obligations of the Prediction section.

Scoring aborts on any of: an unparsable line, an empty prediction file, duplicate, missing or extra
`read_id`s, missing, unknown or mistyped fields, more than one benchmark or split, a prediction of
another benchmark or split than its read tasks, an output that does not match its prediction, and a
snapshot mismatch (`history_id`, `task_id` or `version` differs from the read task; a cited or
context ID names a message after `version` or no message; gold evidence lies after `version`).
The error reports the count per category and up to five example keys each.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

OUTPUTS = ("answer", "state", "unknown", "invalid")
_NULL = type(None)
_ANY = (str, int, float, bool, list, dict, _NULL)
PREDICTION_FIELDS = {
    "benchmark": str, "split": str, "history_id": str, "read_id": str, "task_id": str,
    "version": int, "output": str, "prediction": _ANY, "cited_ids": list, "context_ids": list,
    "further_retrieval": bool, "raw_output": (str, _NULL),
}


class EvaluationError(ValueError):
    """Scoring aborted. `problems` maps a category to the offending keys."""

    def __init__(self, problems: dict[str, list]):
        self.problems = {k: list(v) for k, v in problems.items() if v}
        lines = [f"{cat}: {len(keys)} (e.g. {keys[:5]})" for cat, keys in self.problems.items()]
        super().__init__("; ".join(lines))


def read_jsonl(path: Path) -> list[dict]:
    """Read JSON Lines; any unparsable or non-object line aborts, naming the line."""
    rows, bad = [], []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad.append(f"{path}:{number}")
            continue
        if not isinstance(row, dict):
            bad.append(f"{path}:{number}")
            continue
        rows.append(row)
    if bad:
        raise EvaluationError({"unparsable_line": bad})
    return rows


def _typed(value, types) -> bool:
    types = types if isinstance(types, tuple) else (types,)
    if isinstance(value, bool) and bool not in types:
        return False
    return isinstance(value, types)


@dataclass(frozen=True)
class Aligned:
    read_task: dict
    prediction: dict

    @property
    def read_id(self) -> str:
        return self.read_task["read_id"]

    @property
    def output(self) -> str:
        return self.prediction["output"]


def _field_problems(rows: list[dict], problems: dict) -> None:
    for index, row in enumerate(rows):
        key = row.get("read_id", f"predictions[{index}]")
        for name, types in PREDICTION_FIELDS.items():
            if name not in row:
                problems["missing_field"].append(f"{key}.{name}")
            elif not _typed(row[name], types):
                problems["wrong_type"].append(f"{key}.{name}")
            elif row[name] == "":
                problems["empty_string"].append(f"{key}.{name}")
        for name in row.keys() - PREDICTION_FIELDS.keys() - {"metadata"}:
            problems["unknown_field"].append(f"{key}.{name}")


def align(read_tasks: list[dict], messages: Iterable[dict], gold: Iterable[dict],
          predictions: list[dict]) -> dict[str, Aligned]:
    """Return read_id -> Aligned in read-task order, or raise EvaluationError."""
    problems: dict[str, list] = defaultdict(list)
    if not predictions:
        problems["empty_file"].append("predictions")
    _field_problems(predictions, problems)
    if problems.get("missing_field") or problems.get("wrong_type"):
        raise EvaluationError(problems)
    scopes = {(r["benchmark"], r["split"]) for r in predictions}
    task_scopes = {(t["benchmark"], t["split"]) for t in read_tasks}
    if len(scopes) > 1:
        problems["mixed_scope"].append(sorted(scopes))
    if len(task_scopes) > 1:
        problems["mixed_scope"].append(sorted(task_scopes))
    elif scopes and task_scopes and scopes != task_scopes:
        problems["scope_mismatch"].append((sorted(scopes), sorted(task_scopes)))

    tasks = {t["read_id"]: t for t in read_tasks}
    keys = [row["read_id"] for row in predictions]
    problems["duplicate_key"] = [k for k, n in Counter(keys).items() if n > 1]
    problems["missing_key"] = sorted(tasks.keys() - set(keys))
    problems["extra_key"] = sorted(set(keys) - tasks.keys())

    versions: dict[str, dict[str, int]] = defaultdict(dict)
    for message in messages:
        versions[message["history_id"]][message["message_id"]] = message["version"]
    evidence_at: dict[str, int] = defaultdict(int)
    for row in gold:
        for evidence in row.get("evidence_ids") or []:
            version = versions.get(row["history_id"], {}).get(evidence)
            if version is not None:
                evidence_at[row["task_id"]] = max(evidence_at[row["task_id"]], version)

    for row in predictions:
        rid = row["read_id"]
        if row["output"] not in OUTPUTS:
            problems["bad_value"].append(rid)
        elif (row["prediction"] is None) != (row["output"] in ("unknown", "invalid")):
            problems["bad_value"].append(rid)
        task = tasks.get(rid)
        if task is None:
            continue
        if any(row[f] != task[f] for f in ("history_id", "task_id", "version")):
            problems["snapshot_mismatch"].append(rid)
            continue
        visible = versions.get(task["history_id"], {})
        for cited in row["cited_ids"] + row["context_ids"]:
            if not isinstance(cited, str) or visible.get(cited, task["version"] + 1) > \
                    task["version"]:
                problems["snapshot_mismatch"].append(f"{rid}:{cited}")
        if evidence_at.get(task["task_id"], 0) > task["version"]:
            problems["snapshot_mismatch"].append(f"{rid}:gold evidence")
    if any(problems.values()):
        raise EvaluationError(problems)
    by_key = {row["read_id"]: row for row in predictions}
    return {rid: Aligned(task, by_key[rid]) for rid, task in tasks.items()}


def gold_index(gold: Iterable[dict], annotation: str) -> dict[str, dict]:
    """task_id -> gold record of one annotation (an annotation MAY cover only some tasks)."""
    index: dict[str, dict] = {}
    duplicates = []
    for row in gold:
        if row["annotation"] != annotation:
            continue
        if row["task_id"] in index:
            duplicates.append(row["task_id"])
        index[row["task_id"]] = row
    if duplicates:
        raise EvaluationError({"duplicate_gold": duplicates})
    if not index:
        raise EvaluationError({"unknown_annotation": [annotation]})
    return index
