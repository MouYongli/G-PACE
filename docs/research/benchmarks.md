# Benchmarks

Registry and cards for every benchmark in `docs/research/plan.md` (section 6). Download sources are pinned in `configs/data/sources.yaml` and fetched with `scripts/data/` (see the Benchmarks section of `README.md`). Each benchmark has one section here; its slug is shared by `configs/benchmarks/<slug>.yaml`, `tests/fixtures/benchmarks/<slug>/` and `$PROJECT_ROOT/data/<slug>/<version>/`. Split this file into a folder when a card grows beyond about 100 lines.

## Registry

| Slug | Benchmark | Role in the plan | Status |
| --- | --- | --- | --- |
| `change-seq` | Controlled change sequences (self-built) | RQ4; staleness detection ground truth | to build |
| `multiwoz` | MultiWOZ 2.4 (main), 2.2 (auxiliary) | RQ2, RQ4; per-turn state tracking | to bind |
| `locomo` | LoCoMo | RQ1, RQ3; end-of-history QA | to bind |
| `longmemeval-s` | LongMemEval S (cleaned) | RQ1 adverse setting, RQ3 | to bind |
| `halumem-medium` | HaluMem-Medium | RQ2, RQ4, graph quality | to bind |
| `memoryagentbench` | MemoryAgentBench | RQ1, RQ4; incremental chunks | to bind |
| `stale`, `memora` | STALE, Memora (conditional) | Stale-memory use; added only if released with a usable license | to check |

Status values: `to check` (availability or license unknown), `to bind` / `to build`, `bound` (data, manifest and config in place), `verified` (adapter reproduces the counts below).

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

Pending. See plan section 6.2.

## multiwoz

Pending. See plan section 6.2.

## locomo

Pending. See plan section 6.2.

## longmemeval-s

Pending. See plan section 6.2.

## halumem-medium

Pending. See plan section 6.2.

## memoryagentbench

Pending. See plan section 6.2.
