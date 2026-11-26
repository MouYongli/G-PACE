"""Reference checks for the record contracts in docs/research/contracts.md.

The contract tests run these checks on the synthetic fixtures in tests/fixtures/benchmarks/.
Implementations in src/grace/ (adapters, harness, evaluator) must accept and reject the same
inputs; they may reuse these tests against their own code.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

NULL = type(None)
STR, INT, BOOL, LIST, OBJ = str, int, bool, list, dict
ANY = (str, int, float, bool, list, dict, NULL)
ROLES = {"user", "agent", "peer", "document"}
OUTPUTS = {"answer", "state", "unknown", "invalid"}
TIME = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$")

# Field -> allowed types. Every listed field is required; `metadata` is the only optional field.
HISTORY = {"benchmark": STR, "split": STR, "history_id": STR, "subset": (STR, NULL),
           "n_messages": INT, "segments": LIST}
SEGMENT = {"segment_id": STR, "first_version": INT, "last_version": INT,
           "timestamp": (STR, NULL), "timestamp_raw": (STR, NULL)}
MESSAGE = {"benchmark": STR, "split": STR, "history_id": STR, "version": INT, "message_id": STR,
           "segment_id": (STR, NULL), "speaker": (STR, NULL), "role": STR, "text": STR,
           "timestamp": (STR, NULL), "timestamp_raw": (STR, NULL)}
READ_TASK = {"benchmark": STR, "split": STR, "history_id": STR, "read_id": STR, "task_id": STR,
             "version": INT, "kind": STR, "question": (STR, NULL), "state_schema": (STR, NULL),
             "asked_at": (STR, NULL), "asked_at_raw": (STR, NULL)}
GOLD = {"benchmark": STR, "split": STR, "history_id": STR, "task_id": STR, "annotation": STR,
        "reference": ANY, "evidence_ids": (LIST, NULL), "evidence_segment_ids": (LIST, NULL),
        "evidence_unresolved": LIST, "labels": OBJ}
PREDICTION = {"benchmark": STR, "split": STR, "history_id": STR, "read_id": STR, "task_id": STR,
              "version": INT, "output": STR, "prediction": ANY, "cited_ids": LIST,
              "context_ids": LIST, "further_retrieval": BOOL, "raw_output": (STR, NULL)}


class ContractError(ValueError):
    """A contract violation. `problems` maps a category to the offending keys."""

    def __init__(self, problems: dict[str, list]):
        self.problems = {k: v for k, v in problems.items() if v}
        lines = [f"{cat}: {len(keys)} (e.g. {keys[:5]})" for cat, keys in self.problems.items()]
        super().__init__("; ".join(lines))


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ContractError({"invalid_json": [f"{path}:{number}: {exc}"]}) from exc
    return rows


def _typed(value, types) -> bool:
    types = types if isinstance(types, tuple) else (types,)
    if isinstance(value, bool) and bool not in types:
        return False  # bool is a subclass of int
    return isinstance(value, types)


def check_fields(rows: list[dict], spec: dict, name: str) -> None:
    """Missing, unknown and mistyped fields and empty strings, reported with the record index."""
    problems = defaultdict(list)
    for index, row in enumerate(rows):
        where = f"{name}[{index}]"
        for field, types in spec.items():
            if field not in row:
                problems["missing_field"].append(f"{where}.{field}")
            elif not _typed(row[field], types):
                problems["wrong_type"].append(f"{where}.{field}")
            elif row[field] == "":
                problems["empty_string"].append(f"{where}.{field}")
        for field in row.keys() - spec.keys() - {"metadata"}:
            problems["unknown_field"].append(f"{where}.{field}")
        if "metadata" in row and not isinstance(row["metadata"], dict):
            problems["wrong_type"].append(f"{where}.metadata")
    if problems:
        raise ContractError(problems)


def _single_scope(rows: list[dict], name: str) -> None:
    scopes = {(row["benchmark"], row["split"]) for row in rows}
    if len(scopes) > 1:
        raise ContractError({"mixed_scope": [f"{name}: {sorted(scopes)}"]})


def _duplicates(keys) -> list:
    return [key for key, count in Counter(keys).items() if count > 1]


def _time_fields(rows, fields, name, problems):
    for index, row in enumerate(rows):
        for field in fields:
            value = row.get(field)
            if value is not None and not TIME.match(value):
                problems["bad_time"].append(f"{name}[{index}].{field}={value!r}")


def check_histories(rows: list[dict]) -> dict[str, dict]:
    check_fields(rows, HISTORY, "histories")
    _single_scope(rows, "histories")
    problems = defaultdict(list)
    problems["duplicate_key"] = _duplicates(row["history_id"] for row in rows)
    for row in rows:
        hid, segments = row["history_id"], row["segments"]
        if row["n_messages"] < 1:
            problems["bad_count"].append(hid)
        check_fields(segments, SEGMENT, f"segments[{hid}]")
        _time_fields(segments, ("timestamp",), f"segments[{hid}]", problems)
        segment_ids = [s["segment_id"] for s in segments]
        problems["duplicate_key"] += [(hid, s) for s in _duplicates(segment_ids)]
        expected = 1
        for segment in segments:
            if segment["first_version"] != expected or segment["last_version"] < expected:
                problems["segment_coverage"].append((hid, segment["segment_id"]))
            expected = segment["last_version"] + 1
        if segments and expected != row["n_messages"] + 1:
            problems["segment_coverage"].append((hid, "end"))
    if any(problems.values()):
        raise ContractError(problems)
    return {row["history_id"]: row for row in rows}


def check_messages(histories: dict[str, dict], rows: list[dict]) -> dict[str, dict[str, dict]]:
    """Return history_id -> message_id -> message, after checking versions and segments."""
    check_fields(rows, MESSAGE, "messages")
    _single_scope(rows, "messages")
    problems = defaultdict(list)
    _time_fields(rows, ("timestamp",), "messages", problems)
    by_history = defaultdict(list)
    for row in rows:
        if row["history_id"] not in histories:
            problems["unknown_history"].append(row["history_id"])
        if row["role"] not in ROLES:
            problems["bad_value"].append((row["history_id"], row["message_id"], row["role"]))
        by_history[row["history_id"]].append(row)
    result = {}
    for hid, history in histories.items():
        messages = by_history.get(hid, [])
        ids = [m["message_id"] for m in messages]
        problems["duplicate_key"] += [(hid, m) for m in _duplicates(ids)]
        versions = [m["version"] for m in messages]
        problems["duplicate_version"] += [(hid, v) for v in _duplicates(versions)]
        versions = sorted(m["version"] for m in messages)
        if versions != list(range(1, history["n_messages"] + 1)):
            problems["version_gap"].append(hid)
        ranges = {s["segment_id"]: s for s in history["segments"]}
        for m in messages:
            segment = ranges.get(m["segment_id"])
            if ranges and (segment is None or not
                           segment["first_version"] <= m["version"] <= segment["last_version"]):
                problems["segment_mismatch"].append((hid, m["message_id"]))
            if not ranges and m["segment_id"] is not None:
                problems["segment_mismatch"].append((hid, m["message_id"]))
        result[hid] = {m["message_id"]: m for m in messages}
    if any(problems.values()):
        raise ContractError(problems)
    return result


def check_read_tasks(histories: dict[str, dict], rows: list[dict]) -> dict[str, dict]:
    check_fields(rows, READ_TASK, "read_tasks")
    _single_scope(rows, "read_tasks")
    problems = defaultdict(list)
    _time_fields(rows, ("asked_at",), "read_tasks", problems)
    problems["duplicate_key"] = _duplicates(row["read_id"] for row in rows)
    for row in rows:
        rid, history = row["read_id"], histories.get(row["history_id"])
        if history is None:
            problems["unknown_history"].append(rid)
        elif not 1 <= row["version"] <= history["n_messages"]:
            problems["snapshot_mismatch"].append(rid)
        if rid != f"{row['task_id']}@{row['version']}":
            problems["bad_read_id"].append(rid)
        if row["kind"] == "question":
            ok = isinstance(row["question"], str) and row["state_schema"] is None
        elif row["kind"] == "state":
            ok = row["question"] is None and isinstance(row["state_schema"], str)
        else:
            ok = False
        if not ok:
            problems["bad_value"].append(rid)
    if any(problems.values()):
        raise ContractError(problems)
    return {row["read_id"]: row for row in rows}


def check_gold(histories, messages, schedules: list[dict[str, dict]], rows: list[dict]) -> dict:
    """Return (annotation, task_id) -> gold record; `schedules` are all read-task files."""
    check_fields(rows, GOLD, "gold")
    _single_scope(rows, "gold")
    problems = defaultdict(list)
    problems["duplicate_key"] = _duplicates((row["annotation"], row["task_id"]) for row in rows)
    read_versions = defaultdict(list)
    for schedule in schedules:
        for task in schedule.values():
            read_versions[task["task_id"]].append(task["version"])
    for row in rows:
        hid, key = row["history_id"], (row["annotation"], row["task_id"])
        if hid not in histories:
            problems["unknown_history"].append(key)
            continue
        known = messages[hid]
        segments = {s["segment_id"] for s in histories[hid]["segments"]}
        for evidence in row["evidence_ids"] or []:
            if evidence not in known:
                problems["unknown_evidence"].append((key, evidence))
            elif any(known[evidence]["version"] > v for v in read_versions[row["task_id"]]):
                problems["snapshot_mismatch"].append((key, evidence))
        for evidence in row["evidence_segment_ids"] or []:
            if evidence not in segments:
                problems["unknown_evidence"].append((key, evidence))
    if any(problems.values()):
        raise ContractError(problems)
    return {(row["annotation"], row["task_id"]): row for row in rows}


def align_predictions(read_tasks: dict[str, dict], messages, gold, rows: list[dict]) -> dict:
    """Evaluator alignment: abort on any problem; return read_id -> prediction."""
    check_fields(rows, PREDICTION, "predictions")
    _single_scope(rows, "predictions")
    keys = [row["read_id"] for row in rows]
    problems = defaultdict(list)
    problems["duplicate_key"] = _duplicates(keys)
    problems["missing_key"] = sorted(read_tasks.keys() - set(keys))
    problems["extra_key"] = sorted(set(keys) - read_tasks.keys())
    evidence_after = {
        task_id: max((messages[g["history_id"]][e]["version"] for e in g["evidence_ids"] or []),
                     default=0)
        for (_, task_id), g in gold.items()
    }
    for row in rows:
        rid, task = row["read_id"], read_tasks.get(row["read_id"])
        if row["output"] not in OUTPUTS:
            problems["bad_value"].append(rid)
        elif (row["prediction"] is None) != (row["output"] in {"unknown", "invalid"}):
            problems["bad_value"].append(rid)
        if task is None:
            continue
        copied = ("benchmark", "split", "history_id", "task_id", "version")
        if any(row[f] != task[f] for f in copied):
            problems["snapshot_mismatch"].append(rid)
            continue
        visible = messages.get(task["history_id"], {})
        for cited in row["cited_ids"] + row["context_ids"]:
            if cited not in visible or visible[cited]["version"] > task["version"]:
                problems["snapshot_mismatch"].append((rid, cited))
        if evidence_after.get(task["task_id"], 0) > task["version"]:
            problems["snapshot_mismatch"].append((rid, "gold evidence"))
    if any(problems.values()):
        raise ContractError(problems)
    return dict(zip(keys, rows, strict=True))


def load_benchmark(directory: Path) -> dict:
    """Check every record file of one fixture benchmark and return the parsed records."""
    histories = check_histories(read_jsonl(directory / "histories.jsonl"))
    messages = check_messages(histories, read_jsonl(directory / "messages.jsonl"))
    schedules = {
        path.name: check_read_tasks(histories, read_jsonl(path))
        for path in sorted(directory.glob("read_tasks*.jsonl"))
    }
    gold = check_gold(histories, messages, list(schedules.values()),
                      read_jsonl(directory / "gold.jsonl"))
    return {"histories": histories, "messages": messages, "schedules": schedules, "gold": gold}
