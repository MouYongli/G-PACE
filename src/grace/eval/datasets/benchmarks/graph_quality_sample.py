"""Segment sample for the graph-quality annotation (task T024, plan 6.7).

Plan 6.7 measures claim recall on 40 sampled segments of about 20 messages each from development
histories. The user fixed the split of the 40 segments on 2026-11-28: 16 from LoCoMo dev (8 per
history) and 24 from LongMemEval-S dev. Guideline: docs/research/graph-quality-annotation.md.

The sample is a pure function of the development records and the seed string `SAMPLE_SEED`.
Every seeded choice orders candidates by the SHA-256 of `<seed>:<purpose>:<key>`, so it depends
neither on Python's random module nor on file order.

- A segment is a window of consecutive messages inside one source segment (a LoCoMo session or a
  LongMemEval-S haystack session): the whole session when it has at most `MAX_WHOLE` messages,
  otherwise `WINDOW` messages from a seeded start. Each segment carries the `CONTEXT` messages
  before it in the same history as read-only context.
- LoCoMo: per history, `LOCOMO_PER_HISTORY` sessions in seeded order.
- LongMemEval-S: `LME_SEGMENTS` histories, one segment each, allocated over question types by
  largest remainder and chosen in seeded order inside a type. Half of them (in seeded order) take
  an evidence session (one of `evidence_segment_ids`), and the window then holds an evidence
  message; the other half take a filler session with at least `MIN_FILLER` messages.

Only development splits are loaded, through `splits.load_split`.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.splits import load_split

SAMPLE_SEED = "T024-segments-v1"
LOCOMO_PER_HISTORY = 8
LME_SEGMENTS = 24
WINDOW = 20
MAX_WHOLE = 24
CONTEXT = 6
MIN_FILLER = 8
SPLIT = "dev"


class SampleError(ValueError):
    """The records cannot be sampled as the protocol requires."""


def rank(purpose: str, key: str, seed: str = SAMPLE_SEED) -> str:
    """Seeded sort key: hex SHA-256 of `seed:purpose:key`."""
    return hashlib.sha256(f"{seed}:{purpose}:{key}".encode()).hexdigest()


def allocate(sizes: Mapping[str, int], total: int) -> dict[str, int]:
    """Largest-remainder allocation of `total` slots over strata of the given sizes.

    Each stratum gets `floor(total * n / N)`; the remaining slots go to the largest fractional
    parts, ties broken by stratum name. No stratum gets more slots than it has members.
    """
    n_all = sum(sizes.values())
    if not 0 < total <= n_all:
        raise SampleError(f"cannot allocate {total} slots over {n_all} members")
    quota = {k: total * n // n_all for k, n in sizes.items()}
    rest = total - sum(quota.values())
    order = sorted(sizes, key=lambda k: (-(total * sizes[k] % n_all), k))
    for key in order[:rest]:
        quota[key] += 1
    return quota


def window(n: int, purpose: str, key: str, must_hold: int | None = None) -> tuple[int, int]:
    """Half-open index range [start, end) of the window inside a source segment of n messages.

    The whole segment when n <= MAX_WHOLE; otherwise WINDOW messages from a seeded start, chosen
    among the starts whose window holds index `must_hold` when one is given.
    """
    if n <= MAX_WHOLE:
        return 0, n
    starts = list(range(n - WINDOW + 1))
    if must_hold is not None:
        starts = [s for s in starts if s <= must_hold < s + WINDOW]
    start = min(starts, key=lambda s: rank(purpose, f"{key}:{s}"))
    return start, start + WINDOW


@dataclass(frozen=True)
class Segment:
    key: str                     # <benchmark>:<history_id>:<segment_id>:<first>-<last> (versions)
    benchmark: str
    history_id: str
    segment_id: str
    kind: str                    # session (LoCoMo), evidence or filler (LongMemEval-S)
    stratum: str                 # history (LoCoMo) or question type (LongMemEval-S)
    message_ids: tuple[str, ...]
    context_ids: tuple[str, ...]
    first_version: int
    last_version: int

    def to_record(self) -> dict[str, Any]:
        return {"key": self.key, "benchmark": self.benchmark, "history_id": self.history_id,
                "segment_id": self.segment_id, "kind": self.kind, "stratum": self.stratum,
                "first_version": self.first_version, "last_version": self.last_version,
                "message_ids": list(self.message_ids), "context_ids": list(self.context_ids)}


def _by_source(messages: Sequence[Any]) -> dict[tuple[str, str], list[Any]]:
    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for m in messages:
        groups[(m.history_id, m.segment_id)].append(m)
    for group in groups.values():
        group.sort(key=lambda m: m.version)
    return groups


def _segment(benchmark: str, kind: str, stratum: str, history: list[Any], source: list[Any],
             start: int, end: int) -> Segment:
    chosen = source[start:end]
    first = chosen[0].version
    before = [m for m in history if m.version < first][-CONTEXT:]
    m0 = chosen[0]
    return Segment(
        key=f"{benchmark}:{m0.history_id}:{m0.segment_id}:{first}-{chosen[-1].version}",
        benchmark=benchmark, history_id=m0.history_id, segment_id=m0.segment_id, kind=kind,
        stratum=stratum, message_ids=tuple(m.message_id for m in chosen),
        context_ids=tuple(m.message_id for m in before), first_version=first,
        last_version=chosen[-1].version)


def sample_locomo(records: Any) -> list[Segment]:
    sources = _by_source(records.messages)
    histories: dict[str, list[Any]] = defaultdict(list)
    for m in records.messages:
        histories[m.history_id].append(m)
    out = []
    for history_id in sorted(histories):
        history = sorted(histories[history_id], key=lambda m: m.version)
        sessions = sorted({sid for (hid, sid) in sources if hid == history_id})
        if len(sessions) < LOCOMO_PER_HISTORY:
            raise SampleError(f"{history_id}: {len(sessions)} sessions, need {LOCOMO_PER_HISTORY}")
        chosen = sorted(sessions, key=lambda s: rank("locomo-session", f"{history_id}:{s}"))
        for sid in chosen[:LOCOMO_PER_HISTORY]:
            source = sources[(history_id, sid)]
            start, end = window(len(source), "locomo-window", f"{history_id}:{sid}")
            out.append(_segment("locomo", "session", history_id, history, source, start, end))
    return sorted(out, key=lambda s: (s.history_id, s.first_version))


def sample_longmemeval(records: Any) -> list[Segment]:
    gold = {g.history_id: g for g in records.gold}
    types: dict[str, list[str]] = defaultdict(list)
    for history_id, g in gold.items():
        types[str(g.labels["question_type"])].append(history_id)
    quota = allocate({t: len(ids) for t, ids in types.items()}, LME_SEGMENTS)
    picked = []
    for qtype in sorted(types):
        ordered = sorted(types[qtype], key=lambda h: rank("lme-history", h))
        picked += [(qtype, h) for h in ordered[:quota[qtype]]]
    picked.sort(key=lambda item: rank("lme-kind", item[1]))
    half = len(picked) // 2
    sources = _by_source(records.messages)
    histories: dict[str, list[Any]] = defaultdict(list)
    for m in records.messages:
        histories[m.history_id].append(m)
    out = []
    for i, (qtype, history_id) in enumerate(picked):
        history = sorted(histories[history_id], key=lambda m: m.version)
        g = gold[history_id]
        evidence_sessions = set(g.evidence_segment_ids or ())
        own = sorted({sid for (hid, sid) in sources if hid == history_id})
        if i < half:
            kind = "evidence"
            candidates = [s for s in own if s in evidence_sessions]
        else:
            kind = "filler"
            candidates = [s for s in own if s not in evidence_sessions
                          and len(sources[(history_id, s)]) >= MIN_FILLER]
        if not candidates:
            raise SampleError(f"{history_id}: no {kind} session to sample")
        sid = min(candidates, key=lambda s: rank(f"lme-{kind}", f"{history_id}:{s}"))
        source = sources[(history_id, sid)]
        hold = None
        if kind == "evidence":
            evidence = set(g.evidence_ids or ())
            idx = [j for j, m in enumerate(source) if m.message_id in evidence]
            if idx:
                hold = min(idx, key=lambda j: rank("lme-evidence", f"{history_id}:{j}"))
        start, end = window(len(source), "lme-window", f"{history_id}:{sid}", hold)
        out.append(_segment("longmemeval-s", kind, qtype, history, source, start, end))
    return sorted(out, key=lambda s: (s.kind, s.stratum, s.history_id))


def _message_row(by_id: Mapping[tuple[str, str], Any], dates: Mapping[tuple[str, str], Any],
                 history_id: str, mid: str) -> dict[str, Any]:
    m = by_id[(history_id, mid)]
    return {"message_id": m.message_id, "version": m.version, "segment_id": m.segment_id,
            "date": m.timestamp or dates.get((history_id, m.segment_id)),
            "speaker": m.speaker, "role": m.role, "text": m.text}


def draw() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Draw the sample from the development records.

    Returns the sample record (IDs, parameters, data provenance; no message text) and one row per
    segment with the message and context text, for the annotators.
    """
    segments: list[Segment] = []
    data = []
    rows: list[dict[str, Any]] = []
    for slug, sampler in (("locomo", sample_locomo), ("longmemeval-s", sample_longmemeval)):
        records = load_split(slug, SPLIT)
        config = load_config(slug)
        data.append({"benchmark": slug, "version": config.version, "split": SPLIT,
                     "manifest_sha256": config.manifests()[config.version]})
        drawn = sampler(records)
        segments += drawn
        by_id = {(m.history_id, m.message_id): m for m in records.messages}
        dates = {(h.history_id, s.segment_id): s.timestamp
                 for h in records.histories for s in h.segments}
        participants: dict[str, list[str]] = defaultdict(list)
        for m in records.messages:
            who = m.speaker or m.role
            if who not in participants[m.history_id]:
                participants[m.history_id].append(who)

        for s in drawn:
            row = s.to_record()
            row["participants"] = participants[s.history_id]
            row["messages"] = [_message_row(by_id, dates, s.history_id, mid)
                               for mid in s.message_ids]
            row["context"] = [_message_row(by_id, dates, s.history_id, mid)
                              for mid in s.context_ids]
            rows.append(row)
    record = {
        "task": "T024",
        "seed": SAMPLE_SEED,
        "parameters": {"locomo_per_history": LOCOMO_PER_HISTORY, "lme_segments": LME_SEGMENTS,
                       "window": WINDOW, "max_whole": MAX_WHOLE, "context": CONTEXT,
                       "min_filler": MIN_FILLER, "split": SPLIT},
        "data": data,
        "n_segments": len(segments),
        "n_messages": sum(len(s.message_ids) for s in segments),
        "segments": [s.to_record() for s in segments],
    }
    return record, rows


def write(record: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], record_path: Path,
          rows_path: Path) -> None:
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    with rows_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
