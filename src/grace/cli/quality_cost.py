"""E014 quality-versus-cost tables, cumulative cost curves and break-even (plan 8.2, 8.3).

    uv run python -m grace.cli.quality_cost \\
        --config configs/experiments/E014-dev-quality-cost.yaml \\
        --manifest <runs manifest .yaml> --out <new directory under the runs root> [--probe RUN_DIR]

The manifest (a file under the runs root, not tracked) lists, for one target, every system and
budget with its run directories (system or read runs; a read run carries its ingest upstream) and
the score runs of the same reads, paths relative to the runs root:

    target: locomo-dev
    entries:
      - {system: grace, budget: 1024, runs: [E014/.../E014-...], scores: [E014/.../E014-...]}

Pricing and the three accountings of cached tokens are those of
`grace.eval.analysis.metrics.cost.quality_cost` and the `cost` section of the config. Writes into
`--out` (created exclusively; it never writes into an input run):

- `quality.csv`: per system and budget, reads, F1, successes (F1 >= threshold), unknown and
  invalid outputs, and the mean system cost per read (ingestion included) in every ledger;
- `ledgers.csv`: per system and budget, W, U and A totals per ledger;
- `similar-quality.csv`: per system, the cheapest budget whose F1 reaches the reference minus each
  margin;
- `success.csv`: cost per successful read (total cost including failures over successes);
- `cumulative.csv` and `crossings.json`: cumulative cost over reads per history at the c marks,
  ingestion paid before the first read; crossing read counts against the break-even baseline;
- `break-even.csv` and `c-star.json`: M*(c) per history over the c grid and the smallest c from
  which payback stays within the history's own reads;
- `cache.json`: unreported runs, the static prefix per prompt and the probe's cached tokens;
- `inputs.json`: code SHA, command and every run read with the SHA-256 of its run.json.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shlex
import sys
from pathlib import Path

import yaml

from grace.config.paths import REPO_ROOT, shared_dir
from grace.eval.analysis.metrics.cost import quality_cost as qc
from grace.eval.analysis.metrics.cost.ledger import SYSTEM, RunCost, load_run
from grace.eval.runner.harness import rundir
from grace.llm.prompts import PROMPTS_DIR

# Prompts without a system message of their own that continue another prompt's conversation: the
# continued prompt's fixed prefix is theirs too (configs/common/prompts.yaml notes).
CONTINUES = {"plan-query-repair": "plan-query"}
MARK = "⁣E014-MARK⁣"


def static_prefixes(counter, block: int) -> dict[str, dict]:
    """prompt_sha256 -> {name, tokens}: block-aligned tokens of the rendered fixed system message
    of each pinned prompt (the chat-template prefix up to the start of the user turn)."""
    pinned = yaml.safe_load((REPO_ROOT / "configs/common/prompts.yaml").read_text())["prompts"]
    raw = {}
    for name in pinned:
        system = (PROMPTS_DIR / name / "system.txt")
        text = system.read_text(encoding="utf-8") if system.exists() else ""
        if not text.strip():
            raw[name] = None
            continue
        rendered = counter.render([{"role": "system", "content": text},
                                   {"role": "user", "content": MARK}])
        raw[name] = counter.count_text(rendered[:rendered.index(MARK)])
    out = {}
    for name, spec in pinned.items():
        tokens = raw.get(name)
        if tokens is None and name in CONTINUES:
            tokens = raw.get(CONTINUES[name])
        out[spec["sha256"]] = {"name": name, "tokens": qc.block_floor(tokens or 0, block)}
    return out


def write_csv(path: Path, header, rows) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def dump(path: Path, data) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_scores(score_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (score_dir / "scores.jsonl").read_text().splitlines()
            if line.strip()]


def budget_key(value) -> str:
    return str(value)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--probe", type=Path, default=None,
                        help="probe read run on a server that reports cached tokens")
    parser.add_argument("--counter", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    config = yaml.safe_load(args.config.read_text())
    manifest = yaml.safe_load(args.manifest.read_text())
    runs_root = shared_dir("runs_root").resolve()
    out = args.out.resolve()
    if runs_root not in out.parents:
        raise SystemExit(f"--out {out} is not under the runs root {runs_root}")
    out.mkdir(parents=True, exist_ok=False)
    cost = config["cost"]
    marks = {name: float(v) for name, v in cost["c_marks"].items()}
    steps = int(cost.get("c_grid_steps", 100))
    grid = sorted({round(i / steps, 6) for i in range(steps + 1)} | set(marks.values()))
    ledger_cs = {"logical": 1.0, "computed": 0.0, **{f"c={v:.3f}": v for v in marks.values()}}
    threshold = float(str(config["metrics"]["cost_per_success"]["success"]).split(">=")[1])

    # Systems ------------------------------------------------------------------------------
    systems: dict[tuple[str, str], qc.System] = {}
    scores: dict[tuple[str, str], list[dict]] = {}
    inputs = []
    for entry in manifest["entries"]:
        key = (entry["system"], budget_key(entry["budget"]))
        loaded: list[RunCost] = []
        for rel in entry["runs"]:
            run = load_run(runs_root / rel)
            for item in (run, *run.upstream):
                if item.run.get("status") != "completed":
                    raise SystemExit(f"{key}: run {item.run_id} is {item.run.get('status')}")
                inputs.append({"system": key[0], "budget": key[1], "run_id": item.run_id,
                               "stage": item.run.get("stage"), "code_sha": item.run["code_sha"],
                               "path": item.run_dir.resolve().as_posix(),
                               "run_json_sha256": hashlib.sha256(
                                   (item.run_dir / "run.json").read_bytes()).hexdigest()})
            loaded.append(run)
        systems[key] = qc.System(f"{key[0]}@{key[1]}", loaded)
        rows = []
        for rel in entry.get("scores", []):
            score_dir = runs_root / rel
            inputs.append({"system": key[0], "budget": key[1], "run_id": score_dir.name,
                           "stage": "score", "path": score_dir.resolve().as_posix(),
                           "run_json_sha256": hashlib.sha256(
                               (score_dir / "run.json").read_bytes()).hexdigest()})
            rows += read_scores(score_dir)
        reads = {rid for _, rid, _ in systems[key].read_rows()}
        if rows and {r["read_id"] for r in rows} != reads:
            raise SystemExit(f"{key}: scores do not cover exactly the reads of the runs")
        scores[key] = rows

    # Accountings --------------------------------------------------------------------------
    block = int(cost["cache_imputation"]["block_tokens"])
    if args.counter == "none":
        prefixes = {}
    else:
        from grace.llm.tokens import HFTokenCounter
        counter = HFTokenCounter.from_model_config(REPO_ROOT / config["models"]["answer"])
        prefixes = static_prefixes(counter, block)
    all_records = [r for s in systems.values() for r in s.records]
    unreported = qc.unreported_runs(all_records)
    probe = {}
    if args.probe is not None:
        probe_run = load_run(args.probe, include_ingest=False)
        if probe_run.run.get("status") != "completed":
            raise SystemExit(f"probe {probe_run.run_id} is not completed")
        inputs.append({"system": "probe", "budget": None, "run_id": probe_run.run_id,
                       "stage": "read", "path": probe_run.run_dir.resolve().as_posix(),
                       "run_json_sha256": hashlib.sha256(
                           (probe_run.run_dir / "run.json").read_bytes()).hexdigest()})
        probe = qc.probe_cached_means(probe_run.records)
    weightings = {name: dict(w or {}) for name, w in cost["weights"].items()}

    def pricer(accounting: str, weighting: str) -> qc.Pricer:
        return qc.Pricer(accounting, weightings[weighting], unreported,
                         {sha: p["tokens"] for sha, p in prefixes.items()},
                         {t: v["mean_cached"] for t, v in probe.items()})

    accountings = [a for a in qc.ACCOUNTINGS if a != "probe" or probe]
    pricers = {(a, w): pricer(a, w) for a in accountings for w in weightings}
    dump(out / "cache.json", {
        "unreported_runs": sorted([list(k) for k in unreported]),
        "static_prefix_tokens": {p["name"]: p["tokens"] for p in prefixes.values()},
        "block_tokens": block, "probe": probe,
        "probe_run": str(args.probe) if args.probe else None})

    # Quality and cost per read ------------------------------------------------------------
    quality_rows, ledger_rows, success_rows = [], [], []
    points: dict[str, list[dict]] = {}
    for (name, budget), system in systems.items():
        n_reads = len(system.read_rows())
        summary = qc.f1_summary(scores[(name, budget)], threshold)
        for (accounting, weighting), p in pricers.items():
            for ledger, c in ledger_cs.items():
                total = qc.total_cost(system, p, c)
                parts = {cat: p.price([r for r in system.records if r.category == cat], c)
                         for cat in SYSTEM}
                per_read = total / n_reads if n_reads else None
                quality_rows.append((name, budget, n_reads, summary["f1"], summary["n_success"],
                                     summary["n_unknown"], summary["n_invalid"], accounting,
                                     weighting, ledger, round(per_read, 3)))
                ledger_rows.append((name, budget, accounting, weighting, ledger,
                                    *(round(parts[c_], 3) for c_ in SYSTEM), round(total, 3)))
                success_rows.append((name, budget, accounting, weighting, ledger, n_reads,
                                     summary["n_success"],
                                     None if not summary["n_success"]
                                     else round(total / summary["n_success"], 3)))
                if (accounting, weighting, ledger) == ("imputed", "tokens", "logical"):
                    points.setdefault(name, []).append(
                        {"budget": budget, "f1": summary["f1"], "tokens": per_read})
    header = ("system", "budget", "reads", "f1", "n_success", "n_unknown", "n_invalid",
              "accounting", "weighting", "ledger", "cost_per_read")
    write_csv(out / "quality.csv", header, quality_rows)
    write_csv(out / "ledgers.csv", ("system", "budget", "accounting", "weighting", "ledger",
                                    "W", "U", "A", "total"), ledger_rows)
    write_csv(out / "success.csv", ("system", "budget", "accounting", "weighting", "ledger",
                                    "reads", "n_success", "cost_per_success"), success_rows)

    # Tokens at similar quality (logical tokens: no accounting dependence) ------------------
    sq = config["metrics"]["tokens_at_similar_quality"]
    ref_name, _, ref_budget = sq["reference"].partition("@")
    ref = next((pt for pt in points.get(ref_name, []) if pt["budget"] == ref_budget), None)
    sq_rows = []
    if ref is not None and ref["f1"] is not None:
        for margin in sq["margins"]:
            target = ref["f1"] - float(margin)
            for name, pts in sorted(points.items()):
                best = qc.cheapest_at_quality(pts, target)
                sq_rows.append((name, margin, round(target, 4),
                                None if best is None else best["budget"],
                                None if best is None else best["f1"],
                                None if best is None else round(best["tokens"], 1)))
    write_csv(out / "similar-quality.csv", ("system", "margin", "target_f1", "budget", "f1",
                                            "logical_tokens_per_read"), sq_rows)

    # Cumulative curves and break-even against the baseline ---------------------------------
    base_name = cost["baseline_for_break_even"]
    base_key = next((k for k in systems if k[0] == base_name), None)
    cum_rows, crossings, be_rows, cstars = [], [], [], {}
    cum_config = config["metrics"]["cumulative_over_reads"]
    seed = cum_config.get("seed")
    cum_budgets = {budget_key(b) for b in cum_config.get("budgets", ["1024", "full"])}
    if base_key is not None:
        baseline = systems[base_key]
        for (accounting, weighting), p in pricers.items():
            for mark, c in [("logical", 1.0), ("computed", 0.0), *marks.items()]:
                base_curves = qc.cumulative(baseline, p, c, upfront_writes=True)
                for key, system in systems.items():
                    if key[1] not in cum_budgets:
                        continue
                    orders = [("run", None)]
                    if seed is not None and key != base_key:
                        orders.append((f"seed={seed}",
                                       lambda rows: random.Random(seed).sample(rows, len(rows))))
                    for order_name, order in orders:
                        curves = qc.cumulative(system, p, c, upfront_writes=True, order=order)
                        for h, pts in curves.items():
                            cum_rows += [(key[0], key[1], h, accounting, weighting, mark, c,
                                          order_name, m, round(v, 3))
                                         for m, v in enumerate(pts, start=1)]
                            if key != base_key and h in base_curves:
                                crossings.append({
                                    "system": key[0], "budget": key[1], "history_id": h,
                                    "accounting": accounting, "weighting": weighting,
                                    "c": c, "mark": mark, "order": order_name,
                                    "reads": len(pts),
                                    "crossing": qc.crossing(pts, base_curves[h]),
                                    "final_system": round(pts[-1], 1),
                                    "final_baseline": round(base_curves[h][-1], 1)})
            for key, system in systems.items():
                if key == base_key or not key[0].startswith("grace"):
                    continue
                be = qc.break_even(system, baseline, p, p, grid)
                be_rows += [(key[0], key[1], accounting, weighting, *b.to_row()) for b in be]
                at_marks = {f"{m}={c}": {b.history_id: {"M*": b.m_star, "delta": round(b.delta, 1),
                                                        "W": round(b.w, 1)}
                                         for b in be if b.c == c} for m, c in marks.items()}
                cstars.setdefault(f"{key[0]}@{key[1]}", {})[f"{accounting}/{weighting}"] = {
                    "c_star": qc.c_star(be), **at_marks}
    write_csv(out / "cumulative.csv", ("system", "budget", "history_id", "accounting",
                                       "weighting", "mark", "c", "order", "reads",
                                       "cumulative"), cum_rows)
    dump(out / "crossings.json", crossings)
    write_csv(out / "break-even.csv", ("system", "budget", "accounting", "weighting",
                                       "history_id", "c", "W", "system_read", "baseline_read",
                                       "delta", "m_star", "reads"), be_rows)
    dump(out / "c-star.json", cstars)

    code = rundir.code_state()
    dump(out / "inputs.json", {
        "command": " ".join(["python -m grace.cli.quality_cost",
                             *(shlex.quote(a) for a in argv)]),
        "code_sha": code.sha, "code_dirty": code.dirty,
        "config_sha256": rundir.file_sha256(args.config),
        "manifest_sha256": rundir.file_sha256(args.manifest), "manifest": manifest,
        "inputs": inputs})
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
