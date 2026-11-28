"""E006: run GRACE's writer only on annotated segments and export the extracted graphs.

Plan 6.7 measures claim precision and recall on sampled segments of development histories (task
T024: 40 segments, each with the 6 messages before it as read-only context). Writing the whole
history prefix before every segment would cost the whole development histories (LongMemEval-S
haystacks hold about 50 sessions each) for 578 scored messages, so this probe writes each segment
on its own (`segment_history`):

- a fresh message log and claim store per segment, holding the context messages followed by the
  segment messages, renumbered as versions 1..k in their original order;
- the context messages go through the writer like any other message, so that claims stated in the
  context are known claims when the segment is written (restatements become attributions, and an
  ending stance has a claim to end); they are scored by nobody (the scorer reads only claims
  attributed to segment messages);
- message IDs, speakers, roles, texts and timestamps are unchanged; the graph's history ID is the
  segment ID `graph_id(segment)`, so the change sets of one segment are self-contained.

What the writer does not see compared with a full-history run: the claims, entities and
history-local predicates of everything before the context. The scorer can also read full-history
runs (`graphs/<history_id>/`), which measures this difference on LoCoMo.

The writer sees only visible records (messages and a history header built from them); gold data
never reaches it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from grace.context.api import HistoryInfo, Message, Segment
from grace.context.pipeline.update.extract import Extractor
from grace.context.pipeline.update.updater import WriterConfig
from grace.eval.runner.probes.writer_extract import drive_history


def graph_id(segment: Mapping[str, Any]) -> str:
    """Directory-safe ID of one sampled segment (its sample key with `:` as `__`)."""
    return str(segment["key"]).replace(":", "__")


def segment_history(history: HistoryInfo, messages: Sequence[Message],
                    segment: Mapping[str, Any]) -> tuple[HistoryInfo, list[Message]]:
    """The context and segment messages of one sampled segment as a history of their own."""
    by_id = {m.message_id: m for m in messages if m.history_id == history.history_id}
    wanted = list(segment["context_ids"]) + list(segment["message_ids"])
    missing = [mid for mid in wanted if mid not in by_id]
    if missing:
        raise ValueError(f"{segment['key']}: messages not in the records: {missing[:5]}")
    chosen = sorted((by_id[mid] for mid in wanted), key=lambda m: m.version)
    gid = graph_id(segment)
    out = [replace(m, history_id=gid, version=n) for n, m in enumerate(chosen, start=1)]
    spans: dict[str | None, list[int]] = {}
    for m in out:
        spans.setdefault(m.segment_id, []).append(m.version)
    segments = []
    for sid, versions in spans.items():
        if sid is None:
            continue
        original = history.segment(sid)
        segments.append(Segment(sid, min(versions), max(versions),
                                original.timestamp if original else None,
                                original.timestamp_raw if original else None))
    info = replace(history, history_id=gid, n_messages=len(out), segments=tuple(segments),
                   metadata={})
    return info, out


def drive_segment(history: HistoryInfo, messages: Sequence[Message], segment: Mapping[str, Any],
                  extractor_for: Callable[[HistoryInfo], Extractor], config: WriterConfig,
                  out_dir: Path) -> list[dict[str, Any]]:
    """Write one segment with its context and save its graph under `graphs/<graph_id>/`."""
    info, sub = segment_history(history, messages, segment)
    records = drive_history(info, sub, extractor_for(info), config, out_dir)
    for r in records:
        r["segment"] = segment["key"]
        r["source_history_id"] = history.history_id
    return records
