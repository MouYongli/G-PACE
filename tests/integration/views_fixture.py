"""Fixture history for the view tests (T018) and a deterministic fake LLM for view rendering.

The history combines the running examples of plan 3.5 with every kind of change a view must
survive: new matches, an acceptance that empties a negated view (non-monotone), a repeated mention
(citation-stale only), an evidence-only mention, a state change with a valid end, a late
correction, a rejection, a switch of the current choice and a past-dated claim. Speakers follow the
change-sequence generator (`user`, `assistant`).

`fake_transport` stands in for the OpenAI-compatible server behind `grace.llm.client.ChatClient`:
it writes one sentence per unit of the `render-view` prompt, the unit's values joined by "; ",
so its output passes the rendering check and is a deterministic function of each unit alone.
"""

from __future__ import annotations

import json
import re

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entries import (
    Attribution,
    Certainty,
    Claim,
    CommunicativeFunction,
    Entity,
    EvidenceLink,
    Polarity,
    ReportMode,
    Supersession,
    SupersessionKind,
    ValidTime,
    Value,
)
from grace.context.memory.graph.store import ClaimStore

HISTORY = "t018-fixture"


def claim(cid, s, p, o, v, start=None, end=None):
    obj = o if isinstance(o, Value) else Entity(o)
    return Claim(cid, s, p, obj, None, ValidTime(start, end), v)


def att(aid, cid, v, speaker, fn):
    return Attribution(aid, cid, speaker, CommunicativeFunction(fn), ReportMode.OWN,
                       Polarity.POSITIVE, Certainty.CERTAIN, False, f"m{v}", v)


def ev(eid, cid, v):
    return EvidenceLink(eid, cid, f"m{v}", None, v)


def time(text):
    return Value(text, "time")


def new(cid, s, p, o, v, speaker, fn, **kw):
    """A new claim with its attribution and evidence link (IDs derived from the claim ID)."""
    return (claim(cid, s, p, o, v, **kw), att("a" + cid[1:], cid, v, speaker, fn),
            ev("e" + cid[1:], cid, v))


def changeset(v, *news, attributions=(), evidence=(), supersessions=(), **kw):
    return ChangeSet(HISTORY, v,
                     claims=tuple(n[0] for n in news),
                     attributions=tuple(n[1] for n in news) + tuple(attributions),
                     evidence_links=tuple(n[2] for n in news) + tuple(evidence),
                     supersessions=tuple(supersessions), **kw)


def changesets() -> list[ChangeSet]:
    return [
        changeset(1, new("c_berlin", "lina", "livesIn", "Berlin", 1, "user", "inform"),
                  new("c_atlas", "lina", "maintains", "Atlas", 1, "user", "inform")),
        changeset(2, new("c_violin", "melanie", "playsInstrument", "violin", 2, "melanie",
                         "inform")),
        changeset(3, new("c_req", "request1", "arriveBy", time("20:45:00"), 3, "user",
                         "request"),
                  new("c_dest", "request1", "destination", "Vienna", 3, "user", "request")),
        changeset(4, new("c_offer", "request1", "selectedService", "TR7143", 4, "assistant",
                         "offer"),
                  new("c_arr", "TR7143", "scheduledArrival", time("20:38:00"), 4, "assistant",
                      "inform")),
        changeset(5, new("c_offer2", "request1", "selectedService", "TR9999", 5, "assistant",
                         "offer"),
                  new("c_arr9", "TR9999", "scheduledArrival", time("21:10:00"), 5, "assistant",
                      "inform")),
        # The user accepts TR7143: a new attribution, nothing superseded.
        changeset(6, attributions=(att("a_acc", "c_offer", 6, "user", "accept"),),
                  evidence=(ev("e_acc", "c_offer", 6),)),
        changeset(7, new("c_clarinet", "melanie", "playsInstrument", "clarinet", 7, "melanie",
                         "inform")),
        # Melanie mentions the violin again: citation-stale only.
        changeset(8, attributions=(att("a_violin2", "c_violin", 8, "melanie", "inform"),),
                  evidence=(ev("e_violin2", "c_violin", 8),)),
        # Lina moved to Munich: a state change with a valid end.
        changeset(9, new("c_munich", "lina", "livesIn", "Munich", 9, "user", "inform",
                         start="2023-03-01"),
                  supersessions=(Supersession("s_berlin", "c_berlin", SupersessionKind.CHANGE,
                                              "2023-03-01", "c_munich", "a_munich", 9),)),
        changeset(10, new("c_boreal", "lina", "maintains", "Boreal", 10, "user", "inform")),
        # Late correction of the arrival time of TR7143.
        changeset(11, new("c_arr2", "TR7143", "scheduledArrival", time("20:40:00"), 11,
                          "assistant", "inform"),
                  supersessions=(Supersession("s_arr", "c_arr", SupersessionKind.CORRECTION,
                                              None, "c_arr2", "a_arr2", 11),)),
        # The user rejects TR7143: the current choice empties; pending is unchanged.
        changeset(12, attributions=(att("a_rej", "c_offer", 12, "user", "reject"),),
                  evidence=(ev("e_rej", "c_offer", 12),)),
        # The user accepts TR9999: the choice switches, pending empties.
        changeset(13, attributions=(att("a_acc2", "c_offer2", 13, "user", "accept"),),
                  evidence=(ev("e_acc2", "c_offer2", 13),)),
        # A past state with a stated valid end; kept in parallel, never current.
        changeset(14, new("c_hamburg", "lina", "livesIn", "Hamburg", 14, "user", "inform",
                          start="2010-01-01", end="2015-01-01")),
        # An evidence-only mention of the clarinet.
        changeset(15, evidence=(ev("e_clarinet2", "c_clarinet", 15),)),
    ]


HEAD = 15


def build_store(mode: str = "rdf11", upto: int = HEAD) -> ClaimStore:
    store = ClaimStore(HISTORY, mode)
    for cs in changesets():
        if cs.version <= upto:
            store.commit(cs)
    return store


# ---------------------------------------------------------------------------------------------
# Fake LLM

_UNIT = re.compile(r"^\[([^\]]+)\] (.*)$")


def fake_sentences(user_text: str) -> list[dict]:
    """One sentence per unit: its values, then the view title (which names the binding's subject,
    required by the rendering check)."""
    head, rows = user_text.split("Rows:\n", 1)
    title = head.rsplit("View: ", 1)[1].strip()
    out = []
    for line in rows.splitlines():
        m = _UNIT.match(line)
        if m:
            values = [pair.split(" = ", 1)[1] for pair in m.group(2).split("; ")]
            out.append({"rows": [m.group(1)], "text": "; ".join(values) + f" ({title})."})
    return out


def completion(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"completion_tokens": len(text.split()), "prompt_tokens": 0}}


class FakeTransport:
    """`Transport` of ChatClient. `rewrite(sentences, user_text)` may corrupt the output."""

    def __init__(self, rewrite=None):
        self.rewrite = rewrite
        self.requests: list[dict] = []

    def __call__(self, url, payload, headers, timeout):
        self.requests.append(payload)
        user = payload["messages"][-1]["content"]
        sentences = fake_sentences(user)
        if self.rewrite is not None:
            out = self.rewrite(sentences, user)
            if isinstance(out, str):
                return completion(out)
            sentences = out
        return completion(json.dumps({"sentences": sentences}))
