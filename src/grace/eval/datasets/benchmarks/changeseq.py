"""Controlled change-sequence adapter (card: docs/research/benchmarks.md#change-seq; design
docs/research/change-sequences.md, sections 5 and 9; contracts.md, "Benchmark mapping").

Reads a dataset written by `eval/datasets/changeseq/build.py` (`dataset.json`, one directory per
sequence) from files only; it does not import the generator.

- One sequence is one history (`history_id` = sequence ID); its episodes are the segments, dated by
  the episode date; messages keep the generator message ID, speaker `user` / `assistant` with roles
  `user` / `agent`, and the episode date as their timestamp.
- Every question of every read schedule is a `question` read task at its read version, with one
  `task_id` per question: `<sequence>:<schedule>:r<j>:q<n>`. The sequence's primary schedule is
  `read_tasks.jsonl`; every other schedule `<name>` is `read_tasks.<name>.jsonl`. A schedule's
  questions are in the file only for the sequences that have that schedule.
- Gold (`annotation` = `generator`, or the adapter option `annotation`): the reference is the
  surface answer set (`answer_text`); evidence IDs are the gold evidence messages; `labels` carry
  the question type, the question-level change-type label (`change_type`, `change_types`), the
  expected abstention, `premise_outdated`, the view template, and `pair_id` / `pair_role` /
  `pair_kind` of known-then and seen-from-now questions; `metadata` keeps the binding, the
  canonical answer, witnesses, outdated values, (tau, kappa) and the schedule.

The gold claim graph, `labels.jsonl` (per-message invalidation ground truth) and the reference
values stay in the sequence directories as write-side gold (scoring side only).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from grace.eval.datasets.benchmarks.base import (
    NATIVE_SCHEDULE,
    Adapter,
    HistoryBuilder,
    Records,
    SplitSpec,
)
from grace.eval.datasets.benchmarks.records import Gold, ReadTask, RecordError

DATASET_FILE = "dataset.json"
ROLES = {"user": "user", "assistant": "agent"}
LABEL_FIELDS = ("change_type", "change_types", "expected_abstention", "premise_outdated",
                "pair_id", "pair_role", "pair_kind", "template")
METADATA_FIELDS = ("binding_id", "answer", "witnesses", "outdated_values", "outdated_text",
                   "tau", "kappa", "schedule", "read_index")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise RecordError(f"missing {path}")
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RecordError(f"{path}:{number}: {exc}") from exc
    return rows


class ChangeSeqAdapter(Adapter):
    slug = "change-seq"

    def convert(self, source_dirs: Mapping[str, Path], split: SplitSpec,
                options: Mapping[str, Any]) -> Records:
        (_, directory), = source_dirs.items()
        dataset = json.loads((directory / DATASET_FILE).read_text(encoding="utf-8"))
        annotation = str(options.get("annotation", "generator"))
        records = Records(self.slug, split.name)
        found = set()
        for entry in dataset["sequences"]:
            if not split.has_history(entry["sequence_id"]):
                continue
            found.add(entry["sequence_id"])
            self._convert(records, directory / entry["path"], entry, annotation)
        missing = sorted((split.histories or set()) - found)
        if missing:
            raise RecordError(f"{directory / DATASET_FILE}: split {split.name} names unknown "
                              f"histories {missing}")
        return records

    def _convert(self, records: Records, seq_dir: Path, entry: Mapping[str, Any],
                 annotation: str) -> None:
        sid = entry["sequence_id"]
        meta = json.loads((seq_dir / "meta.json").read_text(encoding="utf-8"))
        if meta["sequence_id"] != sid:
            raise RecordError(f"{seq_dir}/meta.json: sequence_id {meta['sequence_id']!r} "
                              f"!= {sid!r}")
        builder = HistoryBuilder(self.slug, records.split, sid,
                                 metadata={"family": meta["family"]})
        episode = None
        for number, m in enumerate(_jsonl(seq_dir / "messages.jsonl"), start=1):
            if m["version"] != number:
                raise RecordError(f"{seq_dir}/messages.jsonl:{number}: version {m['version']}")
            if m["speaker"] not in ROLES:
                raise RecordError(f"{seq_dir}/messages.jsonl:{number}: speaker {m['speaker']!r}")
            if m["episode"] != episode:
                episode = m["episode"]
                builder.segment(episode, m["timestamp"], m["timestamp"])
            builder.message(m["message_id"], m["speaker"], ROLES[m["speaker"]], m["text"],
                            m["timestamp"], m["timestamp"])
        records.add(builder)
        primary = meta["primary_schedule"]
        for path in sorted((seq_dir / "schedules").glob("*.jsonl")):
            name = path.stem
            file = NATIVE_SCHEDULE if name == primary else f"read_tasks.{name}.jsonl"
            tasks = records.schedules.setdefault(file, [])
            for q in _jsonl(path):
                task_id = f"{sid}:{q['question_id']}"
                version = q["read_version"]
                tasks.append(ReadTask.from_record({
                    "benchmark": self.slug, "split": records.split, "history_id": sid,
                    "read_id": f"{task_id}@{version}", "task_id": task_id, "version": version,
                    "kind": "question", "question": q["text"], "state_schema": None,
                    "asked_at": q["asked_at"], "asked_at_raw": q["asked_at"]}))
                records.gold.append(Gold(
                    benchmark=self.slug, split=records.split, history_id=sid, task_id=task_id,
                    annotation=annotation, reference=q["answer_text"],
                    evidence_ids=tuple(q["evidence"]), evidence_segment_ids=None,
                    evidence_unresolved=(),
                    labels={"question_type": q["type"], **{k: q[k] for k in LABEL_FIELDS}},
                    metadata={k: q[k] for k in METADATA_FIELDS}))
