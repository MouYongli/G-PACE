"""Fixture histories and a scripted fake LLM for the writer tests (T022).

The histories are synthetic re-enactments of the three running examples of plan 3.5 (the texts
are written for the tests, not copied from LoCoMo or MultiWOZ). `ScriptedTransport` stands in for
the OpenAI-compatible server behind `grace.llm.client.ChatClient`: each call pops the next reply
from a script. A reply is a JSON-able object (sent as the writer's output), a raw string, an
exception instance (raised as a transport failure) or a function of the user prompt returning one
of these, so a reply can look up the handle the prompt gave to a known claim.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from grace.context.api import HistoryInfo, Message, Segment
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.history.log import MessageLog
from grace.context.pipeline.update.updater import Updater, WriterConfig, llm_writer
from grace.llm.client import ChatClient, Endpoint
from grace.llm.records import CallLedger
from tests.llm.fakes import WordCounter


def message(history: str, version: int, speaker: str, text: str, session: str = "s1",
            role: str | None = None, timestamp: str | None = None) -> Message:
    return Message(benchmark="fixture", split="dev", history_id=history, version=version,
                   message_id=f"{history}:m{version}", segment_id=session, speaker=speaker,
                   role=role or ("agent" if speaker in ("system", "assistant") else "user"),
                   text=text, timestamp=timestamp, timestamp_raw=None)


def history_info(history: str, messages: list[Message],
                 dates: dict[str, str] | None = None) -> HistoryInfo:
    sessions: dict[str, list[int]] = {}
    for m in messages:
        sessions.setdefault(m.segment_id, []).append(m.version)
    segments = tuple(Segment(s, v[0], v[-1], (dates or {}).get(s), None)
                     for s, v in sessions.items())
    return HistoryInfo("fixture", "dev", history, None, len(messages), segments)


# ---------------------------------------------------------------------------------------------
# Running example 1: a multi-valued predicate (LoCoMo conv-26, re-enacted)

MELANIE = "t022-instruments"
MELANIE_DATES = {"s1": "2023-05-25T13:00:00", "s2": "2023-08-28T15:00:00"}


def melanie_messages() -> list[Message]:
    h = MELANIE
    return [
        message(h, 1, "Melanie", "I've been playing the violin a lot lately, it relaxes me."),
        message(h, 2, "Caroline", "That sounds lovely. Anything new since we last talked?", "s2"),
        message(h, 3, "Melanie", "Yes! I started learning the clarinet last month.", "s2"),
        message(h, 4, "Melanie", "The violin is still my favourite though.", "s2"),
    ]


def violin(msg: int, quote: str) -> dict:
    return {"message": msg, "subject": "Melanie", "predicate": "playsInstrument",
            "object": "violin", "object_type": "entity", "function": "inform", "quote": quote}


MELANIE_SCRIPT = [
    {"claims": [violin(1, "playing the violin")], "stances": []},
    {"claims": [{"message": 2, "subject": "Melanie", "predicate": "playsInstrument",
                 "object": "clarinet", "object_type": "entity", "function": "inform",
                 "time_expression": "last month", "quote": "learning the clarinet"},
                violin(3, "The violin is still my favourite")], "stances": []},
]


# ---------------------------------------------------------------------------------------------
# Running examples 2 and 3: request, offer, acceptance (MultiWOZ SNG0296, re-enacted)

TRAIN = "t022-train"


def train_messages() -> list[Message]:
    h = TRAIN
    return [
        message(h, 1, "user", "I need a train to Cambridge that arrives by 20:45 at the latest."),
        message(h, 2, "system", "Sure. Where will you be departing from?"),
        message(h, 3, "user", "From London Kings Cross, on Sunday."),
        message(h, 4, "system", "There are several trains on Sunday."),
        message(h, 5, "user", "Which one would you recommend?"),
        message(h, 6, "system", "TR7143 departs at 19:48 and arrives by 20:38. Shall I book it?"),
        message(h, 7, "user", "Yes, please book it and give me the reference number."),
    ]


def handle_of(user_prompt: str, label_part: str) -> str:
    """The handle `k<i>` the prompt gives to the known claim whose label contains `label_part`."""
    for line in user_prompt.splitlines():
        m = re.match(r"(k\d+): (.*)$", line)
        if m and label_part in m.group(2):
            return m.group(1)
    raise AssertionError(f"no known claim containing {label_part!r} in the prompt")


TRAIN_SCRIPT = [
    # Partial unit m1..m6, flushed by a read at version 6.
    {"claims": [
        {"message": 1, "subject": "request1", "predicate": "arrive by", "object": "20:45",
         "object_type": "time", "function": "request", "quote": "arrives by 20:45"},
        {"message": 1, "subject": "request1", "predicate": "destination", "object": "Cambridge",
         "object_type": "entity", "function": "request", "quote": "to Cambridge"},
        {"id": "n1", "message": 6, "subject": "request1", "predicate": "selectedService",
         "object": "TR7143", "object_type": "entity", "function": "offer",
         "quote": "TR7143 departs at 19:48"},
        {"message": 6, "subject": "TR7143", "predicate": "scheduledArrival", "object": "20:38",
         "object_type": "time", "function": "inform", "quote": "arrives by 20:38"},
        # The offer states another arrival time; the request must survive it.
        {"message": 6, "subject": "request1", "predicate": "arriveBy", "object": "20:38",
         "object_type": "time", "function": "offer", "quote": "arrives by 20:38"}],
     "stances": []},
    # m7: the user accepts the offer (a stance on the known claim; nothing superseded).
    lambda prompt: {"claims": [], "stances": [
        {"message": 1, "claim": handle_of(prompt, "selectedService | TR7143"),
         "function": "accept", "quote": "Yes, please book it"}]},
]


# ---------------------------------------------------------------------------------------------
# Fake server and wiring


def completion(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"completion_tokens": max(1, len(text.split())), "prompt_tokens": 0,
                      "prompt_tokens_details": {"cached_tokens": 0}}}


class ScriptedTransport:
    def __init__(self, script):
        self.script = list(script)
        self.requests: list[dict] = []

    def __call__(self, url, payload, headers, timeout):
        self.requests.append(payload)
        if not self.script:
            raise AssertionError("the writer made more calls than scripted")
        reply = self.script.pop(0)
        if callable(reply):
            reply = reply(payload["messages"][-1]["content"])
        if isinstance(reply, BaseException):
            raise reply
        return completion(reply if isinstance(reply, str) else json.dumps(reply))


class Rig:
    """An updater over a fresh log and store with a scripted writer and a real call ledger."""

    def __init__(self, messages: list[Message], script, *, config: WriterConfig | None = None,
                 dates: dict[str, str] | None = None, max_attempts: int = 1):
        self.tmp = tempfile.TemporaryDirectory()
        self.messages = messages
        history = messages[0].history_id
        self.info = history_info(history, messages, dates)
        self.ledger = CallLedger(Path(self.tmp.name) / "calls.jsonl", "run-t022")
        self.transport = ScriptedTransport(script)
        self.client = ChatClient(Endpoint("http://fake/v1", "writer", "writer@1"), self.ledger,
                                 WordCounter(), max_attempts=max_attempts, backoff_s=0.0,
                                 transport=self.transport, sleep=lambda s: None)
        self.config = config or WriterConfig()
        self.log = MessageLog(history)
        self.store = ClaimStore(history)
        self.updater = Updater(self.info, self.log, self.store,
                               llm_writer(self.config, self.client, self.info), self.config)

    def close(self) -> None:
        self.tmp.cleanup()

    def write_all(self, upto: int | None = None) -> list:
        out = []
        for m in self.messages:
            if upto is not None and m.version > upto:
                break
            out += self.updater.write(m)
        return out
