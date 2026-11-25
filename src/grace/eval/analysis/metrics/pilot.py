"""E001 pilot statistics (docs/work/experiments/E001-pilot-measurements.md), from run files only.

This module reads only files in run directories (structure.md, `analysis/`); gold data reaches it
as the record files the E001 probe run wrote. It computes four things:

- **History lengths**: messages and tokens per history, and the full-history answer prompt of every
  read, from the probe's token counts (`lengths/<slug>.histories.jsonl`, `.reads.jsonl`).
- **Full-history cost** (plan 8.2): the logical input of reading the whole history at every read,
  and the interleaved accounting in which each read pays full price only for what was added since
  the previous read of the same history (the fixed prompt parts and the new messages). One minus
  their ratio is the largest cache-hit share a prefix cache could reach on that schedule.
- **Measured cache ratio**: from `calls.jsonl` of system runs, the share of input tokens the server
  reported as served from its prefix cache, and the compute ratio `c` of cached input, fitted on
  call latencies of a cached and an uncached server condition.
- **Natural update density**: how often a read follows an update that changes what it reads, from
  the gold annotations each benchmark has (MultiWOZ states, HaluMem update memory points, question
  strata of LongMemEval and MemoryAgentBench, per-message staleness labels of change-seq). LoCoMo
  has no update annotation; E002 measures it there.

The cost-ledger package is T030's (`metrics/cost.py`); only the sums E001 needs are computed here.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------------------------
# Files


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{number}: {exc}") from exc
    return rows


def read_run(run_dir: Path) -> dict[str, Any]:
    """run.json, resolved-config.yaml and the call records of one system run."""
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    resolved = yaml.safe_load((run_dir / "resolved-config.yaml").read_text(encoding="utf-8"))
    calls = read_jsonl(run_dir / "calls.jsonl") if (run_dir / "calls.jsonl").exists() else []
    predictions = (read_jsonl(run_dir / "predictions.jsonl")
                   if (run_dir / "predictions.jsonl").exists() else [])
    return {"dir": run_dir, "run": run, "resolved": resolved, "calls": calls,
            "predictions": predictions}


# ---------------------------------------------------------------------------------------------
# Distributions


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear interpolation between closest ranks (numpy's default), q in [0, 100]."""
    if not sorted_values:
        raise ValueError("no values")
    position = (len(sorted_values) - 1) * q / 100.0
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return float(sorted_values[low])
    weight = position - low
    return float(sorted_values[low] * (1 - weight) + sorted_values[high] * weight)


def distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    data = sorted(values)
    if not data:
        return {"n": 0, "sum": 0, "mean": None, "min": None, "p10": None, "p25": None,
                "p50": None, "p75": None, "p90": None, "max": None}
    return {"n": len(data), "sum": sum(data), "mean": round(sum(data) / len(data), 3),
            "min": data[0], "p10": percentile(data, 10), "p25": percentile(data, 25),
            "p50": percentile(data, 50), "p75": percentile(data, 75),
            "p90": percentile(data, 90), "max": data[-1]}


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 6) if whole else None


# ---------------------------------------------------------------------------------------------
# History lengths and full-history cost


def by_history(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        out[row["history_id"]].append(row)
    for items in out.values():
        items.sort(key=lambda r: (r["version"], r.get("read_id", "")))
    return out


def incremental_input(reads: Sequence[Mapping[str, Any]]) -> int:
    """Interleaved accounting of plan 8.2 for one history's reads in version order: the first read
    pays its whole prompt; each later read pays its prompt less the context of the previous read
    (the previous prompt's history prefix is reusable, the fixed parts and new messages are not)."""
    total, previous = 0, None
    for read in reads:
        total += read["prompt_tokens"] - (previous["context_tokens"] if previous else 0)
        previous = read
    return total


def length_tables(histories: Sequence[Mapping[str, Any]], reads: Sequence[Mapping[str, Any]],
                  *, window_tokens: int, output_reserve_tokens: int) -> dict[str, Any]:
    """Length distributions and full-history cost of one benchmark split (probe rows)."""
    logical = sum(r["prompt_tokens"] for r in reads)
    incremental = sum(incremental_input(items) for items in by_history(reads).values())
    over = [r for r in reads if r["prompt_tokens"] + output_reserve_tokens > window_tokens]
    reads_per_history = [len(items) for items in by_history(reads).values()]
    return {
        "histories": len(histories),
        "messages_per_history": distribution(h["n_messages"] for h in histories),
        "tokens_per_history": distribution(h["history_tokens"] for h in histories),
        "tokens_per_message": distribution(h["mean_message_tokens"] for h in histories),
        "reads": len(reads),
        "reads_per_history": distribution(reads_per_history),
        "prompt_tokens_per_read": distribution(r["prompt_tokens"] for r in reads),
        "fixed_prompt_tokens": distribution(r["prompt_tokens"] - r["context_tokens"]
                                            for r in reads),
        "full_history_cost": {
            "logical_input_tokens": logical,
            "incremental_input_tokens": incremental,
            "prefix_reuse_bound": share(logical - incremental, logical),
            "output_reserve_tokens_per_read": output_reserve_tokens,
        },
        "window": {
            "window_tokens": window_tokens,
            "reads_over_window": len(over),
            "share_reads_over_window": share(len(over), len(reads)),
            "histories_over_window": sum(1 for h in histories
                                         if h["history_tokens"] > window_tokens),
        },
    }


def prompt_reserve(fixed_max: int, output_reserve: int, margin: int, round_to: int) -> int:
    """The raw-text engine's prompt_reserve_tokens by the E001 rule."""
    need = fixed_max + output_reserve + margin
    return int(math.ceil(need / round_to) * round_to)


# ---------------------------------------------------------------------------------------------
# Natural update density


def _per_thousand(count: int, messages: int) -> float | None:
    return round(1000.0 * count / messages, 3) if messages else None


def multiwoz_density(reads: Sequence[Mapping], gold: Sequence[Mapping], n_messages: int,
                     annotation: str = "2.4") -> dict[str, Any]:
    """Each state read against the previous state read of the same dialogue (the first read of a
    dialogue against the empty state). An answer change is any added, changed or removed slot; a
    revision changes or removes a slot that already had a value."""
    states = {g["task_id"]: g["reference"] for g in gold if g["annotation"] == annotation}
    added = revised = removed = rereads = changed_reads = revised_reads = 0
    for items in by_history(reads).values():
        previous: Mapping[str, str] = {}
        for index, read in enumerate(items):
            state = states[read["task_id"]]
            a = sum(1 for s in state if s not in previous)
            r = sum(1 for s in state if s in previous and previous[s] != state[s])
            d = sum(1 for s in previous if s not in state)
            added, revised, removed = added + a, revised + r, removed + d
            if index:
                rereads += 1
                changed_reads += bool(a or r or d)
                revised_reads += bool(r or d)
            previous = state
    return {"available": True, "source": f"gold states, annotation {annotation}",
            "messages": n_messages, "reads": len(reads), "rereads": rereads,
            "slot_additions": added, "slot_revisions": revised, "slot_removals": removed,
            "revisions_per_1000_messages": _per_thousand(revised + removed, n_messages),
            "rereads_after_answer_change": changed_reads,
            "share_rereads_after_answer_change": share(changed_reads, rereads),
            "rereads_after_revision": revised_reads,
            "share_rereads_after_revision": share(revised_reads, rereads)}


def _is_true(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def halumem_density(reads: Sequence[Mapping], gold: Sequence[Mapping],
                    memory_points: Sequence[Mapping], n_messages: int) -> dict[str, Any]:
    """Update memory points (`is_update`) per thousand messages, and the reads whose evidence
    cites an update memory point (they read a fact that changed earlier in the history)."""
    updates = [p for p in memory_points if _is_true(p.get("is_update"))]
    updated = defaultdict(set)
    for point in updates:
        updated[point["history_id"]].add(point["memory_content"])
    gold_by_task = {g["task_id"]: g for g in gold}
    hits = 0
    types: dict[str, int] = defaultdict(int)
    for read in reads:
        g = gold_by_task[read["task_id"]]
        types[str(g["labels"].get("question_type"))] += 1
        cited = {e.get("memory_content") for e in
                 (g.get("metadata") or {}).get("evidence_memory_points") or []}
        hits += bool(cited & updated[read["history_id"]])
    return {"available": True, "source": "memory_points.jsonl is_update; question evidence",
            "messages": n_messages, "reads": len(reads), "memory_points": len(memory_points),
            "update_points": len(updates),
            "updates_per_1000_messages": _per_thousand(len(updates), n_messages),
            "reads_citing_update": hits, "share_reads_citing_update": share(hits, len(reads)),
            "reads_by_question_type": dict(sorted(types.items()))}


def stratum_density(reads: Sequence[Mapping], gold: Sequence[Mapping], n_messages: int,
                    label: str, value: str, source: str) -> dict[str, Any]:
    """Reads in an update stratum (LongMemEval knowledge-update, MemoryAgentBench conflict
    resolution): the only update annotation these benchmarks have."""
    gold_by_task = {g["task_id"]: g for g in gold}
    hits = sum(1 for r in reads if gold_by_task[r["task_id"]]["labels"].get(label) == value)
    return {"available": True, "source": source, "messages": n_messages, "reads": len(reads),
            "update_stratum": f"{label}={value}", "reads_in_stratum": hits,
            "share_reads_in_stratum": share(hits, len(reads)),
            "stratum_reads_per_1000_messages": _per_thousand(hits, n_messages)}


def changeseq_density(reads: Sequence[Mapping], gold: Sequence[Mapping],
                      stale_labels: Sequence[Mapping], n_messages: int) -> dict[str, Any]:
    """Controlled reference (not natural): messages that make at least one view answer-stale, and
    the reads of a view that became answer-stale since that view's previous read (or since the
    start). `stale_labels` holds the labels with answer_stale or citation_stale set."""
    stale = defaultdict(list)  # (history, binding) -> versions with answer_stale
    stale_messages, citation_messages = set(), set()
    for label in stale_labels:
        if label["answer_stale"]:
            stale[(label["history_id"], label["binding_id"])].append(label["version"])
            stale_messages.add((label["history_id"], label["version"]))
        if label["citation_stale"]:
            citation_messages.add((label["history_id"], label["version"]))
    gold_by_task = {g["task_id"]: g for g in gold}
    last_read: dict[tuple[str, str], int] = {}
    after = 0
    for read in sorted(reads, key=lambda r: (r["history_id"], r["version"], r["read_id"])):
        binding = (gold_by_task[read["task_id"]].get("metadata") or {}).get("binding_id")
        key = (read["history_id"], binding)
        since = last_read.get(key, 0)
        after += any(since < v <= read["version"] for v in stale.get(key, ()))
        last_read[key] = read["version"]
    return {"available": True, "source": "generator labels (controlled, not natural)",
            "messages": n_messages, "reads": len(reads),
            "answer_stale_messages": len(stale_messages),
            "answer_stale_messages_per_1000": _per_thousand(len(stale_messages), n_messages),
            "citation_stale_messages": len(citation_messages),
            "reads_after_answer_stale_update": after,
            "share_reads_after_answer_stale_update": share(after, len(reads))}


def update_density(slug: str, records: Path) -> dict[str, Any]:
    """Natural update density of one benchmark from the probe's record files."""
    records = Path(records)
    reads = read_jsonl(records / "read_tasks.jsonl")
    gold = read_jsonl(records / "gold.jsonl")
    n_messages = sum(h["n_messages"] for h in read_jsonl(records / "histories.jsonl"))
    if slug == "multiwoz":
        return multiwoz_density(reads, gold, n_messages)
    if slug == "halumem-medium":
        return halumem_density(reads, gold, read_jsonl(records / "memory_points.jsonl"),
                               n_messages)
    if slug == "longmemeval-s":
        return stratum_density(reads, gold, n_messages, "question_type", "knowledge-update",
                               "question type label")
    if slug == "memoryagentbench":
        return stratum_density(reads, gold, n_messages, "competency", "conflict_resolution",
                               "competency label")
    if slug == "change-seq":
        return changeseq_density(reads, gold, read_jsonl(records / "stale_labels.jsonl"),
                                 n_messages)
    return {"available": False, "messages": n_messages, "reads": len(reads),
            "reason": "no update annotation in the gold data; measured by E002 (extraction)"}


# ---------------------------------------------------------------------------------------------
# Measured cost and cache ratio of system runs


def call_sums(calls: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Token sums over call records, every attempt counted (plan 8.1)."""
    calls = list(calls)
    inp = sum(c["input_tokens"] for c in calls)
    cached = sum(c["cached_input_tokens"] for c in calls)
    out = sum(c["output_tokens"] for c in calls)
    return {"calls": len(calls), "failed": sum(1 for c in calls if c["status"] == "failed"),
            "invalid_output": sum(1 for c in calls if c["status"] == "invalid_output"),
            "input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out,
            "logical_tokens": inp + out, "computed_tokens": inp - cached + out,
            "cache_hit_ratio": share(cached, inp),
            "latency_s": round(sum(c["latency_ms"] for c in calls) / 1000.0, 3)}


def run_tables(loaded: Mapping[str, Any]) -> dict[str, Any]:
    """Cost and cache figures of one system run, by ledger category."""
    run, calls = loaded["run"], loaded["calls"]
    categories = defaultdict(list)
    for call in calls:
        categories[call["category"]].append(call)
    outputs: dict[str, int] = defaultdict(int)
    for prediction in loaded["predictions"]:
        outputs[prediction["output"]] += 1
    reads = {c["read_id"] for c in calls if c["category"] == "A" and c["read_id"]}
    answer = [c for c in calls if c["call_type"] == "answer"]
    first = [c for c in answer if c["attempt"] == 1 and c["status"] != "failed"]
    resolved = loaded["resolved"]
    return {
        "run_id": run["run_id"], "status": run["status"], "code_sha": run["code_sha"],
        "engine_config": resolved.get("engine_config"), "benchmark": resolved.get("benchmark"),
        "budget_tokens": resolved.get("budget_tokens"),
        "serving": (resolved.get("model") or {}).get("serving"),
        "histories": len(resolved.get("histories") or []), "n_records": run["n_records"],
        "outputs": dict(sorted(outputs.items())),
        "by_category": {k: call_sums(v) for k, v in sorted(categories.items())},
        "answer_calls": call_sums(answer),
        "answer_first_attempts": len(first),
        "answer_input_per_read": distribution(c["input_tokens"] for c in first),
        "reads_with_answer_call": len(reads),
    }


def solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (small normal equations)."""
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("singular system: the calls do not separate the coefficients")
        a[col], a[pivot] = a[pivot], a[col]
        for row in range(n):
            if row != col:
                factor = a[row][col] / a[col][col]
                for k in range(col, n + 1):
                    a[row][k] -= factor * a[col][k]
    return [a[i][n] / a[i][i] for i in range(n)]


def compute_ratio(calls: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Fit latency_ms = a + b_new * (input - cached) + b_cached * cached + b_out * output by least
    squares over successful calls, and return c = b_cached / b_new (plan 8.2: the compute ratio of
    cache-hit input under local inference). The calls should mix cached and uncached prefixes."""
    rows = [c for c in calls if c["status"] != "failed"]
    xs = [[1.0, c["input_tokens"] - c["cached_input_tokens"], c["cached_input_tokens"],
           c["output_tokens"]] for c in rows]
    ys = [float(c["latency_ms"]) for c in rows]
    if len(rows) < 8:
        return {"calls": len(rows), "c": None, "reason": "fewer than 8 calls"}
    # Scale the token columns to thousands for a well-conditioned system.
    scale = [1.0, 1000.0, 1000.0, 1000.0]
    xs = [[x / s for x, s in zip(row, scale, strict=True)] for row in xs]
    xtx = [[sum(r[i] * r[j] for r in xs) for j in range(4)] for i in range(4)]
    xty = [sum(r[i] * y for r, y in zip(xs, ys, strict=True)) for i in range(4)]
    try:
        beta = solve(xtx, xty)
    except ValueError as exc:
        return {"calls": len(rows), "c": None, "reason": str(exc)}
    fitted = [sum(b * x for b, x in zip(beta, r, strict=True)) for r in xs]
    mean = sum(ys) / len(ys)
    ss_tot = sum((y - mean) ** 2 for y in ys)
    ss_res = sum((y - f) ** 2 for y, f in zip(ys, fitted, strict=True))
    intercept, new, cached, out = beta
    return {"calls": len(rows),
            "uncached_input_tokens": sum(c["input_tokens"] - c["cached_input_tokens"]
                                         for c in rows),
            "cached_input_tokens": sum(c["cached_input_tokens"] for c in rows),
            "intercept_ms": round(intercept, 3), "ms_per_1k_new_input": round(new, 4),
            "ms_per_1k_cached_input": round(cached, 4), "ms_per_1k_output": round(out, 4),
            "r2": round(1 - ss_res / ss_tot, 4) if ss_tot else None,
            "c": round(cached / new, 4) if new > 0 else None}


# ---------------------------------------------------------------------------------------------
# Judging estimate (the judge stage is not run here)


def judge_estimate(predictions: Iterable[Mapping[str, Any]], prompt_tokens: Iterable[int],
                   price_usd_per_mtok: Mapping[str, float], output_tokens: int) -> dict[str, Any]:
    """Count judgeable predictions and estimate the secondary judge's spend from the judge prompt
    tokens of each (counted with the primary model's tokenizer, a proxy for the hosted one)."""
    n = sum(1 for p in predictions if p["output"] == "answer")
    tokens = list(prompt_tokens)
    inp, out = sum(tokens), output_tokens * len(tokens)
    usd = (inp * price_usd_per_mtok["input"] + out * price_usd_per_mtok["output"]) / 1e6
    return {"judgeable_predictions": n, "prompts_counted": len(tokens),
            "judge_input_tokens": inp, "judge_output_tokens_max": out,
            "secondary_usd_estimate": round(usd, 6)}
