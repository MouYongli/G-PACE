"""HaluMem-Medium adapter (card: docs/research/benchmarks.md#halumem-medium).

One user (`uuid`) is one history; its sessions in file order are the segments `session_<k>`
(1-based; the source has no session IDs), dated by `start_time`; each dialogue turn is a message
`session_<k>:<turn index>` with its own timestamp. Every question of a session is read at the
last version of that session. Question evidence in the source cites memory points, not turns, so
`evidence_ids` is null and the cited memory points go into gold `metadata`. Memory points and
update labels are write-side gold, written to `memory_points.jsonl` (scoring side only).
`persona_info` and `token_cost` are excluded and counted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from grace.eval.datasets.benchmarks.base import Adapter, HistoryBuilder, Records, SplitSpec
from grace.eval.datasets.benchmarks.base import time_or_none as _time
from grace.eval.datasets.benchmarks.records import Gold, ReadTask, RecordError

SOURCE_FILE = "HaluMem-Medium.jsonl"
MEMORY_POINTS_FILE = "memory_points.jsonl"
ROLES = {"user": "user", "assistant": "agent"}
EXCLUDED_USER_FIELDS = ("persona_info", "token_cost")


def parse_time(raw: str) -> str:
    """`Sep 19, 2025, 08:32:00` -> `2025-09-19T08:32:00`."""
    return datetime.strptime(raw, "%b %d, %Y, %H:%M:%S").isoformat(timespec="seconds")


class HaluMemAdapter(Adapter):
    slug = "halumem-medium"

    def convert(self, source_dirs: Mapping[str, Path], split: SplitSpec,
                options: Mapping[str, Any]) -> Records:
        (version, directory), = source_dirs.items()
        source = directory / SOURCE_FILE
        records = Records(self.slug, split.name)
        records.scoring[MEMORY_POINTS_FILE] = []
        found = set()
        with source.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                user = json.loads(line)
                if not split.has_history(user["uuid"]):
                    continue
                found.add(user["uuid"])
                self._convert_user(records, user, f"{source}:{number}", version)
        missing = sorted((split.histories or set()) - found)
        if missing:
            raise RecordError(f"{source}: split {split.name} names unknown histories {missing}")
        return records

    def _convert_user(self, records: Records, user: dict, where: str, version: str) -> None:
        uid = user["uuid"]
        for key in EXCLUDED_USER_FIELDS:
            if key in user:
                records.exclusions[f"user_field:{key}"] += 1
        builder = HistoryBuilder(self.slug, records.split, uid)
        reads: list[tuple[str, int, int, dict]] = []
        for k, session in enumerate(user["sessions"], start=1):
            segment_id = f"session_{k}"
            raw = session["start_time"]
            builder.segment(segment_id, _time(raw, parse_time), raw)
            for j, turn in enumerate(session["dialogue"]):
                if not turn["content"].strip():
                    records.exclusions["empty_text"] += 1
                    continue
                if turn["role"] not in ROLES:
                    raise RecordError(f"{where}.{segment_id}[{j}]: unknown role {turn['role']!r}")
                builder.message(f"{segment_id}:{j}", turn["role"], ROLES[turn["role"]],
                                turn["content"], _time(turn.get("timestamp"), parse_time),
                                turn.get("timestamp"))
            end = builder.segment_end()
            for point in session["memory_points"]:
                records.scoring[MEMORY_POINTS_FILE].append({
                    "benchmark": self.slug, "split": records.split, "history_id": uid,
                    "segment_id": segment_id, "annotation": version, **point})
            for j, question in enumerate(session.get("questions", [])):
                reads.append((segment_id, j, end, question))
        records.add(builder)
        for segment_id, j, version_at, question in reads:
            task_id = f"{uid}:{segment_id}:q{j}"
            records.read_tasks.append(ReadTask.from_record({
                "benchmark": self.slug, "split": records.split, "history_id": uid,
                "read_id": f"{task_id}@{version_at}", "task_id": task_id, "version": version_at,
                "kind": "question", "question": question["question"], "state_schema": None,
                "asked_at": None, "asked_at_raw": None}))
            records.gold.append(Gold(
                benchmark=self.slug, split=records.split, history_id=uid, task_id=task_id,
                annotation=version, reference=question["answer"], evidence_ids=None,
                evidence_segment_ids=None, evidence_unresolved=(),
                labels={"question_type": question["question_type"],
                        "difficulty": question.get("difficulty")},
                metadata={"evidence_memory_points": question.get("evidence", [])}))
