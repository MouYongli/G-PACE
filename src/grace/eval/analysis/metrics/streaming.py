"""Answer consistency under LoCoMo evidence-anchored streaming (plan 6.5 and 7, task T031).

Each streaming question is read at v(q) and again at N, and both answers are scored against the
same gold reference (it is valid at both versions, contracts.md "Read task"). Per question:

- `f1_v`, `f1_n`: the official LoCoMo score of its category (`answer.locomo_score`) at v(q) and N;
  `unknown` and `invalid` outputs score 0 here (the invalid-output policy of the Evaluation
  contract applies to registered metrics, which this is not yet) and are counted separately.
- `answer_changed`: the two outputs differ (output kind, or the normalised answer text of
  `answer.normalize_answer`). A changed answer means later writes disturbed the system.
- `delta` = `f1_n` - `f1_v`; `worse_at_n` / `better_at_n` count questions whose score fell / rose.

A question with v(q) = N has one read; it is counted (`final_only`) but not paired. Questions on the
audit's evidence-error list are summarised apart (`reported_separately`), the others under
`streaming`; plan 6.5 excludes questions with missing evidence from the schedule altogether.

Inputs are run-directory files only (structure.md): the system run's `predictions.jsonl` and the
copies of the benchmark records (streaming read tasks, messages, gold) the scoring command writes
next to its output. Alignment and snapshot checks are those of `align.align`. This module imports
nothing from `context/` or the other `eval/` groups.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from statistics import fmean
from typing import Any

from grace.eval.analysis.metrics.align import Aligned
from grace.eval.analysis.metrics.answer import locomo_score, normalize_answer, output_text

STREAMING = "streaming"
SEPARATE = "reported_separately"


def _score(aligned: Aligned, gold: Mapping[str, Any]) -> float:
    output = aligned.output
    if output == "invalid":
        return 0.0
    return locomo_score(int(gold["labels"]["category"]), output,
                        aligned.prediction["prediction"], gold["reference"])


def _answer_key(aligned: Aligned) -> tuple[str, str]:
    return aligned.output, normalize_answer(output_text(aligned.prediction["prediction"]))


def pair_rows(aligned: Mapping[str, Aligned], gold: Mapping[str, Mapping[str, Any]],
              n_messages: Mapping[str, int], separate: Collection[str] = ()) -> list[dict]:
    """One row per question of the aligned streaming reads (read-task order)."""
    by_task: dict[str, list[Aligned]] = defaultdict(list)
    for item in aligned.values():
        by_task[item.read_task["task_id"]].append(item)
    rows = []
    for task_id, reads in by_task.items():
        reads.sort(key=lambda a: a.read_task["version"])
        history_id = reads[0].read_task["history_id"]
        n = n_messages[history_id]
        if task_id not in gold:
            raise ValueError(f"{task_id}: no gold record")
        if len(reads) > 2 or reads[-1].read_task["version"] != n:
            raise ValueError(f"{task_id}: expected reads at v(q) and N={n}, got "
                             f"{[a.read_task['version'] for a in reads]}")
        first, last = reads[0], reads[-1]
        f1_v, f1_n = _score(first, gold[task_id]), _score(last, gold[task_id])
        paired = len(reads) == 2
        rows.append({
            "task_id": task_id, "history_id": history_id,
            "category": int(gold[task_id]["labels"]["category"]),
            "group": SEPARATE if task_id in separate else STREAMING,
            "v": first.read_task["version"], "n": n, "paired": paired,
            "read_v": first.read_id, "read_n": last.read_id,
            "output_v": first.output, "output_n": last.output,
            "f1_v": f1_v, "f1_n": f1_n, "delta": f1_n - f1_v,
            "answer_changed": paired and _answer_key(first) != _answer_key(last),
        })
    return rows


def _mean(values: Sequence[float]) -> float | None:
    return round(fmean(values), 6) if values else None


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Consistency counts over the paired rows, overall and per group."""

    def block(selected: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        paired = [r for r in selected if r["paired"]]
        changed = [r for r in paired if r["answer_changed"]]
        outputs: dict[str, dict[str, int]] = {"v": defaultdict(int), "n": defaultdict(int)}
        for r in paired:
            outputs["v"][r["output_v"]] += 1
            outputs["n"][r["output_n"]] += 1
        return {
            "questions": len(selected), "paired": len(paired),
            "final_only": len(selected) - len(paired),
            "mean_f1_v": _mean([r["f1_v"] for r in paired]),
            "mean_f1_n": _mean([r["f1_n"] for r in paired]),
            "mean_delta": _mean([r["delta"] for r in paired]),
            "answer_changed": len(changed),
            "answer_changed_share": (round(len(changed) / len(paired), 6) if paired else None),
            "worse_at_n": sum(r["delta"] < 0 for r in paired),
            "better_at_n": sum(r["delta"] > 0 for r in paired),
            "outputs": {k: dict(sorted(v.items())) for k, v in outputs.items()},
        }

    return {"all": block(rows),
            STREAMING: block([r for r in rows if r["group"] == STREAMING]),
            SEPARATE: block([r for r in rows if r["group"] == SEPARATE])}
