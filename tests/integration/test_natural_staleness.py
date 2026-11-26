"""E002: one-off extraction mapping, the replay with typed changes, and the totals.

The two scripted histories follow the running examples of plan 3.5 (the violin and the clarinet;
an offer, its acceptance and a rejection) with a fake model, so the change types and the misses of
the citation-based strategies are known by hand (plan 3.4, "Observation").
"""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from types import SimpleNamespace

from grace.config.paths import REPO_ROOT
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import load_vocabulary
from grace.context.views.template_families import load_view_config
from grace.eval.analysis.metrics.natural_staleness import summarise
from grace.eval.runner.probes import natural_extract as nx
from grace.eval.runner.probes import natural_staleness as ns
from grace.llm.prompts import load_pinned

PROMPT = load_pinned("extract-claims-rough", REPO_ROOT / "configs" / "common" / "prompts.yaml")


def claim(s, p, o, function="inform", kind="value", single=False):
    return {"subject": s, "predicate": p, "object": o, "object_kind": kind,
            "function": function, "single_valued": single}


def out(claims=(), stances=(), ended=()):
    return json.dumps({"claims": list(claims), "stances": list(stances), "ended": list(ended)})


MELANIE = [  # (speaker, text, model output)
    ("Melanie", "I play the violin.", out([claim("Melanie", "plays instrument", "violin")])),
    ("Caroline", "Nice!", out()),
    ("Melanie", "I also took up the clarinet.",
     out([claim("Melanie", "playsInstrument", "Clarinet")])),
    ("Melanie", "The violin is still my favourite.",
     out([claim("melanie", "playsInstrument", "VIOLIN")])),
    ("Melanie", "I live in Boston.", out([claim("Melanie", "livesIn", "Boston", single=True)])),
    ("Melanie", "We moved to Denver.", out([claim("Melanie", "livesIn", "Denver", single=True)])),
    ("Melanie", "I gave up the violin.", out(ended=[{"claim": "c1", "kind": "change"}])),
]

TRIP = [
    ("user", "Find me a hotel under 150 a night.",
     out([claim("user's trip", "maxPrice", "150", function="request")])),
    ("assistant", "Hotel A costs 120 a night.",
     out([claim("user's trip", "selectedOption", "Hotel A", function="offer", kind="entity"),
          claim("Hotel A", "pricePerNight", "120")])),
    ("user", "Great, book Hotel A.", out(stances=[{"claim": "c2", "function": "accept"}])),
    ("user", "Actually no, not Hotel A.", out(stances=[{"claim": "c2", "function": "reject"}])),
    ("user", "This is not JSON", "sorry"),
]


def history(history_id, script):
    messages = [SimpleNamespace(history_id=history_id, version=i, message_id=f"m{i}",
                                speaker=speaker, role="peer", text=text, timestamp=None,
                                segment_id="s1")
                for i, (speaker, text, _) in enumerate(script, start=1)]
    info = SimpleNamespace(history_id=history_id, segments=())
    outputs = {i: o for i, (_, _, o) in enumerate(script, start=1)}

    def chat(rendered, version):
        assert rendered[0]["role"] == "system" and "New message" in rendered[1]["content"]
        return outputs[version], "ok", None, [f"c{version:07d}"]

    extraction = nx.extract_history(info, messages, chat, PROMPT, load_vocabulary(),
                                    participants="test")
    return messages, extraction


def base_config():
    return replace(load_view_config(), instantiation_threshold=1, state_speaker=None,
                   choice_predicate="selectedOption")


def replay(history_id, script, roles=None):
    messages, extraction = history(history_id, script)
    vocabulary = ns.vocabulary_from(extraction.vocabulary, "test")
    speakers = list(dict.fromkeys(m.speaker for m in messages))
    if roles is None and len(speakers) != 2:
        speakers = [*speakers, "other"][:2]
    result = ns.measure_history(history_id, extraction.changesets, messages, vocabulary,
                                base_config(), ns.orientations(speakers, roles),
                                benchmark="test", full_check=True)
    return extraction, result


def events_by(result):
    return {(e["version"], e["view_id"], e["orientation"]): e for e in result.events
            if e["outcome"] != "none"}


class ParseTest(unittest.TestCase):
    def test_shapes(self):
        x = nx.parse_output("```json\n" + out([claim("A", "likes", "tea")]) + "\n```")
        self.assertEqual(x.claims[0].predicate, "likes")
        self.assertEqual(nx.parse_output('{"claims": []}'), nx.Extraction())
        for bad in ("[]", '{"claims": [{"subject": "A"}]}', '{"facts": []}',
                    out([claim("A", "likes", "tea", function="maybe")]),
                    '{"stances": [{"claim": "c1", "function": "inform"}]}', "no json"):
            with self.assertRaises(nx.ExtractionError, msg=bad):
                nx.parse_output(bad)

    def test_predicate_names(self):
        self.assertEqual(nx.predicate_name("plays instrument"), "playsInstrument")
        self.assertEqual(nx.predicate_name("livesIn"), "livesIn")
        self.assertEqual(nx.predicate_name("works_at"), "worksAt")
        self.assertEqual(nx.predicate_name("2nd job"), "p2ndJob")
        self.assertIsNone(nx.predicate_name("--"))


class MappingTest(unittest.TestCase):
    def test_change_sets(self):
        _, x = history("mel", MELANIE)
        cs = x.changesets
        self.assertEqual([c.version for c in cs], list(range(1, 8)))
        self.assertEqual(cs[0].claims[0].predicate, "playsInstrument")
        # repeated mention: no new claim, an attribution and an evidence link on c1
        self.assertEqual((cs[3].claims, [a.claim_id for a in cs[3].attributions],
                          [e.claim_id for e in cs[3].evidence_links]), ((), ["c1"], ["c1"]))
        # exclusivity rule (seed vocabulary: livesIn is exclusive)
        (s,) = cs[5].supersessions
        self.assertEqual((s.claim_id, s.kind.value, s.replacing_claim_id), ("c3", "change", "c4"))
        # ended claim: negative inform licence on the claim itself
        (s,) = cs[6].supersessions
        (a,) = cs[6].attributions
        self.assertEqual((s.claim_id, a.claim_id, a.polarity.value), ("c1", "c1", "negative"))
        self.assertEqual(x.vocabulary["playsInstrument"]["exclusive"], False)
        store = ClaimStore("mel")
        for c in cs:
            store.commit(c)
        self.assertFalse(store.state(7).is_current("c1"))

    def test_invalid_output_gives_empty_change_set(self):
        _, x = history("trip", TRIP)
        self.assertTrue(x.changesets[4].empty)
        self.assertEqual(x.records[4]["status"], "invalid_output")
        self.assertEqual(x.status["ok"], 4)


class ReplayTest(unittest.TestCase):
    def test_entity_families(self):
        _, result = replay("mel", MELANIE)
        self.assertEqual(result.soundness_violations, [])
        ev = events_by(result)
        lst, cnt = "list:Melanie:playsInstrument", "count:Melanie:playsInstrument"
        cur = "current:Melanie:livesIn"
        expected = {(3, lst): ("C2", "answer"), (3, cnt): ("C4", "answer"),
                    (4, lst): ("C6", "citation"), (4, cnt): ("C6", "citation"),
                    (6, cur): ("C1", "answer"),
                    (7, lst): ("C1", "answer"), (7, cnt): ("C1", "answer")}
        got = {(v, view): (e["type"], e["outcome"]) for (v, view, o), e in ev.items() if o == 0}
        self.assertEqual(got, expected)
        marks = {(v, view): e["marks"] for (v, view, _), e in ev.items()}
        # the new match is missed by both citation strategies; the count change only by the first
        self.assertIsNone(marks[(3, lst)]["used_claims"])
        self.assertIsNone(marks[(3, lst)]["used_claims_patterns"])
        self.assertIsNone(marks[(3, cnt)]["used_claims"])
        self.assertEqual(marks[(3, cnt)]["used_claims_patterns"], "answer")
        self.assertEqual(marks[(6, cur)]["used_claims"], "answer")
        self.assertEqual(result.views_created["list"], 1)
        self.assertEqual(result.views_created["current"], 1)

    def test_task_families(self):
        _, result = replay("trip", TRIP, roles={"user": "user", "assistant": "assistant"})
        self.assertEqual(result.soundness_violations, [])
        ev = events_by(result)
        pending, choice = "pending:user's trip", "choice:user's trip"
        self.assertEqual((ev[(3, pending, 0)]["type"], ev[(3, pending, 0)]["outcome"]),
                         ("C3", "answer"))
        self.assertIsNone(ev[(3, pending, 0)]["marks"]["used_claims"])
        self.assertEqual(ev[(3, pending, 0)]["marks"]["used_claims_patterns"], "answer")
        self.assertEqual((ev[(4, choice, 0)]["type"], ev[(4, choice, 0)]["outcome"]),
                         ("C3", "answer"))

    def test_summary(self):
        _, mel = replay("mel", MELANIE)
        hist = [{"benchmark": "test", **mel.summary()}]
        totals = summarise(mel.events, hist, {"test": 7},
                           {"max_per_thousand": 1.0, "max_share": 0.1})["test"]
        self.assertEqual((totals["answer_stale"], totals["citation_stale"]), (5, 2))
        self.assertEqual(totals["types"]["C2"]["events"], 1)
        self.assertEqual(totals["missed_by_design"]["answer_events"], 2)
        self.assertFalse(totals["missed_by_design"]["rare"])
        self.assertEqual(totals["citation_strategy_misses"]["used_claims"]["missed_answer"], 2)
        self.assertEqual(
            totals["citation_strategy_misses"]["used_claims_patterns"]["missed_answer"], 1)
        self.assertEqual(totals["untyped_staleness"], 0)
        self.assertEqual(totals["over_marking"]["predicate_level"]["stale_not_marked"], 0)


if __name__ == "__main__":
    unittest.main()
