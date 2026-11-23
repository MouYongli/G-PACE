# Benchmarks

Registry and cards for every benchmark in `docs/research/plan.md` (sections 6.3 to 6.5). Download sources are pinned in `configs/data/sources.yaml` and fetched with `scripts/data/` (see the Benchmarks section of `README.md`). Each benchmark has one section here; its slug is shared by `configs/benchmarks/<slug>.yaml`, `tests/fixtures/benchmarks/<slug>/` and `$PROJECT_ROOT/data/<slug>/<version>/`. Split this file into a folder when a card grows beyond about 100 lines.

## Registry

| Slug | Benchmark | Tier | Read protocol | Role in the plan | Status |
| --- | --- | --- | --- | --- | --- |
| `change-seq` | Controlled change sequences (built here; design in T008) | Main text (core) | Interleaved | RQ2 primary (per-message staleness ground truth); RQ3 maintenance surface | to build |
| `multiwoz` | MultiWOZ 2.4 (main); 2.2 and 2.1 score the same predictions | Main text (core) | Per turn | RQ1 primary for roles (turns after an offer, T006); natural over-marking, no cost claims | to bind |
| `locomo` | LoCoMo, categories 1 to 4 | Main text (core) | End of history; evidence-anchored streaming (T007) | RQ1 slices; RQ2 false positives under streaming; RQ3 amortisation | to bind |
| `longmemeval-s` | LongMemEval S (cleaned); main text uses the knowledge-update, temporal-reasoning and multi-session strata | Main text | End of history, one question per history | RQ1 and RQ3 adverse setting | to bind |
| `halumem-medium` | HaluMem-Medium | Summary table (optional) | Session by session | Graph quality (write path); RQ2 support | to bind |
| `memoryagentbench` | MemoryAgentBench: LongMemEval(S\*) and FactConsolidation at 6K and 32K | Summary table (optional) | Chunk by chunk, several questions per context | RQ3 multi-read; RQ2 support | to bind |
| `beam`, `memora`, `stale` | BEAM, Memora, STALE | Not evaluated | — | Related work only; may enter the supplementary material after the lock if budget remains | not evaluated |

Status values: `to check` (availability or license unknown), `to bind` / `to build`, `bound` (data, manifest and config in place), `verified` (adapter reproduces the counts below), `not evaluated` (considered and left out of the evaluation; no card is kept).

## Card template

Each benchmark section uses these fields. The data owner fills them when binding the data; counts must be reproduced by the adapter before the status becomes `verified`.

| Field | What to record |
| --- | --- |
| Source and license | Official name, citation, download source, release or revision, license and its publishing limits |
| Units | History unit, segment and message, mapped to the records in `contracts.md` |
| Splits and counts | Files, counts per split, development / held-out lists used by the plan |
| Reading protocol | When the system ingests and when it answers; what is masked |
| Evaluation | Official scorer and version, metric direction, denominator, invalid-output policy |
| Known issues | Label errors, overlaps, exclusions (for example images), deviations from the official protocol |
| Manifest | Relative path, size and SHA-256 of every source file; recorded in the config |

## change-seq

Pending. See plan section 6.4 and the generator design (T008).

## multiwoz

Pending. See plan sections 6.3 to 6.5.

## locomo

Pending. See plan sections 6.3 to 6.5.

## longmemeval-s

Pending. See plan sections 6.3 to 6.5.

## halumem-medium

Pending. See plan sections 6.3 to 6.5.

## memoryagentbench

Pending. See plan sections 6.3 to 6.5.
