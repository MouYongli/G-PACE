"""T022 follow-up: drive GRACE's writer over the messages of benchmark histories.

For every history the probe builds a fresh message log and claim store, hands the messages to
`context.pipeline.update.updater.Updater` one by one in version order (`write`), and calls
`finish()` at the end, exactly as an engine would without reads in between. The writer sees only
visible records (messages and the history header); gold data never reaches it.

Per history the probe writes, under `<out>/graphs/<history_id>/`:

- `store/`: the claim store snapshot (`ClaimStore.save`: `store.json`, `changesets.jsonl`,
  `graph.nt`), restored and replayed by the T025 graph channel (`retrieval_recall`,
  `graph: extracted`);
- `writer.json`: the writer state (`Updater.save`: head, history-local vocabulary, failures).

and returns the update records (`UnitResult.to_record()`), one per extraction unit, to be written
to `updates.jsonl`. `limit` cuts each history after its first `limit` messages (a dry run); the
store then ends at that version.

`drive_segment` (E007, ablation G) writes one annotated segment of a history (the T024 graph-quality
sample) from an empty graph: the messages before the segment are appended to the log without
extraction (the writer sees the last `context_messages` of them as earlier context), one empty
change set at the version before the segment moves the store head there, and only the segment's
messages are extracted, at the configured granularity, with versions and message IDs as in the
history. Its graph is saved under `<out>/graphs/<name>/`.

Model calls: one `extract` call per unit and attempt, through `grace.llm` (the caller's
`ChatClient`), recorded in `calls.jsonl` with their true statuses.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from grace.context.api import HistoryInfo, Message
from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.history.log import MessageLog
from grace.context.pipeline.update.extract import Extractor
from grace.context.pipeline.update.updater import Updater, WriterConfig


def drive_history(history: HistoryInfo, messages: Sequence[Message], extractor: Extractor,
                  config: WriterConfig, out_dir: Path, *, limit: int | None = None,
                  progress: Callable[[str], None] | None = None) -> list[dict[str, Any]]:
    """Write every message of one history (or its first `limit`) and save the graph."""
    ordered = sorted(messages, key=lambda m: m.version)
    if limit is not None:
        ordered = ordered[:limit]
    log = MessageLog(history.history_id)
    store = ClaimStore(history.history_id)
    updater = Updater(history, log, store, extractor, config)
    records: list[dict[str, Any]] = []
    for message in ordered:
        for result in updater.write(message):
            records.append(result.to_record())
            if progress is not None:
                progress(f"{history.history_id} v{result.first_version}-{result.last_version} "
                         f"{result.status}")
    for result in updater.finish():
        records.append(result.to_record())
    target = Path(out_dir) / "graphs" / history.history_id
    store.save(target / "store")
    updater.save(target)
    return records


def drive_segment(history: HistoryInfo, messages: Sequence[Message], first_version: int,
                  last_version: int, extractor: Extractor, config: WriterConfig, out_dir: Path,
                  name: str) -> list[dict[str, Any]]:
    """Write the messages `first_version..last_version` of one history from an empty graph."""
    ordered = sorted(messages, key=lambda m: m.version)
    if not 1 <= first_version <= last_version <= len(ordered):
        raise ValueError(f"{name}: versions {first_version}..{last_version} out of range")
    log = MessageLog(history.history_id)
    store = ClaimStore(history.history_id)
    updater = Updater(history, log, store, extractor, config)
    for message in ordered[:first_version - 1]:
        log.append(message)
    if first_version > 1:
        store.commit(ChangeSet(history.history_id, first_version - 1,
                               vocabulary_version=updater.vocabulary.version))
    records: list[dict[str, Any]] = []
    for message in ordered[first_version - 1:last_version]:
        records += [r.to_record() for r in updater.write(message)]
    records += [r.to_record() for r in updater.finish()]
    target = Path(out_dir) / "graphs" / name
    store.save(target / "store")
    updater.save(target)
    return records
