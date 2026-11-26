"""Rolling-summary baselines (plan 7.2): a summary plus recent raw text, in two variants.

- `mode: rewrite` ("expensive"): whenever messages leave the recent window, the whole summary is
  rewritten from the previous summary and the leaving messages. Corrections can replace old
  statements, at a summary call on almost every write.
- `mode: reuse` ("wrong"): messages that leave the recent window are collected, and every
  `block_size` of them are summarised into a new block that is appended; earlier blocks are reused
  and never rewritten, so a late correction cannot revise an old statement.

The recent window holds the messages after the last summarised one: exactly `recent_k` under
`rewrite`; between `recent_k` and `recent_k + block_size - 1` under `reuse`. When a summary call
fails, nothing is marked summarised and the next write retries with the larger set.

Summary calls are `summary` / trigger `write` / ledger `W`, with the pinned prompt
`resources/prompts/summary/`. Its length limit is `max_summary_tokens`; the call's `max_tokens` is
that limit plus `baselines.summary.max_tokens_margin` of `configs/common/budgets.yaml`, and the
returned text is cut to the limit.
"""

from __future__ import annotations

import yaml

from grace.config.paths import REPO_ROOT
from grace.eval.engines.baselines.base import (
    BaselineEngine,
    CallTag,
    pinned_prompt,
    render_message,
    truncate_to,
)

BUDGETS = REPO_ROOT / "configs" / "common" / "budgets.yaml"
NO_SUMMARY = "(none yet)"


def max_tokens_margin() -> int:
    budgets = yaml.safe_load(BUDGETS.read_text(encoding="utf-8"))
    return int(budgets["baselines"]["summary"]["max_tokens_margin"])


def _parse_summary(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("empty summary")
    return text


class RollingSummary(BaselineEngine):
    kind = "summary"

    def __init__(self, model, *, mode: str, recent_k: int = 8, block_size: int = 8,
                 max_summary_tokens: int = 512):
        super().__init__(model)
        if mode not in ("rewrite", "reuse"):
            raise ValueError(f"mode {mode!r} must be rewrite or reuse")
        if recent_k < 0 or block_size < 1 or max_summary_tokens < 1:
            raise ValueError("recent_k >= 0, block_size >= 1 and max_summary_tokens >= 1")
        self.mode, self.recent_k, self.block_size = mode, recent_k, block_size
        self.max_summary_tokens = max_summary_tokens
        self.prompt = pinned_prompt("summary")
        self.max_tokens = max_summary_tokens + max_tokens_margin()
        self.blocks: list[dict] = []  # {"text", "evidence_ids", "version"}
        self.summarised_upto = 0  # last version covered by the summary

    def _on_write(self, message):
        leaving = self.messages[self.summarised_upto: max(0, self.version - self.recent_k)]
        if not leaving or (self.mode == "reuse" and len(leaving) < self.block_size):
            return []
        previous = self.blocks[-1] if self.mode == "rewrite" and self.blocks else None
        new_text = "\n".join(render_message(m, self._history()) for m in leaving)
        messages = self.prompt.render(max_tokens=str(self.max_summary_tokens),
                                      summary=previous["text"] if previous else NO_SUMMARY,
                                      messages=new_text)
        tag = CallTag("summary", "write", message.history_id, message.version)
        result = self.model.chat(messages, tag, prompt_sha256=self.prompt.sha256,
                                 parse=_parse_summary, max_tokens=self.max_tokens)
        if result.ok:
            text = truncate_to(result.parsed, self.max_summary_tokens, self.model.count_tokens)
            evidence = [*(previous["evidence_ids"] if previous else []),
                        *(m.message_id for m in leaving)]
            block = {"text": text, "evidence_ids": evidence, "version": leaving[-1].version}
            self.blocks = [block] if self.mode == "rewrite" else [*self.blocks, block]
            self.summarised_upto = leaving[-1].version
        return list(result.call_ids)

    def _build(self, task, budget, request):
        packer = self._packer()
        summaries = [packer.fragment(f"summary-{i}", "summary", f"[summary] {b['text']}",
                                     b["evidence_ids"]) for i, b in enumerate(self.blocks)]
        recent = [self._message_fragment(packer, m)
                  for m in reversed(self.messages[self.summarised_upto:])]
        position = {f.fragment_id: i for i, f in enumerate([*summaries, *reversed(recent)])}
        context = packer.pack(task, budget, [*summaries, *recent],
                              order=lambda f: position[f.fragment_id])
        return context, [], []

    def _state(self):
        return {"blocks": self.blocks, "summarised_upto": self.summarised_upto}

    def _load_state(self, state):
        self.blocks = state["blocks"]
        self.summarised_upto = state["summarised_upto"]

