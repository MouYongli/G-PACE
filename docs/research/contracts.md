# Interface Contracts

This file is the single specification of the interfaces between modules and tasks. Workers implement against it without reading each other's code; managers review against it; contract tests in `tests/contracts/` and fixtures in `tests/fixtures/` make it executable.

## How to change a contract

- Each section has one owner. Only the owner (or a PR the owner approves) may change it. Owners are assigned in the Issue that introduces the section; `TBD` means no change is allowed until one is assigned.
- A change PR updates, in the same PR: the section text, its `Version` line, the fixtures, the contract tests, and a list of experiments whose results it invalidates.
- Freeze the sections a task depends on, and push them to the task branch, before dispatching workers (see `.agents/roles/manager.md`).
- Split this file into `docs/contracts/` when JSON Schema files are added, a section grows beyond about 100 lines, or two owners change it concurrently.

Conventions used below: `MUST`, `MUST NOT` and `MAY` are normative. All files are UTF-8 JSON Lines (one JSON object per line) unless stated otherwise.

## Benchmark input

> Placeholder (v0.1): this sample-level record and the prediction record below are replaced by history, message and question records in task T001 (`docs/work/tasks/T001-record-contracts.md`).

Owner: TBD (data owner) · Version: 0.1 · Producer: benchmark adapters · Consumers: model runners, evaluator

One record per sample.

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `benchmark` | string | yes | Non-empty; equals the `benchmark` key in `configs/benchmarks/<name>.yaml`. |
| `split` | string | yes | Non-empty; an official split name listed in the config. |
| `sample_id` | string | yes | Non-empty; unique within one benchmark version and split. Keep the original string, including leading zeros; never cast to a number. |
| `input` | string or object | yes | Structure defined on the benchmark card in `docs/research/benchmarks.md`. |
| `reference` | any JSON value or `null` | yes | `null` only for splits without public labels. |

Additional fields MAY be present and MUST be documented on the benchmark card.

Example:

```json
{"benchmark": "bench-a", "split": "fixture", "sample_id": "001", "input": "synthetic 001", "reference": "0"}
```

Adapter obligations:

- Fail on duplicate keys, missing required fields and empty strings. The error names the source file, the source line or record index, and the offending key.
- Compare per-split counts with the manifest; fail on any mismatch.
- Never write into `$PROJECT_ROOT/data`; write converted output to `RUN_DIR`.

## Prediction output

Owner: TBD (evaluation owner) · Version: 0.1 · Producer: model runners · Consumer: evaluator

One record per sample prediction.

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `benchmark` | string | yes | Same value as in the input record. |
| `split` | string | yes | Same value as in the input record. |
| `sample_id` | string | yes | Same value as in the input record. |
| `prediction` | any JSON value | yes | The parsed prediction used for scoring. |

The alignment key is the triple `(benchmark, split, sample_id)` within one data version. Additional fields such as `raw_output` MAY be present and are ignored by the evaluator; keeping the unparsed model output in `raw_output` is recommended so scores can be recomputed.

Example:

```json
{"benchmark": "bench-a", "split": "fixture", "sample_id": "002", "prediction": "1", "raw_output": "Answer: 1"}
```

Evaluator obligations:

- Match by key; accept any line order.
- Abort scoring on duplicate keys, missing keys, extra keys, or more than one split in a file. The error reports the count per category and up to five example keys each.
- A prediction that is present but unparsable is not missing; it is handled by the invalid-output policy in [Evaluation](#evaluation).

## Evaluation

Owner: TBD (evaluation owner) · Version: 0.1

Before any formal comparison, register for each benchmark on its card: official metric, metric direction, evaluation code and version, denominator, and invalid-output policy (count as wrong, or exclude and report).

Each scoring call writes one `metrics.json` object:

| Field | Type | Rules |
| --- | --- | --- |
| `benchmark`, `split` | string | As in the input. |
| `seed` | integer | Seed of the run that produced the predictions. |
| `metric` | string | Registered metric name. |
| `value` | number | Metric value on the registered denominator. |
| `n_total` | integer | Samples in the split. |
| `n_scored` | integer | Samples that entered the denominator. |
| `n_invalid` | integer | Present but unparsable predictions. |
| `evaluator_version` | string | Evaluator code SHA or package version. |

Reporting rules:

- Report every benchmark, split and seed separately, with counts.
- Multi-seed summaries give the mean, the sample standard deviation and the number of runs.
- Cross-benchmark averages follow `docs/work/decisions/D002-evaluation-aggregation.md`; never average without a recorded normalization and weighting.

Required regression tests: empty prediction file, duplicate key, missing key, extra key, mixed splits, shuffled order, unparsable prediction.

## Experiment run

Owner: TBD (integration owner) · Version: 0.1

Every formal run owns one directory, created exclusively (fail if it exists, or use `tempfile.mkdtemp`):

```text
<RUN_DIR>/<experiment>/<run-id>/
  run.json              status and provenance (below)
  resolved-config.yaml  the fully resolved config actually used
  predictions.jsonl     see Prediction output
  metrics.json          see Evaluation
  run.log               stdout and stderr
  report.yaml           written with the experiment-report skill
  cache/                library caches for this run only
```

`RUN_DIR` is `$PROJECT_ROOT/<runs_root>/T<NNN>/artifacts/<worker>/`, with `runs_root` from `configs/paths.yaml`. It lives in the main checkout, outside every worktree, so removing a worktree never removes evidence.

Run ID format: `<experiment>-<UTC timestamp YYYYMMDDTHHMMSSZ>-<4 hex>`, for example `E001-20261121T093000Z-a1b2`.

`run.json` fields:

| Field | Type | Rules |
| --- | --- | --- |
| `run_id`, `experiment` | string | As above. |
| `status` | string | `running`, then exactly one of `completed` or `failed`. |
| `code_sha` | string | Full 40-character SHA. |
| `code_dirty` | boolean | MUST be `false` for a `completed` formal run. |
| `config_path`, `config_sha256` | string | Source config and checksum of `resolved-config.yaml`. |
| `data` | list of objects | One per benchmark: `benchmark`, `version`, `manifest_sha256`, `split`, and the resolved absolute `path`. |
| `project_root` | string | Absolute `PROJECT_ROOT` resolved at run time. |
| `seed` | integer | |
| `command` | string | Exact command line. |
| `environment` | object | `python`, `lock_sha256`, `host`, `device`. |
| `started_at`, `finished_at` | string | ISO 8601 UTC; `finished_at` is `null` while running. |
| `n_samples` | integer | Samples processed. |
| `failure` | string or `null` | Cause when `status` is `failed`. |

Lifecycle:

1. Create the directory and write `run.json` with `status: running`.
2. Write all artifacts, then check the sample count, metrics and exit code.
3. Only then set `status: completed` (or `failed` with `failure`) and `finished_at`.
4. Retries use a new run ID. Never delete or overwrite an earlier run's evidence.
