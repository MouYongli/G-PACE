"""LongMemEval S (cleaned) adapter (card: docs/research/benchmarks.md#longmemeval-s).

Each `question_id` owns one history: its haystack sessions in file order are the segments, dated
by `haystack_dates`; each turn is a message `<session_id>:<turn index>`. One question per history
is read at the end, with `question_date` as `asked_at`. `has_answer` and `answer_session_ids` are
masked in the visible records and become `evidence_ids` and `evidence_segment_ids` in gold.

A session ID that occurs more than once in one history (13 histories in 98d7416; the repeated
sessions are identical copies at another date) keeps its ID on the first occurrence and gets
`<session_id>#<n>` on the n-th. Turns with empty text are excluded and counted.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from grace.eval.datasets.benchmarks.base import Adapter, HistoryBuilder, Records, SplitSpec
from grace.eval.datasets.benchmarks.base import time_or_none as _time
from grace.eval.datasets.benchmarks.records import Gold, ReadTask, RecordError

SOURCE_FILE = "longmemeval_s_cleaned.json"
ROLES = {"user": "user", "assistant": "agent"}


def parse_time(raw: str) -> str:
    """`2023/05/20 (Sat) 02:21` -> `2023-05-20T02:21`."""
    return datetime.strptime(raw, "%Y/%m/%d (%a) %H:%M").isoformat(timespec="minutes")


def is_abstention(question_id: str) -> bool:
    return question_id.endswith("_abs")


class LongMemEvalAdapter(Adapter):
    slug = "longmemeval-s"

    def convert(self, source_dirs: Mapping[str, Path], split: SplitSpec,
                options: Mapping[str, Any]) -> Records:
        (version, directory), = source_dirs.items()
        source = directory / options.get("source_file", SOURCE_FILE)
        if options.get("session_order", "source") != "source":
            raise RecordError("longmemeval-s: only session_order 'source' is implemented")
        items = json.loads(source.read_text(encoding="utf-8"))
        records = Records(self.slug, split.name)
        found = set()
        for index, item in enumerate(items):
            qid = item["question_id"]
            if not split.has_history(qid):
                continue
            found.add(qid)
            self._convert_item(records, item, f"{source}[{index}]", version)
        missing = sorted((split.histories or set()) - found)
        if missing:
            raise RecordError(f"{source}: split {split.name} names unknown histories {missing}")
        return records

    def _convert_item(self, records: Records, item: dict, where: str, version: str) -> None:
        qid = item["question_id"]
        ids, dates, sessions = (item["haystack_session_ids"], item["haystack_dates"],
                                item["haystack_sessions"])
        if not len(ids) == len(dates) == len(sessions):
            raise RecordError(f"{where}: haystack ids, dates and sessions differ in length")
        builder = HistoryBuilder(self.slug, records.split, qid)
        seen: Counter = Counter()
        evidence: list[str] = []
        first_segment: dict[str, str] = {}
        for session_id, raw, turns in zip(ids, dates, sessions, strict=True):
            seen[session_id] += 1
            segment_id = session_id if seen[session_id] == 1 else f"{session_id}#{seen[session_id]}"
            if seen[session_id] > 1:
                records.notes["renamed_duplicate_sessions"] = (
                    records.notes.get("renamed_duplicate_sessions", 0) + 1)
            kept = [(j, t) for j, t in enumerate(turns) if t["content"].strip()]
            records.exclusions["empty_text"] += len(turns) - len(kept)
            if not kept:
                records.exclusions["empty_session"] += 1
                continue
            first_segment.setdefault(session_id, segment_id)
            builder.segment(segment_id, _time(raw, parse_time), raw)
            for j, turn in kept:
                extra = sorted(set(turn) - {"role", "content", "has_answer"})
                if extra:
                    raise RecordError(f"{where}.{segment_id}[{j}]: unknown keys {extra}")
                message_id = f"{segment_id}:{j}"
                if turn.get("has_answer"):
                    evidence.append(message_id)
                builder.message(message_id, turn["role"], ROLES[turn["role"]], turn["content"])
        history = records.add(builder)
        raw_date = item["question_date"]
        records.read_tasks.append(ReadTask.from_record({
            "benchmark": self.slug, "split": records.split, "history_id": qid,
            "read_id": f"{qid}@{history.n_messages}", "task_id": qid,
            "version": history.n_messages, "kind": "question", "question": item["question"],
            "state_schema": None, "asked_at": _time(raw_date, parse_time),
            "asked_at_raw": raw_date}))
        answer_sessions = [str(s) for s in item["answer_session_ids"]]
        unknown = [s for s in answer_sessions if s not in first_segment]
        if unknown:
            raise RecordError(f"{where}.answer_session_ids: unknown sessions {unknown}")
        answer = item["answer"]
        records.gold.append(Gold(
            benchmark=self.slug, split=records.split, history_id=qid, task_id=qid,
            annotation=version, reference=answer if isinstance(answer, str) else str(answer),
            evidence_ids=tuple(evidence),
            evidence_segment_ids=tuple(first_segment[s] for s in answer_sessions),
            evidence_unresolved=(),
            labels={"question_type": item["question_type"], "abstention": is_abstention(qid)}))
