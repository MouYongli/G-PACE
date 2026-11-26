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
- 2026-11-26: follow-up session `m01-T022b` on `task/T022-writer-smoke` from `main` at `ef6e55f` (T022 stays done). User decisions of 2026-11-26 recorded:
  1. The attribution guard keeps its two conditions beyond plan 3.2: the new attribution must be positive, and both claims must be open-ended. Both only ever keep claims side by side and never cause a supersession. They are documented in the `guard.py` docstring; decision D010 (gate on the attribution-guard claims) revisits them. A wording for plan 3.2 is proposed to the plan owner in the follow-up PR; `docs/research/plan.md` is not edited here.
  2. Conflicts stay in the update record and are derivable from the graph (two current open-ended claims of one exclusive predicate, subject and scope). No conflict entry in the Claim graph contract for now; T014 (claim graph owner) adds one only if a later evaluation needs it.
- 2026-11-26: smoke run of the writer with a real model (development data only; not E006, graph quality, and not E007, writer scale and granularity). Qwen3-8B (D006 primary, thinking off, temperature 0, seed 0 now sent with every call from `configs/common/writer.yaml`), segment-8, `json_schema` structured output, vLLM 0.34.0 on GPU 0 (reservation `m01-T022b`, removed after the servers stopped). Driver `grace.cli.writer_smoke` with `eval/runner/probes/writer_extract.py` and statistics from run files in `eval/analysis/metrics/writer.py`; config `configs/experiments/T022-writer-smoke.yaml`. Runs under `runs/T022/artifacts/manager/T022/`, each with `run.json` and `report.yaml`:
  - `T022-20261126T184240Z-9f95` (dry run, 16 messages of conv-26, code `c90c378`): vLLM accepted the schema as `response_format`; outputs parsed, but greetings, questions and reactions came out as claims and time phrases were missing. The prompt `extract-claims` was changed (skip conversational acts, keep time phrases in `time_expression`, a casual-chat example) and re-pinned at `ad6b12f`.
  - `T022-20261126T184421Z-5cf2` (dry run, 16 messages of conv-26 and conv-49, code `ad6b12f`): all calls ok; fewer conversational claims, time phrases kept.
  - `T022-20261126T184442Z-2a64` (full run, LoCoMo dev conv-26 and conv-49, 928 messages, code `ad6b12f`, `code_dirty` false): 148 `extract` calls, 142 `ok`, 6 `invalid_output` (invalid-output rate 0.041), 0 `failed`, no retried attempt. All 6 invalid outputs are cut at `max_tokens` 2048 by a repetition loop (the same claim or stance repeated); splitting recovered every unit, 0 messages given up. Tokens: 589,272 input, 126,735 output (mean 3,982 and 856 per call); cached input is recorded as 0 because the server did not report cached tokens, not because nothing was cached. Committed: 1,199 claims, 1,579 attributions, 22 supersessions, 0 entity merges; 3 conflicts, 21 blocked removals, 192 quotes not found in the message, 4 stances with an unknown local ID dropped.
  - Qualitative look (30 seeded units in `samples.json`, manager only; no gold claims exist for LoCoMo, so no accuracy is claimed). Typical errors: catch-all predicates (`experienced`, `hasMemory`, `hasPlan`, `hasIntention` are about half of all claims) with whole sentences as string objects (340 string objects of six or more words); their share is higher in the second half of each history (conv-26 46% to 51%, conv-49 58% to 71%), plausibly reinforced by the writer copying predicates shown under "known claims" (not tested); conversational acts still extracted (questions as `asks`, "catch you later" as a commitment, thanks as `confirm` stances); wrong subject or relation ("Sam hasChild dad", "Evan livesIn trusty car"); wrong exclusivity choices that cause wrong supersessions (`livesIn` Canada -> "peaceful place close to my home" -> "little island"; `destination` Rockies -> Jasper); spurious ending stances (one message of conv-49 ended ten unrelated claims of the same speaker, which the removal rule allows because speaker and function match); `valid_from` never filled. What works: time phrases on events early in a history ("attended museum, yesterday", "visited Banff, last month"), offer and accept stances on suggestions, no schema or commit errors.
  - Not verified: extraction accuracy (no labels), other granularities and models (E007), MultiWOZ and change sequences.
