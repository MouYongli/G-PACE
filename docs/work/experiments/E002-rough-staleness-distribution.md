---
id: E002
title: Rough natural staleness distribution
created: 2026-11-23
---

# E002 · Rough natural staleness distribution

## Question

How often do the seven change types of plan section 6.4 occur per thousand messages in natural dialogue, and how many are missed by citation-based dependencies? Serves RQ2. If the three missed types are rare, view maintenance is positioned for high-revision workloads.

## Design

Written on 2026-11-26 before the first formal run (session `m01-E002`). Config: `configs/experiments/E002-rough-staleness-distribution.yaml`; driver: `uv run python -m grace.cli.staleness` (subcommands `extract`, `measure`); extraction `src/grace/eval/runner/probes/natural_extract.py`, replay `src/grace/eval/runner/probes/natural_staleness.py`, totals `src/grace/eval/analysis/metrics/natural_staleness.py`. Plan sections 3.4, 5.4, 6.4 and 6.5 ("Measuring the natural distribution of staleness"); change types and decision list from `docs/research/change-sequences.md` section 4.1, which prescribes the same list for extracted graphs.

| Item | Value |
| --- | --- |
| Benchmarks and splits | LoCoMo dev (conv-26, conv-49; 928 messages) and LongMemEval-S dev (98 histories, 48,781 messages), every message, loaded through `load_split` with manifest checks. No held-out data |
| Extraction (stage `ingest`) | One call per message with the one-off prompt `extract-claims-rough` (pinned in `configs/common/prompts.yaml`), Qwen3-32B (`configs/models/qwen3-32b.yaml`, D006 writer-scale model, thinking off, temperature 0, seed 0, max 1,024 output tokens), two local vLLM 0.34 servers (one B200 each), every call through `grace.llm.client`. Input: participants, segment date, the 60 most used predicates of the history, up to 40 known current claims with IDs (claims touched in the last 4 messages, then by word overlap with the message and its context), the 2 preceding messages (600 characters each) and the new message (clipped at 8,000 characters). Output: claims (subject, predicate, object, communicative function, single- or multi-valued), stances on known claims (accept, reject, confirm) and known claims that ended (change or correction). Scope: facts about the participants and their tasks; no general knowledge or assistant-written content. The larger writer is used because this measures a property of the data, so extraction quality matters more than matching GRACE's eventual writer; phase 3 repeats the measurement with the final writer (plan 6.5) |
| Mapping to change sets | Fixed rules, no model (`HistoryWriter`): names matched case-insensitively; predicate exclusivity from the seed vocabulary or the first use, never redefined; a claim equal to a current claim becomes an attribution and evidence link on it (repeated mention); a stance becomes an attribution; an ended claim is superseded (change or correction) under a negative `inform` attribution of the speaker; a new `inform` claim of an exclusive predicate supersedes the current claims with the same subject and predicate and another object. Valid times are unknown. Invalid output leaves the version's change set empty and is counted. Every change set is committed through `ClaimStore` (contract checks) into `snapshot/` |
| Views | The six template families of plan 5.4 with the frozen view code and `resources/views/` (T018), `configs/views/default.yaml` with `instantiation_threshold: 1`, `state_speaker: null` (entity families admit any speaker) and `choice_predicate: selectedOption` (the predicate the prompt prescribes for offers). LongMemEval binds the task families to (user, assistant); a LoCoMo history has two peers, so its task families are measured in both speaker orientations and its entity families once. Creating a view is not a staleness event; creations are counted |
| Measurement (stage `probe`, CPU) | Replay of the extraction run's change sets. After every message each resident view is compared with its state one version earlier by the answer, witness and evidence fingerprints (read-time re-query, the exact reference of plan 5.4); a stale view is repaired at once (template rendering), so every comparison is between adjacent versions. Only views marked by a sound candidate filter (the claim-pattern push without local filters, the "claim pattern" rung of plan 3.4; changed on 2026-11-26, see Log) are re-queried; on LoCoMo every view is re-queried at every version and a stale view outside the filter fails the run. Each (message, view) change is typed by the decision list of change-sequences.md 4.1 (C1 state change superseding a cited claim, C2 new match, C3 negation hit, C4 count or order, C5 late correction, C6 repeated mention, C7 irrelevant update), with W_b and R_b taken from the view and "newly matches" read as "enters the witnesses between t-1 and t" |
| Strategies scored | The two citation-based strategies of plan 5.4 as configured in `configs/views/staleness.yaml`: used claims only, and used claims plus negation and aggregation patterns (both `watch_mentions: false`). A stale (message, view) pair they do not mark is a miss. For over-marking: claim-pattern push with local filters and predicate level |
| Metrics | Per benchmark: occurrences of C1-C6 per 1,000 messages, as (message, view) events and as messages with at least one event; answer- and citation-stale events per 1,000 messages and their ratio; misses of each citation-based strategy (count, per 1,000 messages, share of answer staleness, by type); the three missed-by-design types (C2, C3, C4) as answer-stale events per 1,000 messages and share of answer staleness; over-marking of the two sound push strategies; type × outcome cross-table and staleness without a type C1-C6 (diagnostic) |
| Decision rule for D007 (fixed now) | The missed-by-design types are **rare** on a benchmark when their answer-stale events are below 1 per 1,000 messages **and** below 10% of all answer-stale events. Rare on both benchmarks supports D007's option "RQ2 rests on the controlled sequences" (view maintenance positioned for high-revision workloads); otherwise the natural data itself contains the changes citation-based dependencies miss |
| Seeds and budget | Seed 0, temperature 0; one extraction run per benchmark and one measurement run per extraction run. About 50,000 extraction calls on two GPUs; no hosted API |
| Human labels | None in E002. Plan 6.5 corrects the LoCoMo extraction by hand; that is not done in this rough pass and is the main limit. Each measurement run writes `audit-sample.tsv` (up to 20 typed staleness events per type, seed 20261126) for a later audit of whether the message really expresses the typed change |
| Frozen before the first run | Prompt and pin, mapping rules, view code and templates, the candidate filter and classification, the decision rule and this design |

## Acceptance

- [x] Every number traces to a run report: two extraction runs and two completed measurement runs, each with `report.yaml` (Runs table); the failed measurement run `E002-20261126T055223Z-3d61` also has one and is not quoted.

## Runs

Reports are under `$PROJECT_ROOT/runs/E002/artifacts/manager/E002/<run-id>/report.yaml`. Qwen3-32B at revision `9216db5781bf21249d130ec9da846c4624c16137` on vLLM 0.34.0, GPUs 0 and 2, ports 8121 and 8122, `--enable-prefix-caching --max-model-len 32768 --kv-cache-memory-bytes 85899345920 --max-num-seqs 128` (server logs `runs/E002/artifacts/serve/`).

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |
| `E002-20261126T050042Z-dd83` | 2026-11-26 | completed | `b5a7827` | `runs/E002/artifacts/manager/E002/E002-20261126T050042Z-dd83/report.yaml` (extract, LoCoMo dev) |
| `E002-20261126T052939Z-70bb` | 2026-11-26 | completed | `b5a7827` | `runs/E002/artifacts/manager/E002/E002-20261126T052939Z-70bb/report.yaml` (measure of dd83) |
| `E002-20261126T050049Z-f084` | 2026-11-26 | completed | `b5a7827` | `runs/E002/artifacts/manager/E002/E002-20261126T050049Z-f084/report.yaml` (extract, LongMemEval-S dev) |
| `E002-20261126T055223Z-3d61` | 2026-11-26 | failed | `804afd9` | `runs/E002/artifacts/manager/E002/E002-20261126T055223Z-3d61/report.yaml` (measure of f084; `code_dirty`: an uncommitted edit of this file at start; not quoted) |
| `E002-20261126T081116Z-dac0` | 2026-11-26 | completed | `221f571` | `runs/E002/artifacts/manager/E002/E002-20261126T081116Z-dac0/report.yaml` (measure of f084, repeat of 3d61) |

## Results

From completed runs only: LoCoMo measurement `E002-20261126T052939Z-70bb` (extraction `E002-20261126T050042Z-dd83`), LongMemEval measurement `E002-20261126T081116Z-dac0` (extraction `E002-20261126T050049Z-f084`), all at code `b5a7827` (extractions, LoCoMo measurement) or `221f571` (LongMemEval measurement; differs only by the ledger status fix and documentation, the replay code is identical). Numbers are copied from `distribution.json` and `report.yaml` of these runs. An event is one (message, view) pair; "messages" counts messages with at least one event of the type. No intervals are reported (a rough measurement; LoCoMo has two histories).

**Extraction** (`report.yaml` of the extraction runs).

| | LoCoMo | LongMemEval |
| --- | --- | --- |
| Messages | 928 | 48,781 |
| Invalid outputs (empty change set) | 17 (1.8%) | 1,048 (2.1%) |
| New claims / repeated mentions / stances | 439 / 472 / 194 | 66,736 / 15,045 / 15,618 |
| Supersessions (exclusivity rule + ended) | 5 (4 + 1) | 1,433 (1,253 + 180) |
| Messages clipped at 8,000 characters | 0 | 43 |
| Extraction tokens (input / output) | 1.65M / 62K | 111.0M / 5.56M |
| Resident views created | 96 | 11,182 |

**Change types per 1,000 messages** (stale events only; answer-stale and citation-stale).

| Type | LoCoMo events | LoCoMo messages | LongMemEval events | LongMemEval messages |
| --- | --- | --- | --- | --- |
| C1 state change superseding a cited claim | 6.5 | 5.4 | 16.8 | 14.7 |
| C2 new match | 292.0 | 264.0 | 447.0 | 356.2 |
| C3 negation hit | 0 | 0 | 3.6 | 3.5 |
| C4 count or order | 281.3 | 256.5 | 258.1 | 223.2 |
| C5 late correction | 0 | 0 | 2.5 | 0.9 |
| C6 repeated mention | 872.8 | 399.8 | 547.5 | 268.1 |

C2 falls mostly on the `list` family (LoCoMo 261 of 271; LongMemEval 12,563 of 21,805) and on `constraints` (10; 8,853); C4 almost entirely on `count`, which mirrors `list` (every new member of a list is also a count change), so C2 and C4 events of the same message largely coincide. C3 occurs only on LongMemEval (`pending`: an offered option accepted or declined; 174 events, plus 152 negation hits that left the answer unchanged). C2 "empty to non-empty": 0 on LoCoMo, 27 on LongMemEval.

**Answer and citation staleness.**

| | LoCoMo | LongMemEval |
| --- | --- | --- |
| Answer-stale events (per 1,000 messages) | 537 (578.7) | 35,519 (728.1) |
| Citation-stale events (per 1,000 messages) | 811 (873.9) | 26,704 (547.4) |
| Citation : answer | 1.51 | 0.75 |
| Missed-by-design types C2+C3+C4, answer-stale | 532 = 573.3 per 1,000, 99.1% of answer staleness | 34,571 = 708.7 per 1,000, 97.3% of answer staleness |
| Decision rule (below 1 per 1,000 and below 10%) | not rare | not rare |

**Misses of the citation-based strategies** (stale events not marked at any level).

| Strategy | LoCoMo answer-stale missed | LongMemEval answer-stale missed | Citation-stale missed (LoCoMo; LongMemEval) |
| --- | --- | --- | --- |
| Used claims only | 532 of 537 (99.1%): C2 271, C4 261 | 34,580 of 35,519 (97.4%): C2 21,805, C4 12,592, C3 174, C5 1, C6 8 | 810; 26,700 |
| Used claims + negation and aggregation patterns | 271 (50.5%): all C2 | 21,843 (61.5%): C2 21,805, C4 29, C5 1, C6 8 | 431; 17,392 |

**Sound strategies and checks.** Claim-pattern push with local filters missed nothing and over-marked 0 of 1,348 marked events on LoCoMo and 500 of 62,723 (0.8%) on LongMemEval; predicate level missed nothing and over-marked 3,942 of 5,290 (74.5%) and 40,615 of 102,838 (39.5%). The full re-query of every view at every version on LoCoMo found no staleness outside the candidate filter (0 soundness violations); every stale event received a type C1-C6. Type/outcome deviations from change-sequences.md 4.2 (diagnostic): one C1 event with a citation outcome on LoCoMo (one habit ended and another added in the same message left the count unchanged); on LongMemEval 2 C1 and 2 C5 events with citation outcomes and 8 C6 events with answer outcomes.

## Conclusion

On the extracted graphs of both development sets, the three kinds of change that citation-based dependencies miss are not rare: they are the bulk of answer staleness (99% on LoCoMo, 97% on LongMemEval), at 573 and 709 answer-stale events per 1,000 messages against a pre-set rarity threshold of 1. Measured per message, about a quarter (LoCoMo) to a third (LongMemEval) of all messages add a new member to some resident view (C2). Supersessions of a cited claim (C1), the one change the used-claims-only strategy sees, occur at 5 to 15 messages per 1,000. Acceptance and rejection of offers (C3) are rare in both sets (0 and 3.5 per 1,000), so the negation-hit evidence for RQ2 must come from the controlled sequences and task dialogue (MultiWOZ), while new matches and count changes are abundant in natural dialogue.

For D007 this supports: **the D007 option "missed change types are rare" does not apply**; RQ2's claim that citation-based dependencies miss natural staleness has natural-data support, and view maintenance need not be positioned only for high-revision workloads. The RQ2 hypothesis "citation staleness is far more frequent than answer staleness" is not supported at this granularity (ratio 1.5 on LoCoMo, 0.75 on LongMemEval).

Limits, in order of weight:

- **No hand correction of the extraction.** Plan 6.5 corrects the LoCoMo extraction by hand; this rough pass does not, and nothing was audited. Over-granular or spurious claims inflate C2, C4 and C6; missed claims deflate every type. The verdict "not rare" has a margin of more than two orders of magnitude over the threshold, so it survives even if most typed C2 events were spurious, but the individual rates and the citation:answer ratio do not. `audit-sample.tsv` of each measurement run holds up to 20 typed stale events per type for an audit (one annotator, about 200 events in total, judging whether the message really expresses the typed change for the view; a second annotator on a subset for agreement).
- **Granularity drives the counts.** With `instantiation_threshold: 1` every (entity, predicate) pair with one claim gets a list and a count view, and the count mirrors the list. The rates are per resident view of this configuration; a higher threshold or view selection by read frequency (plan 5.4) would lower them. The decision rule is applied to the configuration as configured.
- **One-off extractor.** Qwen3-32B with a one-off prompt, not GRACE's writer; no valid times; supersession only via the exclusivity rule and claims the model marks as ended. Phase 3 repeats the measurement with the final writer and compiler.
- **LongMemEval histories share sessions** (4,493 distinct sessions in 4,706 session occurrences), so its rates are not from fully independent text; the haystack sessions also include assistant-written content the prompt tries to exclude.
- `calls.jsonl` of the extraction runs records every answered call as `ok`; invalid outputs are recorded in `extractions.jsonl` (fixed in `804afd9` for later runs).

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-26: manager session `m01-E002` started on `task/E002-rough-staleness` from `main` at `da699da`; Issue #110. Design and config written before the first formal run. Two Qwen3-32B servers on GPUs 0 and 2 (ports 8121, 8122), reserved in `runs/compute.yaml`.
- 2026-11-26: smoke checks (not runs; first 60 messages of conv-26, first 80 of LongMemEval `58bf7951`): 7 of 60 LoCoMo outputs used the function `confirm` for a re-emitted claim, which the parser rejected. `confirm` was added to the claim functions of the prompt and the parser (new pin) before any formal run. LongMemEval: 3 of 80 invalid (a fence with trailing text, a stance with function `request`, one output cut at the token limit); kept as invalid. Mean prompt 1.3K (LoCoMo) and 1.9K (LongMemEval) tokens.
- 2026-11-26: extraction runs `E002-20261126T050042Z-dd83` (LoCoMo) and `E002-20261126T050049Z-f084` (LongMemEval) completed at `b5a7827`; servers stopped and the reservation removed afterwards. LoCoMo measurement `E002-20261126T052939Z-70bb` completed. The first LongMemEval measurement `E002-20261126T055223Z-3d61` measured all histories but is `failed` (`code_dirty`: the Runs table of this file was edited before it started); repeated from a clean tree as `E002-20261126T081116Z-dac0`. The replay of a few LongMemEval histories takes up to about 75 minutes (median a few minutes); not profiled, the slow histories are not the ones with the most claims. After the runs, commit `804afd9` makes the extraction stage record invalid output as `invalid_output` in `calls.jsonl`; the formal extraction runs predate it.
- 2026-11-26: design change after the first measurement runs, forced by `main`. Merging `main` brought T019's commit `6571524` (user decisions of 2026-11-26 from T020): the matcher option `attribution: false` was removed as unsound, and the evidence fingerprint is now kept per answer (an answer gaining a message another answer already cites is citation-stale). The probe used that option for its candidate filter and for R_b. Changes: the candidate filter is now the claim-pattern push without local filters (the "claim pattern" rung, sound by plan 3.4); R_b matches the view's patterns with their attribution constraint removed, as section 4.1 defines it; the C3 test applies the negated pattern's attribution constraint as before. The extraction runs are unaffected. Both measurements are repeated on the merged code; the earlier measurement runs (`70bb`, `dac0`, and the failed `3d61`) are superseded and not quoted.
- 2026-11-26: the first reruns (`E002-20261126T104708Z-23b2` LoCoMo, `E002-20261126T104818Z-d0bd` LongMemEval) reproduced every staleness count of the superseded runs, and the LongMemEval replay took 6 minutes instead of 2 hours (the old filter marked far more views). They exposed a probe bug: without the full check, a view outside the candidate filter was skipped before the marks of the other strategies were recorded, so predicate-level over-marking and C7 counts were undercounted on LongMemEval (LoCoMo, with the full check, was not affected). Fixed (such views are typed with unchanged witnesses, no re-query), with a test that the filtered and the full replay record the same events. Both measurements repeated again; `23b2` and `d0bd` are superseded and not quoted.
