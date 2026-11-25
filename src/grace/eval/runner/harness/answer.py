"""The answering step shared by every engine (plan 5.6).

The answering LLM sees only the working context and the task, under one fixed answer prompt. It
has four permitted outputs: an answer, a state, one request for further retrieval, or "unknown".
A further-retrieval request is served once through `ContextEngine.further_retrieval`, followed by
a second answering call in which the request is no longer allowed. Output that cannot be parsed is
`invalid` (after the retries of the model wrapper).

Interim prompt: the shared answer prompt belongs to `resources/prompts/answer/` and is loaded by
`llm/prompts.py` (T004). This placeholder keeps the layout the plan requires: fixed instructions
and output contract first, the context and the task last.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from grace.context import api
from grace.eval.engines.baselines.base import CallTag, ModelPort

ANSWER_INSTRUCTIONS = """\
You answer a task about a conversation history using only the context below. Each context line \
starts with the ID of the message it comes from in square brackets.

OUTPUT CONTRACT. Reply with one JSON object and nothing else, in one of these forms:
{"output": "answer", "answer": "<short answer>", "cited_ids": ["<message ID>", ...]}
{"output": "state", "state": {"<slot>": "<value>", ...}, "cited_ids": ["<message ID>", ...]}
{"output": "retrieve", "request": "<what to search for>"}
{"output": "unknown"}
Use "answer" for a question and "state" for a state request. Cite the IDs of the messages your \
reply relies on. Use "retrieve" at most once, when the context lacks something a search could \
find. Use "unknown" when the context does not support a reply."""
FINAL_NOTE = "Further retrieval is no longer available: reply with answer, state or unknown."
ANSWER_SHA256 = hashlib.sha256(ANSWER_INSTRUCTIONS.encode("utf-8")).hexdigest()


def task_text(task: api.ReadTask) -> str:
    when = f" (asked at {task.asked_at})" if task.asked_at else ""
    if task.kind == "question":
        return f"Question{when}: {task.question}"
    return f"Task{when}: state request; output the current dialogue state over the slot " \
           f"inventory {task.state_schema}."


@dataclass(frozen=True)
class Reply:
    output: str  # answer, state, unknown, retrieve
    value: Any = None
    cited_ids: tuple[str, ...] = ()
    request: str | None = None


def parse_reply(text: str, task: api.ReadTask, *, allow_retrieve: bool) -> Reply:
    """Parse one answering output; raise ValueError when it breaks the output contract."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object")
    data = json.loads(text[start: end + 1])
    if not isinstance(data, dict):
        raise ValueError("not an object")
    output = data.get("output")
    cited = data.get("cited_ids", [])
    if not isinstance(cited, list) or not all(isinstance(c, str) for c in cited):
        raise ValueError("cited_ids must be a list of strings")
    if output == "unknown":
        return Reply("unknown")
    if output == "retrieve" and allow_retrieve:
        request = data.get("request")
        if not isinstance(request, str) or not request.strip():
            raise ValueError("retrieve needs a request")
        return Reply("retrieve", request=request)
    if output == "answer" and task.kind == "question":
        value = data.get("answer")
        ok = (isinstance(value, str) and value.strip()) or (
            isinstance(value, list) and value and all(isinstance(v, str) for v in value))
        if not ok:
            raise ValueError("answer must be a non-empty string or list of strings")
        return Reply("answer", value, tuple(cited))
    if output == "state" and task.kind == "state":
        value = data.get("state")
        if not isinstance(value, dict):
            raise ValueError("state must be an object")
        return Reply("state", value, tuple(cited))
    raise ValueError(f"output {output!r} not permitted here")


def messages_for(context: api.WorkingContext, task: api.ReadTask, final: bool):
    system = ANSWER_INSTRUCTIONS + ("\n" + FINAL_NOTE if final else "")
    return [{"role": "system", "content": system},
            {"role": "user", "content": f"Context:\n{context.text}\n\n{task_text(task)}"}]


@dataclass(frozen=True)
class Answered:
    """Outcome of answering one read: the prediction fields and the final context and trace."""

    output: str
    prediction: Any
    cited_ids: list[str]
    raw_output: str | None
    context: api.WorkingContext
    trace: api.ReadTrace
    dropped_citations: list[str]


def answer(engine: api.ContextEngine, task: api.ReadTask, budget: int | None,
           model: ModelPort, visible_ids: set[str]) -> Answered:
    """Read, answer, serve at most one further retrieval, and answer again."""
    result = engine.read(task, budget)
    context, trace = result.context, result.trace
    tag = CallTag("answer", "read", task.history_id, task.version, task.read_id)
    call_ids = list(trace.call_ids)

    def ask(final: bool):
        def parse(text):
            return parse_reply(text, task, allow_retrieve=not final)
        reply = model.chat(messages_for(context, task, final), tag,
                           prompt_sha256=ANSWER_SHA256, parse=parse)
        call_ids.extend(reply.call_ids)
        return reply

    reply = ask(final=False)
    if reply.ok and reply.parsed.output == "retrieve":
        second = engine.further_retrieval(task, reply.parsed.request, budget)
        context, trace = second.context, second.trace
        call_ids.extend(trace.call_ids)
        reply = ask(final=True)
    trace = api.ReadTrace(**{**trace.__dict__, "call_ids": tuple(call_ids)})
    if not reply.ok:
        return Answered("invalid", None, [], reply.text, context, trace, [])
    parsed: Reply = reply.parsed
    cited = [c for c in dict.fromkeys(parsed.cited_ids) if c in visible_ids]
    dropped = [c for c in parsed.cited_ids if c not in visible_ids]
    value = parsed.value if parsed.output in ("answer", "state") else None
    return Answered(parsed.output, value, cited if value is not None else [], reply.text,
                    context, trace, dropped)
