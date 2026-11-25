"""Raw-text baselines (plan 7.2): full history, last-k, truncation to the same budget.

One engine covers the group:

- full history: `budget_tokens=None` at read time, no `last_k`;
- truncation to the same budget: any token budget; the newest messages that fit are kept;
- last-k: `last_k` messages at most, then the budget applies as well.

"With and without prefix caching" is a property of the serving side, not of the context; the
engine config sets `prefix_caching` and the harness passes it to the model client.

When the full history exceeds `window_tokens`, the oldest messages are dropped and a disclosure
fragment states how many (plan 7.2: "the share is disclosed and nothing is truncated silently").
"""

from __future__ import annotations

from grace.context import api
from grace.eval.engines.baselines.base import BaselineEngine


class RawText(BaselineEngine):
    kind = "raw"

    def __init__(self, model, *, last_k: int | None = None, window_tokens: int | None = None):
        super().__init__(model)
        if last_k is not None and last_k < 1:
            raise ValueError("last_k must be >= 1")
        self.last_k, self.window_tokens = last_k, window_tokens

    def _build(self, task, budget, request):
        packer = self._packer()
        visible = self.messages[-self.last_k:] if self.last_k else self.messages
        position = {m.message_id: i for i, m in enumerate(visible)}
        position["omitted"] = -1

        def order(fragment):
            return position[fragment.fragment_id]

        newest_first = [self._message_fragment(packer, m) for m in reversed(visible)]
        limit = budget if budget is not None else self.window_tokens
        context = packer.pack(task, limit, newest_first, order=order)
        dropped = len(visible) - len(context.fragments)
        for _ in range(3 if budget is None and dropped else 0):  # the note's own size may drop one
            note = packer.fragment("omitted", "other",
                                   f"[{dropped} earlier messages omitted: the full history "
                                   f"exceeds the context window of {self.window_tokens} tokens]",
                                   ())
            context = packer.pack(task, limit, [note, *newest_first], order=order)
            now = len(visible) - len(context.fragments) + 1
            if now == dropped:
                break
            dropped = now
        if budget is None:  # report the full-history condition, not the window
            context = api.WorkingContext(task.read_id, task.history_id, task.version, None,
                                         context.tokens, context.text, context.fragments)
        return context, [], []
