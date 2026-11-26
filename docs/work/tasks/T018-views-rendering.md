---
id: T018
title: Views and rendering
created: 2026-11-23
---

# T018 · Views and rendering

## Goal

Query-defined views as in plan sections 3.4 and 5.4: the six template families, the view store, template serialisation and LLM rendering of result rows, per-row binding of sentences, the render check, partial rebuild on answer staleness and programmatic citation repair.

## Scope

- In scope:
  - View store with query, bound text, witnesses, evidence, dependency patterns and cutoff version.
  - Render check: every value of a row appears in its sentence and nothing else does; failures fall back to the template.
  - Instantiation threshold per binding; standing versus ephemeral views.
- Out of scope: Deciding when a view is stale (T019).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Rebuilt views equal a full rebuild on fixtures.
- [ ] Citation repair makes no LLM call; the ledger shows it.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` view package; rendering prompt registered with T004.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-25: manager session `m01-T018` started on `task/T018-views-rendering` from `main` at 795cb9ea1946fdcf72d572baf62a103531f0a06b; Issue #65. No workers: the manager writes the code.
- 2026-11-25: `src/grace/context/views/` written (view, dependencies, template_families, render, rebuild, store), the six families in `resources/views/`, `configs/views/default.yaml`, prompt `render-view` with schema `llm/render-view` registered in `configs/common/prompts.yaml`. Tests: `tests/integration/test_views.py` (incremental maintenance equals a full rebuild at every version and every third, template and LLM rendering, `rdf11` and `rdf12`; citation repair writes no call record), `tests/unit/test_views_render.py`.
- 2026-11-25: templates aligned with the T015 cross-check reference encodings (PR #72): `current` selects LATEST BY version; `state_speaker` config for the speaker of V1-V3; count-view witnesses behind `view.count_witnesses` (convention still open). F1 (report mode, polarity, derived in `[u, f]`) awaits a user decision; F2 (LATEST witness keys) is fixed by m01-T017b in `pipeline/query/`.
- 2026-11-25: development smoke run of LLM rendering on the fixture with Qwen3-8B (GPU 3, port 8106; not a formal run): 19 render calls, all `ok`; 20 sentences passed the rendering check, 0 failed, 0 fallbacks; 4 citation repairs with 0 calls. Evidence: `$PROJECT_ROOT/runs/T018/artifacts/smoke/` (summary.json, calls.jsonl, views/). Run before the cross-check alignment, at base 795cb9e with uncommitted changes.
- 2026-11-25: seam for T019 (`views/staleness/`, not created): strategies read `ViewStore.views()` (dependency patterns with role, local filters, aggregation and selection flags; used claims and attributions; cut-off; fingerprints), mark with `ViewStore.mark`, and repair with `ViewStore.maintain(..., read_id=..., confirm=...)`; `ViewStore.note_changeset` must see every change set (whole-history invalidation on vocabulary change or entity merge). Dependency patterns are derived in `views/dependencies.py`, since `pipeline/query/patterns.py` has no owner.
- 2026-11-26: deliberate, user-approved change to the frozen rendering check (user decision of 2026-11-26 after E005; session `m01-E005b`, branch `task/E005-render-check`, before the configuration lock D012). `LLMRenderer._check` now also requires the binding's subject (`RenderSpec.required_constants`: the entity of an entity-predicate binding, the task of a task binding) in every LLM sentence, matched like row values (normalised substring: case and every character other than a-z and 0-9 ignored). The predicate (a relation name the renderer puts into words) and the title stay allowed but not required; a view without a binding requires only its rows. Template serialisation, the `render-view` prompt, the templates and `configs/views/default.yaml` are unchanged. Reason: E005 found LLM sentences that drop the task they belong to ("The constraint is arrive by 12:00.") passing the check, the main source of the LLM arm's deficit on V4. Tests: `tests/unit/test_views_render.py` (`BindingConstantTest`), `tests/integration/test_views.py` (`test_sentence_without_the_binding_subject_falls_back`); the fake renderers of `tests/integration/views_fixture.py` and `test_ablation_c.py` now name the view title.
