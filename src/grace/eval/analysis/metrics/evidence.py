"""Evidence in the working context, per read (E013, plan 7.3 ablation E; plan 3.1 evidence recall).

Computed from run-directory files only (predictions, read trace, contexts, calls) and the gold
records; this module imports nothing from `context/` or the other `eval/` groups (structure.md).

Per read with gold evidence messages G (gold `evidence_ids`, a `#char=` span mapped to its
message), R = the prediction's `context_ids` (messages whose source text is in the context, the
strict set of plan 3.1) and L = R plus every message the read trace's provenance names (claim
and view citations, lenient recall):

- `full_evidence_hit`     = 1 if G ⊆ R, else 0;
- `full_evidence_lenient` = 1 if G ⊆ L, else 0;
- `evidence_hit`          = 1 if G ∩ R is non-empty, else 0;
- `evidence_recall`       = |G ∩ R| / |G|;
- `unsupported_answer`    = 1 if the output is `answer` and G ∩ R is empty, else 0.

Reads without gold evidence (abstention questions, evidence that names no message) are not
scored and are counted (`n_excluded`). `invalid` outputs are excluded from every metric and
reported (`exclude_and_report`): their contexts exist, but no answer was parsed. Token means
(`context_tokens`: the context as counted by the run; `prompt_tokens`: input tokens of the read's
last successful answer call) are reported over the same scored reads, outside the 0..1 metrics.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

_SPAN = re.compile(r"^(?P<message>.+)#char=\d+,\d+$")
RATES = ("full_evidence_hit", "full_evidence_lenient", "evidence_hit", "evidence_recall",
         "unsupported_answer")
TOKENS = ("context_tokens", "prompt_tokens")


def message_of(evidence_id: str) -> str:
    m = _SPAN.match(evidence_id)
    return m.group("message") if m else evidence_id


def provenance_messages(trace: Mapping[str, Any] | None) -> set[str]:
    """Every message named by the read trace's provenance (lenient set minus R)."""
    if not trace:
        return set()
    return {message_of(e) for ids in (trace.get("provenance") or {}).values() for e in ids}


def answer_prompt_tokens(calls: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """read_id -> input tokens of its last successful answer call."""
    out: dict[str, int] = {}
    for c in calls:
        if c.get("call_type") == "answer" and c.get("status") == "ok" and c.get("read_id"):
            out[c["read_id"]] = int(c.get("input_tokens") or 0)
    return out


def read_values(prediction: Mapping[str, Any], gold: Mapping[str, Any],
                trace: Mapping[str, Any] | None) -> dict[str, float] | None:
    """The five rates of one read, or None when the read has no gold evidence."""
    g = {message_of(e) for e in (gold.get("evidence_ids") or [])}
    if not g:
        return None
    r = {message_of(e) for e in prediction.get("context_ids") or []}
    lenient = r | provenance_messages(trace)
    hit = bool(g & r)
    return {"full_evidence_hit": float(g <= r), "full_evidence_lenient": float(g <= lenient),
            "evidence_hit": float(hit), "evidence_recall": len(g & r) / len(g),
            "unsupported_answer": float(prediction.get("output") == "answer" and not hit)}


def mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None
