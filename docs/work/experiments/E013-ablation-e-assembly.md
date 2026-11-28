---
id: E013
title: "Ablation E: assembly"
created: 2026-11-23
---

# E013 · Ablation E: assembly

## Question

At the same token budget, does assembly by evidence demand raise full evidence hits and lower unsupported answers compared with a fused top-k? Serves component claim C4.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | LoCoMo and LongMemEval-S development data |
| Systems and baselines | Fixed top-k or RRF truncation versus evidence-demand assembly; expandable pointers versus summaries only |
| Metrics | Full evidence hit rate; unsupported answer rate; final prompt and total tokens |
| Seeds and budget | Seed 0 (temperature 0); memory budgets 256, 512 and 1,024 answering-model tokens |
| Config | `configs/experiments/E013-ablation-e-assembly.yaml`; arms `greedy` (main configuration), `truncate`, `no-open` (read runs on the shared E006 ingest snapshots) and `rrf` (system runs); `pointers-vs-summaries` not runnable (the engine creates no summary items) |

## Acceptance

- [x] Every number traces to a run report.

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| E013-20261128T065836Z-f23b (system: main config, before fill fix) | 2026-11-28 | completed | 990e4d2 | `runs/E013/artifacts/w01-E013/E013/E013-20261128T065836Z-f23b/report.yaml` |
| E013-20261128T065836Z-6320 (system: routing all, before fill fix) | 2026-11-28 | completed | 990e4d2 | same directory scheme |
| E013-20261128T065836Z-15a3 (system: rank truncation, before fill fix) | 2026-11-28 | completed | 990e4d2 | same directory scheme |
| E013-20261128T065835Z-1974 (system: main config, fill fix) | 2026-11-28 | completed | 7528124 | same directory scheme |
| E013-20261128T073033Z-2b78 (system: fill fix + routing all) | 2026-11-28 | completed | 7528124 | same directory scheme |
| E013-20261128T073034Z-ed8f (system: fill fix + rank truncation) | 2026-11-28 | completed | 7528124 | same directory scheme |
| E013-20261128T073135Z-dc16 (system: fill fix + routing all + no open items) | 2026-11-28 | completed | f9ac696 | same directory scheme |
| E013-20261128T073033Z-afba (score of f23b) | 2026-11-28 | completed | 7528124 | same directory scheme |
| E013-20261128T073034Z-16e5 (score of 6320) | 2026-11-28 | completed | 7528124 | same directory scheme |
| E013-20261128T073035Z-d943 (score of 15a3) | 2026-11-28 | completed | 7528124 | same directory scheme |
| E013-20261128T073035Z-5ec2 (score of 1974) | 2026-11-28 | completed | 7528124 | same directory scheme |
| E013-20261128T074540Z-0349, -2c34, E013-20261128T074541Z-5de6 (scores) | 2026-11-28 | failed (code_dirty: uncommitted draft config) | f9ac696 | same directory scheme; rescored below |
| E013-20261128T074547Z-cd90 (score of 2b78) | 2026-11-28 | completed | 18c4c20 | same directory scheme |
| E013-20261128T074547Z-15b2 (score of ed8f) | 2026-11-28 | completed | 18c4c20 | same directory scheme |
| E013-20261128T074548Z-79fc (score of dc16) | 2026-11-28 | completed | 18c4c20 | same directory scheme |
| E013-20261128T075426Z-89f2 (system: new main-configuration reference after the decisions) | 2026-11-28 | completed | 4e4aa94 | same directory scheme |
| E013-20261128T080905Z-053e (score of 89f2) | 2026-11-28 | completed | 4e4aa94 | same directory scheme |

Formal runs (2026-11-28; every run directory under `runs/E013/artifacts/w01-E013/E013/` has a `report.yaml`; arm, budget and score-run IDs per run are in the Results tables):

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| 9 LoCoMo read runs E013-20261128T090250Z-* / T090251Z-* (greedy, truncate, no-open x 256, 512, 1,024; upstream ingest E006-20261128T082608Z-21cb) | 2026-11-28 | completed | a44530f | `report.yaml` in each run directory |
| 3 LoCoMo rrf system runs E013-20261128T090250Z-6815, -583b, E013-20261128T090251Z-7eea | 2026-11-28 | completed | a44530f | same |
| 24 LoCoMo score runs E013-20261128T090612Z-f6e5 ... E013-20261128T090627Z-008e (12 `locomo_score`, 12 `evidence_score`) | 2026-11-28 | completed | 5f91b4c | same |
| 3 LongMemEval-S rrf system runs E013-20261128T090658Z-450c, -10d1, -f05b (the 67 histories of the ingest run) | 2026-11-28 | completed | 5f91b4c | same |
| 9 LongMemEval-S read runs E013-20261128T093822Z-* / T093823Z-f1b3 (first attempt) | 2026-11-28 | failed: snapshot restore, `JSONDecodeError` (message text with U+2028 split by `str.splitlines`); fixed in aa2c9fc | 5f91b4c | same |
| 9 LongMemEval-S read runs E013-20261128T094004Z-842a, E013-20261128T094005Z-* (second attempt) | 2026-11-28 | failed: view restore, `QueryTypeError` (entity `50mm_f_1_8_prime_lens` lexed as a number); fixed in 81e51d7 | aa2c9fc | same |
| 9 LongMemEval-S read runs E013-20261128T094210Z-* (upstream ingest E006-20261128T083145Z-6288) | 2026-11-28 | completed | 81e51d7 | same |
| 12 LongMemEval-S evidence score runs E013-20261128T091523Z-59df, -091531Z-6fd9, -091540Z-d144, E013-20261128T0945*Z-*, E013-20261128T0946*Z-* | 2026-11-28 | completed | 5f91b4c (rrf), 81e51d7 | same |
| 12 LongMemEval-S judge runs E013-20261128T1137*Z-* / T1138*Z-* and 12 score runs E013-20261128T1144*Z-* / T1145*Z-* / T1146*Z-* (9 read runs T094210Z-*, 3 rrf system runs T090658Z-*), one judge rerun E013-20261128T114537Z-b627 | 2026-11-28 | completed | 125d34f (judge), 2389bd3 (score) | `runs/E013/artifacts/w01-judge/E013/<run-id>/report.yaml` |

Development diagnosis runs above the formal block: all rows of the first table are development diagnosis runs (LoCoMo dev, conv-26 and conv-49, 308 end-of-history reads, budget 1,024, Qwen3-8B answering and planning, Qwen3-32B writer with session units), not formal E013 runs. Per-read plan and assembly records and the analysis scripts are in `runs/E013/artifacts/w01-E013/diagnosis/`.

## Results

### Formal ablation (2026-11-28)

Development data only; seed 0. GRACE arms are read runs restoring one shared ingest snapshot per benchmark (written once by the Qwen3-32B writer, E006), so they differ only in assembly; rrf is the text-only fused top-k baseline (BM25 + dense, RRF, top 20). Metrics: `grace.cli.evidence_score` (definitions in `src/grace/eval/analysis/metrics/evidence.py`; not registered in `configs/common/scorers.yaml`): full evidence hit = all gold evidence messages' raw text in the context (`context_ids`); lenient also counts claim and view citations; unsupported answer = output `answer` while no gold evidence message is in the context. Reads without gold evidence are excluded (LoCoMo 6, LongMemEval-S 2). `invalid` outputs are excluded and reported (at most 2 per run). LoCoMo F1 from `grace.cli.locomo_score` (registered `f1`, categories 1-4, 308 scored). LongMemEval-S answer accuracy needs a judge; none was run (`n/a`).

**LoCoMo dev (308 reads; evidence metrics over 302 reads with gold evidence)**

| Budget | Arm | Run | F1 (score run) | unknown | Full evidence hit | lenient | Recall | Unsupported answer | Evidence score run | Context / prompt tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| 256 | greedy | E013-20261128T090250Z-ea12 | 0.261 (E013-20261128T090613Z-f0d6) | 89 | 0.421 | 0.434 | 0.475 | 0.212 | E013-20261128T090614Z-00e9 | 240 / 730 |
| 256 | truncate | E013-20261128T090251Z-4141 | 0.276 (E013-20261128T090624Z-9ba8) | 83 | 0.434 | 0.450 | 0.484 | 0.215 | E013-20261128T090625Z-bc58 | 240 / 730 |
| 256 | no-open | E013-20261128T090250Z-b4a2 | 0.261 (E013-20261128T090617Z-5c96) | 85 | 0.424 | 0.437 | 0.478 | 0.215 | E013-20261128T090617Z-bed0 | 241 / 731 |
| 256 | rrf | E013-20261128T090250Z-6815 | 0.261 (E013-20261128T090621Z-b6c5) | 89 | 0.455 | 0.455 | 0.501 | 0.196 | E013-20261128T090621Z-7504 | 237 / 727 |
| 512 | greedy | E013-20261128T090251Z-e67d | 0.313 (E013-20261128T090614Z-1dce) | 55 | 0.551 | 0.565 | 0.619 | 0.176 | E013-20261128T090615Z-50d2 | 495 / 984 |
| 512 | truncate | E013-20261128T090250Z-d572 | 0.315 (E013-20261128T090626Z-db93) | 55 | 0.560 | 0.570 | 0.623 | 0.173 | E013-20261128T090627Z-008e | 495 / 984 |
| 512 | no-open | E013-20261128T090250Z-1220 | 0.312 (E013-20261128T090618Z-4320) | 53 | 0.555 | 0.568 | 0.622 | 0.173 | E013-20261128T090619Z-ff35 | 495 / 985 |
| 512 | rrf | E013-20261128T090250Z-583b | 0.313 (E013-20261128T090622Z-f2ce) | 61 | 0.555 | 0.555 | 0.625 | 0.150 | E013-20261128T090622Z-6bc9 | 487 / 976 |
| 1024 | greedy | E013-20261128T090251Z-1849 | 0.343 (E013-20261128T090612Z-f6e5) | 43 | 0.632 | 0.642 | 0.711 | 0.129 | E013-20261128T090613Z-611b | 1002 / 1491 |
| 1024 | truncate | E013-20261128T090250Z-7242 | 0.345 (E013-20261128T090623Z-8d11) | 41 | 0.632 | 0.642 | 0.712 | 0.129 | E013-20261128T090624Z-fdbf | 1002 / 1491 |
| 1024 | no-open | E013-20261128T090251Z-f179 | 0.346 (E013-20261128T090615Z-a7cd) | 39 | 0.629 | 0.639 | 0.709 | 0.132 | E013-20261128T090616Z-a243 | 1002 / 1492 |
| 1024 | rrf | E013-20261128T090251Z-7eea | 0.345 (E013-20261128T090619Z-f605) | 44 | 0.632 | 0.632 | 0.719 | 0.116 | E013-20261128T090620Z-fe62 | 985 / 1475 |

**LongMemEval-S dev, main-text strata (67 reads; evidence metrics over 65 reads with gold evidence)**

| Budget | Arm | Run | F1 (score run) | unknown | Full evidence hit | lenient | Recall | Unsupported answer | Evidence score run | Context / prompt tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| 256 | greedy | E013-20261128T094210Z-8d78 | n/a (judge only) | 25 | 0.323 | 0.323 | 0.565 | 0.031 | E013-20261128T094530Z-fc24 | 236 / 731 |
| 256 | truncate | E013-20261128T094210Z-9eca | n/a (judge only) | 27 | 0.369 | 0.385 | 0.577 | 0.015 | E013-20261128T094555Z-f169 | 235 / 729 |
| 256 | no-open | E013-20261128T094210Z-00c9 | n/a (judge only) | 25 | 0.338 | 0.338 | 0.573 | 0.031 | E013-20261128T094620Z-6cf0 | 237 / 731 |
| 256 | rrf | E013-20261128T090658Z-450c | n/a (judge only) | 26 | 0.385 | 0.385 | 0.608 | 0.000 | E013-20261128T091531Z-6fd9 | 233 / 728 |
| 512 | greedy | E013-20261128T094210Z-d012 | n/a (judge only) | 19 | 0.569 | 0.569 | 0.754 | 0.015 | E013-20261128T094538Z-5260 | 491 / 985 |
| 512 | truncate | E013-20261128T094210Z-62a7 | n/a (judge only) | 17 | 0.585 | 0.585 | 0.758 | 0.031 | E013-20261128T094604Z-cb0c | 491 / 985 |
| 512 | no-open | E013-20261128T094210Z-cc12 | n/a (judge only) | 19 | 0.569 | 0.569 | 0.754 | 0.015 | E013-20261128T094629Z-13a0 | 492 / 986 |
| 512 | rrf | E013-20261128T090658Z-10d1 | n/a (judge only) | 17 | 0.615 | 0.615 | 0.781 | 0.015 | E013-20261128T091540Z-d144 | 486 / 980 |
| 1024 | greedy | E013-20261128T094210Z-746d | n/a (judge only) | 19 | 0.677 | 0.677 | 0.827 | 0.000 | E013-20261128T094521Z-adff | 1006 / 1501 |
| 1024 | truncate | E013-20261128T094210Z-55b2 | n/a (judge only) | 18 | 0.692 | 0.692 | 0.837 | 0.000 | E013-20261128T094546Z-d1a0 | 1004 / 1499 |
| 1024 | no-open | E013-20261128T094210Z-a7a3 | n/a (judge only) | 19 | 0.677 | 0.677 | 0.827 | 0.000 | E013-20261128T094612Z-aec8 | 1006 / 1500 |
| 1024 | rrf | E013-20261128T090658Z-f05b | n/a (judge only) | 17 | 0.677 | 0.677 | 0.813 | 0.031 | E013-20261128T091523Z-59df | 998 / 1492 |

Answer-side noise: in LoCoMo reads whose contexts are byte-identical between `greedy` and `truncate`, 6 to 7 predictions differ between runs (of 218, 262 and 288 such reads at 256, 512 and 1,024), so F1 differences below about 0.01 are not distinguishable. On LongMemEval-S one read is 0.015 of a rate.

Findings:

1. **Evidence-demand assembly does not beat rank truncation.** Greedy and truncation build the same context in 218, 262 and 288 of 308 LoCoMo reads (256, 512, 1,024). Where they differ, truncation is as good or slightly better: full evidence hit is equal or higher for `truncate` at every budget on both benchmarks (LoCoMo 0.434 against 0.421 at 256; LongMemEval-S 0.369 against 0.323 at 256, 0.692 against 0.677 at 1,024), and F1 is equal within noise (0.276 against 0.261 at 256). The demand rarely has more than one variable (in the development diagnosis 85 of 308 LoCoMo plans fell back to the single `answer` variable and 215 named one, item 4; 71 fell back in the reference run), so coverage per token only reorders the first pick and then prefers short items.
2. **GRACE does not raise full evidence hits over the rrf baseline.** LoCoMo: equal at 1,024 (0.632 all), lower at 256 (0.421 against 0.455) and 512 (0.551 against 0.555). LongMemEval-S: lower at 256 and 512 (0.323 against 0.385, 0.569 against 0.615), equal at 1,024 (0.677). Claim and view citations add up to 0.016 (lenient against strict); the structured state does not make up for the raw text it displaces at small budgets.
3. **GRACE does not lower unsupported answers.** LoCoMo: GRACE 0.212, 0.176, 0.129 against rrf 0.196, 0.150, 0.116 (256, 512, 1,024). LongMemEval-S: rates are 0 to 0.031 for every arm (0 to 2 reads of 65); no difference can be read from them.
4. **Open items on or off makes no difference** at the main configuration: after the E013 decision that the fallback variable is never listed, only 15 of 308 LoCoMo greedy contexts list open items; F1 0.261/0.312/0.346 (no-open) against 0.261/0.313/0.343 (greedy), full evidence hit within 0.004; LongMemEval-S identical at 512 and 1,024.
5. **Tokens.** Every arm fills the budget (context 233 to 241, 486 to 495, 985 to 1,006 tokens); GRACE's contexts are 3 to 17 tokens longer than rrf's (headings), the prompt adds about 490 tokens for every system.
6. **Pointers versus summaries** was not run: the engine creates no summary items (config `pointers-vs-summaries: runnable: false`).

Two restore bugs found on the LongMemEval-S snapshot and fixed on this branch (not assembly): JSON Lines restore of the message log, claim store and view store split records at U+2028 (`str.splitlines`), and the query lexer read an entity starting with digits (`50mm_f_1_8_prime_lens`) as a number. Both made every read run of LongMemEval-S fail before any read; the completed runs use 81e51d7.

### Development diagnosis (2026-11-28): why GRACE scored below rrf in E007

Not a result of the ablation; development data only. Question: on LoCoMo dev every E007 GRACE arm scored below the rrf baseline (GRACE Qwen3-32B session F1 0.293, system run E007-20261128T062349Z-8899, score E007-20261128T063748Z-9feb; rrf 0.347, system run E001-20261125T182212Z-2cd5, score E007-20261128T062931Z-a884). Net gap: 16.7 F1 points summed over 308 reads (GRACE worse on 52 reads, better on 24).

Causes, from the E007 run files (per read, gold evidence against contexts, read traces and predictions), each then tested by a variant run:

1. **Claim citations suppressed raw evidence (bug, fixed).** The rank-order fill skipped any candidate whose message was cited by an already selected claim. Query answers rank first, so in every read with state items (81 reads) the raw messages behind them were removed (5.3 per read), and the context showed lines such as `[D3:1] event = school_event` without the message text or its date. In 28 reads the gold evidence was in the fused candidates but reached the context only as a claim citation; rrf beat GRACE on them by 7.4 F1 points. Raw-text full evidence hit: GRACE 163 of 308 reads, rrf 191. Fix in `assembly/select.py` (only message and chunk items count as shown). With the fix, full evidence hit is 187 and F1 is 0.314 (system E013-20261128T065835Z-1974, score -5ec2), against 0.296 for a rerun of the unfixed main configuration (system -f23b, score -afba).
2. **Routing left BM25 out (T025 code, not changed here).** Rule routing sends a request with a time cue (`when`, `last`, a year) and no identifier to dense and graph. The graph channel exists only when a query compiled, and is empty when the query has no answers (117 of 223 compiled queries), so 110 to 121 reads were effectively dense-only (F1 0.229 against rrf 0.276 on them in E007, 5.7 points). Widening happens only when the route is graph alone. `routing: all` adds 0.009 on top of the fix (0.323, system -2b78, score -cd90) and 0.007 without it (0.303, system -6320, score -16e5).
3. **The open-items section caused abstention.** 33 reads listed `Open items (not found in memory)`; 24 of them are the fallback variable `answer`, i.e. the question itself, judged unsupported by the lexical stand-in for verification (50% of question terms). The answering LLM answered `unknown` in 20 of them (rrf: 9). Removing the section on top of fix and routing all gives F1 0.338, unknown 44 (rrf 44), raw full evidence hit 194 (rrf 191) (system -dc16, score -79fc). Remaining gap to rrf: 2.8 F1 points summed (0.009), against 0.9 points (0.003) between two runs of the same configuration.
4. **Greedy selection does not matter here.** Rank truncation equals greedy: 0.296 against 0.296 before the fix (system -15a3, score -d943), 0.318 against 0.314 after it (system -ed8f, score -15b2). 215 of 308 plans name one variable and 85 name none, so coverage per token decides only the first pick (the shortest supporting item for `answer`), and the fill does the rest.
5. **Temporal questions (category 2) fail for every system, not because dates are missing.** Contexts carry ISO timestamps on every raw message (`(2023-05-08T13:56)`), and both systems answer with ISO dates (43 and 44 of 70 predictions), which share no token with gold such as `7 May 2023`. Written as the gold writes dates, 20 (GRACE) and 21 (rrf) predictions would match. The answer prompt and the date rendering are shared by all systems, so token F1 on category 2 does not separate them (0.071 against 0.081); the judge metric or a shared date rendering decides this, not assembly.
6. **Planner and expansion.** 85 of 308 plans fell back (31 parse, 24 type, 15 declined, 13 time, 2 anchor failures) and 121 needed one repair. A fallback gives the demand `answer` and no graph channel. The assembler's query expansion ran in 37 reads and closed the open variable in 4: for `answer` the extra query is the question again, and it uses the read's one further retrieval.
7. **Text retrieval itself matches rrf.** Where GRACE searched BM25 and dense only (101 reads), both per-channel rankings were identical to rrf's in 87 reads and the fused set was the same in 80; the differences come from chunking long messages.

Decisions of s00-super on these findings (2026-11-28, development configuration before D012): see the Log. Items 2 to 4 of the decisions are implemented on this branch; the answer path, the date rendering and the scorer are unchanged.

**E007's answer-accuracy table is stale.** Its GRACE rows (LoCoMo dev F1 per writer arm) were produced before the fill fix and with rule routing, the open-items listing of the fallback variable and the fallback query expansion. They no longer describe the main configuration; the reference for later experiments is the rerun below.

**New reference of the main configuration** (code 4e4aa94: fill fix, `routing: all`, no open item for the fallback variable, no query expansion for a fallback plan; system E013-20261128T075426Z-89f2, score E013-20261128T080905Z-053e): F1 0.330 (308 scored, 0 invalid, 47 unknown); by category 0.311 (1, n 69), 0.081 (2, n 70), 0.114 (3, n 26), 0.501 (4, n 143); raw full evidence hit 193 of 308 reads (rrf 191). rrf: 0.347, 44 unknown. The variant without any open items (0.338, -79fc) also removed the 18 contexts that still list open planner variables; the difference to the reference is within about three times the rerun noise. 71 plans fell back; the assembler's query expansion ran in 25 reads (compiled plans only).

**Temporal scoring.** Token F1 on category 2 stays near 0.08 for every system because answers are written as ISO dates (item 5 above); no answer-path or scorer change was made. No judge accuracy exists for these runs: the LoCoMo judge is the remote comparison judge of the pilot (E001 reports it for `rrf` only), and it was not run here. s00-super raises the date format for D012.

### Judge (uncalibrated, T035 pending)

Local primary judge DeepSeek-V4-Flash-0731 (D006; `configs/judges/blind.yaml` v2, chat mode, thinking off, temperature 0); registered metric `judge-accuracy` (`grace.cli.judge_score`: answer reads take the verdict, `unknown` is correct exactly on abstention tasks). Not calibrated against human labels (T035): development evidence only. Judge runs at 125d34f, score runs at 2389bd3; run directories `runs/E013/artifacts/w01-judge/E013/<run-id>/` with `report.yaml`. Judge rerun noise: 46 of 46 identical verdicts (E013-20261128T114537Z-b627 against E013-20261128T113752Z-80f5), 260 of 265 on a LoCoMo run. Strata have fewer than 100 reads (descriptive). Judge-invalid verdicts 0 and invalid predictions 0 in every LongMemEval-S run; local input-token counts equal the server's on every call.

**LongMemEval-S dev, main-text strata (67 reads: knowledge-update 15, multi-session 26, temporal-reasoning 26)**

| Budget | Arm | Upstream run | Judge run | Score run | accuracy | unknown | knowledge-update | multi-session | temporal-reasoning |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 256 | greedy | E013-20261128T094210Z-8d78 | E013-20261128T113800Z-3b30 | E013-20261128T114542Z-31f8 | 0.328 | 27 | 0.600 | 0.192 | 0.308 |
| 256 | truncate | E013-20261128T094210Z-9eca | E013-20261128T113809Z-0a72 | E013-20261128T114550Z-b699 | 0.299 | 29 | 0.533 | 0.154 | 0.308 |
| 256 | no-open | E013-20261128T094210Z-00c9 | E013-20261128T113728Z-732b | E013-20261128T114510Z-07eb | 0.328 | 27 | 0.600 | 0.192 | 0.308 |
| 256 | rrf | E013-20261128T090658Z-450c | E013-20261128T113711Z-ff0a | E013-20261128T114454Z-fff2 | 0.328 | 28 | 0.533 | 0.192 | 0.346 |
| 512 | greedy | E013-20261128T094210Z-d012 | E013-20261128T113833Z-50c3 | E013-20261128T114615Z-24c9 | 0.403 | 21 | 0.733 | 0.308 | 0.308 |
| 512 | truncate | E013-20261128T094210Z-62a7 | E013-20261128T113744Z-cda6 | E013-20261128T114526Z-6d94 | 0.463 | 19 | 0.733 | 0.385 | 0.385 |
| 512 | no-open | E013-20261128T094210Z-cc12 | E013-20261128T113825Z-906b | E013-20261128T114606Z-9e25 | 0.418 | 21 | 0.733 | 0.308 | 0.346 |
| 512 | rrf | E013-20261128T090658Z-10d1 | E013-20261128T113702Z-0c91 | E013-20261128T114446Z-3a69 | 0.463 | 19 | 0.867 | 0.385 | 0.308 |
| 1,024 | greedy | E013-20261128T094210Z-746d | E013-20261128T113752Z-80f5 | E013-20261128T114534Z-2f31 | 0.433 | 21 | 0.933 | 0.269 | 0.308 |
| 1,024 | truncate | E013-20261128T094210Z-55b2 | E013-20261128T113736Z-6229 | E013-20261128T114518Z-0559 | 0.418 | 20 | 0.933 | 0.308 | 0.231 |
| 1,024 | no-open | E013-20261128T094210Z-a7a3 | E013-20261128T113817Z-0be7 | E013-20261128T114558Z-459f | 0.403 | 21 | 0.933 | 0.231 | 0.269 |
| 1,024 | rrf | E013-20261128T090658Z-f05b | E013-20261128T113719Z-2cde | E013-20261128T114502Z-7c11 | 0.418 | 19 | 0.933 | 0.269 | 0.269 |

Reading: on 67 reads one read is 0.015; at each budget the arms differ by at most 4 reads (greedy against truncate and rrf at 512), within the 3-read difference between two identical main-configuration read runs (E012 `full` against E013 greedy at 1,024). The judge does not separate the assembly arms or GRACE from rrf on LongMemEval-S dev; accuracy rises from 256 to 512 for every arm and is flat or lower from 512 to 1,024 (rrf 0.463 -> 0.418, truncate 0.463 -> 0.418).

## Conclusion

On development data (LoCoMo dev, 308 reads; LongMemEval-S dev main-text strata, 67 reads; budgets 256 to 1,024), C4 is not supported in the current implementation: evidence-demand assembly neither raises full evidence hits nor lowers unsupported answers compared with rank truncation of the same candidates or with the rrf fused top-k baseline. Greedy and truncation mostly build identical contexts because the demand has one variable in almost every read and support is the lexical placeholder of plan 5.6 (no verification call). Whether a real verification call, multi-variable plans or summaries with expandable pointers change this is untested. LongMemEval-S answer accuracy is pending a judge (T035).

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: confirmed as optional (user, 2026-11-25); plan sections 7.3, 9 and 9.3 now say so.
- 2026-11-28: development diagnosis of the E007 gap to rrf on LoCoMo dev (session w01-E013, branch `task/E013-ablation-e-assembly`): 7 system runs and their scores in `runs/E013/artifacts/w01-E013/`; fixed the rank-order fill so that claim citations no longer hide raw evidence (`assembly/select.py`, test in `tests/unit/test_assembly.py`); development variants in `configs/experiments/E013-dev/`; draft `configs/experiments/E013-ablation-e-assembly.yaml` (not reviewed). Findings in Results, "Development diagnosis".
- 2026-11-28: decisions of s00-super on the diagnosis (development configuration, before D012). (1) Fill fix accepted (evidence: raw full evidence hit 163 -> 187, F1 0.296 -> 0.314). (2) The main configuration uses `routing: all`: `configs/retrieval/default.yaml` changed, rule routing kept as the E012 arm `configs/retrieval/rules.yaml`, T025 code unchanged (evidence: 110 to 121 reads were dense-only, F1 +0.007 to +0.009 with routing all). (3) The fallback `answer` variable is never listed as an open item; the section stays for planner variables (`Demand.fallback`; evidence: 24 of 33 open-item reads, 20 unknown answers against 9 for rrf, F1 +0.015 without the section). (4) No assembler query expansion for a fallback plan; kept for compiled plans (`Assembler.assemble(query_expansion=...)`; evidence: 37 expansions closed 4 variables, the fallback query repeats the request and spends the read's retrieval). (5) No answer-path or scorer change for temporal scoring; judge accuracy next to F1 where available; the date-format effect is noted in Results. Tests: `tests/unit/test_assembly.py`, `tests/integration/test_grace_engine.py`.
- 2026-11-28: reference rerun of the main configuration after the decisions (LoCoMo dev, 308 reads, budget 1,024): system E013-20261128T075426Z-89f2, score E013-20261128T080905Z-053e, F1 0.330, 47 unknown (Results).
- 2026-11-28: formal ablation (session w01-E013, branch `task/E013-formal`): `configs/experiments/E013-ablation-e-assembly.yaml` finished (arms greedy, truncate, no-open, rrf; pointers-vs-summaries not runnable), arm configs in `configs/experiments/E013/`, new scorer `grace.cli.evidence_score`, `locomo_score` accepts read runs. 24 system/read runs and 36 score runs completed; two snapshot-restore bugs fixed after 18 failed LongMemEval-S read runs (Runs). Results and Conclusion written. Proposed status: E013 active -> review.
- 2026-11-28: recorded done with a remark by the integration owner (s00-super): PR #176 merged; C4 not supported on development data. Remark: LongMemEval-S answer accuracy waits for a judge.
- 2026-11-28: judge (uncalibrated, T035 pending): the local primary judge (DeepSeek-V4-Flash-0731, D006) judged the 9 LongMemEval-S read runs and the 3 rrf system runs, and `judge-accuracy` was scored (session w01-judge; Results, "Judge (uncalibrated, T035 pending)"). At each budget the arms and rrf lie within 4 of 67 reads.
