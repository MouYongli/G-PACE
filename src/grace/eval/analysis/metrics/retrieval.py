"""Evidence recall of retrieval conditions (T025), computed from run-directory files only.

Inputs, all JSON Lines in the run directory: `retrievals.jsonl` of the T025 probe (per read, the
fused evidence IDs of every condition at every cut-off), and the probe's copies of the benchmark
records (`messages.jsonl`, `gold.jsonl`). This module imports nothing from `context/` or the
other `eval/` groups (structure.md).

Per read and condition at cut-off K, with G the gold evidence messages and R the K candidates:

- `recall@K` = |G ∩ R| / |G| (mean over scored reads);
- `full@K`   = 1 if G ⊆ R, else 0 (all evidence retrieved);
- `hit@K`    = 1 if G ∩ R is non-empty, else 0.

Gold evidence IDs are mapped to their `message_id` (a `#char=` span refines a message). Gold IDs
that name no message of the history are dropped and counted (`n_gold_unresolved`); a read whose
gold evidence is empty after that (abstention questions, unresolved evidence) is not scored and is
counted in `n_excluded`. A read whose gold evidence lies after its version is still scored (no
system can retrieve it; counted in `n_gold_after_read`).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

_SPAN = re.compile(r"^(?P<message>.+)#char=\d+,\d+$")
METRICS = ("recall", "full", "hit")


def _message(evidence_id: str) -> str:
    match = _SPAN.match(evidence_id)
    return match["message"] if match else evidence_id


def gold_sets(gold_rows: Iterable[Mapping[str, Any]], message_rows: Iterable[Mapping[str, Any]],
              annotation: str | None = None) -> dict[str, dict[str, Any]]:
    """task_id -> {"evidence": set of message IDs, "unresolved": n, "after": n, "labels": {...}}.

    `after` counts gold messages whose version is greater than the read version (filled in by
    `score`)."""
    versions: dict[tuple[str, str], int] = {}
    for m in message_rows:
        versions[(m["history_id"], m["message_id"])] = m["version"]
    out = {}
    for g in gold_rows:
        if annotation is not None and g["annotation"] != annotation:
            continue
        if g["task_id"] in out:
            raise ValueError(f"duplicate gold for {g['task_id']}")
        ids = [_message(e) for e in (g.get("evidence_ids") or [])]
        known = {e for e in ids if (g["history_id"], e) in versions}
        out[g["task_id"]] = {
            "evidence": known, "unresolved": len(set(ids) - known),
            "versions": {e: versions[(g["history_id"], e)] for e in known},
            "labels": dict(g.get("labels") or {})}
    return out


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def score(retrievals: Iterable[Mapping[str, Any]], gold: Mapping[str, Mapping[str, Any]],
          strata: Sequence[str] = ()) -> dict[str, Any]:
    """Recall of every condition at every cut-off, overall and per stratum label."""
    rows = list(retrievals)
    per: dict[tuple[str, str, str | None], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    totals: dict[str | None, int] = defaultdict(int)
    excluded: dict[str | None, int] = defaultdict(int)
    unresolved = after = 0
    for row in rows:
        g = gold.get(row["task_id"])
        if g is None:
            raise ValueError(f"no gold for {row['task_id']}")
        keys: list[str | None] = [None] + [f"{label}={g['labels'].get(label)}"
                                           for label in strata]
        for key in keys:
            totals[key] += 1
        unresolved += g["unresolved"]
        evidence = g["evidence"]
        if not evidence:
            for key in keys:
                excluded[key] += 1
            continue
        after += sum(1 for v in g["versions"].values() if v > row["version"])
        for cond, by_cutoff in row["conditions"].items():
            for cutoff, entry in by_cutoff.items():
                found = evidence & set(entry["ids"])
                values = {"recall": len(found) / len(evidence),
                          "full": float(found == evidence), "hit": float(bool(found))}
                for key in keys:
                    for metric, value in values.items():
                        per[(cond, cutoff, key)][metric].append(value)
    result: dict[str, Any] = {"n_reads": len(rows), "n_gold_unresolved": unresolved,
                              "n_gold_after_read": after, "conditions": {}, "strata": {}}
    for (cond, cutoff, key), metrics in sorted(per.items(), key=lambda kv: (
            kv[0][0], int(kv[0][1]), kv[0][2] or "")):
        cell = {m: _mean(metrics[m]) for m in METRICS}
        cell.update(n_total=totals[key], n_scored=len(metrics["recall"]),
                    n_excluded=excluded[key])
        if key is None:
            result["conditions"].setdefault(cond, {})[cutoff] = cell
        else:
            result["strata"].setdefault(key, {}).setdefault(cond, {})[cutoff] = cell
    return result
