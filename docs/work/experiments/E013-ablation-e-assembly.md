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
| Seeds and budget | TBD in config |
| Config | `configs/experiments/E013-ablation-e-assembly.yaml` (to be created) |

## Acceptance

- [ ] Every number traces to a run report.

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

All rows are development diagnosis runs (LoCoMo dev, conv-26 and conv-49, 308 end-of-history reads, budget 1,024, Qwen3-8B answering and planning, Qwen3-32B writer with session units), not formal E013 runs. Per-read plan and assembly records and the analysis scripts are in `runs/E013/artifacts/w01-E013/diagnosis/`.

## Results

No formal E013 run yet.

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

**Temporal scoring.** Token F1 on category 2 stays near 0.08 for every system because answers are written as ISO dates (item 5 above); no answer-path or scorer change was made. No judge accuracy exists for these runs: the LoCoMo judge is the remote comparison judge of the pilot (E001 reports it for `rrf` only), and it was not run here. s00-super raises the date format for D012.

## Conclusion

Pending.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: confirmed as optional (user, 2026-11-25); plan sections 7.3, 9 and 9.3 now say so.
- 2026-11-28: development diagnosis of the E007 gap to rrf on LoCoMo dev (session w01-E013, branch `task/E013-ablation-e-assembly`): 7 system runs and their scores in `runs/E013/artifacts/w01-E013/`; fixed the rank-order fill so that claim citations no longer hide raw evidence (`assembly/select.py`, test in `tests/unit/test_assembly.py`); development variants in `configs/experiments/E013-dev/`; draft `configs/experiments/E013-ablation-e-assembly.yaml` (not reviewed). Findings in Results, "Development diagnosis".
- 2026-11-28: decisions of s00-super on the diagnosis (development configuration, before D012). (1) Fill fix accepted (evidence: raw full evidence hit 163 -> 187, F1 0.296 -> 0.314). (2) The main configuration uses `routing: all`: `configs/retrieval/default.yaml` changed, rule routing kept as the E012 arm `configs/retrieval/rules.yaml`, T025 code unchanged (evidence: 110 to 121 reads were dense-only, F1 +0.007 to +0.009 with routing all). (3) The fallback `answer` variable is never listed as an open item; the section stays for planner variables (`Demand.fallback`; evidence: 24 of 33 open-item reads, 20 unknown answers against 9 for rrf, F1 +0.015 without the section). (4) No assembler query expansion for a fallback plan; kept for compiled plans (`Assembler.assemble(query_expansion=...)`; evidence: 37 expansions closed 4 variables, the fallback query repeats the request and spends the read's retrieval). (5) No answer-path or scorer change for temporal scoring; judge accuracy next to F1 where available; the date-format effect is noted in Results. Tests: `tests/unit/test_assembly.py`, `tests/integration/test_grace_engine.py`.
