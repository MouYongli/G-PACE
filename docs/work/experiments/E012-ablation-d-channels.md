---
id: E012
title: "Ablation D: retrieval channels"
created: 2026-11-23
---

# E012 · Ablation D: retrieval channels

## Question

What does each channel contribute that the others do not, and is the graph gain due to retrieval or to attribution-and-time verification? Serves RQ1 and component claim C1.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | LoCoMo, LongMemEval-S and MultiWOZ development data |
| Systems and baselines | Remove BM25, dense or graph in turn with candidates and returned tokens fixed; graph channel switch x verification switch on the same candidates |
| Metrics | Slice accuracy; path evidence recall; stale-value use |
| Seeds and budget | Seed 0; memory budget 1,024 tokens; 20 fused candidates, depth 20 per channel |
| Config | `configs/experiments/E012-ablation-d-channels.yaml`; arm engines `configs/experiments/E012/` |

## Acceptance

- [x] Every number traces to a run report.

## Runs

All runs under `runs/E012/artifacts/w01-E012/E012/<run-id>/` (report in `report.yaml` of each). Read runs restore a shared main-configuration ingest snapshot: LoCoMo `E006-20261128T082608Z-21cb`, LongMemEval-S main-text strata `E006-20261128T083145Z-6288`, other strata `E006-20261128T084142Z-ee92`.

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| E012-20261128T090721Z-5a64 | 2026-11-28 | completed | a769ac4 | LoCoMo read, full |
| E012-20261128T091234Z-33b9 | 2026-11-28 | completed | a769ac4 | LoCoMo F1 of -5a64 |
| E012-20261128T091235Z-993f | 2026-11-28 | completed | a769ac4 | LoCoMo read, no-bm25 |
| E012-20261128T091606Z-13ba | 2026-11-28 | completed | a769ac4 | LoCoMo F1 of -993f |
| E012-20261128T091607Z-3ce8 | 2026-11-28 | completed | a769ac4 | LoCoMo read, no-dense |
| E012-20261128T091848Z-035b | 2026-11-28 | completed | a769ac4 | LoCoMo F1 of -3ce8 |
| E012-20261128T091850Z-4650 | 2026-11-28 | completed | a769ac4 | LoCoMo read, no-graph-channel |
| E012-20261128T092134Z-5186 | 2026-11-28 | completed | a769ac4 | LoCoMo F1 of -4650 |
| E012-20261128T092135Z-334e | 2026-11-28 | completed | a769ac4 | LoCoMo read, no-graph-state |
| E012-20261128T092523Z-57bb | 2026-11-28 | completed | a769ac4 | LoCoMo F1 of -334e |
| E012-20261128T092525Z-bac4 | 2026-11-28 | completed | a769ac4 | LoCoMo read, no-verification |
| E012-20261128T092922Z-2ce4 | 2026-11-28 | completed | a769ac4 | LoCoMo F1 of -bac4 |
| E012-20261128T092923Z-2106 | 2026-11-28 | completed | a769ac4 | LoCoMo read, no-graph-no-verification |
| E012-20261128T093202Z-5bbc | 2026-11-28 | completed | a769ac4 | LoCoMo F1 of -2106 |
| E012-20261128T093228Z-2d2a | 2026-11-28 | completed | 8201795 | LoCoMo read, no-graph |
| E012-20261128T093503Z-c0cb | 2026-11-28 | completed | 8201795 | LoCoMo F1 of -2d2a |
| E012-20261128T093504Z-5645 | 2026-11-28 | completed | 8201795 | LoCoMo read, rules |
| E012-20261128T093742Z-8da6 | 2026-11-28 | completed | 8201795 | LoCoMo F1 of -5645 |
| E012-20261128T093747Z-5666 | 2026-11-28 | completed | 8201795 | LoCoMo read, full (repeat, rerun noise) |
| E012-20261128T094033Z-1df7 | 2026-11-28 | completed | 8201795 | LoCoMo F1 of -5666 |
| E012-20261128T094046Z-72d5 | 2026-11-28 | completed | 8201795 | LoCoMo per-arm metrics (channel_ablation, 10 arms) |
| E012-20261128T094042Z-10c1, -094058Z-bc45, -094114Z-3210, -094129Z-ab1f | 2026-11-28 | failed | 8201795 | LongMemEval (ee92) reads full, no-bm25, no-dense, no-graph-channel: history 41275add does not restore (QueryTypeError) |
| E012-20261128T094145Z-d1fe | 2026-11-28 | failed | 8201795 | LongMemEval (ee92) read no-graph-state, stopped by the session after the failures above |
| E012-20261128T094231Z-2963, -094246Z-15bf | 2026-11-28 | failed | 8201795 | LongMemEval (6288) reads full, no-bm25: histories f9e8c073, 0ddfec37_abs do not restore (JSONDecodeError) |
| E012-20261128T094305Z-5859 | 2026-11-28 | failed | 8201795 | LongMemEval (6288) read no-dense, stopped by the session |
| E012-20261128T094342Z-cbf5, -094404Z-02fa | 2026-11-28 | failed | 8201795 | LongMemEval (6288) reads full, no-bm25: four more histories do not restore (QueryTypeError) |
| E012-20261128T094427Z-0854 | 2026-11-28 | failed | 8201795 | LongMemEval (6288) read no-dense, stopped by the session |
| E012-20261128T094451Z-a006 .. -095154Z-3eac (9 runs) | 2026-11-28 | completed | 8201795 | Superseded by the all-history reruns below (kept): LongMemEval main-text strata reads, 61 of 67 histories, one per arm (-a006 full, -08ce no-bm25, -bdc5 no-dense, -6ff6 no-graph-channel, -b112 no-graph-state, -01ec no-graph, -03a2 no-verification, -4f5e no-graph-no-verification, -3eac rules) |
| E012-20261128T095245Z-3c53 .. -095615Z-1bb9 (9 runs) | 2026-11-28 | completed | 8201795 | Superseded (kept): LongMemEval other strata reads, 30 of 31 histories (-3c53 full, -833e no-bm25, -6e7e no-dense, -29e5 no-graph-channel, -a493 no-graph-state, -e73c no-graph, -c15f no-verification, -db93 no-graph-no-verification, -1bb9 rules) |
| E012-20261128T095643Z-68a2 | 2026-11-28 | completed | 8201795 | Superseded: LongMemEval main-text strata per-arm metrics, 61 histories |
| E012-20261128T095654Z-a8a7 | 2026-11-28 | completed | 8201795 | Superseded: LongMemEval other strata per-arm metrics, 30 histories |
| E012-20261128T101305Z-8c1f .. -102035Z-e806 (9 runs) | 2026-11-28 | completed | 83905a9 | LongMemEval main-text strata reads, all 67 histories (-8c1f full, -844a no-bm25, -c07e no-dense, -b89e no-graph-channel, -58db no-graph-state, -6bdc no-graph, -8857 no-verification, -5e7e no-graph-no-verification, -e806 rules) |
| E012-20261128T102129Z-87c1 .. -102501Z-e6a1 (9 runs) | 2026-11-28 | completed | 83905a9 | LongMemEval other strata reads, all 31 histories (-87c1 full, -d315 no-bm25, -6b32 no-dense, -8dfb no-graph-channel, -fe69 no-graph-state, -bc4f no-graph, -882f no-verification, -3888 no-graph-no-verification, -e6a1 rules) |
| E012-20261128T102529Z-38cd | 2026-11-28 | completed | 83905a9 | LongMemEval main-text strata per-arm metrics, 67 reads |
| E012-20261128T102541Z-8574 | 2026-11-28 | completed | 83905a9 | LongMemEval other strata per-arm metrics, 31 reads |

## Results

Development data only; one seed; no judge. Every number below is copied from `channels.json` of the named per-arm run (`metrics.json` of the F1 score runs for F1). Differences are paired against the arm `full` on the same snapshot; brackets give a 95% bootstrap interval over reads (seed 0, 2,000 resamples; reads, not histories, are resampled, so the intervals are optimistic for two LoCoMo histories). Rerun noise: a repeat of `full` differs by +0.001 F1 [-0.001, +0.003], 6 of 308 contexts differ (planner outputs vary at temperature 0).

### What the arms switch

- Channel arms change `channels` in the retrieval config; `total: 20` fused candidates and the 1,024-token budget stay fixed.
- The graph reaches the context two ways: its channel's evidence messages in fusion, and the planner's query answers (and view sentences) as state items. `no-graph-channel` removes the first, `no-graph-state` the second, `no-graph` both. The planner still runs in every arm, so the demand variables are the same.
- **Verification has no LLM step to switch.** The verification call of plan 5.6 is not implemented (T026 log). What exists is the deterministic read-time filter of assembly (`retired`, `valid`, `scope`, `attribution`), switched by the new assembly key `verification`. In the main configuration only `retired` can fire: the engine never sets an attribution constraint (`engine._constraints`), and neither query answers nor messages carry a valid-time interval or a scope. The 2x2 is therefore run over what exists.

### LoCoMo dev (308 reads; per-arm run E012-20261128T094046Z-72d5)

| Arm | F1 | dF1 vs full | unknown | fused recall | path recall | full hit (raw) | graph cands | state shown |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full | 0.341 | | 0.140 | 0.746 | 0.725 | 0.632 | 0.256 | 0.260 |
| full (repeat) | 0.342 | +0.001 [-0.001, +0.003] | 0.140 | 0.744 | 0.725 | 0.632 | 0.260 | 0.263 |
| no-bm25 | 0.324 | -0.017 [-0.043, +0.007] | 0.156 | 0.700 | 0.692 | 0.596 | 0.260 | 0.263 |
| no-dense | 0.284 | -0.057 [-0.088, -0.028] | 0.224 | 0.603 | 0.592 | 0.507 | 0.266 | 0.269 |
| no-graph-channel | 0.339 | -0.002 [-0.014, +0.007] | 0.143 | 0.736 | 0.734 | 0.626 | 0 | 0.263 |
| no-graph-state | 0.351 | +0.009 [-0.003, +0.024] | 0.149 | 0.757 | 0.724 | 0.642 | 0.266 | 0 |
| no-graph | 0.340 | -0.002 [-0.014, +0.009] | 0.153 | 0.738 | 0.719 | 0.636 | 0 | 0 |
| no-verification | 0.341 | +0.000 [-0.002, +0.002] | 0.140 | 0.744 | 0.725 | 0.632 | 0.260 | 0.263 |
| no-graph-no-verification | 0.340 | -0.001 [-0.012, +0.009] | 0.153 | 0.738 | 0.719 | 0.636 | 0 | 0 |
| rules | 0.331 | -0.011 [-0.029, +0.008] | 0.136 | 0.729 | 0.705 | 0.616 | 0.263 | 0.266 |

F1 by LoCoMo category (n 69 / 70 / 26 / 143; difference to full in parentheses):

| Arm | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| full | 0.317 | 0.081 | 0.126 | 0.520 |
| no-bm25 | 0.327 (+0.010) | 0.076 (-0.005) | 0.132 (+0.006) | 0.479 (-0.041) |
| no-dense | 0.230 (-0.087) | 0.071 (-0.010) | 0.076 (-0.050) | 0.455 (-0.067) |
| no-graph-channel | 0.312 (-0.005) | 0.081 (+0.000) | 0.133 (+0.006) | 0.516 (-0.003) |
| no-graph-state | 0.329 (+0.012) | 0.081 (+0.000) | 0.134 (+0.008) | 0.533 (+0.013) |
| no-graph | 0.292 (-0.025) | 0.081 (+0.000) | 0.131 (+0.005) | 0.527 (+0.008) |
| no-verification | 0.319 (+0.002) | 0.081 (+0.000) | 0.130 (+0.004) | 0.518 (-0.002) |
| rules | 0.311 (-0.006) | 0.081 (-0.000) | 0.152 (+0.026) | 0.495 (-0.024) |

Intervals on the category differences: no-dense category 1 -0.087 [-0.156, -0.025], category 4 -0.067 [-0.120, -0.018]; no-bm25 category 4 -0.041 [-0.089, +0.009]; no-graph category 1 -0.025 [-0.067, +0.011]. Category 2 F1 is near 0.08 for every arm because answers are ISO dates (E013 diagnosis) and does not separate arms.

Unique contribution at the candidate level (arm `full`; gold evidence messages among the fused candidates, by which channels ranked them within depth 20): 163 BM25 and dense, 16 all three, 19 dense and graph, 1 BM25 and graph, **82 dense only, 34 BM25 only, 11 graph only** (graph only: 9 in category 1, 1 each in 3 and 4). The graph channel returns candidates in 26% of reads (it exists only when the planner compiled a query with answers).

Rule routing: 119 of 308 reads were routed to dense alone and 4 to BM25 alone (run -5645 traces). It made the same LLM calls as `routing: all` (plan 327 vs 326, repair 123 vs 121) and saved 4 of 326 query embeddings, so it does not lower per-read cost here; its read-side tokens per read were 4,390 against 4,362.

Verification switch: contexts differ from `full` in 7 of 308 reads with the filter off, against 6 of 308 between two runs of `full`; with the graph off, in 2 of 308. No measurable effect.

### LongMemEval-S dev (per-arm runs E012-20261128T102529Z-38cd, main-text strata, 67 reads; E012-20261128T102541Z-8574, other strata, 31 reads)

All 98 development histories, read at code 83905a9 (main's snapshot-restore fixes; an earlier pass on 61 + 30 restorable histories is superseded and gave the same picture). No answer accuracy (no judge run). Path recall and unknown share; abstention questions have no evidence and count only in `unknown`.

| Arm | path recall (main) | dPath (main) | unknown (main) | path recall (other) | dPath (other) | unknown (other) |
| --- | --- | --- | --- | --- | --- | --- |
| full | 0.827 | | 0.313 | 0.872 | | 0.226 |
| no-bm25 | 0.853 | +0.026 [-0.040, +0.092] | 0.284 | 0.889 | +0.017 [+0.000, +0.050] | 0.290 |
| no-dense | 0.696 | -0.131 [-0.199, -0.071] | 0.448 | 0.717 | -0.156 [-0.289, -0.033] | 0.355 |
| no-graph-channel | 0.835 | +0.008 [+0.000, +0.023] | 0.313 | 0.883 | +0.011 [+0.000, +0.033] | 0.194 |
| no-graph-state | 0.827 | +0.000 [-0.023, +0.023] | 0.299 | 0.872 | +0.000 | 0.226 |
| no-graph | 0.819 | -0.008 [-0.031, +0.015] | 0.299 | 0.872 | +0.000 | 0.194 |
| no-verification | 0.827 | +0.000 | 0.313 | 0.872 | +0.000 | 0.226 |
| no-graph-no-verification | 0.819 | -0.008 [-0.031, +0.015] | 0.299 | 0.872 | +0.000 | 0.194 |
| rules | 0.837 | +0.010 [-0.054, +0.076] | 0.313 | 0.872 | +0.000 | 0.226 |

Path recall of `full` by stratum: knowledge-update 0.893 (n 15), multi-session 0.710 (n 26), temporal-reasoning 0.904 (n 26); single-session-assistant 0.727 (n 11), -preference 0.861 (n 6), -user 1.000 (n 14). Without dense: -0.107, -0.193, -0.083; -0.091, -0.444, -0.077. Without BM25, multi-session rises by 0.100: BM25 candidates displace dense ones that carry the evidence. Unique evidence among the fused candidates of `full`: dense only 16 + 5, BM25 only 2 + 0, graph only 0 + 0 (main + other); the graph channel returns candidates in 15% and 42% of reads.

### Not measured

- **Stale-value use.** Neither LoCoMo nor LongMemEval carries gold for the superseded value, and the knowledge-update stratum needs the judge. Not measured here; the controlled sequences (E016) are where it can be.
- **MultiWOZ.** Not run. Estimate: per-turn reads need a `system` run per arm (the read stage restores only end-of-history snapshots), so each arm re-runs the Qwen3-32B writer. E011's GRACE system run on its MultiWOZ dev subset took about 20 minutes wall time over 10 shards per arm (about 3.3M writer tokens), on the shared writer server that E011 is using. Nine arms would be about 3 hours of shared writer load, and arms would differ in writer output as well as in the switch. The read request is a fixed state request ("report the current state for ..."), so the text channels have little to rank. Left as an open item for s00-super.

## Conclusion

Development evidence, before D012. On LoCoMo and LongMemEval-S dev at 1,024 tokens:

- C1 holds for dense and partly for BM25: removing dense costs 0.057 F1 on LoCoMo (multi-hop and single-hop categories) and 13 to 16 points of path recall on LongMemEval; removing BM25 costs 0.017 F1 (interval includes 0), concentrated in category 4 (-0.041), and does not hurt LongMemEval.
- The graph channel, as extracted and queried now, contributes no measurable accuracy: removing it entirely changes LoCoMo F1 by -0.002 [-0.014, +0.009]. Its only consistent trace is category 1 (-0.025, interval includes 0) and 11 evidence messages only it found. Showing the query answers as state items does not help (+0.009 without them).
- The "graph gain from retrieval or verification" question cannot be answered on this code: there is no graph gain to split, and the only verification step that exists (the read-time filter) is inert on these data.
- C3 is not supported: rule routing costs 0.011 F1 and no tokens are saved.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-28: w01-E012 (s00-super batch 2). Added read-side switches `state_items` and `verification` to the assembly config (defaults unchanged), arm configs, the experiment config and `grace.cli.channel_ablation`; `locomo_score` now accepts read runs. LoCoMo arms run on the E006 ingest snapshot. The arms run at a769ac4 had unquoted `description` values in two engine configs (`no-graph`, `rules`), which failed to parse; both were fixed (quotes only) at 8201795 and rerun; the other arm files differ between the two SHAs only by those quotes.
- 2026-11-28: LongMemEval snapshot defects found while restoring (not fixed here, outside E012's scope): (1) `MessageLog.restore` splits the log with `str.splitlines()`, which also splits on Unicode line separators inside message text, so histories f9e8c073 and 0ddfec37_abs of E006-20261128T083145Z-6288 fail with JSONDecodeError (fix: split on "\n" only); (2) a stored view query with an entity whose name starts with digits (`1950s_era_Cuban_peso_note`, `50mm_f_1_8_prime_lens`) does not re-parse (`grammar.parse`, QueryTypeError), so 7405e8b1, b46e15ee, f0e564bc, gpt4_2655b836 (6288) and 41275add (E006-20261128T084142Z-ee92) fail. The LoCoMo snapshot is unaffected. LongMemEval arms rerun on the restorable histories.
- 2026-11-28: MultiWOZ not run (estimate in Results). Proposed status: E012 planned -> review.
- 2026-11-28: both restore defects were fixed on main meanwhile (aa2c9fc, 81e51d7, E013). After merging main, all LongMemEval arms were rerun on all 98 histories at 83905a9; the Results use these runs, the partial runs stay in the Runs table as superseded.
