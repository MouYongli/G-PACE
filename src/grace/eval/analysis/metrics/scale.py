"""E004 scale statistics (docs/work/experiments/E004-scale-experiment.md), from run files only.

Reads `run.json`, `graph.json`, `machine.json` and `measurements.jsonl` of completed E004 runs
(structure.md: `analysis/` reads only files in run directories and imports no engine code).

Per measurement (one arm, cell, seed and repetition):

- `write_ms`: write-side decision time per committed change set (`match_ms`, pattern matching on
  the change-set records; pull has none);
- `read_ms`: database time per read (`check_db_ms` + `maintain_db_ms`: the fingerprint re-query,
  or the maintenance re-evaluation of a marked view);
- `period_ms = w * write_ms + read_ms`: the decision cost of one read period of `w` writes, and
  `per_write_ms = period_ms / w`.

Arms are compared within the same (cell, seed, repetition) because they ran back to back on the
same machine state (paired). The cost ratio `period_ms(arm) / period_ms(pull)` is summarised by
its geometric mean over the pairs with a percentile bootstrap interval over pairs.

**Crossover.** Along one axis of the grid (writes per read by default) with the other factors
fixed, the log ratio `log(period_ms(arm) / period_ms(pull))` is interpolated linearly in
`log(axis)` between adjacent levels; the crossover is the first level where the sign changes. Its
uncertainty comes from the bootstrap: every replicate resamples the pairs at every level and
recomputes the crossover; the summary gives the median and the 2.5 / 97.5 percentiles of the
replicates that cross, and the share that are cheaper than pull over the whole range, more
expensive over the whole range, or cross.

**Noise.** Per (cell, arm) the coefficient of variation of `period_ms` across repetitions of the
same seed (timing noise) and across seeds (graph realisation); the load average before and after
each measurement and the CPU/wall ratio are summarised per run.

**Checks.** Pull and hybrid must repair exactly the same views with the same actions at every read
(equal LLM work by construction); the number of measurement pairs that differ is reported and
must be 0.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

CELL = ("mix", "blocks", "views", "read_scope", "writes_per_read")
PAIR = ("seed", "repetition")
REFERENCE = "pull"
BOOTSTRAP = 2000


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_runs(dirs: Iterable[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Measurements of completed runs (each tagged with its run ID) and the run descriptions."""
    measurements, runs = [], []
    for d in dirs:
        d = Path(d)
        run = json.loads((d / "run.json").read_text(encoding="utf-8"))
        if run.get("experiment") != "E004" or run.get("status") != "completed":
            raise ValueError(f"{d}: not a completed E004 run (status {run.get('status')})")
        graph = json.loads((d / "graph.json").read_text(encoding="utf-8"))
        machine = json.loads((d / "machine.json").read_text(encoding="utf-8"))
        rows = read_jsonl(d / "measurements.jsonl")
        for r in rows:
            r["run_id"] = run["run_id"]
        measurements += rows
        loads = [x for r in rows for x in (r["load_before"][0], r["load_after"][0])]
        ratios = [r["cpu_s"] / r["wall_s"] for r in rows if r["wall_s"] > 0]
        runs.append({"run_id": run["run_id"], "code_sha": run["code_sha"],
                     "run_json_sha256": sha256(d / "run.json"), "seed": run["seed"],
                     "graph": {k: graph[k] for k in ("mix", "blocks", "views", "claims",
                                                     "attributions", "evidence_links",
                                                     "supersessions", "versions", "triples",
                                                     "bindings", "admitted_bindings",
                                                     "window_versions", "prefix_build_s",
                                                     "skipped_cells")},
                     "query_ms_by_family": diagnostics_by_family(graph["query_diagnostics"]),
                     "machine": machine, "measurements": len(rows),
                     "load_1min": _spread(loads), "cpu_wall_ratio": _spread(ratios)})
    return measurements, runs


def diagnostics_by_family(diagnostics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Median query time per family in each timed form, over block 0's views, and over the seeded
    sample of other views (median and maximum); whether every form returned the same number of
    rows wherever several ran; whether the probe's inlining gave the engine's text.

    Forms (`grace.eval.runner.probes.scale.query_diagnostics`): since 2026-11-26 `compiled` is
    the engine's text (single-member constants inlined), `inlined` the probe's inlining of the
    pre-change form and `values` the pre-change form. In runs of design version 2 (code before
    that date) `compiled` was the pre-change form and there is no `values`."""
    out: dict[str, Any] = {}
    for family in sorted({d["family"] for d in diagnostics}):
        ds = [d for d in diagnostics if d["family"] == family and d.get("block0", True)]
        entry: dict[str, Any] = {"n": len(ds)}
        for form in ("compiled", "inlined", "values"):
            timed = [d[f"{form}_ms"] for d in ds if f"{form}_ms" in d]
            if timed:
                entry[f"{form}_ms"] = round(statistics.median(timed), 4)
        sample = [d for d in diagnostics if d["family"] == family and not d.get("block0", True)]
        if sample:
            entry["sample"] = {"n": len(sample),
                               "compiled_ms": _spread([d["compiled_ms"] for d in sample]),
                               "with_rows": sum(1 for d in sample if d["compiled_rows"])}
        agree = [len({d[k] for k in d if k.endswith("_rows")}) == 1
                 for d in diagnostics if d["family"] == family]
        entry["rows_agree"] = all(agree)
        texts = [d["inlined_text_equal"] for d in diagnostics
                 if d["family"] == family and "inlined_text_equal" in d]
        if texts:
            entry["inlined_text_equal"] = all(texts)
        out[family] = entry
    return out


def _spread(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {"min": round(min(values), 3), "median": round(statistics.median(values), 3),
            "max": round(max(values), 3)}


def costs(m: Mapping[str, Any]) -> dict[str, float]:
    """Decision costs of one measurement, in ms."""
    periods = m["reads"]
    writes = m["writes"]
    s = m["strategy_summary"]
    write_ms = s["match_ms"] / writes
    read_ms = (s["check_db_ms"] + s["maintain_db_ms"]) / periods
    w = m["writes_per_read"]
    period = w * write_ms + read_ms
    return {"write_ms": write_ms, "read_ms": read_ms, "period_ms": period,
            "per_write_ms": period / w, "checks_per_read": s["checks"] / periods,
            "rebuilds": s["rebuilds"], "citation_repairs": s["citation_repairs"],
            "units_rendered": s["units_rendered"], "llm_calls": s["llm_calls"]}


def cell_key(m: Mapping[str, Any]) -> tuple:
    return tuple(m[k] for k in CELL)


def _geo(values: Sequence[float]) -> float:
    return math.exp(statistics.fmean(math.log(v) for v in values))


def _ratio(a: float, b: float) -> float:
    # A zero cost (no checks at all) is floored at 1 microsecond so the log is defined.
    return max(a, 1e-3) / max(b, 1e-3)


def pairs(measurements: Iterable[Mapping[str, Any]]) -> dict[tuple, dict[tuple, dict[str, Any]]]:
    """cell -> (seed, repetition) -> arm -> measurement."""
    out: dict[tuple, dict[tuple, dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    for m in measurements:
        out[cell_key(m)][tuple(m[k] for k in PAIR)][m["arm"]] = m
    return out


def _cv(values: Sequence[float]) -> float | None:
    if len(values) < 2 or statistics.fmean(values) == 0:
        return None
    return statistics.stdev(values) / statistics.fmean(values)


def cell_table(measurements: Sequence[Mapping[str, Any]], arms: Sequence[str],
               rng: random.Random) -> list[dict[str, Any]]:
    table = []
    for cell, by_pair in sorted(pairs(measurements).items(), key=lambda kv: _sortable(kv[0])):
        complete = {p: a for p, a in by_pair.items() if all(x in a for x in arms)}
        row: dict[str, Any] = dict(zip(CELL, cell, strict=True))
        row["pairs"] = len(complete)
        for arm in arms:
            cs = [costs(a[arm]) for a in complete.values()]
            entry = {k: round(statistics.median(c[k] for c in cs), 5)
                     for k in ("write_ms", "read_ms", "period_ms", "per_write_ms",
                               "checks_per_read")}
            entry["period_ms_min"] = round(min(c["period_ms"] for c in cs), 5)
            entry["period_ms_max"] = round(max(c["period_ms"] for c in cs), 5)
            by_seed = defaultdict(list)
            for p, a in complete.items():
                by_seed[p[0]].append(costs(a[arm])["period_ms"])
            within = [v for v in (_cv(x) for x in by_seed.values()) if v is not None]
            entry["cv_repetitions"] = round(statistics.fmean(within), 4) if within else None
            seed_means = [statistics.fmean(x) for x in by_seed.values()]
            entry["cv_seeds"] = round(_cv(seed_means), 4) if _cv(seed_means) is not None else None
            entry["rebuilds"] = sum(c["rebuilds"] for c in cs)
            entry["citation_repairs"] = sum(c["citation_repairs"] for c in cs)
            entry["units_rendered"] = sum(c["units_rendered"] for c in cs)
            entry["llm_calls"] = sum(c["llm_calls"] for c in cs)
            if arm != REFERENCE and REFERENCE in arms:
                ratios = [_ratio(costs(a[arm])["period_ms"], costs(a[REFERENCE])["period_ms"])
                          for a in complete.values()]
                entry["ratio_to_pull"] = round(_geo(ratios), 4)
                lo, hi = _boot_ci(ratios, rng)
                entry["ratio_ci"] = [round(lo, 4), round(hi, 4)]
                entry["cheaper_than_pull"] = ("yes" if hi < 1 else "no" if lo > 1
                                              else "undecided")
            row[arm] = entry
        if "hybrid" in arms and REFERENCE in arms:
            row["repairs_differ"] = sum(a["hybrid"]["repairs"] != a[REFERENCE]["repairs"]
                                        for a in complete.values())
        table.append(row)
    return table


def _sortable(cell: tuple) -> tuple:
    return tuple((1, 0) if v == "all" else (0, v) for v in cell)


def _boot_ci(ratios: Sequence[float], rng: random.Random) -> tuple[float, float]:
    logs = [math.log(r) for r in ratios]
    if len(logs) == 1:
        return ratios[0], ratios[0]
    reps = sorted(statistics.fmean(rng.choices(logs, k=len(logs))) for _ in range(BOOTSTRAP))
    return math.exp(reps[int(0.025 * BOOTSTRAP)]), math.exp(reps[int(0.975 * BOOTSTRAP) - 1])


def crossing(levels: Sequence[float], logs: Sequence[float]) -> tuple[str, float | None]:
    """Where the log ratio first changes sign along `levels` (interpolated in log level)."""
    if all(v < 0 for v in logs):
        return "cheaper_everywhere", None
    if all(v > 0 for v in logs):
        return "dearer_everywhere", None
    for i in range(1, len(levels)):
        a, b = logs[i - 1], logs[i]
        if a == 0:
            return "crosses", levels[i - 1]
        if (a < 0) != (b < 0) or b == 0:
            x0, x1 = math.log(levels[i - 1]), math.log(levels[i])
            t = a / (a - b)
            return "crosses", math.exp(x0 + t * (x1 - x0))
    return "crosses", levels[-1]


def crossovers(measurements: Sequence[Mapping[str, Any]], arms: Sequence[str], axis: str,
               rng: random.Random) -> list[dict[str, Any]]:
    """Crossover of each arm against pull along `axis`, per combination of the other factors."""
    others = [k for k in CELL if k != axis]
    groups: dict[tuple, dict[Any, list[dict[str, dict[str, Any]]]]] = defaultdict(
        lambda: defaultdict(list))
    for cell, by_pair in pairs(measurements).items():
        c = dict(zip(CELL, cell, strict=True))
        for a in by_pair.values():
            if all(x in a for x in arms):
                groups[tuple(c[k] for k in others)][c[axis]].append(a)
    out = []
    for key, by_level in sorted(groups.items(), key=lambda kv: _sortable(kv[0])):
        levels = sorted(by_level)
        if len(levels) < 2 or any(isinstance(v, str) for v in levels):
            continue
        for arm in arms:
            if arm == REFERENCE:
                continue
            ratios = {lv: [_ratio(costs(a[arm])["period_ms"], costs(a[REFERENCE])["period_ms"])
                           for a in by_level[lv]] for lv in levels}
            point = [statistics.fmean(math.log(r) for r in ratios[lv]) for lv in levels]
            kind, x = crossing(levels, point)
            boots = []
            for _ in range(BOOTSTRAP):
                sample = [statistics.fmean(math.log(r) for r in rng.choices(ratios[lv],
                                                                            k=len(ratios[lv])))
                          for lv in levels]
                boots.append(crossing(levels, sample))
            crossed = sorted(v for k, v in boots if k == "crosses")
            share = {k: round(sum(b[0] == k for b in boots) / BOOTSTRAP, 4)
                     for k in ("cheaper_everywhere", "dearer_everywhere", "crosses")}
            out.append({
                **dict(zip(others, key, strict=True)), "axis": axis, "arm": arm,
                "levels": levels, "ratio_by_level": [round(math.exp(v), 4) for v in point],
                "kind": kind, "crossover": round(x, 3) if x is not None else None,
                "crossover_ci": ([round(crossed[int(0.025 * len(crossed))], 3),
                                  round(crossed[max(int(0.975 * len(crossed)) - 1, 0)], 3)]
                                 if crossed else None),
                "bootstrap_share": share})
    return out


def summarise(measurements: Sequence[Mapping[str, Any]], arms: Sequence[str], seed: int = 0
              ) -> dict[str, Any]:
    rng = random.Random(f"E004-bootstrap:{seed}")
    table = cell_table(measurements, arms, rng)
    return {"cells": table,
            "crossover_writes_per_read": crossovers(measurements, arms, "writes_per_read", rng),
            "crossover_views": crossovers(measurements, arms, "views", rng),
            "crossover_blocks": crossovers(measurements, arms, "blocks", rng),
            "checks": {"repairs_differ_pull_hybrid": sum(r.get("repairs_differ", 0)
                                                         for r in table),
                       "llm_calls": sum(r[a]["llm_calls"] for r in table for a in arms)}}


def write_summary(dirs: Sequence[Path], out: Path, config: Mapping[str, Any]) -> Path:
    measurements, runs = load_runs(dirs)
    arms = list(config["arms"])
    summary = {"experiment": "E004", "runs": runs, "arms": dict(config["arms"]),
               "n_measurements": len(measurements), "bootstrap": BOOTSTRAP,
               **summarise(measurements, arms)}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    path = out / "summary.json"
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = ["cell_table", "costs", "crossing", "crossovers", "load_runs", "summarise",
           "write_summary"]
