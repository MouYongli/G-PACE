"""The blind judge: fixed model snapshot and prompt, system identity hidden (plan 6.7, 7.1).

A judge sees exactly three strings: the question, the reference answer of the scored annotation,
and the prediction rendered as text. It never sees the run, the engine, the working context,
citations, raw output or metadata, so it cannot tell systems apart. Only `answer` predictions are
judged; `unknown` and `invalid` are scored by rule (metrics/answer.py, metrics/record.py).

Each judgement is one `judgements.jsonl` record (Experiment run section): `read_id`, `task_id`,
`annotation`, `judge`, `verdict` (`correct`, `incorrect` or `invalid`), `raw_output`, `call_id`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from grace.llm.client import ChatClient
from grace.llm.prompts import Prompt
from grace.llm.records import CallContext

VERDICTS = ("correct", "incorrect", "invalid")


@dataclass(frozen=True)
class Judgement:
    read_id: str
    task_id: str
    annotation: str
    judge: str
    verdict: str
    raw_output: str | None
    call_id: str

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {self.verdict!r}")


def render_value(value) -> str:
    """A prediction or reference as plain text: lists joined with "; "."""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        raise ValueError("states are scored by metrics/dst.py, not judged")
    if value is None:
        raise ValueError("nothing to judge")
    return str(value)


def blind_inputs(read_task: Mapping, gold: Mapping, prediction: Mapping) -> dict[str, str]:
    """The only judge inputs. Nothing about the producing system passes through here."""
    if prediction["output"] != "answer":
        raise ValueError(f"only answer predictions are judged, got {prediction['output']!r}")
    if read_task["kind"] != "question" or not read_task.get("question"):
        raise ValueError("only question reads are judged")
    return {"question": read_task["question"], "reference": render_value(gold["reference"]),
            "response": render_value(prediction["prediction"])}


def parse_label(text: str | None) -> str:
    """Blind-judge rule: the reply is exactly one word, CORRECT or INCORRECT (case and
    surrounding whitespace and a final period ignored); anything else is `invalid`."""
    word = (text or "").strip().rstrip(".").strip().upper()
    return {"CORRECT": "correct", "INCORRECT": "incorrect"}.get(word, "invalid")


class Judge:
    """A judge = a name, a prompt chooser, a parsing rule and decoding, run through `llm/`."""

    def __init__(self, name: str, client: ChatClient,
                 choose_prompt: Callable[[Mapping, Mapping], Prompt],
                 parse: Callable[[str | None], str], decoding: Mapping):
        self.name, self.client = name, client
        self.choose_prompt, self.parse, self.decoding = choose_prompt, parse, dict(decoding)

    def judge(self, read_task: Mapping, gold: Mapping, prediction: Mapping) -> Judgement:
        if gold["task_id"] != read_task["task_id"] or prediction["read_id"] != \
                read_task["read_id"]:
            raise ValueError(f"read {read_task['read_id']}: gold or prediction misaligned")
        prompt = self.choose_prompt(read_task, gold)
        messages = prompt.render(**blind_inputs(read_task, gold, prediction))
        context = CallContext(call_type="judge", trigger="evaluation",
                              history_id=read_task["history_id"], read_id=read_task["read_id"],
                              version=read_task["version"])
        result = self.client.chat(messages, context, prompt_sha256=prompt.sha256,
                                  decoding=self.decoding,
                                  validate=lambda text: None if self.parse(text) != "invalid"
                                  else "unparsable verdict")
        return Judgement(read_id=read_task["read_id"], task_id=read_task["task_id"],
                         annotation=gold["annotation"], judge=self.name,
                         verdict=self.parse(result.text), raw_output=result.text,
                         call_id=result.call_id)


def blind_judge(name: str, client: ChatClient, prompt: Prompt, decoding: Mapping) -> Judge:
    return Judge(name, client, lambda task, gold: prompt, parse_label, decoding)


def write_judgements(path: Path, judgements: list[Judgement]) -> None:
    """Write judgements.jsonl exclusively; one record per read and judge."""
    keys = [(j.read_id, j.judge) for j in judgements]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate judgement for a read and judge")
    with Path(path).open("x", encoding="utf-8") as handle:
        for judgement in judgements:
            handle.write(json.dumps(asdict(judgement), ensure_ascii=False) + "\n")


def read_judgements(path: Path, judge: str) -> dict[str, Judgement]:
    """read_id -> judgement of one judge; duplicates and unknown fields abort."""
    out: dict[str, Judgement] = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        try:
            judgement = Judgement(**json.loads(line))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
        if judgement.judge != judge:
            continue
        if judgement.read_id in out:
            raise ValueError(f"{path}:{number}: duplicate judgement of {judgement.read_id}")
        out[judgement.read_id] = judgement
    return out
