"""Storage of predictions, working contexts, traces and change sets of a run.

`Prediction` is the record of contracts.md, "Prediction" (version 0.2); the other files follow its
"Experiment run" section. Every file is JSON Lines, appended in the order of the run.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from grace.context import api

OUTPUTS = ("answer", "state", "unknown", "invalid")


@dataclass(frozen=True)
class Prediction:
    benchmark: str
    split: str
    history_id: str
    read_id: str
    task_id: str
    version: int
    output: str
    prediction: Any
    cited_ids: list[str]
    context_ids: list[str]
    further_retrieval: bool
    raw_output: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.output not in OUTPUTS:
            raise ValueError(f"{self.read_id}: output {self.output!r} not in {OUTPUTS}")
        if (self.prediction is None) != (self.output in ("unknown", "invalid")):
            raise ValueError(f"{self.read_id}: prediction must be null iff unknown or invalid")

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        if not self.metadata:
            del record["metadata"]
        return record


class RunWriter:
    """Appends the system-stage artefacts to a run directory."""

    FILES = ("predictions.jsonl", "contexts.jsonl", "traces/write.jsonl", "traces/read.jsonl",
             "changesets.jsonl")

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        (self.run_dir / "traces").mkdir(exist_ok=True)
        for name in self.FILES:
            (self.run_dir / name).touch(exist_ok=False)
        self.counts = dict.fromkeys(self.FILES, 0)

    def _append(self, name: str, record: dict[str, Any]) -> None:
        with (self.run_dir / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.counts[name] += 1

    def write(self, result: api.WriteResult) -> None:
        self._append("traces/write.jsonl", result.trace.to_record())
        if result.changeset is not None:
            self._append("changesets.jsonl", dict(result.changeset))

    def read(self, prediction: Prediction, context: api.WorkingContext,
             trace: api.ReadTrace) -> None:
        if list(trace.included_ids) != prediction.context_ids:
            raise ValueError(f"{prediction.read_id}: trace included_ids differ from context_ids")
        self._append("predictions.jsonl", prediction.to_record())
        self._append("contexts.jsonl", context.to_record())
        self._append("traces/read.jsonl", trace.to_record())
