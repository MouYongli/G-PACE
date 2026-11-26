---
id: T022
title: "Writer: extraction and graph update"
created: 2026-11-23
---

# T022 · Writer: extraction and graph update

## Goal

The write path of plan section 5.1: the writer extracts claim patches anchored to message spans; the program validates them and decides, by attribution and exclusivity rules, whether to append, supersede or keep claims side by side; entity alignment adds versioned equivalence entries.

## Scope

- In scope:
  - Output constrained by a JSON schema; failed patches leave the raw-text path intact.
  - Extraction granularity as a parameter (message, segment, session); knowledge versions follow the evidence message.
  - The writer never reads view text, staleness marks or fingerprints.
- Out of scope: Vocabulary evolution (T032).
- Candidate worker subtasks and write scopes: to be set by the manager.

## Acceptance

- [ ] Attribution-guard handling passes the three running examples of plan section 3.5 on fixtures.
- [ ] Every call, retry and failure is in the cost ledger.
- [ ] `make test` and `make lint` pass.

## Deliverables

`src/grace/` writer package; extraction prompt registered with T004.

## Log

- 2026-11-23: created from the full project DAG.
- 2026-11-26: manager session `m01-T022` started on `task/T022-writer` from `main` at `9db00d1`; Issue #121. No workers dispatched (one package with tightly coupled modules); CPU only, scripted fake LLM transports, no model server and no benchmark data.
- 2026-11-26: design. Package `src/grace/context/pipeline/update/`: `segment.py` (granularity `message`, `segment` of n messages inside a session, `session`; units are cut from the messages after the store head; a read inside an incomplete unit flushes the arrived part with trigger `read`), `candidates.py` (vocabulary, entities and current claims under per-call handles `k<i>`, from the graph only), `patch.py` (writer output; `parse_patch` is both the client's `validate` and the updater's check, so `ok` in `calls.jsonl` means a usable patch), `extract.py` (`Extractor` interface, `NullExtractor`, `LLMWriter`: one `extract` call per unit, fixed system prefix, schema sent as `response_format` `json_schema`), `validate.py` (names, predicates and aliases, history-local predicates with label `v1+<n>`, canonical literals, valid times without invented dates, quote anchors), `guard.py` (plan 3.2 replacement rule plus two stricter conditions that only keep claims side by side: positive polarity of a', both claims open-ended; G2(ii) removal; conflicts reported; `enabled: false` is the no-guard variant), `commit.py` (one change set per message version, IDs `c<v>.<n>`; a rejected change set is committed empty), `updater.py` (orchestration, `WriterConfig`, `llm_writer`, save and restore). Invalid output splits the unit in halves down to single messages; a failed call leaves the unit pending and is retried up to `max_unit_failures`. Prompt `extract-claims` and schema `llm/extract-claims` pinned in `configs/common/prompts.yaml`; config `configs/common/writer.yaml` (segments of 8, T013).
- 2026-11-26: acceptance on fixtures. `tests/integration/test_writer.py` runs the three running examples of plan 3.5 through the whole write path (scripted writer output -> parse -> resolve -> guard -> commit -> compiled queries): two instrument claims kept and a repeated mention adds only an attribution and an evidence link; an offered arrival time is kept beside the requested 20:45 and reported as a conflict; the acceptance is a new attribution that empties "offered and not yet accepted" and fills "current choice" with no supersession. Ledger tests check that every call ID in the update results is in `calls.jsonl` and vice versa with the true status (`invalid_output` for trailing text, a cut output and an out-of-range message number; `failed` for every transport attempt). `tests/unit/test_writer_units.py` covers granularity, patch parsing, literals, vocabulary and the guard conditions one by one. Not verified: output quality of a real writer model (no live model run in this task; E006 and E007 measure graph quality and writer scale).
