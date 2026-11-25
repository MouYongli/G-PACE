"""The official per-type judge of LongMemEval (`src/evaluation/evaluate_qa.py` upstream).

Upstream sends one user message, chosen by question type and abstention, to the judge model and
counts the reply as correct when it contains "yes" (case-insensitive). The five templates are in
`resources/prompts/judge-longmemeval-*`:

| Gold labels | Template |
| --- | --- |
| `abstention: true` (question ID ending in `_abs`) | `abstention` |
| `question_type` = `temporal-reasoning` | `temporal-reasoning` |
| `question_type` = `knowledge-update` | `knowledge-update` |
| `question_type` = `single-session-preference` | `single-session-preference` |
| `single-session-user`, `single-session-assistant`, `multi-session` | `default` |

The judge model and decoding are in `configs/judges/longmemeval-official.yaml`. Like the blind
judge it sees only question, reference and response (judge.blind_inputs).
"""

from __future__ import annotations

from collections.abc import Mapping

from grace.eval.analysis.judging.judge import Judge
from grace.llm.client import ChatClient
from grace.llm.prompts import Prompt

DEFAULT_TYPES = ("single-session-user", "single-session-assistant", "multi-session")
TYPED = ("temporal-reasoning", "knowledge-update", "single-session-preference")
TEMPLATES = ("default", *TYPED, "abstention")


def template_for(labels: Mapping, task_id: str) -> str:
    abstention = labels.get("abstention")
    if abstention is None:
        abstention = task_id.endswith("_abs")
    if abstention:
        return "abstention"
    question_type = labels.get("question_type")
    if question_type in TYPED:
        return question_type
    if question_type in DEFAULT_TYPES:
        return "default"
    raise ValueError(f"task {task_id}: unknown LongMemEval question_type {question_type!r}")


def parse_yes(text: str | None) -> str:
    """Upstream rule: correct iff "yes" occurs in the lower-cased reply."""
    if text is None or not text.strip():
        return "invalid"
    return "correct" if "yes" in text.lower() else "incorrect"


def longmemeval_judge(name: str, client: ChatClient, prompts: Mapping[str, Prompt],
                      decoding: Mapping) -> Judge:
    missing = set(TEMPLATES) - prompts.keys()
    if missing:
        raise ValueError(f"missing LongMemEval templates {sorted(missing)}")

    def choose(read_task: Mapping, gold: Mapping) -> Prompt:
        return prompts[template_for(gold["labels"], gold["task_id"])]

    return Judge(name, client, choose, parse_yes, decoding)
