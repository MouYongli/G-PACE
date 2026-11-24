# Experiments

An experiment answers one question under fixed conditions. Its file holds the design, the list of runs and the results, so everything about it is in one place. Status and dates live in `../plan/plan.yaml`; the config lives in `configs/experiments/E<NNN>-<slug>.yaml`.

The design is written before the first formal run and is not changed afterwards without a dated log entry. Runs and results are filled in with the `experiment-report` skill, and only from `completed` runs.

## Index

| ID | Title | Description |
| --- | --- | --- |
| [E001](E001-pilot-measurements.md) | Pilot measurements | Plan phase 1: costs, lengths, cache ratio and update density on development histories |
| [E002](E002-rough-staleness-distribution.md) | Rough natural staleness distribution | First estimate of how often each change type occurs in natural dialogue |
| [E003](E003-ablation-a-gold.md) | Ablation A on gold graphs | Eight staleness strategies on generator gold graphs, by change type |
| [E004](E004-scale-experiment.md) | Scale experiment: push, pull, hybrid | Database cost of push, pull and hybrid checks as views, writes and graph size grow |
| [E005](E005-ablation-c-gold.md) | Ablation C on gold graphs | Template serialisation versus LLM rendering as input to the answering LLM |
| [E006](E006-graph-quality.md) | Graph quality | Direct evaluation of the extracted claim graph |
| [E007](E007-ablation-g-writer.md) | Ablation G: writer scale, thinking, granularity | What limits extraction, and which granularity fits the write budget |
| [E008](E008-ablation-a-extracted.md) | Ablation A on extracted graphs | Staleness strategies end to end, separating detection misses from extraction misses |
| [E009](E009-natural-staleness-distribution.md) | Natural staleness distribution | Frequency of each change type in natural dialogue with the formal writer and compiler |
| [E010](E010-ablation-c-extracted.md) | Ablation C on extracted graphs | View content source and source annotation with extracted graphs; view hit rate |
| [E011](E011-ablation-b-attribution-guard.md) | Ablation B: attribution guard, representation, time | 2x2x2 over attribution guard, representation and time, plus the two single-arm controls |
| [E012](E012-ablation-d-channels.md) | Ablation D: retrieval channels | Unique contribution of the lexical, dense and graph channels |
| [E013](E013-ablation-e-assembly.md) | Ablation E: assembly | Evidence-demand assembly versus rank truncation (optional, supplementary) |
| [E014](E014-dev-quality-cost.md) | Development quality-versus-cost curves | All systems and baselines on development data with the three ledgers |
| [E015](E015-ablations-f-h.md) | Ablations F and H; call-type invocation arm of G | Vocabulary evolution, routing and fusion, and how LLM call types are invoked (optional) |
| [E016](E016-formal-controlled.md) | Formal run: controlled sequences | Ablation A and the maintenance cost surface on held-out template families |
| [E017](E017-formal-multiwoz.md) | Formal run: MultiWOZ | Attribution-guard handling on the MultiWOZ test set |
| [E018](E018-formal-locomo.md) | Formal run: LoCoMo | Question answering, amortisation and streaming on the eight held-out histories |
| [E019](E019-formal-longmemeval.md) | Formal run: LongMemEval-S | Three strata of the adverse single-read setting |
| [E020](E020-formal-optional.md) | Formal run: optional benchmarks and systems | HaluMem-Medium, MemoryAgentBench, Mem0g and Graphiti (optional) |
| [E021](E021-robustness.md) | Robustness checks | Main conclusions under other models and settings |


## Template

```markdown
---
id: E<NNN>
title: <title>
created: <YYYY-MM-DD>
---

# E<NNN> · <title>

## Question

The question and the research question it serves (link to `docs/research/plan.md`), with the result that would change the plan.

## Design

| Item | Value |
| --- | --- |
| Benchmarks and splits | |
| Systems and baselines | |
| Metrics | links to `docs/research/contracts.md` sections |
| Seeds and budget | |
| Config | `configs/experiments/E<NNN>-<slug>.yaml` |

## Acceptance

- [ ] Every number traces to a run report.

## Runs

| Run ID | Date | Status | Code SHA | Report |
| --- | --- | --- | --- | --- |

## Results

Filled only from completed runs; report scored and invalid counts with every metric.

## Conclusion

What the results support, what they do not, and what follows for the plan.

## Log

- <YYYY-MM-DD>: created.
```
