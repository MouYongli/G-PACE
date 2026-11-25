"""Adapter interface, benchmark configs, manifest and count checks (docs/research/contracts.md,
"Benchmark records", adapter obligations).

An adapter turns the source files of one benchmark version into the visible records (histories,
messages, read tasks) and the scoring-side gold of one split. Everything that is common to all
adapters lives here: the config of `configs/benchmarks/<slug>.yaml`, the manifest check, the
record checks (duplicate keys, version gaps, segment coverage, evidence resolution, snapshot
mismatches), the count check against the config and the writer of the record files.
"""

from __future__ import annotations

import abc
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT
from grace.eval.datasets.benchmarks.records import (
    Gold,
    HistoryInfo,
    Message,
    ReadTask,
    RecordError,
    Segment,
)

CONFIG_DIR = REPO_ROOT / "configs" / "benchmarks"
SPLIT_KINDS = ("development", "held-out", "fixture")
NATIVE_SCHEDULE = "read_tasks.jsonl"
COUNT_KEYS = ("histories", "messages", "read_tasks", "gold")


class DataError(RuntimeError):
    """The source data does not match its config: manifest checksum, file hash or counts."""


# ---------------------------------------------------------------------------------------------
# Config


@dataclass(frozen=True)
class SplitSpec:
    """One split of `configs/benchmarks/<slug>.yaml`.

    `histories` selects whole histories (every task of the history is in the split); `tasks`
    selects tasks (a history is in the split when at least one of its tasks is). Exactly one of
    `histories`, `tasks` and `history_list_file` (a file of history IDs inside the version
    directory, resolved by `resolve`) is given.
    """

    name: str
    kind: str
    histories: frozenset[str] | None = None
    tasks: frozenset[str] | None = None
    history_list_file: str | None = None
    counts: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def from_config(cls, name: str, raw: Mapping[str, Any]) -> SplitSpec:
        kind = raw.get("kind")
        if kind not in SPLIT_KINDS:
            raise DataError(f"split {name}: kind {kind!r} not in {SPLIT_KINDS}")
        selectors = [k for k in ("histories", "tasks", "history_list_file") if raw.get(k)]
        if len(selectors) != 1:
            raise DataError(f"split {name}: give exactly one of histories, tasks, "
                            f"history_list_file (got {selectors})")
        unknown = sorted(set(raw) - {"kind", "histories", "tasks", "history_list_file",
                                     "counts", "rule"})
        if unknown:
            raise DataError(f"split {name}: unknown keys {unknown}")
        counts = dict(raw.get("counts") or {})
        bad = sorted(set(counts) - set(COUNT_KEYS))
        if bad:
            raise DataError(f"split {name}: unknown count keys {bad}")
        return cls(
            name=name, kind=kind,
            histories=frozenset(map(str, raw["histories"])) if raw.get("histories") else None,
            tasks=frozenset(map(str, raw["tasks"])) if raw.get("tasks") else None,
            history_list_file=raw.get("history_list_file"), counts=counts)

    def resolve(self, source_dir: Path) -> SplitSpec:
        """Replace `history_list_file` by the history IDs it lists (one per line)."""
        if self.history_list_file is None:
            return self
        path = source_dir / self.history_list_file
        ids = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        ids = [i for i in ids if i]
        if len(ids) != len(set(ids)):
            raise DataError(f"{path}: duplicate history IDs")
        return SplitSpec(self.name, self.kind, histories=frozenset(ids), counts=self.counts)

    def has_history(self, history_id: str) -> bool:
        return self.histories is not None and history_id in self.histories

    def has_task(self, history_id: str, task_id: str) -> bool:
        if self.histories is not None:
            return history_id in self.histories
        return self.tasks is not None and task_id in self.tasks


@dataclass(frozen=True)
class BenchmarkConfig:
    """`configs/benchmarks/<slug>.yaml`: data version, manifests, splits and adapter options."""

    benchmark: str
    version: str
    data_root: str
    manifest_sha256: str
    extra_manifests: Mapping[str, str]
    splits: Mapping[str, SplitSpec]
    options: Mapping[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BenchmarkConfig:
        for key in ("benchmark", "version", "data_root", "manifest_sha256", "splits"):
            if not raw.get(key):
                raise DataError(f"benchmark config: {key} is not set")
        return cls(
            benchmark=raw["benchmark"], version=str(raw["version"]), data_root=raw["data_root"],
            manifest_sha256=raw["manifest_sha256"],
            extra_manifests={str(k): v for k, v in (raw.get("extra_manifests") or {}).items()},
            splits={name: SplitSpec.from_config(name, spec)
                    for name, spec in raw["splits"].items()},
            options=dict(raw.get("adapter") or {}))

    def source_dir(self, project_root: Path, version: str | None = None) -> Path:
        return project_root / self.data_root / (version or self.version)

    def manifests(self) -> dict[str, str]:
        """Version directory -> expected SHA-256 of its MANIFEST.sha256."""
        return {self.version: self.manifest_sha256, **self.extra_manifests}


def load_config(slug: str, config_dir: Path = CONFIG_DIR) -> BenchmarkConfig:
    path = config_dir / f"{slug}.yaml"
    if not path.is_file():
        raise DataError(f"no benchmark config {path}")
    config = BenchmarkConfig.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
    if config.benchmark != slug:
        raise DataError(f"{path}: benchmark is {config.benchmark!r}, expected {slug!r}")
    return config


# ---------------------------------------------------------------------------------------------
# Manifests


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(directory: Path, expected: str, check_files: bool = True) -> None:
    """Check the SHA-256 of `directory/MANIFEST.sha256` and, optionally, every file it lists."""
    manifest = directory / "MANIFEST.sha256"
    if not manifest.is_file():
        raise DataError(f"missing {manifest}")
    actual = sha256_file(manifest)
    if actual != expected:
        raise DataError(f"{manifest}: SHA-256 {actual} does not match the config ({expected})")
    if not check_files:
        return
    bad = []
    for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        path = directory / name
        if not path.is_file() or sha256_file(path) != digest:
            bad.append(f"{manifest}:{number}: {name}")
    if bad:
        raise DataError(f"files do not match the manifest: {bad[:5]} ({len(bad)} total)")


# ---------------------------------------------------------------------------------------------
# Records of one split


@dataclass
class Records:
    """All records of one benchmark and split, as produced by an adapter."""

    benchmark: str
    split: str
    histories: list[HistoryInfo] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    schedules: dict[str, list[ReadTask]] = field(default_factory=lambda: {NATIVE_SCHEDULE: []})
    gold: list[Gold] = field(default_factory=list)
    exclusions: Counter = field(default_factory=Counter)
    scoring: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def read_tasks(self) -> list[ReadTask]:
        return self.schedules[NATIVE_SCHEDULE]

    def counts(self) -> dict[str, int]:
        return {"histories": len(self.histories), "messages": len(self.messages),
                "read_tasks": len(self.read_tasks), "gold": len(self.gold)}

    def add(self, builder: HistoryBuilder) -> HistoryInfo:
        history, messages = builder.finish()
        self.histories.append(history)
        self.messages.extend(messages)
        return history


class HistoryBuilder:
    """Builds one history: messages get versions 1..N in call order; segments cover them."""

    def __init__(self, benchmark: str, split: str, history_id: str, subset: str | None = None,
                 metadata: Mapping[str, Any] | None = None):
        self.benchmark, self.split, self.history_id = benchmark, split, history_id
        self.subset, self.metadata = subset, dict(metadata or {})
        self.messages: list[Message] = []
        self._segments: list[dict[str, Any]] = []
        self._segmented: bool | None = None

    @property
    def version(self) -> int:
        return len(self.messages)

    def segment(self, segment_id: str, timestamp: str | None = None,
                timestamp_raw: str | None = None) -> None:
        """Open a segment; it ends when the next one opens or the history finishes."""
        if self._segmented is False:
            raise RecordError(f"{self.history_id}: segment after unsegmented messages")
        self._segmented = True
        self._segments.append({"segment_id": segment_id, "first_version": self.version + 1,
                               "timestamp": timestamp, "timestamp_raw": timestamp_raw})

    def message(self, message_id: str, speaker: str | None, role: str, text: str,
                timestamp: str | None = None, timestamp_raw: str | None = None,
                metadata: Mapping[str, Any] | None = None) -> Message:
        if self._segmented is None:
            self._segmented = False
        segment_id = self._segments[-1]["segment_id"] if self._segmented else None
        record = {"benchmark": self.benchmark, "split": self.split, "history_id": self.history_id,
                  "version": self.version + 1, "message_id": message_id,
                  "segment_id": segment_id, "speaker": speaker, "role": role, "text": text,
                  "timestamp": timestamp, "timestamp_raw": timestamp_raw}
        if metadata:
            record["metadata"] = dict(metadata)
        message = Message.from_record(record)
        self.messages.append(message)
        return message

    def segment_end(self) -> int:
        """Last version of the open segment so far (the version a session-end read sees)."""
        return self.version

    def finish(self) -> tuple[HistoryInfo, list[Message]]:
        if not self.messages:
            raise RecordError(f"{self.history_id}: history without messages")
        segments = []
        for index, seg in enumerate(self._segments):
            end = (self._segments[index + 1]["first_version"] - 1
                   if index + 1 < len(self._segments) else self.version)
            if end < seg["first_version"]:
                raise RecordError(f"{self.history_id}: segment {seg['segment_id']} is empty")
            segments.append(Segment(seg["segment_id"], seg["first_version"], end,
                                    seg["timestamp"], seg["timestamp_raw"]))
        history = HistoryInfo(self.benchmark, self.split, self.history_id, self.subset,
                              self.version, tuple(segments), self.metadata)
        return history, list(self.messages)


# ---------------------------------------------------------------------------------------------
# Checks


def _dups(keys: Iterable) -> list:
    return [key for key, count in Counter(keys).items() if count > 1]


def _raise(problems: Mapping[str, list], where: str) -> None:
    problems = {k: v for k, v in problems.items() if v}
    if problems:
        detail = "; ".join(f"{k}: {len(v)} (e.g. {v[:5]})" for k, v in problems.items())
        raise RecordError(f"{where}: {detail}")


def validate(records: Records) -> None:
    """Cross-record checks of contracts.md: keys, versions, segments, evidence, snapshots."""
    where = f"{records.benchmark}/{records.split}"
    problems: dict[str, list] = defaultdict(list)
    scope = (records.benchmark, records.split)
    for kind, items in (("histories", records.histories), ("messages", records.messages),
                        ("gold", records.gold),
                        *((name, tasks) for name, tasks in records.schedules.items())):
        problems["mixed_scope"] += [f"{kind}:{i}" for i, r in enumerate(items)
                                    if (r.benchmark, r.split) != scope]
    histories = {h.history_id: h for h in records.histories}
    problems["duplicate_history"] = _dups(h.history_id for h in records.histories)
    by_history: dict[str, list[Message]] = defaultdict(list)
    for m in records.messages:
        if m.history_id not in histories:
            problems["unknown_history"].append(m.history_id)
        by_history[m.history_id].append(m)
    message_index: dict[str, dict[str, Message]] = {}
    for hid, history in histories.items():
        messages = by_history.get(hid, [])
        problems["duplicate_message"] += [(hid, i) for i in _dups(m.message_id for m in messages)]
        if sorted(m.version for m in messages) != list(range(1, history.n_messages + 1)):
            problems["version_gap"].append(hid)
        expected = 1
        for seg in history.segments:
            if seg.first_version != expected or seg.last_version < seg.first_version:
                problems["segment_coverage"].append((hid, seg.segment_id))
            expected = seg.last_version + 1
        if history.segments and expected != history.n_messages + 1:
            problems["segment_coverage"].append((hid, "end"))
        problems["duplicate_segment"] += [(hid, s) for s in
                                          _dups(s.segment_id for s in history.segments)]
        for m in messages:
            seg = history.segment(m.segment_id)
            if history.segments and (seg is None or
                                     not seg.first_version <= m.version <= seg.last_version):
                problems["segment_mismatch"].append((hid, m.message_id))
            if not history.segments and m.segment_id is not None:
                problems["segment_mismatch"].append((hid, m.message_id))
        message_index[hid] = {m.message_id: m for m in messages}
    read_versions: dict[str, list[int]] = defaultdict(list)
    task_history: dict[str, str] = {}
    for name, tasks in records.schedules.items():
        problems["duplicate_read"] += [(name, r) for r in _dups(t.read_id for t in tasks)]
        for t in tasks:
            history = histories.get(t.history_id)
            if history is None:
                problems["unknown_history"].append(t.read_id)
            elif not 1 <= t.version <= history.n_messages:
                problems["snapshot_mismatch"].append(t.read_id)
            if task_history.setdefault(t.task_id, t.history_id) != t.history_id:
                problems["task_in_two_histories"].append(t.task_id)
            read_versions[t.task_id].append(t.version)
    problems["duplicate_gold"] = _dups(g.key for g in records.gold)
    for g in records.gold:
        if g.task_id not in read_versions:
            problems["gold_without_task"].append(g.key)
            continue
        if task_history[g.task_id] != g.history_id:
            problems["gold_history_mismatch"].append(g.key)
            continue
        known = message_index.get(g.history_id, {})
        for evidence in g.evidence_ids or ():
            if evidence not in known:
                problems["unknown_evidence"].append((g.key, evidence))
            elif any(known[evidence].version > v for v in read_versions[g.task_id]):
                problems["snapshot_mismatch"].append((g.key, evidence))
        segments = {s.segment_id for s in histories[g.history_id].segments}
        for evidence in g.evidence_segment_ids or ():
            if evidence not in segments:
                problems["unknown_evidence"].append((g.key, evidence))
    _raise(problems, where)


def check_counts(records: Records, expected: Mapping[str, int]) -> None:
    """Fail unless every count given in the config equals the count of the records."""
    actual = records.counts()
    mismatch = {k: (v, actual[k]) for k, v in expected.items() if actual[k] != v}
    if mismatch:
        detail = ", ".join(f"{k}: expected {e}, got {a}" for k, (e, a) in mismatch.items())
        raise DataError(f"{records.benchmark}/{records.split}: count mismatch ({detail})")


# ---------------------------------------------------------------------------------------------
# Output


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            # ASCII escapes keep U+2028 and other line separators in the text out of the line
            # structure, so readers that use str.splitlines() see one record per line.
            handle.write(json.dumps(row) + "\n")


def write_records(records: Records, out_dir: Path) -> list[Path]:
    """Write the record files, `exclusions.json` and `counts.json` into `out_dir` (a RUN_DIR
    path, never `$PROJECT_ROOT/data`)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    def emit(name: str, rows: Iterable[Mapping[str, Any]]) -> None:
        _write_jsonl(out_dir / name, rows)
        written.append(out_dir / name)

    emit("histories.jsonl", (h.to_record() for h in records.histories))
    order = {h.history_id: i for i, h in enumerate(records.histories)}
    messages = sorted(records.messages, key=lambda m: (order[m.history_id], m.version))
    emit("messages.jsonl", (m.to_record() for m in messages))
    for name, tasks in records.schedules.items():
        emit(name, (t.to_record() for t in tasks))
    emit("gold.jsonl", (g.to_record() for g in records.gold))
    for name, rows in records.scoring.items():
        emit(name, rows)
    for name, payload in (("exclusions.json", dict(sorted(records.exclusions.items()))),
                          ("counts.json", {**records.counts(), "notes": records.notes})):
        (out_dir / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                    encoding="utf-8")
        written.append(out_dir / name)
    return written


# ---------------------------------------------------------------------------------------------
# Adapter interface


class Adapter(abc.ABC):
    """Converts the source files of one benchmark version into the records of one split.

    `convert` reads only `source_dirs` (version -> directory, all checked against their
    manifests by the caller) and emits only what `split` selects. It counts every excluded input
    in `Records.exclusions` by reason. It does not check counts or write files; `splits.py`
    does both.
    """

    slug: str

    @abc.abstractmethod
    def convert(self, source_dirs: Mapping[str, Path], split: SplitSpec,
                options: Mapping[str, Any]) -> Records:
        """Return the records of `split`."""


def stratified_sample(keys_by_stratum: Mapping[Any, Iterable[str]], fraction: float,
                      seed: str) -> set[str]:
    """Deterministic split rule: in every stratum, the `round(fraction * n)` keys (half up) with
    the smallest SHA-256 of `<seed>:<key>`. Used to publish the development lists in the configs;
    the configs, not this function, are authoritative."""
    chosen: set[str] = set()
    for keys in keys_by_stratum.values():
        ranked = sorted(keys, key=lambda k: hashlib.sha256(f"{seed}:{k}".encode()).hexdigest())
        chosen.update(ranked[:int(len(ranked) * fraction + 0.5)])
    return chosen


def time_or_none(raw: str | None, parse) -> str | None:
    """Parse a source time string with `parse` (str -> ISO string); None stays None."""
    if raw is None or not str(raw).strip():
        return None
    try:
        return parse(str(raw).strip())
    except ValueError as exc:
        raise RecordError(f"cannot parse time {raw!r}: {exc}") from exc
