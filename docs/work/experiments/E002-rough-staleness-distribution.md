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
| Measurement (stage `probe`, CPU) | Replay of the extraction run's change sets. After every message each resident view is compared with its state one version earlier by the answer, witness and evidence fingerprints (read-time re-query, the exact reference of plan 5.4); a stale view is repaired at once (template rendering), so every comparison is between adjacent versions. Only views marked by a sound candidate filter (claim-pattern matching without attribution constraints or local filters, wider than the claim-pattern rung of plan 3.4) are re-queried; on LoCoMo every view is re-queried at every version and a stale view outside the filter fails the run. Each (message, view) change is typed by the decision list of change-sequences.md 4.1 (C1 state change superseding a cited claim, C2 new match, C3 negation hit, C4 count or order, C5 late correction, C6 repeated mention, C7 irrelevant update), with W_b and R_b taken from the view and "newly matches" read as "enters the witnesses between t-1 and t" |
| Strategies scored | The two citation-based strategies of plan 5.4 as configured in `configs/views/staleness.yaml`: used claims only, and used claims plus negation and aggregation patterns (both `watch_mentions: false`). A stale (message, view) pair they do not mark is a miss. For over-marking: claim-pattern push with local filters and predicate level |
| Metrics | Per benchmark: occurrences of C1-C6 per 1,000 messages, as (message, view) events and as messages with at least one event; answer- and citation-stale events per 1,000 messages and their ratio; misses of each citation-based strategy (count, per 1,000 messages, share of answer staleness, by type); the three missed-by-design types (C2, C3, C4) as answer-stale events per 1,000 messages and share of answer staleness; over-marking of the two sound push strategies; type × outcome cross-table and staleness without a type C1-C6 (diagnostic) |
| Decision rule for D007 (fixed now) | The missed-by-design types are **rare** on a benchmark when their answer-stale events are below 1 per 1,000 messages **and** below 10% of all answer-stale events. Rare on both benchmarks supports D007's option "RQ2 rests on the controlled sequences" (view maintenance positioned for high-revision workloads); otherwise the natural data itself contains the changes citation-based dependencies miss |
| Seeds and budget | Seed 0, temperature 0; one extraction run per benchmark and one measurement run per extraction run. About 50,000 extraction calls on two GPUs; no hosted API |
| Human labels | None in E002. Plan 6.5 corrects the LoCoMo extraction by hand; that is not done in this rough pass and is the main limit. Each measurement run writes `audit-sample.tsv` (up to 20 typed staleness events per type, seed 20261126) for a later audit of whether the message really expresses the typed change |
| Frozen before the first run | Prompt and pin, mapping rules, view code and templates, the candidate filter and classification, the decision rule and this design |

## Acceptance

- [ ] Every number traces to a run report.

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |

## Results

Not run.

## Conclusion

Pending.

## Log

- 2026-11-23: created from the full project DAG.
