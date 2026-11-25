"""MemoryAgentBench adapter (card: docs/research/benchmarks.md#memoryagentbench).

Only the subsets of the plan are converted: LongMemEval(S*) (Accurate_Retrieval, source
`longmemeval_s*`) and FactConsolidation single- and multi-hop at 6K and 32K (Conflict_Resolution,
sources `factconsolidation_{sh,mh}_{6k,32k}`). One context row is one history
`<source>:<k>` (k counts rows of that source in file order); the source has no context IDs.

Chunks are messages and segments at once (`chunk_<k>`, 1-based, role `document`, no speaker):
- LongMemEval(S*): the context is a Python-literal list alternating `Chat Time: ...` headers and
  sessions; one chunk is one session, rendered as its header followed by `<role>: <content>`
  lines (the same text the source context carries).
- FactConsolidation: the context is a header line and numbered facts; one chunk is
  `facts_per_chunk` consecutive facts. The header line is excluded and counted.
All questions of a context are read at the last chunk. Task IDs are `<history_id>:<qa_pair_id>`.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from grace.eval.datasets.benchmarks.base import Adapter, HistoryBuilder, Records, SplitSpec
from grace.eval.datasets.benchmarks.longmemeval import is_abstention
from grace.eval.datasets.benchmarks.longmemeval import parse_time as parse_lme_time
from grace.eval.datasets.benchmarks.records import Gold, ReadTask, RecordError

FILES = {"accurate_retrieval": "Accurate_Retrieval-00000-of-00001.parquet",
         "conflict_resolution": "Conflict_Resolution-00000-of-00001.parquet"}
SUBSETS = {
    "longmemeval_s*": ("longmemeval-s-star", "accurate_retrieval"),
    "factconsolidation_sh_6k": ("factconsolidation-sh-6k", "conflict_resolution"),
    "factconsolidation_mh_6k": ("factconsolidation-mh-6k", "conflict_resolution"),
    "factconsolidation_sh_32k": ("factconsolidation-sh-32k", "conflict_resolution"),
    "factconsolidation_mh_32k": ("factconsolidation-mh-32k", "conflict_resolution"),
}
FACT = re.compile(r"\d+\. ")
CHAT_TIME = "Chat Time: "


def lme_chunks(context: str, where: str) -> list[str]:
    items = ast.literal_eval(context)
    if not isinstance(items, list) or len(items) % 2:
        raise RecordError(f"{where}: context is not a list of (header, session) pairs")
    chunks = []
    for header, session in zip(items[::2], items[1::2], strict=True):
        if not isinstance(header, str) or not isinstance(session, list):
            raise RecordError(f"{where}: context pair is not (str, list)")
        lines = [header] + [f"{turn['role']}: {turn['content']}" for turn in session]
        chunks.append("\n".join(lines))
    return chunks


def fact_chunks(context: str, per_chunk: int, exclusions: Counter, where: str) -> list[str]:
    lines = context.split("\n")
    facts = [line for line in lines if FACT.match(line)]
    other = [line for line in lines if not FACT.match(line)]
    exclusions["fact_context_header"] += sum(1 for line in other if line.strip())
    if any(line.strip() for line in other[1:]):
        raise RecordError(f"{where}: unexpected non-fact lines in the context")
    return ["\n".join(facts[i:i + per_chunk]) for i in range(0, len(facts), per_chunk)]


class MemoryAgentBenchAdapter(Adapter):
    slug = "memoryagentbench"

    def convert(self, source_dirs: Mapping[str, Path], split: SplitSpec,
                options: Mapping[str, Any]) -> Records:
        (version, directory), = source_dirs.items()
        per_chunk = int(options.get("facts_per_chunk", 20))
        records = Records(self.slug, split.name)
        selected = set()
        for competency, name in FILES.items():
            source = directory / name
            rows = pq.read_table(source).to_pylist()
            seen: Counter = Counter()
            for index, row in enumerate(rows):
                src = row["metadata"]["source"]
                k = seen[src]
                seen[src] += 1
                if src not in SUBSETS:
                    records.exclusions[f"subset_not_in_plan:{src}"] += 1
                    continue
                history_id = f"{src}:{k}"
                qa_ids = row["metadata"]["qa_pair_ids"]
                tasks = [(i, f"{history_id}:{q}") for i, q in enumerate(qa_ids)
                         if split.has_task(history_id, f"{history_id}:{q}")]
                selected.update(t for _, t in tasks)
                if tasks:
                    self._convert_row(records, row, history_id, tasks, competency, per_chunk,
                                      f"{source}[{index}]", version)
        wanted = split.tasks or set()
        missing = sorted(wanted - selected)
        if missing:
            raise RecordError(f"memoryagentbench: split {split.name} names unknown tasks "
                              f"{missing[:5]} ({len(missing)} total)")
        return records

    def _convert_row(self, records: Records, row: dict, history_id: str,
                     tasks: list[tuple[int, str]], competency: str, per_chunk: int,
                     where: str, version: str) -> None:
        meta = row["metadata"]
        subset, _ = SUBSETS[meta["source"]]
        if meta["source"] == "longmemeval_s*":
            chunks = lme_chunks(row["context"], where)
        else:
            chunks = fact_chunks(row["context"], per_chunk, records.exclusions, where)
        builder = HistoryBuilder(self.slug, records.split, history_id, subset,
                                 metadata={"source": meta["source"]})
        for k, text in enumerate(chunks, start=1):
            if not text.strip():
                records.exclusions["empty_chunk"] += 1
                continue
            builder.segment(f"chunk_{k}")
            builder.message(f"chunk_{k}", None, "document", text)
        history = records.add(builder)
        n = history.n_messages
        questions, answers = row["questions"], row["answers"]
        if len(questions) != len(answers) or len(questions) != len(meta["qa_pair_ids"]):
            raise RecordError(f"{where}: questions, answers and qa_pair_ids differ in length")
        records.exclusions["questions_in_other_split"] += len(questions) - len(tasks)
        for i, task_id in tasks:
            raw_date = (meta.get("question_dates") or [None] * len(questions))[i]
            question_id = (meta.get("question_ids") or [None] * len(questions))[i]
            labels: dict[str, Any] = {"competency": competency}
            if meta.get("question_types"):
                labels["question_type"] = meta["question_types"][i]
            if question_id is not None:
                labels["abstention"] = is_abstention(question_id)
            records.read_tasks.append(ReadTask.from_record({
                "benchmark": self.slug, "split": records.split, "history_id": history_id,
                "read_id": f"{task_id}@{n}", "task_id": task_id, "version": n,
                "kind": "question", "question": questions[i], "state_schema": None,
                "asked_at": parse_lme_time(raw_date) if raw_date else None,
                "asked_at_raw": raw_date}))
            metadata = {"qa_pair_id": meta["qa_pair_ids"][i]}
            if question_id is not None:
                metadata["longmemeval_question_id"] = question_id
            records.gold.append(Gold(
                benchmark=self.slug, split=records.split, history_id=history_id,
                task_id=task_id, annotation=version, reference=list(answers[i]),
                evidence_ids=None, evidence_segment_ids=None, evidence_unresolved=(),
                labels=labels, metadata=metadata))
