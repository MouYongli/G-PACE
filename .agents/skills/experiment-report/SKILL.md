---
name: experiment-report
description: Write the report for a formal experiment run. Use whenever a formal run finishes, including failed or partial runs, before any number is quoted in a PR, result page or paper.
---

# Experiment Report

1. Check that `RUN_DIR/<experiment>/<run-id>/run.json` follows `docs/research/contracts.md#experiment-run` and that its `status` is final (`completed` or `failed`).
2. Copy `report.yaml` from this skill to `RUN_DIR/<experiment>/<run-id>/report.yaml` and fill it from `run.json`, `metrics.json` and `run.log`. Do not retype numbers by hand; copy them from the files.
3. Report scored and invalid counts next to every metric.
4. Add a row to the Runs table of `docs/work/experiments/E<NNN>-*.md` for every run (any status). Only `completed` runs may be copied into its Results section; link each number to the run ID and code SHA. Append a dated line to its `## Log`.
5. A failed run still gets a report; record the failure cause and keep the directory.
