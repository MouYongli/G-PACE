---
id: D004
title: Python version and inference environment
created: 2026-11-22
---

# D004 · Python version and inference environment

## Context

The plan (section 7) runs Qwen3-8B for writing, planning, rendering and reading, an embedding model, and a long-context second reader, all locally; the write side of LongMemEval-S alone is estimated at 80M to 680M tokens. Everything else (claim graph, SPARQL, BM25, exact cosine, statistics, judging aggregation) needs only CPU. The machine has 8 NVIDIA B200 GPUs (Blackwell, sm_100) shared with other users, driver 580 (CUDA 13.0 runtime), a system CUDA toolkit 13.5 that is newer than the driver supports, and system Python 3.12. vLLM pins its own torch and CUDA wheels and changes often. With `requires-python = ">=3.10"`, CI resolved on 3.10 while runs would use 3.12.

## Decision

- **Python 3.12 everywhere.** `.python-version` pins 3.12; `requires-python = ">=3.12,<3.13"`; CI and ruff target 3.12.
- **Two environments.** The research environment (`.venv`, `make setup`) is CPU-only and holds all research code, tests and analysis. The serving environment (`envs/serve/.venv`, `make setup-serve`) holds only vLLM with its torch and CUDA wheels, locked separately in `envs/serve/uv.lock`.
- **HTTP boundary.** Research code calls models through the OpenAI-compatible API of vLLM servers started with `scripts/serve-model.sh`, one server per model and reserved GPU set, with prefix caching on. GPU packages are never added to `pyproject.toml`.
- **No system CUDA dependency.** Wheels bring their own CUDA runtime; the locked torch is a cu130 build, matching the driver's CUDA 13.0. The system toolkits are 12.8, 12.9 and 13.5; 13.5 is newer than the driver supports and no 13.0 toolkit is installed, so kernels that compile at run time (JIT) are checked in the serving smoke test, and `CUDA_HOME` is set explicitly if one is needed.
- **Model weights** live in the Hugging Face cache (`HF_HOME`), shared by all worktrees, never under `data/`. Every formal run records the model revision.
- **External memory baselines** (Mem0, Graphiti) get their own environments, set up by the task that integrates them.
- **Research dependencies** cover phase 1: graph store and SPARQL (`pyoxigraph`), RDF and SHACL (`rdflib`, `pyshacl`), BM25 (`bm25s`), exact cosine (`numpy`), structured-output validation (`jsonschema`), the inference client (`openai`), token counting with the model's tokenizer and chat template (`transformers`, without torch), configs (`pyyaml`); analysis extra: `pandas`, `scipy`, `statsmodels`, `matplotlib`. No approximate vector index, training framework or orchestration framework.

## Consequences

- CI and all non-GPU work run without GPUs or vLLM.
- vLLM can be upgraded or rolled back without touching the research lock, and several model servers can run side by side on different GPUs.
- Cache-hit token counts reported by the server feed the measured cache ratio of plan section 8 (to be verified in T004).
- `run.json` should record the serving stack (model revision, vLLM, torch, CUDA and driver versions, GPU model). The `environment` field of the experiment-run contract lists only `python`, `lock_sha256`, `host` and `device`; extending it is requested from that section's owner.
- GPU use must be reserved in `COMPUTE_ALLOCATION` because the machine is shared.

## Revisit when

vLLM drops Python 3.12 or a needed library requires 3.13; the project moves to another machine or to hosted inference; the judge provider (still open) needs its own SDK.

## Log

- 2026-11-22: accepted at the user's request (T009).
