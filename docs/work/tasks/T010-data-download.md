---
id: T010
title: Benchmark download scripts
created: 2026-11-22
---

# T010 · Benchmark download scripts

## Goal

Reproducible downloads of the five downloaded benchmarks (MultiWOZ 2.4/2.2/2.1, LoCoMo with the audit error lists, LongMemEval-S cleaned, HaluMem-Medium, MemoryAgentBench) at pinned revisions into `$PROJECT_ROOT/data/<slug>/<version>/`, each with a manifest whose SHA-256 is fixed in advance, so that T002 can bind the data and fill `configs/benchmarks/`.

## Scope

- In scope: `configs/data/sources.yaml`; `src/grace/cli/data/download.py` and `src/grace/paths.py`; bash entry points `scripts/data/download.sh` and `scripts/data/b<N>_<slug>.sh`; offline tests; the Benchmarks section of `README.md`; the `scripts/` convention in AGENTS.md and its translation.
- Out of scope: running the download into `$PROJECT_ROOT/data` (done by the data maintainer); adapters, splits and counts (T002); generating change-seq (T008 and later).
- Candidate worker subtasks: none.

## Acceptance

- [x] Offline tests cover download, registered checksums, manifest hash, unpacking without macOS metadata, rerun verification, unsafe paths and dry runs (`make test`).
- [x] A full download into a scratch directory reproduces the registered `manifest_sha256` of all seven versions twice, and a rerun verifies all seven.
- [x] The data maintainer runs `scripts/data/download.sh` in the main checkout and makes `data/` read-only.

## Deliverables

The files in scope.

## Log

- 2026-11-22: created at the user's request; branch `task/T010-data-download`.
- 2026-11-22: full download tested in a scratch directory: 7 versions, about 1.1 GB, 19 s; registered file checksums and manifest hashes match.
- 2026-11-25: verified in the main checkout: `data/` holds the seven versions (downloaded 2026-11-23) and is read-only; the SHA-256 of every `MANIFEST.sha256` equals the registered `manifest_sha256` in `configs/data/sources.yaml`, and `sha256sum -c` passes for every file.
