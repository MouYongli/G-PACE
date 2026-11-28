---
id: E007
title: "Ablation G: writer scale, thinking, granularity"
created: 2026-11-23
---

# E007 · Ablation G: writer scale, thinking, granularity

## Question

How much graph quality and answer accuracy does a larger writer or thinking recover, and what do the three extraction granularities cost? Serves RQ3. The granularity result fixes the main configuration (plan section 8.4).

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | Controlled sequences (5 density-10 sequences of the T015 model-rendered development set, 1,000 messages); LoCoMo development histories (conv-26, conv-49, 928 messages); the 40 annotated T024 segments (578 messages, for E006 scoring) |
| Systems and baselines | Writer: primary versus larger same-family model; thinking off versus on; granularity per message, per segment, per session |
| Metrics | Writer tokens; graph quality as in E006; answer accuracy; parse-failure and repair rates |
| Seeds and budget | Seed 0, temperature 0 in every arm; max_tokens 4096 (message, segment-8), 12288 (session), 16384 (thinking) |
| Config | `configs/experiments/E007-ablation-g-writer.yaml` (driver `grace.cli.writer_ablation`); recall proxy `configs/experiments/E007-recall-locomo.yaml`; graph quality with E006's `grace.cli.graph_quality score` |

## Acceptance

- [ ] Every number traces to a run report.

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| `E007-dry-seg-1` | 2026-11-28 | failed | `b7c62c3` | dry run (writer 32b-segment8, 2 T024 segments, uncommitted code); `runs/E007/artifacts/w01-E007/E007/E007-dry-seg-1/` |
| `E007-dry-think-1` | 2026-11-28 | completed | `d88d908` | dry run (writer 32b-segment8-think, 1 T024 segment, superseded mode); `runs/E007/artifacts/w01-E007/E007/E007-dry-think-1/` |
| `E007-20261128T001630Z-aed4` | 2026-11-28 | completed | `d88d908` | writer 32b-segment8 on t024-segments; superseded (segment-only mode, graphs not read by the E006 scorer); `runs/E007/artifacts/w01-E007/E007/E007-20261128T001630Z-aed4/report.yaml` |
| `E007-20261128T001630Z-da86` | 2026-11-28 | completed | `d88d908` | writer 8b-segment8 on locomo-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T001630Z-da86/report.yaml` |
| `E007-20261128T001630Z-e513` | 2026-11-28 | completed | `d88d908` | writer 32b-segment8 on locomo-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T001630Z-e513/report.yaml` |
| `E007-20261128T001937Z-22db` | 2026-11-28 | failed | `d88d908` | writer 32b-session on locomo-dev; aborted by the worker within a minute: started with an untracked test file (code_dirty true); relaunched under; `runs/E007/artifacts/w01-E007/E007/E007-20261128T001937Z-22db/report.yaml` |
| `E007-20261128T001937Z-59b7` | 2026-11-28 | failed | `d88d908` | writer 32b-message on t024-segments; aborted by the worker within a minute: started with an untracked test file (code_dirty true); relaunched under; `runs/E007/artifacts/w01-E007/E007/E007-20261128T001937Z-59b7/report.yaml` |
| `E007-20261128T001937Z-6b6b` | 2026-11-28 | failed | `d88d908` | writer 32b-session on t024-segments; aborted by the worker within a minute: started with an untracked test file (code_dirty true); relaunched under; `runs/E007/artifacts/w01-E007/E007/E007-20261128T001937Z-6b6b/report.yaml` |
| `E007-20261128T001937Z-c0e1` | 2026-11-28 | failed | `d88d908` | writer 32b-message on locomo-dev; aborted by the worker within a minute: started with an untracked test file (code_dirty true); relaunched under; `runs/E007/artifacts/w01-E007/E007/E007-20261128T001937Z-c0e1/report.yaml` |
| `E007-20261128T002008Z-1f87` | 2026-11-28 | completed | `1343fb6` | writer 32b-session on locomo-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002008Z-1f87/report.yaml` |
| `E007-20261128T002008Z-860d` | 2026-11-28 | completed | `1343fb6` | writer 32b-message on t024-segments; superseded (segment-only mode, graphs not read by the E006 scorer); `runs/E007/artifacts/w01-E007/E007/E007-20261128T002008Z-860d/report.yaml` |
| `E007-20261128T002008Z-9da7` | 2026-11-28 | failed | `1343fb6` | writer 32b-session on t024-segments; ParseException: Expected SelectQuery, found end of text  (at char 336), (line:9, col:14); `runs/E007/artifacts/w01-E007/E007/E007-20261128T002008Z-9da7/report.yaml` |
| `E007-20261128T002008Z-e01f` | 2026-11-28 | completed | `1343fb6` | writer 32b-message on locomo-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002008Z-e01f/report.yaml` |
| `E007-20261128T002410Z-581d` | 2026-11-28 | completed | `d6aec1d` | writer 32b-session on t024-segments; superseded (segment-only mode, graphs not read by the E006 scorer); `runs/E007/artifacts/w01-E007/E007/E007-20261128T002410Z-581d/report.yaml` |
| `E007-20261128T002410Z-8686` | 2026-11-28 | completed | `d6aec1d` | writer 8b-segment8 on t024-segments; superseded (segment-only mode, graphs not read by the E006 scorer); `runs/E007/artifacts/w01-E007/E007/E007-20261128T002410Z-8686/report.yaml` |
| `E007-20261128T002500Z-7946` | 2026-11-28 | completed | `d6aec1d` | writer 8b-session on locomo-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002500Z-7946/report.yaml` |
| `E007-20261128T002500Z-a973` | 2026-11-28 | completed | `d6aec1d` | writer 32b-session on changeseq-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002500Z-a973/report.yaml` |
| `E007-20261128T002500Z-e19f` | 2026-11-28 | failed | `d6aec1d` | writer 32b-segment8-think on t024-segments; aborted by the worker: superseded by the context+segment mode of E006 (commit 714577d); the segment-only graph; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002500Z-e19f/report.yaml` |
| `E007-20261128T002500Z-ff7d` | 2026-11-28 | completed | `d6aec1d` | writer 32b-segment8 on changeseq-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002500Z-ff7d/report.yaml` |
| `E007-20261128T002505Z-e0e0` | 2026-11-28 | completed | `d6aec1d` | recall (graph channel) on `E007-20261128T001630Z-e513`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002505Z-e0e0/report.yaml` |
| `E007-20261128T002505Z-ff77` | 2026-11-28 | completed | `d6aec1d` | recall (graph channel) on `E007-20261128T001630Z-da86`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002505Z-ff77/report.yaml` |
| `E007-20261128T002721Z-7812` | 2026-11-28 | running | `d6aec1d` | writer 32b-segment8-think on locomo-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002721Z-7812/report.yaml` |
| `E007-20261128T002721Z-8619` | 2026-11-28 | completed | `d6aec1d` | writer 32b-message on changeseq-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002721Z-8619/report.yaml` |
| `E007-20261128T002800Z-3c65` | 2026-11-28 | completed | `d6aec1d` | writer 8b-message on t024-segments; superseded (segment-only mode, graphs not read by the E006 scorer); `runs/E007/artifacts/w01-E007/E007/E007-20261128T002800Z-3c65/report.yaml` |
| `E007-20261128T002800Z-ac49` | 2026-11-28 | completed | `d6aec1d` | writer 8b-session on t024-segments; superseded (segment-only mode, graphs not read by the E006 scorer); `runs/E007/artifacts/w01-E007/E007/E007-20261128T002800Z-ac49/report.yaml` |
| `E007-20261128T002800Z-c019` | 2026-11-28 | completed | `d6aec1d` | recall (graph channel) on `E007-20261128T002008Z-1f87`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002800Z-c019/report.yaml` |
| `E007-20261128T002954Z-22c4` | 2026-11-28 | completed | `d6aec1d` | writer 8b-message on locomo-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002954Z-22c4/report.yaml` |
| `E007-20261128T002954Z-85cf` | 2026-11-28 | completed | `d6aec1d` | writer 8b-session on changeseq-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002954Z-85cf/report.yaml` |
| `E007-20261128T002954Z-9911` | 2026-11-28 | completed | `d6aec1d` | recall (graph channel) on `E007-20261128T002500Z-7946`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002954Z-9911/report.yaml` |
| `E007-20261128T002954Z-accd` | 2026-11-28 | completed | `d6aec1d` | writer 8b-segment8 on changeseq-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T002954Z-accd/report.yaml` |
| `E007-20261128T003307Z-7735` | 2026-11-28 | completed | `4c209fe` | score (E006 scorer, segments) of `E007-20261128T001630Z-aed4`; upstream superseded, 0 writer claims found (graph IDs); `runs/E007/artifacts/w01-E007/E007/E007-20261128T003307Z-7735/report.yaml` |
| `E007-20261128T003307Z-a0ae` | 2026-11-28 | completed | `4c209fe` | score (E006 scorer, segments) of `E007-20261128T002410Z-8686`; upstream superseded, 0 writer claims found (graph IDs); `runs/E007/artifacts/w01-E007/E007/E007-20261128T003307Z-a0ae/report.yaml` |
| `E007-20261128T003308Z-842a` | 2026-11-28 | completed | `4c209fe` | score (E006 scorer, segments) of `E007-20261128T002008Z-860d`; upstream superseded, 0 writer claims found (graph IDs); `runs/E007/artifacts/w01-E007/E007/E007-20261128T003308Z-842a/report.yaml` |
| `E007-20261128T003308Z-a33d` | 2026-11-28 | completed | `4c209fe` | score (E006 scorer, segments) of `E007-20261128T002800Z-ac49`; upstream superseded, 0 writer claims found (graph IDs); `runs/E007/artifacts/w01-E007/E007/E007-20261128T003308Z-a33d/report.yaml` |
| `E007-20261128T003309Z-ad27` | 2026-11-28 | completed | `4c209fe` | score (E006 scorer, segments) of `E007-20261128T002410Z-581d`; upstream superseded, 0 writer claims found (graph IDs); `runs/E007/artifacts/w01-E007/E007/E007-20261128T003309Z-ad27/report.yaml` |
| `E007-20261128T003438Z-23eb` | 2026-11-28 | running | `714577d` | writer 32b-segment8-think on t024-segments; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003438Z-23eb/report.yaml` |
| `E007-20261128T003438Z-39d2` | 2026-11-28 | completed | `714577d` | writer 32b-segment8 on t024-segments; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003438Z-39d2/report.yaml` |
| `E007-20261128T003438Z-4a4e` | 2026-11-28 | completed | `714577d` | writer 8b-segment8 on t024-segments; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003438Z-4a4e/report.yaml` |
| `E007-20261128T003438Z-4f4f` | 2026-11-28 | completed | `714577d` | writer 32b-session on t024-segments; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003438Z-4f4f/report.yaml` |
| `E007-20261128T003438Z-e1c8` | 2026-11-28 | completed | `714577d` | writer 8b-session on t024-segments; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003438Z-e1c8/report.yaml` |
| `E007-20261128T003438Z-ee1d` | 2026-11-28 | completed | `714577d` | writer 32b-message on t024-segments; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003438Z-ee1d/report.yaml` |
| `E007-20261128T003513Z-452d` | 2026-11-28 | completed | `714577d` | score (E006 scorer, full-history, LoCoMo segments) of `E007-20261128T001630Z-e513`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003513Z-452d/report.yaml` |
| `E007-20261128T003516Z-7132` | 2026-11-28 | completed | `714577d` | score (E006 scorer, full-history, LoCoMo segments) of `E007-20261128T001630Z-da86`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003516Z-7132/report.yaml` |
| `E007-20261128T003520Z-1b87` | 2026-11-28 | completed | `714577d` | score (E006 scorer, full-history, LoCoMo segments) of `E007-20261128T002008Z-1f87`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003520Z-1b87/report.yaml` |
| `E007-20261128T003523Z-908d` | 2026-11-28 | completed | `714577d` | score (E006 scorer, full-history, LoCoMo segments) of `E007-20261128T002500Z-7946`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003523Z-908d/report.yaml` |
| `E007-20261128T003540Z-7178` | 2026-11-28 | completed | `714577d` | score (E006 scorer, full-history, LoCoMo segments) of `T022-20261126T214758Z-c1fa`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003540Z-7178/report.yaml` |
| `E007-20261128T003544Z-c23b` | 2026-11-28 | completed | `714577d` | score (E006 scorer, full-history, LoCoMo segments) of `T022-20261126T214758Z-613e`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003544Z-c23b/report.yaml` |
| `E007-20261128T003731Z-0d06` | 2026-11-28 | completed | `714577d` | writer 8b-message on t024-segments; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003731Z-0d06/report.yaml` |
| `E007-20261128T003855Z-e127` | 2026-11-28 | completed | `714577d` | score (E006 scorer, full-history, LoCoMo segments) of `E007-20261128T002008Z-e01f`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003855Z-e127/report.yaml` |
| `E007-20261128T003905Z-b458` | 2026-11-28 | completed | `714577d` | recall (graph channel) on `E007-20261128T002008Z-e01f`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T003905Z-b458/report.yaml` |
| `E007-20261128T004158Z-79d3` | 2026-11-28 | completed | `714577d` | score (E006 scorer, segments) of `E007-20261128T003438Z-39d2`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T004158Z-79d3/report.yaml` |
| `E007-20261128T004203Z-c002` | 2026-11-28 | completed | `714577d` | score (E006 scorer, segments) of `E007-20261128T003438Z-4f4f`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T004203Z-c002/report.yaml` |
| `E007-20261128T004207Z-c26f` | 2026-11-28 | completed | `714577d` | score (E006 scorer, segments) of `E007-20261128T003438Z-ee1d`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T004207Z-c26f/report.yaml` |
| `E007-20261128T004213Z-0520` | 2026-11-28 | completed | `714577d` | score (E006 scorer, segments) of `E007-20261128T003438Z-4a4e`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T004213Z-0520/report.yaml` |
| `E007-20261128T004220Z-41aa` | 2026-11-28 | completed | `714577d` | score (E006 scorer, segments) of `E007-20261128T003438Z-e1c8`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T004220Z-41aa/report.yaml` |
| `E007-20261128T004242Z-5779` | 2026-11-28 | completed | `714577d` | writer 8b-message on changeseq-dev; `runs/E007/artifacts/w01-E007/E007/E007-20261128T004242Z-5779/report.yaml` |
| `E007-20261128T004407Z-dc73` | 2026-11-28 | completed | `714577d` | score (E006 scorer, segments) of `E007-20261128T003731Z-0d06`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T004407Z-dc73/report.yaml` |
| `E007-20261128T004411Z-13b9` | 2026-11-28 | completed | `714577d` | score (E006 scorer, full-history, LoCoMo segments) of `E007-20261128T002954Z-22c4`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T004411Z-13b9/report.yaml` |
| `E007-20261128T004411Z-38af` | 2026-11-28 | completed | `714577d` | recall (graph channel) on `E007-20261128T002954Z-22c4`; `runs/E007/artifacts/w01-E007/E007/E007-20261128T004411Z-38af/report.yaml` |

## Results

Partial (thinking arms still running or not run; see Log). All numbers below are from completed runs listed in Runs; each row names its writer run, its score run (E006 scorer, T024 agent labels, loose level, lower-upper bounds from the two label files) and, for LoCoMo, its recall run. Code: writer runs at `d88d908`, `1343fb6`, `d6aec1d` (LoCoMo, controlled sequences; the writer, prompt and schema are the same at all three) and `714577d` (T024 segments); score runs at `714577d`; recall runs at `d6aec1d` or `714577d` (each report names its SHA).

Extraction modes, compared only within a mode: **LoCoMo dev** = full-history writing (every message of both histories in order; the score covers the 16 LoCoMo T024 segments, read from the history graphs); **T024 segments** = each of the 40 segments written on its own with its 6 context messages first (E006's `context+segment` mode; message counts include the 228 context messages, which are extracted but not scored); **controlled sequences** = full-history writing, no graph-quality score yet (no scorer for the gold graphs).

Token columns are per message of history (calls x tokens / messages). "Cached" is the prompt prefix the server reported as cached; "n/r" = not reported: the shared Qwen3-8B server runs without `--enable-prompt-tokens-details`, so its cached count is unknown, not zero (both models share one tokenizer and the same prompts, so the Qwen3-32B cached share at the same granularity is a close estimate). Output tokens of thinking arms include the thinking.

#### LoCoMo dev (full history)

| Arm | Writer run | Messages | Calls | Input / msg | Cached / msg | Uncached / msg | Output / msg | Parse failures (rate); repaired splits | Empty patches | Claims | Loose P | Loose R | Loose F1 | Score run | Graph R@20 / RRF-all R@20 (recall run) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8b-message | `E007-20261128T002954Z-22c4` | 928 | 928 | 4806 | n/r | n/r | 311.8 | 26 (0.028); 0/0 | 28/902 (0.031) | 1389 | 0.069-0.074 | 0.187-0.253 | 0.101-0.114 | `E007-20261128T004411Z-13b9` | 0.071 / 0.730 (`E007-20261128T004411Z-38af`) |
| 8b-segment8 | `E007-20261128T001630Z-da86` | 928 | 142 | 776 | n/r | n/r | 146.3 | 4 (0.0282); 2/2 | 7/138 (0.0507) | 1187 | 0.050-0.058 | 0.111-0.137 | 0.069-0.082 | `E007-20261128T003516Z-7132` | 0.071 / 0.734 (`E007-20261128T002505Z-ff77`) |
| 8b-session | `E007-20261128T002500Z-7946` | 928 | 44 | 285 | n/r | n/r | 97.5 | 0 (0.0); 0/0 | 0/44 (0.0) | 806 | 0.089-0.093 | 0.115-0.159 | 0.101-0.117 | `E007-20261128T003523Z-908d` | 0.081 / 0.741 (`E007-20261128T002954Z-9911`) |
| 32b-message | `E007-20261128T002008Z-e01f` | 928 | 928 | 4621 | 3824 | 796 | 87.3 | 0 (0.0); 0/0 | 389/928 (0.4192) | 688 | 0.136-0.158 | 0.221-0.275 | 0.169-0.201 | `E007-20261128T003855Z-e127` | 0.099 / 0.747 (`E007-20261128T003905Z-b458`) |
| 32b-segment8 | `E007-20261128T001630Z-e513` | 928 | 136 | 743 | 541 | 202 | 55.2 | 0 (0.0); 0/0 | 38/136 (0.2794) | 621 | 0.195-0.215 | 0.210-0.275 | 0.202-0.241 | `E007-20261128T003513Z-452d` | 0.105 / 0.741 (`E007-20261128T002505Z-e0e0`) |
| 32b-session | `E007-20261128T002008Z-1f87` | 928 | 44 | 274 | 173 | 101 | 40.0 | 0 (0.0); 0/0 | 0/44 (0.0) | 462 | 0.250-0.273 | 0.225-0.297 | 0.237-0.284 | `E007-20261128T003520Z-1b87` | 0.117 / 0.743 (`E007-20261128T002800Z-c019`) |

#### T024 segments (context+segment)

| Arm | Writer run | Messages | Calls | Input / msg | Cached / msg | Uncached / msg | Output / msg | Parse failures (rate); repaired splits | Empty patches | Claims | Loose P | Loose R | Loose F1 | Score run | Graph R@20 / RRF-all R@20 (recall run) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8b-message | `E007-20261128T003731Z-0d06` | 806 | 806 | 4359 | n/r | n/r | 355.4 | 24 (0.0298); 0/0 | 148/782 (0.1893) | 1827 | 0.080-0.094 | 0.206-0.279 | 0.116-0.141 | `E007-20261128T004407Z-dc73` | - |
| 8b-segment8 | `E007-20261128T003438Z-4a4e` | 806 | 140 | 840 | n/r | n/r | 109.9 | 4 (0.0286); 3/3 | 25/136 (0.1838) | 837 | 0.169-0.202 | 0.200-0.265 | 0.183-0.229 | `E007-20261128T004213Z-0520` | - |
| 8b-session | `E007-20261128T003438Z-e1c8` | 806 | 79 | 523 | n/r | n/r | 77.7 | 0 (0.0); 0/0 | 19/79 (0.2405) | 706 | 0.209-0.246 | 0.203-0.272 | 0.206-0.259 | `E007-20261128T004220Z-41aa` | - |
| 32b-message | `E007-20261128T003438Z-ee1d` | 806 | 806 | 4154 | 3698 | 455 | 86.6 | 1 (0.0012); 0/0 | 488/805 (0.6062) | 752 | 0.168-0.189 | 0.179-0.254 | 0.174-0.216 | `E007-20261128T004207Z-c26f` | - |
| 32b-segment8 | `E007-20261128T003438Z-39d2` | 806 | 142 | 842 | 698 | 144 | 59.1 | 5 (0.0352); 3/3 | 53/137 (0.3869) | 504 | 0.304-0.342 | 0.212-0.298 | 0.250-0.319 | `E007-20261128T004158Z-79d3` | - |
| 32b-session | `E007-20261128T003438Z-4f4f` | 806 | 83 | 547 | 380 | 167 | 40.2 | 2 (0.0241); 2/2 | 29/81 (0.358) | 480 | 0.349-0.395 | 0.216-0.303 | 0.267-0.343 | `E007-20261128T004203Z-c002` | - |

#### Controlled sequences (full history)

| Arm | Writer run | Messages | Calls | Input / msg | Cached / msg | Uncached / msg | Output / msg | Parse failures (rate); repaired splits | Empty patches | Claims | Loose P | Loose R | Loose F1 | Score run | Graph R@20 / RRF-all R@20 (recall run) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8b-message | `E007-20261128T004242Z-5779` | 1000 | 1000 | 3910 | n/r | n/r | 40.5 | 0 (0.0); 0/0 | 677/1000 (0.677) | 202 | - | - | - | - | - |
| 8b-segment8 | `E007-20261128T002954Z-accd` | 1000 | 158 | 651 | n/r | n/r | 24.5 | 1 (0.0063); 1/1 | 54/157 (0.3439) | 183 | - | - | - | - | - |
| 8b-session | `E007-20261128T002954Z-85cf` | 1000 | 65 | 285 | n/r | n/r | 23.8 | 1 (0.0154); 1/1 | 10/64 (0.1562) | 182 | - | - | - | - | - |
| 32b-message | `E007-20261128T002721Z-8619` | 1000 | 1000 | 3900 | 3731 | 168 | 38.5 | 0 (0.0); 0/0 | 661/1000 (0.661) | 176 | - | - | - | - | - |
| 32b-segment8 | `E007-20261128T002500Z-ff7d` | 1000 | 158 | 651 | 582 | 68 | 24.1 | 1 (0.0063); 1/1 | 40/157 (0.2548) | 166 | - | - | - | - | - |
| 32b-session | `E007-20261128T002500Z-a973` | 1000 | 67 | 296 | 246 | 50 | 23.0 | 2 (0.0299); 2/2 | 3/65 (0.0462) | 171 | - | - | - | - | - |

Prompt round (one round, user decision of 2026-11-26), scored once on the 16 LoCoMo T024 segments from the full-history graphs (the segments were not used to write the prompt), segment-8:

| Writer | Prompt | Writer run | Empty patches | Claims | Loose P | Loose R | Score run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Qwen3-32B | T022 | `T022-20261126T214758Z-c1fa` | 44/136 | 474 | 0.172-0.179 | 0.183-0.253 | `E007-20261128T003540Z-7178` |
| Qwen3-32B | E007 | `E007-20261128T001630Z-e513` | 38/136 | 621 | 0.195-0.215 | 0.210-0.275 | `E007-20261128T003513Z-452d` |
| Qwen3-8B | T022 | `T022-20261126T214758Z-613e` | 6/136 | 957 | 0.068-0.077 | 0.126-0.159 | `E007-20261128T003544Z-c23b` |
| Qwen3-8B | E007 | `E007-20261128T001630Z-da86` | 7/138 | 1187 | 0.050-0.058 | 0.111-0.137 | `E007-20261128T003516Z-7132` |

(T022 counted 45 empty units for `c1fa`: units with nothing committed; 44 returned an empty patch.)

## Conclusion

Pending the thinking arms and the main-configuration decision (s00-super). What the completed runs support, each comparison within one extraction mode:

- Granularity: session units give the highest claim precision for both writers in both modes (Qwen3-32B loose P 0.250-0.273 full-history and 0.349-0.395 on segments; Qwen3-8B 0.089-0.093 and 0.209-0.246) at about the same recall as segment-8, and the fewest writer tokens per message (Qwen3-32B on LoCoMo: input 274 vs 743 for segment-8 and 4,621 for message; output 40 vs 55 and 87). Per-message units have the lowest precision and about six times the input tokens (the fixed prompt is resent per message; most of it is a cached prefix). Recommended main configuration: session granularity (proposal; s00-super decides). Not measured: the cost of read-triggered flushes inside an open session (no reads in these runs), which session units make more frequent under per-turn reading.
- Scale: Qwen3-32B is about four times as precise as Qwen3-8B in full-history writing (segment-8 0.195-0.215 vs 0.050-0.058) and about 1.7 times on segments, at similar recall, with fewer output tokens.
- The one prompt round helped Qwen3-32B (full history: P 0.172-0.179 to 0.195-0.215, R 0.183-0.253 to 0.210-0.275, empty patches 44 to 38 of 136) but not Qwen3-8B in full-history writing (P 0.068-0.077 to 0.050-0.058, R 0.126-0.159 to 0.111-0.137), where emotion and mention predicates the prompt forbids grew (`hasEmotionalImpact` 339, `mentions` 293 claims).

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-26: design inputs from the T022 writer smoke comparison (PR #129), recorded by the integration owner on user decisions: one prompt round on development data to raise Qwen3-32B extraction coverage (45/136 empty units in the smoke run), before the configuration lock (D012), with the same prompt then used for every writer arm; report empty-patch rate and output tokens next to quality (Qwen3-32B used about 2.7 times fewer output tokens than Qwen3-8B on the same input); session granularity needs larger schema array bounds (claims 32, stances 16, same_as 8 are sized for segment-8) and a re-pinned schema.
- 2026-11-28: worker session `w01-E007` (no manager layer; directed by `s00-super`) on `task/E007-ablation-g-writer`; Issue #141. Qwen3-32B server (revision `9216db5781bf21249d130ec9da846c4624c16137`, vLLM with `--reasoning-parser qwen3` for the thinking arms) on GPU 0, port 8253, reserved in `runs/compute.yaml`; Qwen3-8B on the shared server of `s00-super` (port 8252, started without `--enable-prompt-tokens-details`, so its cached tokens are not reported).
- 2026-11-28: prompt round (one round, before D012). Inputs: the empty units of the Qwen3-32B smoke run `T022-20261126T214758Z-c1fa` outside the T024 sessions (facts inside chit-chat missed: a childhood book, a family hobby, a diet, an incident at a supermarket). Changes to `extract-claims` (re-pinned): facts wrapped in chit-chat are kept, a list of easily missed kinds of facts, a per-message check, feelings only through what they are about, `hasEmotionalImpact`, `felt`, `mentions` named as catch-all predicates; all examples are invented, none is taken from benchmark text. Schema bounds widened for session units to 96 claims, 48 stances, 16 same_as (re-pinned; one schema for every arm); session arms use max_tokens 12288. Same prompt, schema and settings in every arm.
- 2026-11-28: driver `grace.cli.writer_ablation` (one arm on one target; `extractions.jsonl` with every raw writer item anchored to its message, graphs per history or segment); writer statistics gained empty patches, empty commits and the repair of invalid outputs by splitting (`eval/analysis/metrics/writer.py`); `metrics.json` has `writer_tokens` per message and call (D007). pyshacl is not thread safe: run `E007-20261128T002008Z-9da7` failed with a ParseException in SHACL validation under 8 parallel segments; validation is serialised in the driver since `d6aec1d`. Four runs started with an untracked test file (code_dirty) were aborted within a minute and relaunched.
- 2026-11-28: the first T024 arm runs wrote each segment from an empty graph without extracting its context and named graphs by a sanitised key; the E006 scorer (merged from main, PR #148) found no graphs in them (5 score runs with 0 writer claims). The T024 target now uses E006's probe (`context+segment`, `714577d`) and all T024 arms were rerun; the earlier runs are superseded (Runs).
- 2026-11-28: results of the scale and granularity arms (thinking off) on LoCoMo dev, the controlled sequences and the T024 segments, with E006 scores and the graph-channel recall proxy: Results. Answer accuracy was not run (no answering pipeline over extracted graphs exists yet); the T025 recall probe on each arm's graphs stands in as a proxy (graph R@20 0.071-0.117, fused R@20 0.730-0.747 across arms; fusion moves by about one point). D007 request (s00-super): writer tokens per granularity, model and thinking setting per message of history, input split into cached prefix and rest, are in the Results tables and in each writer run's `report.yaml` (`metrics.writer_tokens`).
- 2026-11-28: not run or not finished in this session: thinking on for Qwen3-8B (needs a Qwen3-8B server with a reasoning parser; the shared server has none); thinking on for Qwen3-32B is running on LoCoMo dev and the T024 segments (runs `E007-20261128T002721Z-7812`, `E007-20261128T003438Z-23eb`); graph quality on the controlled sequences (no scorer against their gold graphs yet).
