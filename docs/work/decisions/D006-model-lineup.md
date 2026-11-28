---
id: D006
title: Model line-up and judge snapshot
created: 2026-11-23
---

# D006 · Model line-up and judge snapshot

## Context

Plan section 7.1 fixes the primary model (Qwen3-8B, thinking disabled) and leaves four choices to phase 1: a contemporary open-weight small model, a long-context second answering model that fits a full LongMemEval-S history (about 115K tokens), the larger same-family model used as writer in ablation G, and the blind judge snapshot. The judge must stay available until publication. The change-sequence renderer must come from outside every evaluated model family and differ from the judge (`docs/research/change-sequences.md`).

## Options

Facts checked on 2026-11-25 against the Hugging Face model cards and `config.json` files of the pinned revisions. API prices come from third-party aggregators, not from official price pages.

| Role | Candidates | Licence | Window | Weights | Notes |
| --- | --- | --- | --- | --- | --- |
| Contemporary small model | Qwen3.5-9B (2026-02); Gemma 4 12B IT (2026-05) | Apache-2.0 | 262K | 19.3 GB; 23.9 GB | Qwen3.5-9B is closest to 8B but comes from the same vendor as the primary model. Gemma adds family diversity |
| Long-context answering model | Qwen3.5-27B; Gemma 4 31B IT; DeepSeek-V4-Flash-0731 | Apache-2.0; Apache-2.0; MIT | 262K; 262K; 1M | 55.6 GB; 62.5 GB; 166.9 GB | Estimated KV cache at 115K tokens: about 7 GiB (Qwen3.5-27B, 16 of 64 layers use full attention) and about 18 GiB (Gemma 4 31B). DeepSeek needs at least two GPUs |
| Writer scale (same family as the primary) | Qwen3-14B; Qwen3-32B | Apache-2.0 | 32,768 native | about 30 GB; 65.5 GB | Qwen3-32B gives a 4× scale gap |
| Judge | Local open-weight snapshot; hosted API snapshot | — | — | — | A hosted snapshot can be retired before publication. A local snapshot cannot, but has to earn trust through calibration |

Hosted judge, Azure OpenAI gpt-4.1-mini version 2025-04-14 (the user's Sweden Central standard deployment):

- Microsoft's lifecycle page lists the version for retirement on 2027-04-14, with deployments ending 2027-10-14. Formal runs after the configuration lock (D012) may fall later than that.
- The regional price is roughly USD 0.48 input and 1.94 output per million tokens (third-party figures), so about USD 0.20 per 1,000 blind judgements of about 400 input tokens.

## Decision

Taken by the user.

| Role | Model | Pin |
| --- | --- | --- |
| Primary (unchanged, plan 7.1) | Qwen3-8B | `configs/models/qwen3-8b.yaml` |
| Contemporary small model | Qwen3.5-9B | `configs/models/qwen3.5-9b.yaml` |
| Long-context second answering models | Qwen3.5-27B and Gemma 4 31B IT | `configs/models/qwen3.5-27b.yaml`, `configs/models/gemma-4-31b-it.yaml` |
| Writer scale (ablation G) | Qwen3-32B | `configs/models/qwen3-32b.yaml` |
| Embedding (unchanged, plan 7.1) | Qwen3-Embedding-0.6B at `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | to be pinned with `llm/embedding.py` |
| Change-sequence renderer (T015) | Mistral-Small-3.2-24B-Instruct-2506 (`mistralai/Mistral-Small-3.2-24B-Instruct-2506`, Apache 2.0), served locally; revision pinned when downloaded | to be pinned by T015 in `configs/models/` |
| Primary judge | DeepSeek-V4-Flash-0731 at `7872f01b1d1fe23eabc4c98b48bffcef5a386062`, served locally | `configs/judges/blind.yaml` (`model`) |
| Secondary judge | Azure OpenAI gpt-4.1-mini, version 2025-04-14, budget EUR 50 for the project | `configs/judges/blind.yaml` (`comparison_model`, E001 only); `configs/judges/longmemeval-official.yaml` (`model`) |

The secondary judge has two uses:

- In E001 it judges the same pilot predictions as the primary judge. Each judge's agreement with the 200 adjudicated human labels and with the other judge is reported. This costs about USD 8.
- On LongMemEval it serves as the judge of the official templates, at about USD 4 to 8. This deviates from upstream, which uses gpt-4o-2024-08-06, and the paper says so.

The rest of the budget is a reserve for reruns and negative controls. Every GPT run must finish before 2027-04-14.

Every model is served with thinking disabled and temperature 0. Azure keys and endpoints are read only from environment variables (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`) and never written to the repository.

## Consequences

- Evaluated model families are Qwen and Gemma. The change-sequence renderer (T015) must come from another family and differ from the primary judge, so it cannot be DeepSeek. The candidates are a hosted model from another family, or gpt-4.1-mini if the remaining budget allows it.
- Prompts are frozen for Qwen3-8B and Qwen3.5-9B together (T004).
- Before E001 judges anything:
  - the token counting and thinking mode of DeepSeek-V4-Flash are settled; it has no Jinja chat template;
  - judge calls to Azure are counted from the usage the server reports, because no tokenizer is available.
- DeepSeek-V4-Flash needs at least two B200 GPUs. They are reserved in `runs/compute.yaml` before each judging run.
- The judge decision is revisited if E001 shows that the primary judge agrees clearly worse with the human labels than the secondary judge.

## Revisit when

- A chosen model or judge snapshot is withdrawn, or its licence changes.
- The E001 judge comparison shows that the primary judge is clearly worse than the secondary judge.
- The Azure deployment would retire before a planned GPT run.

## Log

- 2026-11-23: proposed as part of the full project DAG.
- 2026-11-25: evidence summarised: model cards, `config.json`, judge prices and the Azure lifecycle. The user chose the line-up and the judge plan with a EUR 50 GPT budget. Models downloaded at the pinned revisions; Gemma 4 12B was removed from the cache.
- 2026-11-25: the user chose the change-sequence renderer: Mistral-Small-3.2-24B-Instruct-2506, an open-weight model outside the evaluated families (Qwen, Gemma) and different from the primary judge (DeepSeek), served locally for reproducibility (change-sequences design section 7). It was preferred over Azure gpt-4.1-mini, which retires on 2027-04-14 and is also the native backbone of the Graphiti row.
- 2026-11-28: amendment taken by the user on the E007 evidence (PR #150): the main configuration's writer is Qwen3-32B (`configs/models/qwen3-32b.yaml`), not Qwen3-8B. Planning, rendering and answering stay on Qwen3-8B. In full-history writing at session granularity Qwen3-32B reaches loose claim precision 0.25-0.27 against 0.09 for Qwen3-8B at similar recall, with fewer writer tokens per message (output 40 against 98). Qwen3-8B as writer is kept as the small-writer arm of ablation G. This deviates from plan section 7.1 (Qwen3-8B for writing); write cost is reported both in tokens and in GPU time, since tokens of the two models are not equally priced. A shared Qwen3-32B server (port 8253, GPU 0) is reserved by `s00-super`.
