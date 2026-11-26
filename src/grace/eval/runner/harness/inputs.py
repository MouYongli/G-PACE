"""The visible benchmark records a system stage reads (contracts.md, "Benchmark records").

Two sources, both reduced to the visible records (histories, messages, one read-task schedule);
gold records are never handed on:

- `load_dev(slug, split)`: benchmark data, through the single split entry point
  `grace.eval.datasets.benchmarks.splits.load_split` (manifest check, held-out guard, record and
  count checks). The harness accepts development splits only (`kind: development` in
  `configs/benchmarks/<slug>.yaml`), whatever the state of the preregistration tag.
- `load_fixture(directory)`: synthetic fixture records for tests and CI (`tests/fixtures/`). Only
  the split `fixture` is accepted, and only the three visible files are opened, never
  `gold.jsonl`.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from grace.config.paths import project_root
from grace.context import api
from grace.eval.datasets.benchmarks.base import NATIVE_SCHEDULE, BenchmarkConfig, load_config
from grace.eval.datasets.benchmarks.splits import load_split

VISIBLE = ("histories.jsonl", "messages.jsonl")


def schedule_file(schedule: str | None) -> str:
    return NATIVE_SCHEDULE if schedule in (None, "native") else f"read_tasks.{schedule}.jsonl"


@dataclass(frozen=True)
class HistoryInputs:
    history: api.HistoryInfo
    messages: tuple[api.Message, ...]
    reads: tuple[api.ReadTask, ...]


@dataclass(frozen=True)
class Inputs:
    benchmark: str
    split: str
    schedule: str  # read-task file name, e.g. read_tasks.jsonl
    data_version: str
    manifest_sha256: str
    path: Path  # fixture directory, or the benchmark's source directory under data_root
    histories: tuple[HistoryInputs, ...]
    extra_manifests: tuple[tuple[str, str], ...] = ()  # further data versions read: (version, sha)

    @property
    def n_reads(self) -> int:
        return sum(len(h.reads) for h in self.histories)


def assemble(histories: Sequence[api.HistoryInfo], messages: Sequence[api.Message],
             reads: Sequence[api.ReadTask], history_ids: list[str] | None,
             where: str) -> tuple[str, str, tuple[HistoryInputs, ...]]:
    """Group visible records by history and check their scope, keys and versions."""
    scopes = {(x.benchmark, x.split) for x in (*histories, *messages, *reads)}
    if len(scopes) != 1:
        raise ValueError(f"{where}: expected one benchmark and split, found {sorted(scopes)}")
    benchmark, split = scopes.pop()
    by_id = {h.history_id: h for h in histories}
    if len(by_id) != len(histories):
        raise ValueError(f"{where}: duplicate history_id")
    msgs, tasks = defaultdict(list), defaultdict(list)
    for m in messages:
        msgs[m.history_id].append(m)
    for t in reads:
        tasks[t.history_id].append(t)
    unknown = (msgs.keys() | tasks.keys()) - by_id.keys()
    if unknown:
        raise ValueError(f"{where}: records of unknown histories {sorted(unknown)}")
    read_ids = [t.read_id for t in reads]
    if len(set(read_ids)) != len(read_ids):
        raise ValueError(f"{where}: duplicate read_id")
    selected = history_ids if history_ids is not None else list(by_id)
    out = []
    for hid in selected:
        if hid not in by_id:
            raise ValueError(f"history {hid!r} not in {where}")
        history = by_id[hid]
        ordered = sorted(msgs[hid], key=lambda m: m.version)
        if [m.version for m in ordered] != list(range(1, history.n_messages + 1)):
            raise ValueError(f"history {hid!r}: message versions are not 1..{history.n_messages}")
        for t in tasks[hid]:
            if not 1 <= t.version <= history.n_messages:
                raise ValueError(f"read {t.read_id!r}: version outside 1..{history.n_messages}")
        out.append(HistoryInputs(history, tuple(ordered),
                                 tuple(sorted(tasks[hid], key=lambda t: t.version))))
    return benchmark, split, tuple(out)


def load_dev(slug: str, split: str = "dev", schedule: str | None = None,
             history_ids: list[str] | None = None, *, data_root: Path | None = None,
             config: BenchmarkConfig | None = None) -> Inputs:
    """Visible records of a development split, loaded and checked by `load_split`.

    `config` replaces `configs/benchmarks/<slug>.yaml` (E001: change-seq development data that is
    still the output of an upstream T015 run); its split must still be of kind `development`."""
    config = config or load_config(slug)
    spec = config.splits.get(split)
    if spec is None or spec.kind != "development":
        raise ValueError(f"{slug}/{split} refused: the harness runs development splits only")
    records = load_split(slug, split, config=config, data_root=data_root)
    name = schedule_file(schedule)
    if name not in records.schedules:
        raise ValueError(f"{slug}/{split} has no schedule {name}; has {sorted(records.schedules)}")
    benchmark, got, histories = assemble(records.histories, records.messages,
                                         records.schedules[name], history_ids, f"{slug}/{split}")
    if (benchmark, got) != (slug, split):
        raise ValueError(f"{slug}/{split}: records are of {benchmark}/{got}")
    path = config.source_dir(data_root if data_root is not None else project_root())
    extra = tuple(sorted((v, sha) for v, sha in config.manifests().items() if v != config.version))
    return Inputs(benchmark, split, name, config.version, config.manifest_sha256, path, histories,
                  extra)


def _rows(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
    return rows


def load_fixture(directory: Path, schedule: str | None = None,
                 history_ids: list[str] | None = None) -> Inputs:
    """Visible records of a synthetic fixture directory (split `fixture` only)."""
    directory = Path(directory)
    files = (*VISIBLE, schedule_file(schedule))
    histories = [api.HistoryInfo.from_record(r) for r in _rows(directory / files[0])]
    messages = [api.Message.from_record(r) for r in _rows(directory / files[1])]
    reads = [api.ReadTask.from_record(r) for r in _rows(directory / files[2])]
    splits = {x.split for x in (*histories, *messages, *reads)}
    if splits != {"fixture"}:
        raise ValueError(f"{directory}: split {sorted(splits)} refused; directories are read for "
                         "synthetic fixtures only, benchmark data goes through load_dev")
    benchmark, split, items = assemble(histories, messages, reads, history_ids, str(directory))
    lines = [f"{hashlib.sha256((directory / n).read_bytes()).hexdigest()}  {n}\n"
             for n in sorted(files)]
    manifest = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    return Inputs(benchmark, split, files[2], "fixture", manifest, directory, items)
