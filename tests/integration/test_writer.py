"""The writer end to end (T022): scripted LLM -> patch -> validation -> guard -> commit.

Acceptance of T022:
- the three running examples of plan 3.5 on fixtures (`RunningExampleTest`);
- every call, retry and failure in the cost ledger (`LedgerTest`).
"""

from __future__ import annotations

import tempfile
import unittest
import urllib.error
from dataclasses import replace
from pathlib import Path

from grace.context.memory.graph.entries import Entity, SupersessionKind, Value
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.history.log import MessageLog
from grace.context.pipeline.query.execute import run
from grace.context.pipeline.query.grammar import parse
from grace.context.pipeline.update.segment import Granularity
from grace.context.pipeline.update.updater import Updater, WriterConfig, llm_writer
from grace.llm.records import read_calls
from tests.integration.writer_fixture import (
    MELANIE_DATES,
    MELANIE_SCRIPT,
    TRAIN_SCRIPT,
    Rig,
    handle_of,
    melanie_messages,
    message,
    train_messages,
)

INSTRUMENTS = "SELECT ?i WHERE { (Melanie, playsInstrument, ?i) }"
OPEN_OFFERS = """SELECT ?train WHERE {
  (request1, selectedService, ?train) [system, offer]
  NOT EXISTS { (request1, selectedService, ?train) [user, accept] }
}"""
CHOICE = "SELECT ?train WHERE { (request1, selectedService, ?train) [user, accept] }"
REQUIRED = "SELECT ?t WHERE { (request1, arriveBy, ?t) [user, request] }"


def answers(store, text, version):
    return {a.values for a in run(parse(text), store, version).answers}


def witnesses(store, text, version):
    return {a.values: a.witnesses for a in run(parse(text), store, version).answers}


class RigTest(unittest.TestCase):
    def rig(self, *args, **kwargs) -> Rig:
        rig = Rig(*args, **kwargs)
        self.addCleanup(rig.close)
        return rig


class RunningExampleTest(RigTest):
    def test_multi_valued_predicate_keeps_both_values(self):
        """Example 1: the clarinet does not overwrite the violin; a repeated mention of the violin
        adds an attribution and an evidence link only (citation-level change)."""
        rig = self.rig(melanie_messages(), MELANIE_SCRIPT, dates=MELANIE_DATES)
        results = rig.write_all()
        self.assertEqual([r.status for r in results], ["ok", "ok"])
        store = rig.store
        self.assertEqual(store.versions(), (1, 2, 3, 4))
        state = store.state(4)
        self.assertEqual(len(state.claims), 2)
        self.assertEqual(state.supersessions, {})
        self.assertEqual(answers(store, INSTRUMENTS, 4), {(Entity("violin"),),
                                                          (Entity("clarinet"),)})
        self.assertEqual(answers(store, INSTRUMENTS, 2), {(Entity("violin"),)})
        # knowledge versions follow the evidence message, not the last message of the unit
        clarinet = next(c for c in state.claims.values() if c.object == Entity("clarinet"))
        self.assertEqual(clarinet.version, 3)
        self.assertEqual(clarinet.valid_time.expression, "last month")
        # the repeated mention at version 4: no claim, one attribution, one evidence link
        cs4 = store.changeset(4)
        self.assertEqual((len(cs4.claims), len(cs4.attributions), len(cs4.evidence_links)),
                         (0, 1, 1))
        self.assertEqual(results[1].notes["repeated_mention"], 1)
        before = witnesses(store, INSTRUMENTS, 3)
        after = witnesses(store, INSTRUMENTS, 4)
        self.assertEqual(set(before), set(after))           # answers unchanged
        violin = next(c for c in state.claims.values() if c.object == Entity("violin"))
        self.assertEqual([e.message_id for e in state.evidence_for(violin.claim_id)],
                         [f"{rig.info.history_id}:m1", f"{rig.info.history_id}:m4"])
        span = state.evidence_for(violin.claim_id)[0].span
        self.assertEqual(rig.messages[0].text[span.start:span.end], "playing the violin")

    def test_offer_does_not_overwrite_request_and_acceptance_is_non_monotone(self):
        """Examples 2 and 3: the offered arrival time (system, offer) does not supersede the
        requirement (user, request); the acceptance is a new attribution on the offer's claim,
        supersedes nothing, empties "offered and not yet accepted" and fills "current choice"."""
        rig = self.rig(train_messages(), TRAIN_SCRIPT)
        self.assertEqual(rig.write_all(upto=6), [])           # the segment of 8 is incomplete
        flushed = rig.updater.flush(6, read_id="r1")          # a read at version 6 falls inside
        self.assertEqual([(r.status, r.partial, r.trigger) for r in flushed],
                         [("ok", True, "read")])
        store = rig.store
        self.assertEqual(store.head, 6)
        required = {(Value("20:45:00", "time"),)}
        self.assertEqual(answers(store, REQUIRED, 6), required)
        self.assertEqual(answers(store, OPEN_OFFERS, 6), {(Entity("TR7143"),)})
        self.assertEqual(answers(store, CHOICE, 6), set())
        # the competing arrival value is kept side by side and reported as a conflict
        self.assertEqual(store.state(6).supersessions, {})
        self.assertEqual([(c["version"], c["reason"]) for c in flushed[0].conflicts],
                         [(6, "speaker_or_function")])
        # the alias "arrive by" resolved to the seed predicate arriveBy
        self.assertTrue(all(c.predicate in ("arriveBy", "destination", "selectedService",
                                            "scheduledArrival")
                            for c in store.state(6).claims.values()))

        offer_claim = next(c for c in store.state(6).claims.values()
                           if c.predicate == "selectedService")
        results = rig.updater.write(rig.messages[6])
        self.assertEqual([(r.status, r.trigger) for r in results], [("ok", "write")])
        cs7 = store.changeset(7)
        self.assertEqual(cs7.claims, ())
        self.assertEqual(cs7.supersessions, ())
        self.assertEqual([(a.claim_id, a.speaker, a.function.value) for a in cs7.attributions],
                         [(offer_claim.claim_id, "user", "accept")])
        self.assertEqual(answers(store, OPEN_OFFERS, 7), set())
        self.assertEqual(answers(store, CHOICE, 7), {(Entity("TR7143"),)})
        self.assertEqual(answers(store, REQUIRED, 7), required)
        # time travel: a read at version 6 is unchanged by the later write
        self.assertEqual(answers(store, OPEN_OFFERS, 6), {(Entity("TR7143"),)})
        # the read-triggered extraction is write cost: category W, trigger read, read_id r1
        calls = read_calls(rig.ledger.path)
        self.assertEqual([(c.trigger, c.category, c.read_id, c.version) for c in calls],
                         [("read", "W", "r1", 6), ("write", "W", None, 7)])


def lina(version, text, speaker="user", session="s1"):
    return message("t022-guard", version, speaker, text, session)


def claim(msg, s, p, o, **kw):
    return {"message": msg, "subject": s, "predicate": p, "object": o,
            "object_type": kw.pop("object_type", "entity"), **kw}


class GuardThroughWriterTest(RigTest):
    """The guard on writer output: change, quote, other speaker, removal, correction."""

    def run_guard(self, messages, script, **config):
        cfg = replace(WriterConfig(), granularity=Granularity("message", None), **config)
        rig = self.rig(messages, script, config=cfg)
        results = rig.write_all()
        return rig, results

    def test_same_speaker_change_supersedes_with_valid_end(self):
        rig, results = self.run_guard(
            [lina(1, "I live in Berlin."), lina(2, "Since March 2023 I live in Munich.")],
            [{"claims": [claim(1, "Lina", "livesIn", "Berlin")], "stances": []},
             {"claims": [claim(1, "Lina", "livesIn", "Munich", valid_from="2023-03-01")],
              "stances": []}])
        sup = rig.store.changeset(2).supersessions
        self.assertEqual(len(sup), 1)
        self.assertEqual((sup[0].kind, sup[0].valid_end), (SupersessionKind.CHANGE,
                                                           "2023-03-01"))
        state = rig.store.state(2)
        self.assertEqual(state.claims[sup[0].replacing_claim_id].object, Entity("Munich"))
        self.assertEqual(results[1].conflicts, [])

    def test_quote_and_other_speaker_keep_both(self):
        rig, results = self.run_guard(
            [lina(1, "I live in Berlin."),
             lina(2, "My sister says I live in Munich now, which is wrong."),
             lina(3, "You live in Hamburg, right?", speaker="assistant")],
            [{"claims": [claim(1, "Lina", "livesIn", "Berlin")], "stances": []},
             {"claims": [claim(1, "Lina", "livesIn", "Munich", report_mode="quote")],
              "stances": []},
             {"claims": [claim(1, "Lina", "livesIn", "Hamburg")], "stances": []}])
        state = rig.store.state(3)
        self.assertEqual(state.supersessions, {})
        self.assertEqual(len(state.claims), 3)
        self.assertEqual([c["reason"] for r in results for c in r.conflicts],
                         ["report_mode", "speaker_or_function", "speaker_or_function"])

    def test_removal_and_its_guard(self):
        rig, results = self.run_guard(
            [lina(1, "I play the violin and the cello."),
             lina(2, "You don't play the cello any more, do you?", speaker="assistant"),
             lina(3, "Right, I stopped playing the violin in June 2023.")],
            [{"claims": [claim(1, "Lina", "playsInstrument", "violin", id="n1"),
                         claim(1, "Lina", "playsInstrument", "cello")], "stances": []},
             lambda p: {"claims": [], "stances": [
                 {"message": 1, "claim": _handle(p, "cello"), "function": "inform",
                  "polarity": "negative", "ends": "change",
                  "quote": "You don't play the cello any more"}]},
             lambda p: {"claims": [], "stances": [
                 {"message": 1, "claim": _handle(p, "violin"), "function": "inform",
                  "polarity": "negative", "ends": "change", "valid_until": "2023-06-01",
                  "quote": "I stopped playing the violin"}]}])
        self.assertEqual(rig.store.changeset(2).supersessions, ())
        self.assertEqual(results[1].blocked[0]["reason"], "speaker_or_function")
        sup = rig.store.changeset(3).supersessions
        self.assertEqual([(s.replacing_claim_id, s.valid_end) for s in sup], [(None, "2023-06-01")])

    def test_ending_needs_a_quote_that_mentions_the_claim(self):
        """User decision of 2026-11-26 (D010 evidence): G2(ii) alone let one message end ten
        unrelated claims of its speaker; the writer now drops an ending stance whose quote does
        not mention the claim's object."""
        rig, results = self.run_guard(
            [lina(1, "I play the violin, I have a dog called Rex and I live in Berlin."),
             lina(2, "Well, that chapter of my life is over. I stopped playing the violin.")],
            [{"claims": [claim(1, "Lina", "playsInstrument", "violin"),
                         claim(1, "Lina", "hasPet", "Rex"),
                         claim(1, "Lina", "livesIn", "Berlin")], "stances": []},
             lambda p: {"claims": [], "stances": [
                 {"message": 1, "claim": _handle(p, "violin"), "function": "inform",
                  "polarity": "negative", "ends": "change",
                  "quote": "I stopped playing the violin"},
                 {"message": 1, "claim": handle_of(p, "hasPet | Rex"), "function": "inform",
                  "polarity": "negative", "ends": "change",
                  "quote": "that chapter of my life is over"},
                 {"message": 1, "claim": handle_of(p, "livesIn | Berlin"), "function": "inform",
                  "polarity": "negative", "ends": "change"}]}])
        state = rig.store.state(2)
        ended = sorted(state.claims[s.claim_id].object.id for s in state.supersessions.values())
        self.assertEqual(ended, ["violin"])
        self.assertEqual(sorted(d.reason for d in results[1].dropped),
                         ["ended_without_evidence", "ended_without_quote"])
        self.assertEqual(results[1].notes["ending_dropped"], 2)
        # a dropped stance leaves no attribution either
        self.assertEqual(len(rig.store.changeset(2).attributions), 1)

    def test_correction_and_no_guard_variant(self):
        script = [{"claims": [claim(1, "request1", "arriveBy", "20:15", object_type="time",
                                    function="request")], "stances": []},
                  {"claims": [claim(1, "request1", "arriveBy", "20:38", object_type="time",
                                    function="offer")], "stances": []},
                  {"claims": [claim(1, "request1", "arriveBy", "21:15", object_type="time",
                                    function="request", correction=True)], "stances": []}]
        msgs = [lina(1, "Arrive by 20:15 please."), lina(2, "TR1 arrives 20:38.", "system"),
                lina(3, "Sorry, I meant 21:15.")]
        rig, _ = self.run_guard(msgs, [dict(x) for x in script])
        state = rig.store.state(3)
        kinds = sorted((s.kind.value, state.claims[s.claim_id].object.lexical)
                       for s in state.supersessions.values())
        self.assertEqual(kinds, [("correction", "20:15:00")])   # the offer 20:38 survives
        rig2, _ = self.run_guard(msgs, [dict(x) for x in script], guard=False)
        state2 = rig2.store.state(3)
        superseded = sorted(state2.claims[s.claim_id].object.lexical
                            for s in state2.supersessions.values())
        self.assertEqual(superseded, ["20:15:00", "20:38:00"])  # latest value wins


def _handle(prompt: str, word: str) -> str:
    from tests.integration.writer_fixture import handle_of
    return handle_of(prompt, f"playsInstrument | {word}")


class LedgerTest(RigTest):
    """Every call, retry and failure is in the cost ledger with its true status."""

    def assert_ledger_matches(self, rig, results):
        calls = read_calls(rig.ledger.path)
        listed = [c for r in results for c in r.call_ids]
        self.assertEqual(sorted(listed), sorted(c.call_id for c in calls))
        statuses = {c.call_id: c.status for c in calls}
        for r in results:
            self.assertEqual(list(r.call_statuses), [statuses[c] for c in r.call_ids])
        self.assertTrue(all(c.call_type == "extract" and c.category == "W" for c in calls))
        return calls

    def test_invalid_output_splits_the_unit(self):
        rig = self.rig(melanie_messages(), [
            {"claims": [], "stances": []},                                     # session 1
            '```json\n{"claims": [], "stances": []}\n```\nHope this helps!',  # trailing text
            {"claims": [claim(2, "Melanie", "playsInstrument", "clarinet")],
             "stances": []},                                                   # m2, m3
            {"claims": [], "stances": []}], dates=MELANIE_DATES)               # m4
        results = rig.write_all()
        self.assertEqual([r.status for r in results], ["ok", "split", "ok", "ok"])
        calls = self.assert_ledger_matches(rig, results)
        self.assertEqual([c.status for c in calls], ["ok", "invalid_output", "ok", "ok"])
        self.assertEqual(rig.store.versions(), (1, 2, 3, 4))
        self.assertIn("not a single JSON value", results[1].error)
        clarinet = next(iter(rig.store.state(4).claims.values()))
        self.assertEqual(clarinet.version, 3)

    def test_unusable_output_of_one_message_commits_empty(self):
        cfg = replace(WriterConfig(), granularity=Granularity("message", None))
        rig = self.rig([lina(1, "I live in Berlin.")],
                       ['{"claims": [{"message": 1, "subject": "Lina", "predic'], config=cfg)
        results = rig.write_all()
        self.assertEqual([r.status for r in results], ["invalid_output"])
        calls = self.assert_ledger_matches(rig, results)
        self.assertEqual([c.status for c in calls], ["invalid_output"])
        self.assertTrue(rig.store.changeset(1).empty)       # version committed, nothing in it
        self.assertEqual(rig.log.head, 1)                   # the raw text stays

    def test_structural_fault_is_invalid_output(self):
        cfg = replace(WriterConfig(), granularity=Granularity("message", None))
        rig = self.rig([lina(1, "I live in Berlin.")],
                       [{"claims": [claim(4, "Lina", "livesIn", "Berlin")], "stances": []}],
                       config=cfg)
        results = rig.write_all()
        self.assertEqual(results[0].status, "invalid_output")
        self.assertIn("outside 1..1", results[0].error)
        self.assertEqual([c.status for c in self.assert_ledger_matches(rig, results)],
                         ["invalid_output"])

    def test_failed_calls_are_retried_and_finally_given_up(self):
        cfg = replace(WriterConfig(), granularity=Granularity("message", None),
                      max_unit_failures=2)
        down = urllib.error.URLError("connection refused")
        rig = self.rig([lina(1, "I live in Berlin."), lina(2, "I like tea.")],
                       [down, down,                                   # write(m1): 2 attempts
                        {"claims": [claim(1, "Lina", "livesIn", "Berlin")], "stances": []},
                        {"claims": [], "stances": []},                 # write(m2): m1 retried
                        ], config=cfg, max_attempts=2)
        first = rig.updater.write(rig.messages[0])
        self.assertEqual([r.status for r in first], ["failed"])
        self.assertEqual(rig.store.head, 0)                # nothing committed, m1 still pending
        second = rig.updater.write(rig.messages[1])
        self.assertEqual([r.status for r in second], ["ok", "ok"])
        calls = self.assert_ledger_matches(rig, first + second)
        self.assertEqual([(c.status, c.attempt) for c in calls],
                         [("failed", 1), ("failed", 2), ("ok", 1), ("ok", 1)])

        rig2 = self.rig([lina(1, "I live in Berlin.")], [down] * 4, config=cfg, max_attempts=2)
        results = rig2.updater.write(rig2.messages[0]) + rig2.updater.finish()
        self.assertEqual([r.status for r in results], ["failed", "failed_final"])
        self.assertTrue(rig2.store.changeset(1).empty)
        calls = self.assert_ledger_matches(rig2, results)
        self.assertEqual([c.status for c in calls], ["failed"] * 4)

    def test_response_format_carries_the_schema(self):
        rig = self.rig(melanie_messages(), MELANIE_SCRIPT, dates=MELANIE_DATES)
        rig.write_all()
        payload = rig.transport.requests[0]
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertIn("claims", payload["response_format"]["json_schema"]["schema"]["properties"])
        system = payload["messages"][0]["content"]
        self.assertTrue(all(r["messages"][0]["content"] == system
                            for r in rig.transport.requests))     # fixed, cacheable prefix
        user = rig.transport.requests[1]["messages"][-1]["content"]
        self.assertIn("[1] Caroline (2023-08-28): That sounds lovely.", user)
        self.assertIn("Melanie | playsInstrument | violin", user)   # known claim with a handle

        rig2 = self.rig(melanie_messages(), MELANIE_SCRIPT, dates=MELANIE_DATES,
                        config=replace(WriterConfig(), structured_output="none"))
        rig2.write_all()
        self.assertNotIn("response_format", rig2.transport.requests[0])


class VocabularyAndEntityTest(RigTest):
    def test_new_predicate_and_vocabulary_version(self):
        cfg = replace(WriterConfig(), granularity=Granularity("message", None))
        script = [{"claims": [claim(1, "Lina", "livesIn", "Berlin")], "stances": []},
                  {"claims": [claim(1, "Lina", "has pet", "dog", exclusive=False)],
                   "stances": []},
                  {"claims": [claim(1, "Lina", "hasPet", "cat")], "stances": []}]
        msgs = [lina(1, "I live in Berlin."), lina(2, "I have a dog."), lina(3, "And a cat.")]
        rig = self.rig(msgs, [dict(x) for x in script], config=cfg)
        rig.write_all()
        labels = [rig.store.changeset(v).vocabulary_version for v in (1, 2, 3)]
        self.assertEqual(labels, ["v1", "v1+1", "v1+1"])
        state = rig.store.state(3)
        self.assertEqual(sorted(c.predicate for c in state.claims.values()),
                         ["hasPet", "hasPet", "livesIn"])
        self.assertEqual(state.supersessions, {})          # multi-valued: dog and cat coexist

        rig2 = self.rig(msgs, [dict(x) for x in script],
                        config=replace(cfg, unknown_predicates="drop"))
        results = rig2.write_all()
        self.assertEqual([d.reason for r in results for d in r.dropped],
                         ["unknown_predicate", "unknown_predicate"])

    def test_entity_alignment_appends_equivalence(self):
        cfg = replace(WriterConfig(), granularity=Granularity("message", None))
        h = "t022-alias"
        msgs = [message(h, 1, "Caroline", "Melanie plays the violin."),
                message(h, 2, "Caroline", "Mel, as we call Melanie, plays the violin so well.")]
        script = [{"claims": [claim(1, "Melanie", "playsInstrument", "violin")], "stances": []},
                  {"claims": [claim(1, "Mel", "playsInstrument", "violin")], "stances": [],
                   "same_as": [{"message": 1, "name": "Mel", "same_as": "Melanie"}]}]
        rig = self.rig(msgs, script, config=cfg)
        rig.write_all()
        cs2 = rig.store.changeset(2)
        self.assertEqual([(q.entity_a, q.entity_b) for q in cs2.entity_merges],
                         [("Mel", "Melanie")])
        # the mention under the alias is a repeated mention of Melanie's claim
        self.assertEqual(cs2.claims, ())
        (first,) = rig.store.changeset(1).claims
        self.assertEqual([a.claim_id for a in cs2.attributions], [first.claim_id])

    def test_item_drops_keep_the_rest(self):
        cfg = replace(WriterConfig(), granularity=Granularity("message", None))
        rig = self.rig([lina(1, "I live in Berlin.")], [{"claims": [
            claim(1, "Lina", "livesIn", "Berlin", quote="I live in Rome"),
            claim(1, "Lina", "age", "thirty", object_type="integer")],
            "stances": [{"message": 1, "claim": "k9", "function": "accept"}]}], config=cfg)
        results = rig.write_all()
        self.assertEqual(results[0].status, "ok")
        self.assertEqual(sorted(d.reason for d in results[0].dropped),
                         ["bad_object", "unknown_handle"])
        self.assertEqual(results[0].notes["quote_not_found"], 1)
        (claim_,) = rig.store.state(1).claims.values()
        self.assertIsNone(rig.store.state(1).evidence_for(claim_.claim_id)[0].span)



class EntityIdTest(RigTest):
    """Entity IDs are bare names of the query IR grammar; the surface name is the label."""

    MESSAGES = [message("t022-ids", 1, "Caroline", "Caroline's mom lives in Sweden."),
                message("t022-ids", 2, "Caroline", "My mom\u2019s still in Sweden, she loves it."),
                message("t022-ids", 3, "Caroline", "Carolines mom is a band; José plays in it.")]
    SCRIPT = [
        {"claims": [claim(1, "Caroline's mom", "livesIn", "Sweden",
                          quote="Caroline's mom lives in Sweden")], "stances": []},
        {"claims": [claim(1, "Caroline\u2019s  mom", "livesIn", "Sweden")], "stances": []},
        {"claims": [claim(1, "Carolines mom", "hasMember", "José"),
                    claim(1, "true", "isA", "band")], "stances": []}]

    def write(self):
        cfg = replace(WriterConfig(), granularity=Granularity("message", None))
        rig = self.rig(self.MESSAGES, [dict(x) for x in self.SCRIPT], config=cfg)
        return rig, rig.write_all()

    def test_ids_are_safe_deterministic_and_collision_free(self):
        rig, results = self.write()
        state = rig.store.state(3)
        subjects = sorted({c.subject for c in state.claims.values()})
        self.assertEqual(subjects, ["Carolines_mom", "Carolines_mom_2", "e_true"])
        objects = sorted(c.object.id for c in state.claims.values()
                         if isinstance(c.object, Entity))
        self.assertEqual(objects, ["Jose", "Sweden", "band"])
        # curly apostrophe and extra space: the same surface name, a repeated mention
        self.assertEqual(results[1].notes["repeated_mention"], 1)
        self.assertEqual(rig.updater.entity_labels,
                         {"Carolines_mom": "Caroline's mom", "Carolines_mom_2": "Carolines mom",
                          "Jose": "José", "e_true": "true"})
        self.assertEqual(results[0].notes["entity_id_normalised"], 1)
        self.assertEqual(results[2].notes["entity_id_normalised"], 3)
        # the same input gives the same IDs
        rig2, _ = self.write()
        self.assertEqual(sorted(rig2.store.state(3).claims), sorted(state.claims))
        self.assertEqual(rig2.updater.entity_labels, rig.updater.entity_labels)

    def test_labels_survive_save_and_restore(self):
        rig, _ = self.write()
        with tempfile.TemporaryDirectory() as tmp:
            rig.updater.save(Path(tmp))
            again = Updater(rig.info, rig.log, rig.store,
                            llm_writer(rig.config, rig.client, rig.info), rig.config)
            again.restore_state(Path(tmp))
        self.assertEqual(again.entity_labels, rig.updater.entity_labels)

    def test_ir_and_planner_parse_queries_naming_the_ids(self):
        import json

        from grace.context.pipeline.query.grammar import to_text
        from grace.context.pipeline.query.ir import QueryTypeError
        from grace.context.pipeline.query.planner import Planner, PlanningContext, run_plan
        from grace.eval.runner.probes.retrieval_recall import load_extracted_graphs
        from grace.llm.client import ChatClient, Endpoint
        from grace.llm.records import CallLedger
        from tests.llm.fakes import WordCounter

        rig, _ = self.write()
        with self.assertRaises(QueryTypeError):   # the raw surface name is not in the grammar
            parse("SELECT ?x WHERE { (Caroline's mom, livesIn, ?x) }")
        for entity in rig.updater.entity_labels:
            query = parse(f"SELECT ?x WHERE {{ ({entity}, ?p, ?x) }}")
            self.assertEqual(to_text(query).split("(")[1].split(",")[0], entity)  # bare name
        self.assertEqual(answers(rig.store, "SELECT ?x WHERE { (Carolines_mom, livesIn, ?x) }",
                                 3), {(Entity("Sweden"),)})
        self.assertEqual(answers(rig.store, "SELECT ?s WHERE { (?s, hasMember, Jose) }", 3),
                         {(Entity("Carolines_mom_2"),)})

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "graphs" / rig.info.history_id
            rig.store.save(out / "store")
            rig.updater.save(out)
            graph = load_extracted_graphs(Path(tmp), [rig.info.history_id])[rig.info.history_id]
            predicates, entities = graph.fragment("Where does Caroline's mom live?")
            self.assertIn(("Carolines_mom", ("Caroline's mom",)),
                          [(e.id, e.names) for e in entities])
            ir = "SELECT ?x WHERE { (Carolines_mom, livesIn, ?x) [Caroline, inform] }"
            content = json.dumps({"ir": ir, "variables": [], "fallback_channels": ["bm25"]})
            replies = [{"choices": [{"message": {"content": content}}],
                        "usage": {"completion_tokens": 5}}]
            client = ChatClient(Endpoint("http://fake/v1", "m", "m@1"),
                                CallLedger(Path(tmp) / "calls.jsonl", "run-t"), WordCounter(),
                                transport=lambda *a: replies.pop(0), max_attempts=1,
                                sleep=lambda s: None)
            ctx = PlanningContext(rig.info.history_id, "q@3", 3,
                                  "Where does Caroline's mom live?", "2023-05-08", predicates,
                                  entities, graph.speakers)
            plan = Planner(client=client).plan(ctx)
        self.assertEqual((plan.route, plan.failure), ("llm", None))
        plan, result = run_plan(plan, rig.store, 3)
        self.assertEqual({a.values for a in result.answers}, {(Entity("Sweden"),)})

class CommitFallbackTest(RigTest):
    def test_rejected_change_set_commits_empty_and_later_versions_continue(self):
        cfg = replace(WriterConfig(), granularity=Granularity("segment", 2))
        rig = self.rig([lina(1, "I live in Berlin."), lina(2, "I like tea.")], [
            {"claims": [claim(1, "Lina", "livesIn", "Berlin", id="n1"),
                        claim(2, "Lina", "likes", "tea", object_type="string")],
             "stances": [{"message": 2, "claim": "n1", "function": "confirm"}]}], config=cfg)
        original = rig.store.commit
        calls = []

        def reject_first(cs, validate=False):
            calls.append(cs.version)
            if cs.version == 1 and not cs.empty:
                from grace.context.memory.graph.store import CommitError
                raise CommitError("simulated rejection")
            return original(cs, validate=validate)

        rig.store.commit = reject_first
        (result,) = rig.write_all()
        self.assertEqual(result.status, "ok")
        self.assertEqual([e["version"] for e in result.commit_errors], [1])
        self.assertTrue(rig.store.changeset(1).empty)
        cs2 = rig.store.changeset(2)
        self.assertEqual([c.predicate for c in cs2.claims], ["likes"])
        self.assertEqual(cs2.attributions[0].claim_id, cs2.claims[0].claim_id)
        self.assertEqual([d.reason for d in result.dropped], ["unresolved_local_id"])


class SaveRestoreTest(RigTest):
    def test_restore_resumes_pending_messages_and_vocabulary(self):
        rig = self.rig(train_messages(), TRAIN_SCRIPT)
        rig.write_all(upto=6)
        rig.updater.flush(6, read_id="r1")
        with tempfile.TemporaryDirectory() as tmp:
            rig.store.save(Path(tmp) / "graph")
            rig.log.save(Path(tmp) / "log")
            rig.updater.save(Path(tmp) / "writer")
            store = ClaimStore.restore(Path(tmp) / "graph")
            log = MessageLog.restore(Path(tmp) / "log", rig.info.history_id)
            updater = Updater(rig.info, log, store,
                              llm_writer(rig.config, rig.client, rig.info), rig.config)
            updater.restore_state(Path(tmp) / "writer")
        self.assertEqual(updater.head, 6)
        self.assertEqual(updater.pending(), [])
        results = updater.write(rig.messages[6])
        self.assertEqual([r.status for r in results], ["ok"])
        self.assertEqual(answers(store, CHOICE, 7), {(Entity("TR7143"),)})


if __name__ == "__main__":
    unittest.main()
