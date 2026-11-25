"""Load the visible benchmark records a system stage reads (contracts.md, "Benchmark records").

Interim loader: the single entry point for loading splits, with the held-out guard, is
`eval/datasets/benchmarks/splits.py` (T002). Until it exists this loader reads converted records
from a directory and is deliberately stricter: it accepts only the `fixture` split and splits whose
name starts with `dev`, and it never opens `gold.jsonl`.

Only the three visible files are read: `histories.jsonl`, `messages.jsonl` and one read-task file
(`read_tasks.jsonl`, or `read_tasks.<schedule>.jsonl`).
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from grace.context import api

VISIBLE = ("histories.jsonl", "messages.jsonl")


def schedule_file(schedule: str | None) -> str:
    return "read_tasks.jsonl" if schedule in (None, "native") else f"read_tasks.{schedule}.jsonl"


def allowed_split(split: str) -> bool:
    return split == "fixture" or split.startswith("dev")


@dataclass(frozen=True)
class HistoryInputs:
    history: api.HistoryInfo
    messages: tuple[api.Message, ...]
    reads: tuple[api.ReadTask, ...]


@dataclass(frozen=True)
class Inputs:
    benchmark: str
    split: str
    directory: Path
    files: tuple[str, ...]
    histories: tuple[HistoryInputs, ...]

    @property
    def n_reads(self) -> int:
        return sum(len(h.reads) for h in self.histories)

    def manifest_sha256(self) -> str:
        """Checksum of the files read, in the sha256sum layout of `resources_sha256`."""
        lines = [f"{hashlib.sha256((self.directory / n).read_bytes()).hexdigest()}  {n}\n"
                 for n in sorted(self.files)]
        return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _rows(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
    return rows


def load(directory: Path, schedule: str | None = None,
         history_ids: list[str] | None = None) -> Inputs:
    """Load and check the visible records of one benchmark and split."""
    directory = Path(directory)
    files = (*VISIBLE, schedule_file(schedule))
    histories = [api.HistoryInfo.from_record(r) for r in _rows(directory / files[0])]
    messages = [api.Message.from_record(r) for r in _rows(directory / files[1])]
    reads = [api.ReadTask.from_record(r) for r in _rows(directory / files[2])]
    scopes = {(x.benchmark, x.split) for x in (*histories, *messages, *reads)}
    if len(scopes) != 1:
        raise ValueError(f"{directory}: expected one benchmark and split, found {sorted(scopes)}")
    benchmark, split = scopes.pop()
    if not allowed_split(split):
        raise ValueError(f"split {split!r} refused: only fixture and dev* splits may be read "
                         "before T002's split loader and the T033 preregistration tag exist")
    by_id = {h.history_id: h for h in histories}
    if len(by_id) != len(histories):
        raise ValueError(f"{directory}: duplicate history_id")
    msgs, tasks = defaultdict(list), defaultdict(list)
    for m in messages:
        msgs[m.history_id].append(m)
    for t in reads:
        tasks[t.history_id].append(t)
    unknown = (msgs.keys() | tasks.keys()) - by_id.keys()
    if unknown:
        raise ValueError(f"{directory}: records of unknown histories {sorted(unknown)}")
    read_ids = [t.read_id for t in reads]
    if len(set(read_ids)) != len(read_ids):
        raise ValueError(f"{directory}: duplicate read_id")
    selected = history_ids if history_ids is not None else list(by_id)
    out = []
    for hid in selected:
        if hid not in by_id:
            raise ValueError(f"history {hid!r} not in {directory}")
        history = by_id[hid]
        ordered = sorted(msgs[hid], key=lambda m: m.version)
        if [m.version for m in ordered] != list(range(1, history.n_messages + 1)):
            raise ValueError(f"history {hid!r}: message versions are not 1..{history.n_messages}")
        for t in tasks[hid]:
            if not 1 <= t.version <= history.n_messages:
                raise ValueError(f"read {t.read_id!r}: version outside 1..{history.n_messages}")
        out.append(HistoryInputs(history, tuple(ordered),
                                 tuple(sorted(tasks[hid], key=lambda t: t.version))))
    return Inputs(benchmark, split, directory, files, tuple(out))
