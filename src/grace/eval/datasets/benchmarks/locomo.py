"""LoCoMo adapter (card: docs/research/benchmarks.md#locomo).

One `sample_id` is one history; `session_<k>` lists are its segments, dated by
`session_<k>_date_time`; each turn is a message with its `dia_id`, both speakers `peer`.
Categories 1 to 4 are read at the end of the history; category 5 (adversarial) is excluded and
counted. Image fields (`img_url`, `blip_caption`, `query`, `re-download`) and the generated
summaries (`event_summary`, `session_summary`, `observation`) are excluded and counted.
The evidence-anchored streaming schedule and v(q) belong to T007.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from grace.eval.datasets.benchmarks.base import Adapter, HistoryBuilder, Records, SplitSpec
from grace.eval.datasets.benchmarks.base import time_or_none as _time
from grace.eval.datasets.benchmarks.records import Gold, ReadTask, RecordError

SOURCE_FILE = "locomo10.json"
IMAGE_FIELDS = ("img_url", "blip_caption", "query", "re-download")
SUMMARY_FIELDS = ("event_summary", "session_summary", "observation")
TURN_FIELDS = {"speaker", "dia_id", "text", *IMAGE_FIELDS}
SESSION = re.compile(r"session_(\d+)")
SESSION_DATE = re.compile(r"session_(\d+)_date_time")


def parse_time(raw: str) -> str:
    """`1:56 pm on 8 May, 2023` -> `2023-05-08T13:56` (minute precision, as in the source)."""
    return datetime.strptime(raw, "%I:%M %p on %d %B, %Y").isoformat(timespec="minutes")


class LoCoMoAdapter(Adapter):
    slug = "locomo"

    def convert(self, source_dirs: Mapping[str, Path], split: SplitSpec,
                options: Mapping[str, Any]) -> Records:
        (version, directory), = source_dirs.items()
        source = directory / SOURCE_FILE
        samples = json.loads(source.read_text(encoding="utf-8"))
        excluded_categories = {int(c) for c in options.get("exclude_categories", [5])}
        records = Records(self.slug, split.name)
        found = set()
        for index, sample in enumerate(samples):
            sid = sample["sample_id"]
            if not split.has_history(sid):
                continue
            found.add(sid)
            self._convert_sample(records, sample, f"{source}[{index}]", version,
                                 excluded_categories)
        missing = sorted((split.histories or set()) - found)
        if missing:
            raise RecordError(f"{source}: split {split.name} names unknown histories {missing}")
        return records

    def _convert_sample(self, records: Records, sample: dict, where: str, version: str,
                        excluded_categories: set[int]) -> None:
        sid = sample["sample_id"]
        conversation = sample["conversation"]
        for key in SUMMARY_FIELDS:
            if sample.get(key):
                records.exclusions[f"summary:{key}"] += 1
        sessions = sorted(int(m.group(1)) for k in conversation
                          if (m := SESSION.fullmatch(k)))
        dated = {int(m.group(1)) for k in conversation if (m := SESSION_DATE.fullmatch(k))}
        records.exclusions["session_date_without_session"] += len(dated - set(sessions))
        unknown = sorted(k for k in conversation if not SESSION.fullmatch(k)
                         and not SESSION_DATE.fullmatch(k) and k not in ("speaker_a", "speaker_b"))
        if unknown:
            raise RecordError(f"{where}.conversation: unknown keys {unknown}")
        builder = HistoryBuilder(self.slug, records.split, sid)
        for k in sessions:
            turns = conversation[f"session_{k}"]
            if not turns:
                records.exclusions["empty_session"] += 1
                continue
            raw = conversation.get(f"session_{k}_date_time")
            builder.segment(f"session_{k}", _time(raw, parse_time), raw)
            for number, turn in enumerate(turns):
                extra = sorted(set(turn) - TURN_FIELDS)
                if extra:
                    raise RecordError(f"{where}.session_{k}[{number}]: unknown keys {extra}")
                if any(f in turn for f in IMAGE_FIELDS):
                    records.exclusions["image_fields_removed_from_turn"] += 1
                text = turn["text"]
                if not text.strip():
                    records.exclusions["empty_text"] += 1
                    continue
                builder.message(turn["dia_id"], turn["speaker"], "peer", text)
        history = records.add(builder)
        turn_ids = {m.message_id for m in builder.messages}
        for index, qa in enumerate(sample["qa"]):
            category = qa["category"]
            if category in excluded_categories:
                records.exclusions[f"category_{category}"] += 1
                continue
            task_id = f"{sid}:q{index}"
            records.read_tasks.append(ReadTask.from_record({
                "benchmark": self.slug, "split": records.split, "history_id": sid,
                "read_id": f"{task_id}@{history.n_messages}", "task_id": task_id,
                "version": history.n_messages, "kind": "question", "question": qa["question"],
                "state_schema": None, "asked_at": None, "asked_at_raw": None}))
            evidence = [str(e) for e in qa["evidence"]]
            resolved = [e for e in evidence if e in turn_ids]
            unresolved = [e for e in evidence if e not in turn_ids]
            status = "missing" if not evidence else "unresolved" if unresolved else "complete"
            answer = qa["answer"]
            records.gold.append(Gold(
                benchmark=self.slug, split=records.split, history_id=sid, task_id=task_id,
                annotation=version, reference=answer if isinstance(answer, str) else str(answer),
                evidence_ids=tuple(resolved), evidence_segment_ids=None,
                evidence_unresolved=tuple(unresolved), labels={"category": category},
                metadata={"evidence_status": status}))
            if status != "complete":
                records.notes.setdefault("evidence_incomplete", []).append(task_id)
