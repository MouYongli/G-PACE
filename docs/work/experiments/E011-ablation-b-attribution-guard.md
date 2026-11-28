---
id: E011
title: "Ablation B: attribution guard, representation, time"
created: 2026-11-23
---

# E011 · Ablation B: attribution guard, representation, time

## Question

Does the attribution guard let the system answer both 'what was requested' and 'what is selected now', and is the gain due to the guard, to structure or to open predicates? Serves RQ1. If tagged hybrid retrieval obtains most of the gain attributed to the guard, the conclusion narrows to 'speaker and dialogue-act information helps'.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | MultiWOZ 2.4 turns after an offer (development); controlled sequences (late corrections, as-known pairs); LoCoMo and LongMemEval development slices |
| Systems and baselines | Attribution guard (off, on) x representation (slot table, open-predicate claim graph) x time (single, bitemporal); tagged hybrid retrieval; the 'system values are not written' rule |
| Metrics | Paired correctness of original constraint and current selection; original-constraint retention; stale-value use; share of the gain attributed to the guard that the tagged arm obtains |
| Seeds and budget | Decoding seed 0, temperature 0; memory budget 256 tokens on MultiWOZ, 1,024 on change-seq and LoCoMo; MultiWOZ: seeded subset of 270 of the 426 dev dialogues with a paired item (sample seed 28), offer-turn reads only (374 reads, 313 paired items) |
| Config | `configs/experiments/E011-ablation-b-attribution-guard.yaml`; driver `grace.cli.ablation_b` |

## Acceptance

- [x] Every number traces to a run report (score runs and the compare summaries under `runs/E011/artifacts/w01-E011/compare/`).

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| system, change-seq, `configs/engines/grace.yaml` (shards overlapped: unsorted history order; not used): `E011-20261128T083557Z-05bf`, `E011-20261128T083557Z-3bb7`, `E011-20261128T083557Z-450d`, `E011-20261128T083557Z-5de4`, `E011-20261128T083557Z-f910` | 2026-11-28 | completed | `95f5537` | `report.yaml` in each run directory |
| score, MultiWOZ never-write (T028 rows): `E011-20261128T083600Z-f9ee` | 2026-11-28 | completed | `95f5537` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/grace.yaml`: `E011-20261128T083634Z-2b1d`, `E011-20261128T083634Z-3318`, `E011-20261128T083634Z-44f3`, `E011-20261128T083634Z-7c5e`, `E011-20261128T083634Z-911f`, `E011-20261128T083634Z-caae`, `E011-20261128T083634Z-df3b`, `E011-20261128T083635Z-6287`, `E011-20261128T083636Z-ad85`, `E011-20261128T083637Z-623f` | 2026-11-28 | completed | `95f5537` | `report.yaml` in each run directory |
| score, MultiWOZ guard projection (T028 rows): `E011-20261128T083642Z-805e` | 2026-11-28 | completed | `95f5537` | `report.yaml` in each run directory |
| score, MultiWOZ overwrite projection (T028 rows): `E011-20261128T083721Z-9b74` | 2026-11-28 | completed | `95f5537` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/grace-noguard.yaml` (killed after the overlap was found; not used): `E011-20261128T085126Z-083f`, `E011-20261128T085126Z-2d92`, `E011-20261128T085126Z-3302`, `E011-20261128T085126Z-39d9`, `E011-20261128T085126Z-b6ad` | 2026-11-28 | failed | `95f5537` | `report.yaml` in each run directory |
| score, change-seq graph-guard-bi on overlapping shards (refused: task predicted twice; not used): `E011-20261128T085133Z-5d70` | 2026-11-28 | failed | `95f5537` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/grace.yaml`: `E011-20261128T085224Z-1455`, `E011-20261128T085224Z-58d0`, `E011-20261128T085224Z-6673`, `E011-20261128T085224Z-c1b5`, `E011-20261128T085224Z-fc45` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, MultiWOZ graph-guard-bi: `E011-20261128T085608Z-ad28` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/grace-noguard.yaml`: `E011-20261128T085637Z-0c6f`, `E011-20261128T085637Z-6ab0`, `E011-20261128T085637Z-bc54`, `E011-20261128T085638Z-0045`, `E011-20261128T085638Z-582b`, `E011-20261128T085639Z-2c69`, `E011-20261128T085639Z-a570`, `E011-20261128T085640Z-2e43`, `E011-20261128T085640Z-b7e3`, `E011-20261128T085641Z-62b3` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/grace-noguard.yaml`: `E011-20261128T091315Z-a476`, `E011-20261128T091315Z-aa1e`, `E011-20261128T091315Z-c363`, `E011-20261128T091315Z-c51d`, `E011-20261128T091315Z-c6a6` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, change-seq graph-guard-bi: `E011-20261128T091323Z-cb48` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, MultiWOZ graph-noguard-bi: `E011-20261128T091656Z-ec2d` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/grace-slots.yaml`: `E011-20261128T091725Z-7026`, `E011-20261128T091725Z-7100`, `E011-20261128T091725Z-aae1`, `E011-20261128T091725Z-dbb8`, `E011-20261128T091726Z-1bf1`, `E011-20261128T091726Z-4cd4`, `E011-20261128T091726Z-6390`, `E011-20261128T091726Z-cea6`, `E011-20261128T091726Z-d773`, `E011-20261128T091727Z-628a` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/grace-slots.yaml`: `E011-20261128T093312Z-2967`, `E011-20261128T093312Z-42f2`, `E011-20261128T093312Z-6857`, `E011-20261128T093312Z-6a81`, `E011-20261128T093312Z-7762` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/grace-slots-noguard.yaml`: `E011-20261128T093413Z-f5d7`, `E011-20261128T093414Z-2234`, `E011-20261128T093414Z-3a33`, `E011-20261128T093414Z-58df`, `E011-20261128T093414Z-7e62`, `E011-20261128T093414Z-ad48`, `E011-20261128T093414Z-d51d`, `E011-20261128T093415Z-8427`, `E011-20261128T093415Z-c789`, `E011-20261128T093415Z-f947` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/grace-slots-noguard.yaml`: `E011-20261128T094528Z-2b31`, `E011-20261128T094528Z-3458`, `E011-20261128T094528Z-5ce0`, `E011-20261128T094528Z-808f`, `E011-20261128T094528Z-a9c4` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/rrf-tagged.yaml`: `E011-20261128T094538Z-5832`, `E011-20261128T094538Z-7cea`, `E011-20261128T094538Z-814d`, `E011-20261128T094538Z-ac75`, `E011-20261128T094538Z-cf68`, `E011-20261128T094538Z-fa96`, `E011-20261128T094539Z-6696`, `E011-20261128T094539Z-73a2`, `E011-20261128T094539Z-9914`, `E011-20261128T094539Z-e6cf` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/rrf.yaml`: `E011-20261128T094706Z-40fe`, `E011-20261128T094707Z-68f4`, `E011-20261128T094707Z-84e8`, `E011-20261128T094707Z-db5e`, `E011-20261128T094707Z-e021`, `E011-20261128T094708Z-27cf`, `E011-20261128T094708Z-4ebb`, `E011-20261128T094708Z-e0e8`, `E011-20261128T094709Z-e62f`, `E011-20261128T094709Z-e682` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/grace-single.yaml`: `E011-20261128T094820Z-4594`, `E011-20261128T094820Z-d1b2`, `E011-20261128T094821Z-153a`, `E011-20261128T094821Z-166b`, `E011-20261128T094821Z-1a74`, `E011-20261128T094821Z-2e68`, `E011-20261128T094821Z-6920`, `E011-20261128T094821Z-7d5b`, `E011-20261128T094821Z-f8f8`, `E011-20261128T094822Z-b6f5` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/rrf-tagged.yaml`: `E011-20261128T095637Z-1b65`, `E011-20261128T095637Z-2a6f`, `E011-20261128T095637Z-ba75`, `E011-20261128T095637Z-cefc`, `E011-20261128T095637Z-f618` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/rrf.yaml`: `E011-20261128T095843Z-5963`, `E011-20261128T095843Z-8d8e`, `E011-20261128T095843Z-aa5a`, `E011-20261128T095843Z-b5e7`, `E011-20261128T095843Z-cd35` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/grace-noguard-single.yaml`: `E011-20261128T095949Z-74d5`, `E011-20261128T095949Z-cb5a`, `E011-20261128T095949Z-d8f3`, `E011-20261128T095950Z-788e`, `E011-20261128T095950Z-92a3`, `E011-20261128T095950Z-e809`, `E011-20261128T095950Z-eeb5`, `E011-20261128T095950Z-f1cc`, `E011-20261128T095950Z-f1ce`, `E011-20261128T095950Z-f4ea` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/grace-single.yaml`: `E011-20261128T100003Z-0e40`, `E011-20261128T100003Z-5c8c`, `E011-20261128T100003Z-77c0`, `E011-20261128T100003Z-7fc1`, `E011-20261128T100003Z-8735` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/grace-slots-single.yaml`: `E011-20261128T101115Z-1e0c`, `E011-20261128T101115Z-66b5`, `E011-20261128T101115Z-80f1`, `E011-20261128T101115Z-87f8`, `E011-20261128T101115Z-8e08`, `E011-20261128T101116Z-658f`, `E011-20261128T101116Z-9d10`, `E011-20261128T101116Z-a9df`, `E011-20261128T101116Z-aa7f`, `E011-20261128T101116Z-b826` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/grace-noguard-single.yaml`: `E011-20261128T101219Z-282e`, `E011-20261128T101219Z-671a`, `E011-20261128T101219Z-7d97`, `E011-20261128T101219Z-9fe2`, `E011-20261128T101219Z-c38c` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/grace-slots-noguard-single.yaml`: `E011-20261128T102153Z-0f74`, `E011-20261128T102154Z-2173`, `E011-20261128T102154Z-25b3`, `E011-20261128T102154Z-2b1a`, `E011-20261128T102154Z-41d5`, `E011-20261128T102154Z-94aa`, `E011-20261128T102154Z-da7c`, `E011-20261128T102155Z-531e`, `E011-20261128T102155Z-ad37`, `E011-20261128T102156Z-b09f` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/grace-slots-single.yaml`: `E011-20261128T102502Z-80f1`, `E011-20261128T102502Z-9929`, `E011-20261128T102502Z-c6a2`, `E011-20261128T102502Z-cd5d`, `E011-20261128T102502Z-e69e` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, multiwoz, `configs/engines/grace.yaml` (rerun): `E011-20261128T103206Z-5a38`, `E011-20261128T103207Z-1660`, `E011-20261128T103207Z-727b`, `E011-20261128T103207Z-b7e7`, `E011-20261128T103207Z-daf5`, `E011-20261128T103208Z-0bce`, `E011-20261128T103208Z-4551`, `E011-20261128T103208Z-847a`, `E011-20261128T103208Z-93dc`, `E011-20261128T103208Z-b9bd` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| system, change-seq, `configs/engines/grace-slots-noguard-single.yaml`: `E011-20261128T103544Z-29a0`, `E011-20261128T103544Z-2ccf`, `E011-20261128T103544Z-34e0`, `E011-20261128T103544Z-9ed4`, `E011-20261128T103544Z-c607` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, MultiWOZ slots-guard-bi: `E011-20261128T104338Z-b13e` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, MultiWOZ slots-noguard-bi: `E011-20261128T104417Z-de9d` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, MultiWOZ tagged: `E011-20261128T104455Z-12d9` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, MultiWOZ rrf: `E011-20261128T104534Z-b43d` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, MultiWOZ graph-guard-single: `E011-20261128T104614Z-e86c` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, change-seq graph-noguard-bi: `E011-20261128T104646Z-ab83` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, change-seq slots-guard-bi: `E011-20261128T104650Z-7025` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, MultiWOZ graph-noguard-single: `E011-20261128T104653Z-20be` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, change-seq slots-noguard-bi: `E011-20261128T104653Z-6a7a` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, change-seq tagged: `E011-20261128T104657Z-e0a7` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, change-seq rrf: `E011-20261128T104700Z-a6a5` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, change-seq graph-guard-single: `E011-20261128T104703Z-cb77` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, change-seq graph-noguard-single: `E011-20261128T104707Z-6b2a` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, change-seq slots-guard-single: `E011-20261128T104710Z-0c35` | 2026-11-28 | completed | `90d06c0` | `report.yaml` in each run directory |
| score, change-seq slots-noguard-single: `E011-20261128T104713Z-f34d` | 2026-11-28 | completed | `ae8b8f7` | `report.yaml` in each run directory |
| system, locomo, `configs/engines/grace.yaml`: `E011-20261128T104719Z-3d06`, `E011-20261128T104719Z-faeb` | 2026-11-28 | completed | `ae8b8f7` | `report.yaml` in each run directory |
| system, locomo, `configs/engines/grace-slots.yaml`: `E011-20261128T104719Z-9f1a`, `E011-20261128T104719Z-bc51` | 2026-11-28 | completed | `ae8b8f7` | `report.yaml` in each run directory |
| score, MultiWOZ slots-guard-single: `E011-20261128T104731Z-4fc3` | 2026-11-28 | completed | `ae8b8f7` | `report.yaml` in each run directory |
| score, MultiWOZ slots-noguard-single: `E011-20261128T104810Z-4505` | 2026-11-28 | completed | `ae8b8f7` | `report.yaml` in each run directory |
| score, MultiWOZ graph-guard-bi rerun: `E011-20261128T104848Z-cb07` | 2026-11-28 | completed | `ae8b8f7` | `report.yaml` in each run directory |
| score, LoCoMo graph-guard-bi conv-26: `E011-20261128T105450Z-346b` | 2026-11-28 | completed | `ae8b8f7` | `report.yaml` in each run directory |
| score, LoCoMo graph-guard-bi conv-49: `E011-20261128T105450Z-5e78` | 2026-11-28 | completed | `ae8b8f7` | `report.yaml` in each run directory |
| score, LoCoMo slots-guard-bi conv-26: `E011-20261128T105451Z-72ec` | 2026-11-28 | completed | `ae8b8f7` | `report.yaml` in each run directory |
| score, LoCoMo slots-guard-bi conv-49: `E011-20261128T105451Z-86c0` | 2026-11-28 | completed | `ae8b8f7` | `report.yaml` in each run directory |

All run directories are under `runs/E011/artifacts/w01-E011/E011/`. Paired contrasts: `runs/E011/artifacts/w01-E011/compare/{multiwoz,change-seq,locomo}-20261128/summary.json`; context, supersession and cost diagnostics: `compare/diagnostics-20261128.txt` (scripts in `scripts/`). Development smoke runs before the config (not formal, code dirty) are in `runs/E011/artifacts/w01-E011/pilot/`.

## Results

Development data only. Percentages; 95% intervals from a cluster bootstrap (10,000 resamples, seed 0; clusters: dialogue on MultiWOZ, scenario family on change-seq, question on LoCoMo). Every arm answers with Qwen3-8B through the shared answer step (the "answer readout"); the GRACE arms write with Qwen3-32B. Invalid outputs count as wrong (`count_as_wrong`).

**How the MultiWOZ state is read out.** Plan 6.5 projects a structured internal state onto the official slots. No such projection exists for GRACE's open-predicate claim graph: the writer uses free predicates and subjects such as `USERs_hotel_booking maintains free_parking`. The pilot slot table has a generic inventory, not the MultiWOZ slots. So every E011 arm is read out the same way: the answering model outputs the state from the working context. A train ID cannot be stated that way, so train accept items are always wrong for these arms. `paired_correct|domain!=train` (n = 188) excludes them. The T028 projection rows, which carry `metadata.current_choice`, are included as reference rows rescored on the same 313 items.

### MultiWOZ dev, 270 dialogues, 374 offer-turn reads, budget 256

| Arm (score run) | `paired_correct` (n=313) | `retained` (n=581) | `choice_correct` (n=313) | paired, domain != train (n=188) | `retained`, conflict (n=157) | offer overwrite, conflict (n=157, lower is better) | JGA 2.4 (n=374) | invalid |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| graph, guard, bitemporal (`…085608Z-ad28`) | 21.4 [16.9, 26.0] | 45.1 [40.8, 49.4] | 33.5 [28.4, 38.7] | 34.6 [27.8, 41.8] | 16.6 [10.6, 22.8] | 11.5 [6.5, 17.0] | 2.1 [0.8, 3.8] | 5 |
| same, rerun (`…104848Z-cb07`) | 20.8 [16.4, 25.3] | 46.0 [41.8, 50.1] | 33.9 [28.8, 39.2] | 33.5 [26.8, 40.7] | 15.3 [9.7, 21.2] | 14.0 [8.6, 20.0] | 1.6 [0.5, 3.0] | 3 |
| graph, no guard, bitemporal (`…091656Z-ec2d`) | 22.7 [18.2, 27.4] | 45.1 [41.0, 49.2] | 35.5 [30.3, 40.7] | 36.7 [29.9, 44.0] | 13.4 [8.2, 19.0] | 11.5 [6.5, 17.0] | 2.1 [0.8, 3.8] | 3 |
| graph, guard, single (`…104614Z-e86c`) | 23.3 [18.6, 28.0] | 46.5 [42.1, 50.9] | 35.8 [30.7, 41.0] | 37.8 [31.0, 44.9] | 14.6 [9.1, 20.5] | 12.7 [7.6, 18.4] | 2.1 [0.8, 3.7] | 2 |
| graph, no guard, single (`…104653Z-20be`) | 21.7 [17.1, 26.3] | 44.9 [40.7, 49.2] | 34.8 [29.6, 40.1] | 35.1 [28.4, 42.3] | 16.6 [10.6, 22.8] | 9.6 [5.2, 14.2] | 1.1 [0.3, 2.2] | 4 |
| slots, guard, bitemporal (`…104338Z-b13e`) | 27.8 [23.0, 32.9] | 51.5 [47.3, 55.7] | 45.0 [39.7, 50.5] | 46.3 [39.0, 53.6] | 26.8 [19.7, 34.0] | 28.0 [21.2, 35.0] | 1.6 [0.5, 3.0] | 5 |
| slots, no guard, bitemporal (`…104417Z-de9d`) | 27.5 [22.7, 32.4] | 50.6 [46.5, 54.8] | 47.0 [41.7, 52.4] | 45.7 [38.6, 53.1] | 25.5 [18.7, 32.5] | 22.9 [16.6, 29.4] | 1.1 [0.3, 2.2] | 2 |
| slots, guard, single (`…104731Z-4fc3`) | 27.5 [22.6, 32.4] | 51.5 [47.2, 55.7] | 47.3 [41.9, 52.6] | 45.7 [38.5, 53.0] | 26.8 [20.0, 33.8] | 28.7 [22.0, 35.8] | 1.6 [0.5, 3.0] | 2 |
| slots, no guard, single (`…104810Z-4505`) | 26.8 [22.0, 31.8] | 51.6 [47.5, 55.6] | 45.4 [40.1, 50.8] | 44.1 [37.0, 51.9] | 26.8 [19.9, 33.5] | 19.7 [13.8, 26.0] | 1.3 [0.3, 2.6] | 2 |
| tagged hybrid retrieval (`…104455Z-12d9`) | 28.4 [23.6, 33.3] | 57.7 [53.2, 61.9] | 42.5 [37.3, 47.7] | 46.3 [39.2, 53.6] | 37.6 [30.1, 45.0] | 26.8 [20.1, 33.3] | 4.3 [2.4, 6.5] | 2 |
| hybrid retrieval, untagged (`…104534Z-b43d`) | 29.1 [24.1, 34.1] | 62.0 [57.7, 66.0] | 46.0 [40.6, 51.4] | 47.3 [40.3, 54.6] | 47.8 [39.5, 55.8] | 25.5 [18.7, 32.5] | 3.7 [1.9, 5.8] | 0 |
| never-write rule, T028 rows (`…083600Z-f9ee`) | 24.9 [20.3, 29.7] | 77.8 [74.3, 81.1] | 32.3 [27.4, 37.2] | 39.9 [33.0, 47.1] | 79.6 [73.0, 85.9] | 5.1 [1.9, 8.8] | 15.0 [11.3, 18.9] | 0 |
| guard projection, T028 rows (`…083642Z-805e`) | 40.9 [35.3, 46.6] | 78.5 [75.0, 81.8] | 51.8 [46.3, 57.3] | 40.4 [33.7, 47.6] | 79.6 [73.0, 85.9] | 5.7 [2.5, 9.6] | 13.1 [9.6, 16.9] | 0 |
| overwrite projection, T028 rows (`…083721Z-9b74`) | 33.2 [28.3, 38.2] | 69.7 [66.2, 73.1] | 46.6 [41.4, 51.9] | 53.7 [46.7, 61.0] | 36.9 [29.2, 44.7] | 54.1 [46.1, 62.2] | 6.1 [3.8, 8.8] | 0 |

Paired contrasts (a - b, points, 95% interval; `compare/multiwoz-20261128`):

| Contrast | `paired_correct` | `retained` | `choice_correct` |
| --- | --- | --- | --- |
| guard, claim graph (on - off) | -1.3 [-4.2, +1.6] | +0.0 [-3.0, +3.1] | -1.9 [-5.4, +1.6] |
| guard, slot table (on - off) | +0.3 [-2.0, +2.8] | +0.9 [-1.7, +3.4] | -1.9 [-4.9, +1.0] |
| writer variance (graph-guard-bi run 1 - run 2) | +0.6 [-2.3, +3.6] | -0.9 [-3.8, +2.1] | -0.3 [-3.8, +3.2] |
| representation (graph - slots, guard, bitemporal) | -6.4 [-10.8, -2.2] | -6.4 [-11.0, -1.6] | -11.5 [-16.8, -6.2] |
| time, claim graph (bitemporal - single) | -1.9 [-5.0, +1.0] | -1.4 [-4.3, +1.6] | -2.2 [-5.9, +1.3] |
| time, slot table (bitemporal - single) | +0.3 [-1.3, +2.0] | +0.0 [-2.4, +2.4] | -2.2 [-4.9, +0.3] |
| tag gain (tagged - untagged) | -0.6 [-3.9, +2.6] | -4.3 [-7.7, -0.8] | -3.5 [-6.5, -0.6] |
| GRACE guard arm - tagged | -7.0 [-11.1, -3.1] | -12.6 [-17.0, -8.1] | -8.9 [-13.5, -4.3] |
| GRACE guard arm - never-write rule | -3.5 [-8.2, +1.0] | -32.7 [-37.4, -28.0] | +1.3 [-3.5, +6.1] |
| guard projection - never-write rule (same T028 rows) | +16.0 [+11.9, +20.2] | +0.7 [+0.2, +1.4] | +19.5 [+15.1, +24.0] |

The share of the guard gain that the tag obtains is undefined: the guard gain is not positive (-1.3 points on `paired_correct`, interval containing 0).

### Controlled change sequences (T015 model-rendered dev set, 25 sequences, 1,145 reads, budget 1,024)

`set-match` covers the four state question types (n = 955). The as-known pairs (`known_then`, `seen_from_now`; n = 190, 52 of them in differing pairs) are the registered historical metric. Late corrections (C5) are only 9 reads of the population, so they are descriptive. Stale-value use counts answers that mention an outdated value of the read (n = 335, lower is better).

| Arm (score run) | `set-match` (n=955) | C5 late correction (n=9) | as-known pairs (n=190) | as-known, differing (n=52) | stale-value use (n=335) | invalid |
| --- | --- | --- | --- | --- | --- | --- |
| graph, guard, bitemporal (`…091323Z-cb48`) | 65.4 [62.9, 67.6] | 44.4 | 65.8 [59.0, 71.7] | 50.0 [42.1, 53.8] | 30.4 [27.9, 33.4] | 25 |
| graph, no guard, bitemporal (`…104646Z-ab83`) | 64.9 [62.3, 67.4] | 44.4 | 65.3 [61.5, 70.7] | 51.9 [42.1, 57.7] | 31.0 [28.6, 34.2] | 28 |
| graph, guard, single (`…104703Z-cb77`) | 64.4 [61.8, 66.7] | 44.4 | 62.1 [56.5, 68.1] | 48.1 [42.1, 50.0] | 30.4 [28.9, 32.1] | 26 |
| graph, no guard, single (`…104707Z-6b2a`) | 64.9 [61.7, 68.2] | 44.4 | 62.6 [57.8, 68.8] | 46.2 [38.9, 50.0] | 30.4 [28.1, 33.2] | 25 |
| slots, guard, bitemporal (`…104650Z-7025`) | 59.5 [57.2, 61.3] | 33.3 | 39.5 [28.9, 51.1] | 21.2 [15.2, 28.1] | 31.0 [25.2, 37.2] | 68 |
| slots, no guard, bitemporal (`…104653Z-6a7a`) | 60.1 [57.9, 62.6] | 22.2 | 47.4 [39.3, 55.3] | 32.7 [23.3, 39.7] | 28.1 [22.8, 33.4] | 62 |
| slots, guard, single (`…104710Z-0c35`) | 62.0 [60.1, 64.2] | 33.3 | 50.5 [42.4, 58.3] | 30.8 [26.2, 38.1] | 28.1 [22.9, 35.3] | 42 |
| slots, no guard, single (`…104713Z-f34d`) | 62.5 [59.7, 64.8] | 33.3 | 54.2 [47.9, 61.9] | 40.4 [28.3, 48.6] | 28.4 [20.7, 34.5] | 30 |
| tagged hybrid retrieval (`…104657Z-e0a7`) | 61.9 [58.5, 64.8] | 33.3 | 61.1 [55.9, 65.7] | 40.4 [29.5, 48.6] | 34.3 [29.5, 39.1] | 13 |
| hybrid retrieval, untagged (`…104700Z-a6a5`) | 62.6 [59.9, 65.4] | 44.4 | 64.2 [58.4, 70.0] | 40.4 [33.3, 47.4] | 34.9 [30.8, 39.1] | 20 |

Paired contrasts on `set-match` (`compare/change-seq-20261128`). Only 5 family clusters, so the intervals are coarse; sequence-level intervals per arm are in each score run's `summary.json` (`_by_sequence`).

| Contrast | `set-match` | as-known pairs |
| --- | --- | --- |
| guard, claim graph | +0.5 [-0.4, +1.7] | +0.5 [-3.7, +3.6] |
| guard, slot table | -0.6 [-2.7, +1.5] | -7.9 [-12.0, -2.8] |
| representation (graph - slots) | +6.0 [+3.1, +8.7] | +26.3 [+17.6, +35.6] |
| time, claim graph (bitemporal - single) | +1.0 [+0.7, +1.4] | +3.7 [+1.7, +5.6] |
| time, slot table (bitemporal - single) | -2.5 [-4.8, -0.6] | -11.1 [-19.0, -4.8] |
| tag gain (tagged - untagged) | -0.7 [-2.5, +1.0] | -3.2 [-6.2, -1.1] |
| GRACE guard arm - tagged | +3.6 [+1.5, +6.6] | +4.7 [+1.5, +9.1] |

### LoCoMo dev (conv-26, conv-49; 308 questions, categories 1-4, budget 1,024)

| Arm (score runs) | F1 |
| --- | --- |
| graph, guard, bitemporal (`…105450Z-346b` conv-26, `…105450Z-5e78` conv-49) | 33.3 (per history: 29.95, 36.59) |
| slots, guard, bitemporal (`…105451Z-72ec` conv-26, `…105451Z-86c0` conv-49) | 16.3 (per history: 14.23, 18.37) |

Graph minus slots: +17.0 [+12.9, +21.4] points (question-level paired bootstrap, descriptive; `compare/locomo-20261128`). The slot arm answers `unknown` on 145 of 308 questions; the graph arm does so on 47.

### Diagnostics (`compare/diagnostics-20261128.txt`)

- **The guard has almost nothing to decide on.** Over the 270 MultiWOZ dialogues, the claim graph with the guard on commits 47 supersessions; with the guard off it commits 68. On change-seq the counts are 151 and 209. The writer puts an offered value on the offered entity (`archway_house priceRange moderate`), not on the user's request subject (`USERs_hotel_booking …`). An offer therefore rarely competes with a user constraint under the same subject and predicate, which is where the guard acts.
- **Guard on/off changes the context no more than writer noise.** On MultiWOZ, 200 of 374 working contexts are identical between guard on and off. Between two runs of the same arm, 191 are identical. On change-seq, 818 of 1,145 contexts are identical between guard on and off.
- **The contexts are mostly raw messages.** On MultiWOZ, 78% of the graph arms' contexts hold at least one claim item, against 2,362 message fragments in total. On change-seq, the contexts hold 1,257 claim fragments against 24,652 message fragments.
- **Cost per read (tokens, all calls, input plus output).** MultiWOZ: graph arms W about 8,600 to 8,900, U about 4,000 to 4,200, A about 900. Slot arms W about 2,550, U about 3,600 to 4,300 (planner over an empty claim graph, serving nothing), A about 930 to 940. Tagged: W 1,186, A 894. Untagged: A 867. Change-seq: graph W about 2,400, U about 4,000; slots W 638, U about 4,150. The slot arms' U should be subtracted when comparing cost.
- Slot arms on change-seq have more invalid answers (42 to 68 against about 25) and larger answer prompts (A about 1,500 to 1,650 against about 1,240).

## Conclusion

Proposed reading. The decision on RQ1's wording belongs to the plan owner.

1. **No effect of the attribution guard is shown on development data.** On MultiWOZ, guard on versus off ties in both representations (claim graph -1.3 [-4.2, +1.6], slots +0.3 [-2.0, +2.8] on `paired_correct`). Both differences are of the size of the writer variance (+0.6 [-2.3, +3.6]). On change-seq the guard also ties (+0.5 [-0.4, +1.7], slots -0.6 [-2.7, +1.5]). By the plan 9.1 rule, the never-write rule ties with the GRACE guard arm on paired correctness (-3.5 [-8.2, +1.0]), so no effect of the attribution guard is claimed. The tag rule cannot be applied: the guard gain is not positive, so the share is undefined. The tag itself gains nothing (-0.6 [-3.9, +2.6]).
2. **The evidence explains the null.** The guard is exercised rarely: about 21 extra supersessions without it over 270 dialogues. Its effect on the contexts is within writer noise. With the answer readout, the answering model mostly reads raw messages. This is a limit of the test as built, not evidence that attribution does not matter. On the same T028 slot rows, the guard as a projection beats the never-write rule by +16.0 [+11.9, +20.2] on `paired_correct`. That comparison holds the extractor fixed and reads the state structurally.
3. **On MultiWOZ through the answer readout, every GRACE arm is below plain hybrid retrieval.** Graph arms are about 7 points below on `paired_correct` and 17 points below on `retained`. The representation contrast also favours slots (-6.4 [-10.8, -2.2]). Every answer-readout arm loses heavily on `retained` and JGA against the projection rows. The answer readout at a 256-token budget is a weak MultiWOZ tracker, so plan 6.5's projection should be the MultiWOZ readout for structured systems.
4. **Open predicates help on change-seq and LoCoMo.** The claim graph beats the slot table by +6.0 [+3.1, +8.7] on change-seq `set-match`, by +26.3 on the as-known pairs, and by +17.0 F1 on LoCoMo (descriptive interval). The "fixed slot table ties on open-domain slices" narrowing does not apply. The slot inventory is the pilot placeholder, which favours the claim graph.
5. **Bitemporality helps the claim graph slightly on change-seq** (+1.0 [+0.7, +1.4]; as-known +3.7 [+1.7, +5.6]; 5 clusters, coarse). In the slot table it hurts (-2.5 [-4.8, -0.6]; as-known -11.1). The bitemporal slot arm offers retired values as extra state items, which may crowd the 1,024-token context. This is not explained further here.

Open items: a MultiWOZ projection from GRACE's claim graph (predicate and subject mapping, a design decision) before MultiWOZ can carry the RQ1 guard claim; a controlled-sequence slice where offers and user constraints share subject and predicate, so that the guard is exercised; C5 has only 9 reads in the population; change-seq intervals rest on 5 clusters; LongMemEval-S was not run.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-24: renamed from `E011-ablation-b-roles.md` and retitled to follow the plan terminology (attribution guard instead of roles).
- 2026-11-28: worker session `w01-E011` (directed by `s00-super`) on `task/E011-ablation-b-attribution-guard` from `e23c68f`; Issue #166. Config written before any formal run (`95f5537`): arms, populations, budgets, metrics, contrasts, interpretation rules. New configs: `grace-noguard`, `grace-single`, `grace-noguard-single`, `writer-noguard`; single-time extension component `single-time`. Pilot (dirty code, not formal): at budget 1,024 the whole dialogue fits at every offer turn, so MultiWOZ uses budget 256.
- 2026-11-28: the first change-seq run of `graph-guard-bi` (`…083557Z-*`) had overlapping shards: the history order of a set differed between processes. Its score run was refused (`…085133Z-5d70`, task predicted twice). The `graph-noguard-bi` shards started after it (`…085126Z-*`) were killed and marked failed. Fixed in `90d06c0` (sorted order); all change-seq arms were rerun. MultiWOZ arms ran at `95f5537` (first arm) and `90d06c0`. The two commits differ only in change-seq sharding.
- 2026-11-28: all MultiWOZ and change-seq arms completed, plus the writer-variance rerun. The LoCoMo representation contrast was added to the config (`ae8b8f7`) before its runs. Results and diagnostics above. Proposed status `E011: active -> review`. The guard null contradicts the RQ1 hypothesis; the diagnostics explain it (the guard is rarely exercised and its effect is within writer noise), but the RQ1 wording and a MultiWOZ projection for the claim graph need a plan-owner decision.
