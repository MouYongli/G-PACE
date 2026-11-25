---
id: E005
title: Ablation C on gold graphs
created: 2026-11-23
---

# E005 · Ablation C on gold graphs

## Question

Does an LLM-rendered view help the answering LLM more than a template serialisation of the same result rows? This is the premise of RQ3. If the template ties, nothing expensive needs caching and the paper becomes 'a staleness criterion plus computing at query time'.

## Design

Written on 2026-11-25 before the first formal run. Config: `configs/experiments/E005-ablation-c-gold.yaml`; driver: `uv run python -m grace.cli.ablation_c` (subcommands `system`, `score`, `compare`); scorer and statistics: `src/grace/eval/analysis/metrics/changeseq.py`. Plan sections 3.4, 4.2 (RQ3 premise), 5.4 and 7.3 (ablation C).

| Item | Value |
| --- | --- |
| Benchmarks and splits | Controlled change sequences, development families only: the model-rendered development set of run `T015-devmodel-20261125T192037Z` (generator `changeseq-generator-2`, surface renderer Mistral-Small-3.2-24B; 5 families, 25 sequences of 200 messages, densities 1, 3, 10, 30), read through the change-seq adapter with an inline benchmark config (as E001; `configs/benchmarks/change-seq.yaml` is not bound yet). Read schedule: the primary schedule of each sequence (A20d1 at density 10, U10 otherwise), 1,145 questions. No held-out data |
| Gold graph | The stored gold claim graph of each sequence (`graph/`), injected by the driver as the gold-graph oracle (structure.md: "Question answering on gold graphs"). Entity IDs of the generator are replaced by their surface labels before the views see the graph (task `k1` becomes "car rental A", item `car-astra` becomes "Opel Astra"), so that view text and questions name things alike; values, predicates, speakers and companions are unchanged |
| Resident views | The 15 gold bindings of each sequence (`bindings.jsonl`; V1 to V6 mapped to the template families `list`, `current`, `count`, `constraints`, `pending`, `choice`), built with the frozen view code of T018 (`src/grace/context/views/`, `resources/views/`) and `configs/views/default.yaml` with the two gold-graph overrides of the T019 replay: `state_speaker: user`, `choice_predicate: selectedService`. Views are built before the first message and, at the first read of every read version, re-queried and repaired (`ViewStore.maintain`, confirm on: local rebuild, citation patch or cut-off advance). The views' answers equal the generator's gold answers on every question of the population (CPU check before the run: 955 of 955 questions; regression test `tests/integration/test_ablation_c.py`) |
| Systems | Three arms, one changed factor (the source of the view text): (1) **template**, template serialisation of the rows (no LLM call); (2) **llm**, LLM rendering of the same rows with the frozen `render-view` prompt, rendering check and template fallback (`views/render.py`; decoding temperature 0, max 512 tokens, max 16 rows per call); (3) **raw**, reference: the raw-text engine of T003 (`configs/engines/full-history.yaml`) at the same budget, i.e. the newest messages that fit. Ablation C's third source (LLM rewriting from raw text) and the provenance factor are not part of E005 |
| Equal display budget | Every arm's working context is limited to the same token budget (answering model's tokenizer). A view arm's context has one fragment per view (title; each sentence after the message IDs it cites; the read-time scope note), taken in an order fixed per read (sha256 of read ID and view ID, identical for both view arms) while it fits; a view that does not fit is skipped. Budgets from `configs/common/budgets.yaml`: **1024 (primary)**, where every template context fits (CPU pre-count over the 350 read points: 390 to 828 tokens, median 502), so only verbosity can cost an arm content; and 512, where the budget binds for both view arms |
| Answering | The shared harness step (`runner/harness/answer.py`, prompt `answer`), Qwen3-8B (`configs/models/qwen3-8b.yaml`, thinking off, temperature 0, seed 0), output reserve 256 tokens, one further retrieval per read (a view arm returns the same views again). The same model renders views (plan 5.6: every call type is served by the same model by default). vLLM 0.34 on GPU 3, port 8106, `--max-model-len 32768`, explicit KV-cache size, prefix caching on |
| Population | Questions about the state at the read version: types `changed`, `uniform`, `presupposition`, `abstention` (955 of 1,145). Historical questions (`known_then`, `seen_from_now`, 190) ask for the state at an earlier knowledge version or world time, which no resident view family states; they are answered by every arm and reported as a descriptive stratum only |
| Metrics | Answer accuracy by normalised set match (deterministic; the primary change-seq scorer of `docs/research/change-sequences.md` section 9; rule in `eval/analysis/metrics/changeseq.py`): `unknown` is correct exactly on abstention questions, an answer to an abstention question is correct when it names no candidate value, otherwise every gold item must be named and no other candidate value (other values of the same view template in the same sequence, gold or outdated) may be; on presupposition questions rejecting the outdated premise is allowed. Invalid outputs count as wrong (D002). Reported with strata by question type, view template and change type. Rendering-check failure rate of the llm arm: failed LLM sentences / LLM sentences checked, and template-fallback units / units rendered. Write-side rendering cost: render calls (ledger W) with input and output tokens from `calls.jsonl`. Context tokens per arm |
| Statistics (D002) | Micro mean over reads; 95% percentile interval from a cluster bootstrap over scenario families (10,000 resamples, seed 20261125), paired for differences (same clusters drawn for both arms). Primary readout: llm − template at budget 1024. Secondary: template − raw and llm − raw; budget 512. Sensitivity: sequence as the cluster unit, macro mean of cluster differences, leave-one-family-out, discordant counts. With five families the family-level interval is coarse; strata below 100 reads are descriptive only |
| Runs | Per budget: three `system` runs (template, llm, raw), one `score` run each; `compare` (not a run) writes `summary.json` with the checksum of every input `run.json` under `runs/E005/artifacts/manager/E005-summary/`. View runs also write `views/view_events.jsonl` (every maintenance event); score runs write `records/` (the split's records, gold as files), `scores.jsonl` (one value per read) and `metrics.json` |
| Judging | None. The deterministic set match is the primary scorer; the blind judge (secondary) is not run. The set-match metric is not yet registered in `configs/common/scorers.yaml` (change-seq metrics are pending there; owner T004 manager); registration is requested in the E005 PR |
| Frozen before the first run | View code, view templates and `configs/views/default.yaml` (T018), prompts `render-view` and `answer` and their pins, budgets, engine configs, the scorer rule and this design |

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
- 2026-11-25: manager session `m01-E005` started on `task/E005-ablation-c-gold` from `63f9d4fff7021651c9626af18bdc0a25ce50e557`; Issue #95. Design and config written before the first formal run; CPU pre-checks (view answers against gold, template context sizes) on the development set.
