"""Annotation sheet for the fragment-coverage annotation of LoCoMo (task T012, plan 6.5).

The sheet lists every question of a development split of LoCoMo (categories 1 to 4) with its gold
answer, the text of its evidence turns and the session date of each turn, and leaves empty columns
for the annotator. Guideline: docs/research/fragment-coverage.md.

Only development splits are accepted; the split is loaded through `splits.load_split`, which checks
the manifest and the counts. Image captions are not part of the visible records (plan 6.5), but the
sheet shows the caption of an evidence turn so that annotators can mark questions whose answer is
only in an image. The independent audit's verdict on a question is shown when it lists one.

The 100 overlap questions are chosen by `select_overlap`: stratified by history and category with
largest-remainder allocation, and inside each stratum by the SHA-256 of `<seed>:<question_id>`.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from grace.config.paths import project_root
from grace.eval.datasets.benchmarks.base import BenchmarkConfig, DataError, load_config
from grace.eval.datasets.benchmarks.locomo import SOURCE_FILE
from grace.eval.datasets.benchmarks.splits import load_split

CATEGORY_NAMES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop"}
AUDIT_FILE = "audit/errors_conv_{index}.json"
OVERLAP_SEED = "T012-overlap-v1"
OVERLAP_SIZE = 100
EVIDENCE_SEPARATOR = " || "
SHEET_COLUMNS = (
    "question_id", "history_id", "category", "category_name", "overlap", "question",
    "gold_answer", "evidence_ids", "evidence_text", "evidence_status", "evidence_image_caption",
    "audit_error_type", "audit_correct_answer",
    # filled by the annotator
    "annotator", "label", "operations", "other_reason", "flags", "rationale",
)
ANNOTATOR_COLUMNS = ("annotator", "label", "operations", "other_reason", "flags", "rationale")


def stable_key(seed: str, question_id: str) -> str:
    return hashlib.sha256(f"{seed}:{question_id}".encode()).hexdigest()


def select_overlap(rows: Sequence[Mapping[str, Any]], size: int = OVERLAP_SIZE,
                   seed: str = OVERLAP_SEED) -> list[str]:
    """Question IDs of the overlap set, sorted.

    Strata are (history_id, category). Each stratum gets `floor(size * n_s / N)` questions; the
    remaining slots go to the strata with the largest fractional parts (ties: stratum key). Inside
    a stratum questions are taken in the order of `stable_key(seed, question_id)`.
    """
    if not 0 < size <= len(rows):
        raise ValueError(f"overlap size {size} must lie in 1..{len(rows)}")
    strata: dict[tuple[str, int], list[str]] = defaultdict(list)
    for row in rows:
        strata[(str(row["history_id"]), int(row["category"]))].append(str(row["question_id"]))
    total = sum(len(ids) for ids in strata.values())
    quota = {k: size * len(ids) // total for k, ids in strata.items()}
    rest = size - sum(quota.values())
    by_fraction = sorted(strata, key=lambda k: (-(size * len(strata[k]) % total), k))
    for key in by_fraction[:rest]:
        quota[key] += 1
    chosen = []
    for key, ids in strata.items():
        chosen += sorted(ids, key=lambda q: stable_key(seed, q))[:quota[key]]
    return sorted(chosen, key=question_order)


def question_order(question_id: str) -> tuple[str, int]:
    history, _, number = question_id.partition(":q")
    return history, int(number)


def _captions(sample: Mapping[str, Any]) -> dict[str, str]:
    captions = {}
    for key, turns in sample["conversation"].items():
        if key.startswith("session_") and isinstance(turns, list):
            for turn in turns:
                if turn.get("blip_caption"):
                    captions[turn["dia_id"]] = turn["blip_caption"]
    return captions


def _audit(source_dir: Path, index: int) -> dict[int, Mapping[str, Any]]:
    path = source_dir / AUDIT_FILE.format(index=index)
    if not path.is_file():
        return {}
    entries = {}
    for entry in json.loads(path.read_text(encoding="utf-8")):
        number = int(str(entry["question_id"]).rsplit("_qa", 1)[1])
        entries[number] = entry
    return entries


def fragment_sheet(split: str = "dev", *, config: BenchmarkConfig | None = None,
                   data_root: Path | None = None, overlap_size: int = OVERLAP_SIZE,
                   seed: str = OVERLAP_SEED) -> list[dict[str, Any]]:
    """Rows of the annotation sheet, in question order, with the overlap column filled."""
    config = config or load_config("locomo")
    spec = config.splits.get(split)
    if spec is None or spec.kind != "development":
        raise DataError(f"locomo/{split}: the fragment annotation uses development splits only")
    records = load_split("locomo", split, config=config, data_root=data_root)
    root = data_root if data_root is not None else project_root()
    source_dir = config.source_dir(root)
    samples = json.loads((source_dir / SOURCE_FILE).read_text(encoding="utf-8"))
    index_of = {s["sample_id"]: i for i, s in enumerate(samples)}
    dates = {(h.history_id, s.segment_id): (s.timestamp or s.timestamp_raw or "")[:10]
             for h in records.histories for s in h.segments}
    messages = {(m.history_id, m.message_id): m for m in records.messages}
    captions = {sid: _captions(samples[i]) for sid, i in index_of.items()
                if spec.has_history(sid)}
    audits = {sid: _audit(source_dir, i) for sid, i in index_of.items() if spec.has_history(sid)}
    questions = {t.task_id: t.question for t in records.schedules["read_tasks.jsonl"]}
    rows = []
    for gold in records.gold:
        sid, number = question_order(gold.task_id)
        evidence = list(gold.evidence_ids or ()) + list(gold.evidence_unresolved)
        texts, image = [], []
        for eid in evidence:
            message = messages.get((sid, eid))
            if message is None:
                texts.append(f"[{eid} | unresolved]")
                continue
            date = dates.get((sid, message.segment_id), "")
            texts.append(f"[{eid} | {date} | {message.speaker}] {message.text}")
            if eid in captions[sid]:
                image.append(f"[{eid}] {captions[sid][eid]}")
        audit = audits[sid].get(number, {})
        category = int(gold.labels["category"])
        rows.append({
            "question_id": gold.task_id, "history_id": sid, "category": category,
            "category_name": CATEGORY_NAMES[category], "overlap": "",
            "question": questions[gold.task_id], "gold_answer": gold.reference,
            "evidence_ids": ";".join(evidence),
            "evidence_text": EVIDENCE_SEPARATOR.join(texts),
            "evidence_status": gold.metadata.get("evidence_status", ""),
            "evidence_image_caption": EVIDENCE_SEPARATOR.join(image),
            "audit_error_type": audit.get("error_type", ""),
            "audit_correct_answer": audit.get("correct_answer", "") if audit else "",
            **{c: "" for c in ANNOTATOR_COLUMNS}})
    rows.sort(key=lambda r: question_order(r["question_id"]))
    chosen = set(select_overlap(rows, overlap_size, seed))
    for row in rows:
        row["overlap"] = "yes" if row["question_id"] in chosen else "no"
    return rows


def write_sheet(rows: Iterable[Mapping[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in SHEET_COLUMNS})
