---
id: T027
title: Structured and tagged baselines
created: 2026-11-23
---

# T027 · Structured and tagged baselines

## Goal

The baselines of plan section 7.2 that need the writer: a fixed-schema slot table with speaker and communicative-function fields and sources, an append-only memory that resolves conflicts at query time without caching, the template-serialisation variant of the system, and hybrid retrieval over chunks tagged with speaker and dialogue act.

## Scope

- In scope:
  - All use the same answering LLM, answer prompt and budgets.
  - Tags are predicted by the same writer and their tokens are charged.
- Out of scope: External systems (T029, T034).
- Layout (decision D013): a system that reuses the GRACE assembly is a config under `configs/engines/`, and the component it replaces lives in `src/grace/context/` next to the original. This holds for the template-serialisation variant, query-time resolution without views, and the slot table of ablation B. Only tagged hybrid retrieval, which does not use the GRACE assembly, goes to `src/grace/eval/engines/baselines/`.
- Open question, to settle with the manager of T003: whether the slot table of the phase 1 pilot and the slot table of ablation B are one implementation or two (see T003). Record the choice in both Logs.
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Each baseline runs on the development set through the common runner and ledger.
- [ ] `make test` and `make lint` pass.

## Deliverables

Replacement components under `src/grace/context/` with their configs under `configs/engines/`; the tagged retrieval baseline under `src/grace/eval/engines/baselines/`.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-24: layout and the open question about the slot table added from decision D013.
- 2026-11-28: worker session `w01-T027` (directed by `s00-super`, no manager this round) started on `task/T027-structured-baselines` from `origin/main` at `b7c62c3`; Issue #139.
- 2026-11-28: slot-table question settled, following the T003 Log of 2026-11-25: two implementations. The pilot slot table stays T003's standalone baseline (`eval/engines/baselines/slots.py`, no guard, no bitemporality); the slot table of ablation B is a separate component inside `context/` (`context/memory/graph/slots.py`, next to the claim store it replaces, with its writer step `context/pipeline/update/slots.py`), because `context/` must not import `eval/` (D013). What they share is the frozen slot inventory and function list, read by both from `configs/engines/slot-table.yaml`. The ablation-B table adds a subject per row (the key is subject and slot), report mode, polarity, correction and valid time; which slots are exclusive is a development placeholder (`DEFAULT_EXCLUSIVE`) frozen with the inventory.
- 2026-11-28: tagged hybrid retrieval (`eval/engines/baselines/tagged.py`, engine `tagged`, `configs/engines/rrf-tagged.yaml`): the RRF settings of `rrf.yaml` with `[speaker: X; acts: ...]` prepended to every chunk before indexing, embedding and display. Speaker from the message; dialogue acts predicted by the writer model with the writer's eight function labels (read from the writer schema), one `extract` call (ledger W) per unit of the writer's granularity (8 messages, 2 earlier), new pinned prompt `tag-dialogue-acts` with schema; a partial unit is tagged before a read (trigger `read`); a failed call gives `acts: unknown`. The writer itself is not called because baselines may import only `api.py` and `memory/index/` from `context/` (structure.md). The schema has no `uniqueItems`: vLLM's grammar backend rejects it with HTTP 400 (first MultiWOZ smoke run `T027-20261128T001353Z-ef8c`: every tagging call failed, all messages tagged `unknown`; kept as evidence, not a valid smoke run).
- 2026-11-28: development smoke runs of `rrf-tagged` (not an experiment: no tuning, no scores), Qwen3-8B on the shared server (port 8252) and Qwen3-Embedding-0.6B (port 8251), budget 1024, code `d10de59`, under `runs/T027/artifacts/w01-T027/T027/`: MultiWOZ `MUL1003.json` `T027-20261128T001524Z-3284` (17 reads, completed; 17 tagging calls, all `ok`); LoCoMo `conv-26` `T027-20261128T001540Z-5af7` (152 reads, completed; 53 tagging calls all `ok`, 62,696 W tokens against 230,876 answer tokens; 2 answer calls `invalid_output` and retried). Most frequent tags in the shown contexts: `inform`, `question`, `inform, question`, `confirm`.
- 2026-11-28: components beside the originals, unit-tested, not yet wired into an engine: `context/memory/graph/slots.py` (append-only slot table, guard on/off x time single/bitemporal, read at a cut-off version), `context/pipeline/update/slots.py` (slot writer, new pinned prompt `extract-slots-attributed` with schema), `context/pipeline/update/deferred.py` (append-only memory: the write path records guard inputs in a `ResolutionLog` and commits no supersession; `resolve_at_read` replays the guard at every read, no caching), `context/views/serialise.py` (template serialisation: views built at every read with the template renderer, nothing cached). Their engine configs under `configs/engines/` wait for the GRACE engine and the T026 assembler; feeding the `ResolutionLog` from `updater.py` is also left for that wiring.
- 2026-11-28: PR #147 merged. Engine configs started on `task/T027-engine-configs` from `origin/main` at `acba43d` (T026's GraceEngine, PR #151), as directed by `s00-super`.
- 2026-11-28: variants built by injecting components into GraceEngine, no variant branch in the engine. Smallest hooks added to `context/engine.py`: a `components` param (`views`, `extension`) whose factories `config/registry.py` resolves lazily (`COMPONENTS`), and a per-history `Extension` (updater `deferred` log, extractor, the graph a read queries, extra state facts, save and restore; the defaults change nothing). `updater.py` gains the optional `deferred` `ResolutionLog` (approved by `s00-super`): the guard still decides against the state resolved at the writer's head, so known claims and repeated mentions match the main configuration, but no supersession is committed and the guard's inputs are logged. Configs: `grace-template.yaml` (`views/serialise.SerialisedViews`: the plan's query matched against the template bindings at the read version, built with the template renderer, dropped after the read), `grace-append-only.yaml` (no views; every read replays the guard over the stored claims and queries a claim store built anew with the derived supersessions), and the four slot-table arms of ablation B, `grace-slots{,-noguard}{,-single}.yaml` (slot writer as the updater's extractor, empty claim graph, current slot values as state items beside BM25 and dense retrieval).
- 2026-11-28: development smoke runs (not formal runs: no tuning, no scores), adapted from T026's smoke script (`runs/T027/artifacts/w01-T027/scripts/variant_smoke.py`). Each run writes the first 80 messages of LoCoMo dev `conv-26`, then asks the first 4 questions at version 80 with budgets 256, 1,024 and full, i.e. 12 reads per variant. Models were Qwen3-8B and Qwen3-Embedding-0.6B on the shared servers, code `44e7147`, run directories `runs/T027/artifacts/w01-T027/T027-smoke-20261128T012320Z-<config>`. All six variants completed. No context went over its budget. All trace fields were present. No read showed a message beyond version 80. All model calls returned `ok` (template 142, append-only 138, each slot arm 133). Per-variant results:
  - template: 87 claims, no view hits.
  - append-only: 96 claims, 0 stored supersessions, 96 claims in the resolution log.
  - slot arms: 68 slot rows, except no-guard bitemporal with 74; slot values were selected as covering state items.
  Writer and slot-writer outputs differ between the parallel runs despite temperature 0, e.g. 87 against 96 claims and 68 against 74 rows. This is likely server-side batching. It does not depend on guard or time, which only act at resolution. No view hit occurred in any read, as in T026's smoke, so the template views were not exercised on real data; the unit test covers a hit.
- 2026-11-28: PR #154 merged (main `2514889`) after review by `s00-super` (merge with follow-ups). Follow-ups on `task/T027-review-fixes`:
  - Bitemporal time factor of the slot arm. In the bitemporal arm, `SlotMemory.state_facts` now also offers the values ended by a change, with `retired` (the superseding version) and their valid interval. The assembler's filter keeps them exactly when the read asks about an earlier state or a window they overlap, as it does for retired claims in the main config. Corrected values are never offered. The single-time arm offers current values only, without valid time. The engine's `_facts` passes `retired` through. Tested with "where did I live in 2021": the bitemporal arm shows the 2021 value; the single arm shows only the current one.
  - Write-time and query-time supersessions compared. A new test runs the main and append-only configs on the same scripts and compares supersessions per version, with the guard on and off. The scripts cover an exclusive replacement without correction (with valid end), an offer against a statement, an ending stance with a valid end, several attributions in one version, and a correction. No divergence was found.
  - Slot adapter statuses. The slot adapter now records the real status of every call, retries and invalid outputs included.
  - Restore checks the ablation arm. Restoring a slot table raises when the snapshot's guard or time differs from the config.
  - No stale hints in the resolution log. In deferred mode, guard inputs are logged only for entries in the committed change set, so a rejected change set leaves no hint. Re-noting the same inputs is accepted; different inputs are refused.
  - Template-view threshold. `SerialisedViews.hit` already used the threshold rule of `ViewStore.materialise`: distinct witness claims against the family threshold. A view below the threshold no longer adds its build event. A test compares hits with the views a resident store holds at thresholds 1 to 3.
- 2026-11-28: reporting notes for E011 (ablation B) and the append-only baseline:
  - Planner calls inflate U in the slot arms. The slot arms keep GRACE's planner, which plans over an empty claim graph, so its LLM calls (ledger U) cost the slot arms without serving them. Report this or subtract it when comparing per-read cost.
  - Write timings of the append-only config include resolution replays. The append-only updater resolves the graph at the writer's head before each message (the guard needs the current state), so its write timings include those replays as well as the extraction.
  - The assembler skips facts whose evidence is already shown. An item whose evidence messages are all already in the context is skipped when filling, so a slot or claim fact can lose to the raw message it came from.
