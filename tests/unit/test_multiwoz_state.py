"""Unit tests of the MultiWOZ state package (T028) on synthetic inputs: slot projection policies,
the claim-graph projection, ReacTOD's loop and validator, the derived offer-turn gold and the
offer-turn metrics."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from types import MappingProxyType

from grace.context import api
from grace.context.memory.graph.entries import (
    Attribution,
    Certainty,
    Claim,
    CommunicativeFunction,
    Entity,
    Polarity,
    ReportMode,
    Supersession,
    SupersessionKind,
    ValidTime,
    Value,
)
from grace.context.memory.graph.store import GraphState
from grace.eval.analysis.metrics import dst
from grace.eval.datasets.benchmarks import multiwoz_derived as md
from grace.eval.engines.baselines import multiwoz as mw
from grace.eval.engines.baselines.multiwoz_reactod import ReacTOD
from grace.eval.runner.harness.models import FakeBackend, RecordingModel
from grace.llm.records import CallLedger
from tests.unit.test_multiwoz_offers import dialogue

SLOTS = frozenset({"train-arriveby", "train-leaveat", "train-day", "train-destination",
                   "hotel-name", "hotel-area", "hotel-bookday"})
SPECS = [
    mw.SlotSpec("hotel-area", "area", "categorical", ("centre", "east", "north", "south", "west")),
    mw.SlotSpec("hotel-bookday", "day", "categorical", ("monday", "tuesday")),
    mw.SlotSpec("hotel-name", "name", "text"),
    mw.SlotSpec("train-arriveby", "arrive by", "time"),
    mw.SlotSpec("train-day", "day", "categorical", ("monday", "tuesday")),
    mw.SlotSpec("train-destination", "destination", "text"),
    mw.SlotSpec("train-leaveat", "leave at", "time"),
]


def row(slot, value, role, function, version):
    return mw.SlotRow(slot, value, role, function, version, str(version - 1))


# The SNG0296 pattern of plan 3.5: the user asks to arrive by 20:45, the system offers TR7143
# arriving 20:38, the user accepts.
SNG0296 = [
    row("train-arriveby", "20:45", "user", "inform", 1),
    row("train-day", "monday", "user", "inform", 1),
    row("train-trainid", "TR7143", "agent", "offer", 6),
    row("train-arriveby", "20:38", "agent", "offer", 6),
    row("train-leaveat", "19:48", "agent", "offer", 6),
    row("train-trainid", "TR7143", "user", "accept", 7),
]


class Projection(unittest.TestCase):
    def test_overwrite_writes_offers(self):
        p = mw.project(SNG0296, 7, "overwrite", SLOTS)
        self.assertEqual(p.state["train-arriveby"], "20:38")
        self.assertEqual(p.state["train-leaveat"], "19:48")
        self.assertIsNone(p.current_choice["train"])   # train IDs are not an official slot

    def test_user_only_keeps_constraint_and_has_no_choice(self):
        p = mw.project(SNG0296, 7, "user-only", SLOTS)
        self.assertEqual(p.state, {"train-arriveby": "20:45", "train-day": "monday"})
        self.assertIsNone(p.current_choice["train"])

    def test_guard_keeps_constraint_and_knows_choice(self):
        p = mw.project(SNG0296, 7, "guard", SLOTS)
        self.assertEqual(p.state["train-arriveby"], "20:45")   # the user's constraint stays
        self.assertEqual(p.state["train-leaveat"], "19:48")    # unconstrained: accepted value
        self.assertEqual(p.current_choice["train"], "tr7143")

    def test_no_look_ahead(self):
        p = mw.project(SNG0296, 6, "guard", SLOTS)   # before the acceptance
        self.assertNotIn("train-leaveat", p.state)
        self.assertIsNone(p.current_choice["train"])

    def test_guard_rejection_drops_choice(self):
        rows = [*SNG0296, row("train-trainid", "TR7143", "user", "reject", 9)]
        self.assertIsNone(mw.project(rows, 9, "guard", SLOTS).current_choice["train"])

    def test_reject_and_agent_requests_are_not_written(self):
        rows = [row("hotel-area", "north", "user", "inform", 1),
                row("hotel-bookday", "when", "agent", "request", 2),
                row("hotel-area", "north", "user", "reject", 3)]
        self.assertEqual(mw.project(rows, 3, "overwrite", SLOTS).state, {"hotel-area": "north"})

    def test_dontcare_and_unknown_policy(self):
        rows = [row("hotel-area", "any", "user", "inform", 1)]
        self.assertEqual(mw.project(rows, 1, "user-only", SLOTS).state["hotel-area"], "dontcare")
        with self.assertRaises(ValueError):
            mw.project(rows, 1, "magic", SLOTS)


def graph_state() -> GraphState:
    """Claim graph of the SNG0296 pattern: the guard kept the request and the offer in parallel;
    a superseded claim must not be projected."""
    vt = ValidTime()
    claims = [
        Claim("c1", "train_task", "arriveBy", Value("20:45:00", "time"), None, vt, 1),
        Claim("c2", "train_task", "arriveBy", Value("20:38:00", "time"), None, vt, 6),
        Claim("c3", "train_task", "selectedService", Entity("TR7143"), None, vt, 6),
        Claim("c4", "train_task", "day", Value("sunday"), None, vt, 1),
        Claim("c5", "train_task", "day", Value("monday"), None, vt, 3),
    ]

    def att(aid, cid, speaker, function, version, polarity=Polarity.POSITIVE):
        return Attribution(aid, cid, speaker, function, ReportMode.OWN, polarity,
                           Certainty.CERTAIN, False, str(version - 1), version)
    atts = [att("a1", "c1", "user", CommunicativeFunction.REQUEST, 1),
            att("a2", "c2", "system", CommunicativeFunction.OFFER, 6),
            att("a3", "c3", "system", CommunicativeFunction.OFFER, 6),
            att("a4", "c3", "user", CommunicativeFunction.ACCEPT, 7),
            att("a5", "c4", "user", CommunicativeFunction.REQUEST, 1),
            att("a6", "c5", "user", CommunicativeFunction.REQUEST, 3)]
    sups = [Supersession("s1", "c4", SupersessionKind.CORRECTION, None, "c5", "a6", 3)]
    return GraphState(7, MappingProxyType({c.claim_id: c for c in claims}),
                      MappingProxyType({a.attribution_id: a for a in atts}),
                      MappingProxyType({}), MappingProxyType({s.supersession_id: s for s in sups}),
                      MappingProxyType({}))


class GraphProjection(unittest.TestCase):
    MAPPING = mw.GraphMapping({"arriveBy": "arriveby", "selectedService": "trainid",
                               "day": "day"})

    def test_rows_and_guard_projection(self):
        rows = mw.rows_from_graph(graph_state(), self.MAPPING, {"user": "user",
                                                                "system": "agent"})
        self.assertEqual({(r.slot, r.value, r.role, r.function) for r in rows if r.current}, {
            ("train-arriveby", "20:45", "user", "request"),
            ("train-arriveby", "20:38", "agent", "offer"),
            ("train-trainid", "TR7143", "agent", "offer"),
            ("train-trainid", "TR7143", "user", "accept"),
            ("train-day", "monday", "user", "request")})
        p = mw.project(rows, 7, "guard", SLOTS)
        self.assertEqual(p.state, {"train-arriveby": "20:45", "train-day": "monday"})
        self.assertEqual(p.current_choice["train"], "tr7143")
        self.assertEqual(mw.project(rows, 7, "overwrite", SLOTS).state["train-arriveby"],
                         "20:38")


class FakeModel:
    """A ModelPort over the recording fake with scripted replies."""

    def __init__(self, replies: Sequence[str], case: unittest.TestCase):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.dir = tempfile.TemporaryDirectory()
        case.addCleanup(self.dir.cleanup)
        ledger = CallLedger(Path(self.dir.name) / "calls.jsonl", "T028-test")

        def respond(messages):
            self.prompts.append(messages[-1]["content"])
            return self.replies.pop(0) if self.replies else "not json"
        self.port = RecordingModel(FakeBackend(respond), ledger, max_attempts=1)


def message(version: int, role: str, text: str) -> api.Message:
    return api.Message.from_record({
        "benchmark": "multiwoz", "split": "fixture", "history_id": "SYN.json",
        "message_id": str(version - 1), "version": version, "segment_id": None,
        "role": role, "speaker": "USER" if role == "user" else "SYSTEM", "text": text,
        "timestamp": None, "timestamp_raw": None})


def task(version: int) -> api.ReadTask:
    return api.ReadTask.from_record({
        "benchmark": "multiwoz", "split": "fixture", "history_id": "SYN.json",
        "read_id": f"SYN.json:{version - 1}@{version}", "task_id": f"SYN.json:{version - 1}",
        "version": version, "kind": "state", "question": None,
        "state_schema": "multiwoz-slots", "asked_at": None, "asked_at_raw": None})


def act(**kwargs) -> str:
    return json.dumps({"thought": "t", **kwargs})


class ReacTODLoop(unittest.TestCase):
    def run_turn(self, replies, text="I need a hotel in the north on monday", state=None):
        model = FakeModel(replies, self)
        tracker = ReacTOD(model.port, SPECS)
        if state:
            tracker.state = dict(state)
        tracker.observe(message(1, "user", text))
        return tracker, tracker.predict(task(1)), model

    def test_classify_then_resolve(self):
        tracker, out, _ = self.run_turn([
            act(action="classify_intent", intent=["hotel"]),
            act(action="resolve_slots", updates=[
                {"slot": "hotel-area", "raw": "north", "value": "North"},
                {"slot": "hotel-bookday", "raw": "monday", "value": "monday"}])])
        self.assertEqual(out.state, {"hotel-area": "north", "hotel-bookday": "monday"})
        self.assertEqual(tracker.turns[0]["end"], "resolved")
        self.assertEqual(len(out.call_ids), 2)

    def test_validator_refusals_are_fed_back(self):
        tracker, out, model = self.run_turn([
            act(action="resolve_slots", updates=[]),                       # order
            act(action="classify_intent", intent="hotel"),
            act(action="resolve_slots", updates=[
                {"slot": "hotel-area", "raw": "up north", "value": "upnorth"}]),   # enumeration
            act(action="resolve_slots", updates=[
                {"slot": "hotel-name", "raw": "the hotel", "value": "the hotel"}]),  # coref
            act(action="get_history", n=2),
            act(action="resolve_slots", updates=[
                {"slot": "hotel-area", "raw": "north", "value": "north"}])])
        self.assertEqual(out.state, {"hotel-area": "north"})
        self.assertEqual(tracker.turns[0]["corrections"], 3)
        self.assertIn("call classify_intent before resolve_slots", model.prompts[1])
        self.assertIn("invalid value for slot hotel-area", model.prompts[3])
        self.assertIn("generic reference 'the hotel'", model.prompts[4])

    def test_time_format_and_cap_falls_back(self):
        replies = [act(action="classify_intent", intent=["train"])] + [
            act(action="resolve_slots", updates=[
                {"slot": "train-arriveby", "raw": "8:45", "value": f"8:4{i}"}])
            for i in range(5)]
        tracker, out, model = self.run_turn(replies, state={"train-day": "monday"})
        self.assertEqual(out.state, {"train-day": "monday"})   # B_t = B_{t-1}
        self.assertEqual(tracker.turns[0]["end"], "cap")
        self.assertEqual(len(model.prompts), 6)
        self.assertIn("invalid format for slot train-arriveby: expected HH:MM", model.prompts[2])

    def test_fallback_intent_and_removal(self):
        _, out, model = self.run_turn([act(action="classify_intent", intent=["none"])],
                                      text="thanks", state={"hotel-area": "north"})
        self.assertEqual(out.state, {"hotel-area": "north"})
        self.assertEqual(len(model.prompts), 1)
        _, out, _ = self.run_turn([
            act(action="classify_intent", intent=["hotel"]),
            act(action="resolve_slots", updates=[
                {"slot": "hotel-area", "raw": "", "value": "none"}])],
            state={"hotel-area": "north"})
        self.assertEqual(out.state, {})

    def test_no_look_ahead_and_duplicates(self):
        model = FakeModel([], self)
        tracker = ReacTOD(model.port, SPECS)
        tracker.observe(message(1, "user", "hi"))
        tracker.observe(message(2, "agent", "hello"))
        with self.assertRaises(ValueError):
            tracker.predict(task(1))   # a read must be at the last observed message
        _, _, model = self.run_turn([act(action="classify_intent", intent=["hotel"]),
                                     act(action="classify_intent", intent=["hotel"])])
        self.assertIn("duplicate call", model.prompts[2])


class DerivedGold(unittest.TestCase):
    def test_sng0296_pattern(self):
        d = dialogue(
            [{"Train-Inform": [["Arrive", "20:45"], ["Day", "monday"]]},
             {"Train-Request": [["Leave", "?"]]},
             {"Train-Inform": [["Dest", "cambridge"]]},
             {"Train-OfferBook": [["Id", "TR7143"], ["Arrive", "20:38"], ["Dest", "cambridge"]]},
             {"Train-Inform": [["People", "1"]]},
             {"Booking-Book": [["Ref", "X"]]}],
            [{"train-arriveby": "20:45", "train-day": "monday"},
             {"train-arriveby": "20:45", "train-day": "monday", "train-destination": "cambridge"},
             {"train-arriveby": "20:45", "train-day": "monday", "train-destination": "cambridge",
              "train-bookpeople": "1"}])
        [gold] = md.derive(d, "multiwoz", "dev")
        self.assertEqual(gold.annotation, "2.4-current-choice")
        self.assertEqual(gold.task_id, "SYN.json:4")
        self.assertEqual(gold.reference["retention"], [
            {"slot": "train-arriveby", "original": "20:45", "offered": ["20:38"],
             "conflict": True},
            {"slot": "train-destination", "original": "cambridge", "offered": ["cambridge"],
             "conflict": False}])
        [pair] = gold.reference["paired"]
        self.assertEqual((pair["response"], pair["offered_entity"]), ("accept", ["tr7143"]))
        self.assertEqual(pair["originals"], {"train-arriveby": "20:45",
                                             "train-destination": "cambridge"})
        self.assertEqual(pair["conflict_slots"], ["train-arriveby"])
        summary = md.summary([gold])
        self.assertEqual((summary["retention_items"], summary["retention_items_conflict"]),
                         (2, 1))
        self.assertEqual((summary["paired_items"], summary["paired_items_conflict"]), (1, 1))


class OfferMetrics(unittest.TestCase):
    ITEM = {"domain": "train", "response": "accept", "entity_slot": "train-trainid",
            "offered_entity": ["tr7143"], "originals": {"train-arriveby": "20:45"},
            "conflict_slots": ["train-arriveby"]}
    ORIGINALS = {"train-arriveby": "20:45"}

    def test_retention_and_paired(self):
        retention = {"slot": "train-arriveby", "original": "20:45", "offered": ["20:38"]}
        self.assertEqual(dst.retained({"train-arriveby": "20:45"}, retention), 1.0)
        self.assertEqual(dst.retained({"train-arriveby": "20:38"}, retention), 0.0)
        self.assertEqual(dst.retained(None, retention), 0.0)
        good = {"train-arriveby": "20:45"}
        self.assertEqual(dst.paired_correct(good, {"train": "TR7143"}, self.ITEM,
                                            self.ORIGINALS), 1.0)
        # the never-write-system-values rule: right constraint, no choice
        self.assertEqual(dst.paired_correct(good, {"train": None}, self.ITEM,
                                            self.ORIGINALS), 0.0)
        # writing the system value: right choice, wrong constraint
        self.assertEqual(dst.paired_correct({"train-arriveby": "20:38"}, {"train": "tr7143"},
                                            self.ITEM, self.ORIGINALS), 0.0)

    def test_reject_and_entity_slot_fallback(self):
        item = {**self.ITEM, "domain": "hotel", "entity_slot": "hotel-name",
                "response": "reject", "offered_entity": ["acorn guest house"]}
        originals = {"hotel-area": "north"}
        self.assertEqual(dst.paired_correct({"hotel-area": "north"}, None, item, originals), 1.0)
        self.assertEqual(dst.paired_correct(
            {"hotel-area": "north", "hotel-name": "acorn guest house"}, None, item, originals),
            0.0)
        self.assertEqual(dst.current_choice({"hotel-name": "A"}, {}, "hotel", "hotel-name"), "a")

    def test_lenient_match(self):
        item = {**self.ITEM, "domain": "hotel", "entity_slot": "hotel-name",
                "offered_entity": ["the acorn guest house"]}
        self.assertEqual(dst.choice_correct("acorn guesthouse", item), 0.0)
        self.assertTrue(dst.choice_correct("acorn guesthouse", item,
                                           lambda a, b: a.replace("the ", "").replace(" ", "")
                                           == b.replace("the ", "").replace(" ", "")))


if __name__ == "__main__":
    unittest.main()
