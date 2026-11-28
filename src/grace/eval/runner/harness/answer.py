"""The answering step shared by every engine (plan 5.6).

The answering LLM sees only the working context and the task, under the one pinned answer prompt
(`resources/prompts/answer/`, registered in `configs/common/prompts.yaml`); its output is checked
against `resources/schemas/llm/answer.json`. It has four permitted outputs: an answer, a state,
one request for further retrieval, or "unknown". A further-retrieval request is served once through
`ContextEngine.further_retrieval`, followed by a second answering call in which the request is no
longer allowed. Output that cannot be parsed is `invalid` (after the retries of the model wrapper).

One extra retrieval per read (plan 5.6). When the read trace says the read's one extra retrieval
is already spent (`ReadTrace.retrieval_used`, e.g. by GRACE's own query expansion), a `retrieve`
output is resolved as `unknown` (`Answered.retrieve_refused`); the answer prompt stays the same for
every system and `further_retrieval` is not called.

Second call: the prompt's `context` holds the fragments of the new working context that were
already in the first one, then a section headed "Further retrieval results" with the fragments the
further retrieval added (or a note that it added none). The fragments are those of the recorded
working context; only their arrangement under the heading differs from its `text`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from grace.context import api
from grace.eval.datasets.benchmarks import multiwoz
from grace.eval.engines.baselines.base import EMPTY_CONTEXT, CallTag, ModelPort, pinned_prompt
from grace.llm import structured

PROMPT = pinned_prompt("answer")
SCHEMA = structured.load_schema("answer")
FURTHER_HEADING = "Further retrieval results"
NOTHING_NEW = "[the further retrieval found nothing that is not already in the context above]"
UNKNOWN_TIME = "unknown"
# Slot inventories named by `ReadTask.state_schema` (contracts.md, "Read task"). The inventory is
# part of the task, not of the gold data.
STATE_SCHEMAS = {multiwoz.STATE_SCHEMA: tuple(sorted(multiwoz.SLOTS))}


def request_text(task: api.ReadTask) -> str:
    """The `request` variable of the answer prompt: the question, or a state request with slots."""
    if task.kind == "question":
        return f"Question: {task.question}"
    slots = STATE_SCHEMAS.get(task.state_schema)
    if slots is None:
        raise ValueError(f"unknown state_schema {task.state_schema!r}")
    return ("State request: output the current dialogue state. Slot names: "
            + ", ".join(slots) + ".")


@dataclass(frozen=True)
class Reply:
    output: str  # answer, state, unknown, retrieve
    value: Any = None
    cited_ids: tuple[str, ...] = ()
    request: str | None = None


def parse_reply(text: str, task: api.ReadTask, *, allow_retrieve: bool) -> Reply:
    """Parse one answering output; raise ValueError when it breaks the output contract."""
    parsed = structured.parse(text, SCHEMA)
    if not parsed.ok:
        raise ValueError(parsed.error)
    data = parsed.value
    output = data["output"]
    if output == "unknown":
        return Reply("unknown")
    if output == "retrieve" and allow_retrieve:
        return Reply("retrieve", request=data["query"])
    if output == "answer" and task.kind == "question":
        return Reply("answer", data["answer"], tuple(data["cited_ids"]))
    if output == "state" and task.kind == "state":
        return Reply("state", data["state"], tuple(data["cited_ids"]))
    raise ValueError(f"output {output!r} not permitted here")


def final_context_text(first: api.WorkingContext, second: api.WorkingContext) -> str:
    """The `context` of the second call: earlier fragments, then the further-retrieval section."""
    before = {f.fragment_id for f in first.fragments}
    kept = [f.text for f in second.fragments if f.fragment_id in before]
    added = [f.text for f in second.fragments if f.fragment_id not in before]
    return ("\n".join(kept) or EMPTY_CONTEXT) + f"\n\n{FURTHER_HEADING}:\n" + (
        "\n".join(added) or NOTHING_NEW)


def messages_for(context_text: str, task: api.ReadTask, asked_at: str | None):
    return PROMPT.render(context=context_text, asked_at=task.asked_at or asked_at or UNKNOWN_TIME,
                         request=request_text(task))


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
    retrieve_refused: bool = False


def answer(engine: api.ContextEngine, task: api.ReadTask, budget: int | None,
           model: ModelPort, visible_ids: set[str], *, asked_at: str | None = None,
           max_tokens: int | None = None) -> Answered:
    """Read, answer, serve at most one further retrieval, and answer again.

    `asked_at` is the current date when the task has none (the time of the last visible message);
    `max_tokens` caps each answering call (budgets.yaml, `answer.output_reserve_tokens`)."""
    result = engine.read(task, budget)
    context, trace = result.context, result.trace
    tag = CallTag("answer", "read", task.history_id, task.version, task.read_id)
    call_ids = list(trace.call_ids)

    def ask(context_text: str, final: bool):
        def parse(text):
            return parse_reply(text, task, allow_retrieve=not final)
        reply = model.chat(messages_for(context_text, task, asked_at), tag,
                           prompt_sha256=PROMPT.sha256, parse=parse, max_tokens=max_tokens)
        call_ids.extend(reply.call_ids)
        return reply

    reply = ask(context.text, final=False)
    refused = bool(reply.ok and reply.parsed.output == "retrieve" and trace.retrieval_used)
    if reply.ok and reply.parsed.output == "retrieve" and not refused:
        second = engine.further_retrieval(task, reply.parsed.request, budget)
        first_context = context
        context, trace = second.context, second.trace
        call_ids.extend(trace.call_ids)
        reply = ask(final_context_text(first_context, context), final=True)
    trace = api.ReadTrace(**{**trace.__dict__, "call_ids": tuple(call_ids)})
    if not reply.ok:
        return Answered("invalid", None, [], reply.text, context, trace, [])
    if refused:
        return Answered("unknown", None, [], reply.text, context, trace, [], True)
    parsed: Reply = reply.parsed
    cited = [c for c in dict.fromkeys(parsed.cited_ids) if c in visible_ids]
    dropped = [c for c in parsed.cited_ids if c not in visible_ids]
    value = parsed.value if parsed.output in ("answer", "state") else None
    return Answered(parsed.output, value, cited if value is not None else [], reply.text,
                    context, trace, dropped)


def is_answer_call(messages) -> bool:
    """Whether chat messages are an answering call (for fake responders in tests)."""
    return messages[0]["content"] == PROMPT.system


def is_final_call(messages) -> bool:
    """Whether an answering call is the second one, after the further retrieval."""
    return is_answer_call(messages) and f"\n\n{FURTHER_HEADING}:\n" in messages[-1]["content"]
