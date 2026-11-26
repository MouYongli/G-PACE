"""Pure logic of the writer package (T022): granularity, patch parsing, guard, value checks."""

from __future__ import annotations

import re
import unittest

from grace.context.api import HistoryInfo, Message, Segment
from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entries import (
    Attribution,
    Certainty,
    Claim,
    CommunicativeFunction,
    Entity,
    EntryError,
    EvidenceLink,
    Polarity,
    ReportMode,
    SupersessionKind,
    ValidTime,
    Value,
)
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import load_vocabulary
from grace.context.pipeline.update.guard import Guard, Pending
from grace.context.pipeline.update.patch import parse_patch
from grace.context.pipeline.update.segment import Granularity, Segmenter, Unit
from grace.context.pipeline.update.validate import (
    EntityTable,
    LocalVocabulary,
    ending_evidence,
    entity_id,
    predicate_name,
    resolve_valid_time,
    resolve_value,
)
from grace.llm.structured import load_schema


def msg(v: int, session: str | None = "s1") -> Message:
    return Message("fixture", "dev", "h", v, f"m{v}", session, "user", "user", f"text {v}",
                   None, None)


def info(sessions: dict[str, tuple[int, int]], n: int) -> HistoryInfo:
    return HistoryInfo("fixture", "dev", "h", None, n,
                       tuple(Segment(s, a, b, None, None) for s, (a, b) in sessions.items()))


def versions(units) -> list[tuple[list[int], bool]]:
    return [([m.version for m in u.messages], u.partial) for u in units]


class SegmenterTest(unittest.TestCase):
    def test_segments_never_cross_sessions(self):
        messages = [msg(v, "s1") for v in range(1, 11)] + [msg(v, "s2") for v in (11, 12)]
        seg = Segmenter(Granularity("segment", 4), info({"s1": (1, 10), "s2": (11, 14)}, 14))
        self.assertEqual(versions(seg.units(messages)),
                         [([1, 2, 3, 4], False), ([5, 6, 7, 8], False), ([9, 10], False)])
        self.assertEqual(versions(seg.units(messages, flush=True))[-1], ([11, 12], True))

    def test_session_closed_without_header(self):
        seg = Segmenter(Granularity("session", None))
        self.assertEqual(versions(seg.units([msg(1, "a"), msg(2, "a")])), [])
        self.assertEqual(versions(seg.units([msg(1, "a"), msg(2, "a"), msg(3, "b")])),
                         [([1, 2], False)])

    def test_end_of_history_closes_and_message_granularity(self):
        seg = Segmenter(Granularity("segment", 8), info({"s1": (1, 3)}, 3))
        self.assertEqual(versions(seg.units([msg(1), msg(2)])), [])
        self.assertEqual(versions(seg.units([msg(1), msg(2), msg(3)])), [([1, 2, 3], False)])
        seg = Segmenter(Granularity("message", None))
        self.assertEqual(versions(seg.units([msg(1), msg(2)])), [([1], False), ([2], False)])

    def test_granularity_records_and_split(self):
        self.assertEqual(Granularity.from_record("segment-16"), Granularity("segment", 16))
        self.assertEqual(Granularity.from_record({"unit": "session"}).name, "session")
        with self.assertRaises(ValueError):
            Granularity("segment", 0)
        with self.assertRaises(ValueError):
            Granularity("session", 4)
        a, b = Unit(tuple(msg(v) for v in (1, 2, 3))).split()
        self.assertEqual(([m.version for m in a.messages], [m.version for m in b.messages]),
                         ([1, 2], [3]))
        with self.assertRaises(ValueError):
            Unit((msg(1), msg(3)))


class PatchTest(unittest.TestCase):
    validator = load_schema("extract-claims")

    def test_usable_and_unusable_outputs(self):
        ok = '{"claims": [{"message": 1, "subject": "A", "predicate": "p", "object": "o"}],' \
             ' "stances": [{"message": 1, "claim": "k1", "function": "accept"}]}'
        patch, error = parse_patch(ok, self.validator, 1)
        self.assertIsNone(error)
        self.assertEqual(patch.claims[0].stance.function, "inform")   # defaults
        self.assertEqual(patch.claims[0].object_type, "entity")
        cases = {
            '{"claims": []}': "schema violation",                       # stances missing
            '{"claims": [], "stances": [], "extra": 1}': "schema violation",
            '{"claims": [], "stances": []} trailing': "not a single JSON value",
            '{"claims": [{"message": 2, "subject": "A", "predicate": "p", "object": "o"}], '
            '"stances": []}': "outside 1..1",
            '{"claims": [], "stances": [{"message": 1, "claim": "c7", "function": "accept"}]}':
                "neither a known handle",
            '{"claims": [{"id": "n1", "message": 1, "subject": "A", "predicate": "p", '
            '"object": "o"}, {"id": "n1", "message": 1, "subject": "B", "predicate": "p", '
            '"object": "o"}], "stances": []}': "duplicate id",
            '{"claims": [{"message": 1, "subject": "  ", "predicate": "p", "object": "o"}], '
            '"stances": []}': "subject is empty",
            "": "empty output",
        }
        for text, reason in cases.items():
            with self.subTest(text=text):
                patch, error = parse_patch(text, self.validator, 1)
                self.assertIsNone(patch)
                self.assertIn(reason, error)

    def test_array_bounds_end_repetition_loops(self):
        """User decision of 2026-11-26: at most 32 claims, 16 stances and 8 same_as entries."""
        import json

        item = {"message": 1, "subject": "A", "predicate": "p", "object": "o"}
        stance = {"message": 1, "claim": "k1", "function": "confirm"}
        alias = {"message": 1, "name": "A", "same_as": "B"}
        for claims, stances, aliases, ok in ((32, 16, 8, True), (33, 0, 0, False),
                                             (0, 17, 0, False), (0, 0, 9, False)):
            text = json.dumps({"claims": [item] * claims, "stances": [stance] * stances,
                               "same_as": [alias] * aliases})
            with self.subTest(claims=claims, stances=stances, aliases=aliases):
                patch, error = parse_patch(text, self.validator, 1)
                self.assertEqual(patch is not None, ok, error)
        schema = self.validator.schema["properties"]
        self.assertEqual([schema[k]["maxItems"] for k in ("claims", "stances", "same_as")],
                         [32, 16, 8])


class ValueTest(unittest.TestCase):
    def test_literals_and_times(self):
        self.assertEqual(resolve_value("20:45", "time").lexical, "20:45:00")
        self.assertEqual(resolve_value("+1,200", "integer").lexical, "1200")
        self.assertEqual(resolve_value("True", "boolean").lexical, "true")
        with self.assertRaises(EntryError):
            resolve_value("thirty", "integer")
        vt, note = resolve_valid_time("2023-03-01", None, None)
        self.assertEqual((vt.start, note), ("2023-03-01", None))
        vt, note = resolve_valid_time("March 2023", None, None)
        self.assertEqual((vt.start, vt.expression), (None, "March 2023"))   # no invented date
        self.assertIsNotNone(note)
        vt, _ = resolve_valid_time("2023-05-01", "2023-01-01", "spring")
        self.assertEqual((vt.start, vt.end, vt.expression), (None, None, "spring"))

    def test_names_and_vocabulary(self):
        self.assertEqual(predicate_name("lives in"), "livesIn")
        self.assertEqual(predicate_name("hasPet"), "hasPet")
        self.assertEqual(predicate_name("2nd job"), "p2ndJob")
        table = EntityTable(["Melanie"])
        self.assertEqual(table.resolve("melanie"), "Melanie")
        self.assertEqual(table.resolve("  New   York "), "New_York")
        self.assertEqual(table.labels, {"New_York": "New York"})
        vocab = LocalVocabulary(load_vocabulary())
        self.assertEqual(vocab.resolve("no later than"), "arriveBy")   # alias
        self.assertIsNone(vocab.resolve("hasPet"))
        self.assertEqual(vocab.add("has pet", False, 3), "hasPet")
        self.assertEqual(vocab.version, "v1+1")
        self.assertFalse(vocab.is_exclusive("hasPet"))
        again = LocalVocabulary.from_record(load_vocabulary(), vocab.to_record())
        self.assertEqual(again.version, "v1+1")
        self.assertIsNone(LocalVocabulary(load_vocabulary(), "drop").add("hasPet", False, 1))


def att(aid, cid, v, speaker, fn, mode=ReportMode.OWN, polarity=Polarity.POSITIVE):
    return Attribution(aid, cid, speaker, CommunicativeFunction(fn), mode, polarity,
                       Certainty.CERTAIN, False, f"m{v}", v)


def store_with(*entries) -> ClaimStore:
    """One claim per (claim ID, subject, predicate, object, speaker, function, end) tuple, all
    at version 1."""
    claims, atts, evs = [], [], []
    for cid, s, p, o, speaker, fn, end in entries:
        claims.append(Claim(cid, s, p, Entity(o), None,
                            ValidTime("2010-01-01", end) if end else ValidTime(), 1))
        atts.append(att("a" + cid, cid, 1, speaker, fn))
        evs.append(EvidenceLink("e" + cid, cid, "m1", None, 1))
    store = ClaimStore("h")
    store.commit(ChangeSet("h", 1, tuple(claims), tuple(atts), tuple(evs)))
    return store


def new_claim(o, start=None, end=None):
    return Claim("cnew", "lina", "livesIn", Entity(o), None, ValidTime(start, end), 2)



class EntityIdTest(unittest.TestCase):
    NAME = re.compile(r"[A-Za-z0-9_]+")

    def test_base_ids(self):
        cases = {"Caroline's mom": "Carolines_mom", "Caroline\u2019s mom": "Carolines_mom",
                 "José": "Jose", "Rock & roll": "Rock_roll", "  New   York ": "New_York",
                 "2023": "e_2023", "2023 trip": "2023_trip", "true": "e_true", "R": "e_R",
                 "_": "entity", "!!!": "entity", "-x-": "x", "a/b (c)": "a_b_c",
                 "北京": "entity", "Ana-Maria": "Ana_Maria"}
        for name, expected in cases.items():
            self.assertEqual(entity_id(name), expected, name)

    def test_every_id_is_a_bare_ir_name(self):
        from grace.context.pipeline.query.grammar import parse, to_text
        table = EntityTable()
        names = ["Caroline's mom", "true", "2023", "x y", "x-y", "X Y", "a\"b", "<iri>",
                 "now()", "default", "?var", "{b}", "Mel", "mel", "ünïcödé"]
        ids = [table.resolve(n) for n in names]
        for entity in ids:
            self.assertRegex(entity, self.NAME)
            text = to_text(parse(f"SELECT ?o WHERE {{ ({entity}, likes, ?o) }}"))
            self.assertIn(f"({entity}, likes, ?o)", text)
        # "x y" and "x-y" are different surface names: different IDs, never merged
        self.assertEqual(ids[3:6], ["x_y", "x_y_2", "x_y"])   # "X Y" is "x y" up to case
        self.assertEqual(ids[12:14], ["Mel", "Mel"])
        self.assertEqual(table.labels["x_y"], "x y")
        self.assertEqual(table.labels["x_y_2"], "x-y")
        self.assertEqual(table.resolve("x_y"), "x_y")  # a name equal to a known ID is that ID

    def test_writer_may_write_the_id_or_the_label(self):
        table = EntityTable(labels={"Carolines_mom": "Caroline's mom"})
        for name in ("Carolines_mom", "carolines_mom", "caroline's MOM", "Caroline\u2019s mom"):
            self.assertEqual(table.resolve(name), "Carolines_mom", name)
        self.assertEqual(table.new_labels, {})


class EndingEvidenceTest(unittest.TestCase):
    def test_object_words_must_be_mentioned(self):
        violin = Entity("violin")
        self.assertIsNone(ending_evidence("playsInstrument", violin, "I stopped playing violins"))
        self.assertIsNone(ending_evidence("hasHobby", Entity("hiking"), "I don't hike any more"))
        self.assertEqual(ending_evidence("playsInstrument", violin, "I quit playing music"),
                         "ended_without_evidence")      # predicate words never suffice alone
        self.assertEqual(ending_evidence("playsInstrument", violin, None), "ended_without_quote")
        self.assertIsNone(ending_evidence("livesIn", Entity("New_York"), "we left New York"))
        self.assertIsNone(ending_evidence("hasPet", Entity("Carolines_dog"),
                                          "the dog died", "Caroline's dog"))
        self.assertEqual(ending_evidence("hasPlan", Value("go to the beach"),
                                         "I changed my plans"), "ended_without_evidence")
        self.assertIsNone(ending_evidence("hasPlan", Value("go to the beach"),
                                          "no beach for us this year"))

    def test_object_without_content_words_falls_back_to_the_predicate(self):
        self.assertIsNone(ending_evidence("ownsCar", Value("true", "boolean"),
                                          "I sold my car"))
        self.assertEqual(ending_evidence("hasExperienced", Value("ok"), "I experienced it"),
                         "ended_without_evidence")      # generic predicate words only
        self.assertIsNone(ending_evidence("age", Value("31", "integer"), "I'm not 31 anymore"))

class GuardTest(unittest.TestCase):
    def test_replacement_conditions(self):
        state = store_with(("c1", "lina", "livesIn", "Berlin", "user", "inform", None)).state(1)
        guard = Guard()
        cases = [
            (att("x", "cnew", 2, "user", "inform"), "supersede"),
            (att("x", "cnew", 2, "user", "inform", mode=ReportMode.QUOTE), "report_mode"),
            (att("x", "cnew", 2, "user", "inform", mode=ReportMode.HYPOTHETICAL), "report_mode"),
            (att("x", "cnew", 2, "assistant", "inform"), "speaker_or_function"),
            (att("x", "cnew", 2, "user", "request"), "speaker_or_function"),
            (att("x", "cnew", 2, "user", "inform", polarity=Polarity.NEGATIVE), "polarity"),
        ]
        for a, expected in cases:
            with self.subTest(a=a):
                d = guard.replacement(state, new_claim("Munich"), a, exclusive=True,
                                      correction=False)
                got = "supersede" if d.supersede else d.conflicts[0].reason
                self.assertEqual(got, expected)
        # not exclusive: neither supersession nor conflict
        d = guard.replacement(state, new_claim("Munich"), cases[0][0], exclusive=False,
                              correction=False)
        self.assertEqual((d.supersede, d.conflicts), ((), ()))
        # the no-guard variant ignores speaker, function and mode, not polarity
        d = Guard(enabled=False).replacement(state, new_claim("Munich"), cases[3][0],
                                             exclusive=True, correction=False)
        self.assertEqual(len(d.supersede), 1)

    def test_valid_end_kind_and_closed_intervals(self):
        state = store_with(("c1", "lina", "livesIn", "Berlin", "user", "inform", None),
                           ("c2", "lina", "livesIn", "Hamburg", "user", "inform",
                            "2015-01-01")).state(1)
        a = att("x", "cnew", 2, "user", "inform")
        d = Guard().replacement(state, new_claim("Munich", "2023-03-01"), a, exclusive=True,
                                correction=False)
        self.assertEqual([(s.claim_id, s.kind, s.valid_end) for s in d.supersede],
                         [("c1", SupersessionKind.CHANGE, "2023-03-01")])  # c2 is a past state
        d = Guard().replacement(state, new_claim("Munich", "2023-03-01"), a, exclusive=True,
                                correction=True)
        self.assertEqual([(s.kind, s.valid_end) for s in d.supersede],
                         [(SupersessionKind.CORRECTION, None)])
        d = Guard().replacement(state, new_claim("Kiel", "2000-01-01", "2001-01-01"), a,
                                exclusive=True, correction=False)
        self.assertEqual((d.supersede, d.conflicts), ((), ()))      # a closed past claim

    def test_pending_claims_and_representatives(self):
        state = store_with(("c1", "Mel", "livesIn", "Berlin", "Melanie", "inform", None)
                           ).state(1)
        a = att("x", "cnew", 2, "Melanie", "inform")
        claim = Claim("cnew", "Melanie", "livesIn", Entity("Munich"), None, ValidTime(), 2)
        d = Guard().replacement(state, claim, a, exclusive=True, correction=False)
        self.assertEqual(d.supersede, ())                           # Mel is not Melanie yet
        reps = {"Mel": "Mel", "Melanie": "Mel"}
        d = Guard().replacement(state, claim, a, exclusive=True, correction=False,
                                pending=Pending(reps=reps))
        self.assertEqual([s.claim_id for s in d.supersede], ["c1"])
        # a claim added earlier in the same change set is a candidate too
        pending = Pending()
        first = Claim("cp", "lina", "livesIn", Entity("Rome"), None, ValidTime(), 2)
        pending.add_claim(first)
        pending.add_attribution(att("ap", "cp", 2, "user", "inform"))
        d = Guard().replacement(state, new_claim("Oslo"), att("x", "cnew", 2, "user", "inform"),
                                exclusive=True, correction=False, pending=pending)
        self.assertEqual([s.claim_id for s in d.supersede], ["cp"])

    def test_removal(self):
        state = store_with(("c1", "lina", "playsInstrument", "violin", "user", "inform",
                            None)).state(1)
        neg = att("x", "c1", 2, "user", "inform", polarity=Polarity.NEGATIVE)
        d = Guard().removal(state, "c1", neg, kind=SupersessionKind.CHANGE,
                            valid_end="2023-06-01")
        self.assertEqual([(s.replacing_claim_id, s.valid_end) for s in d.supersede],
                         [(None, "2023-06-01")])
        d = Guard().removal(state, "c1", neg, kind=SupersessionKind.CORRECTION,
                            valid_end="2023-06-01")
        self.assertEqual(d.supersede[0].valid_end, None)            # a correction has no end
        for a, reason in [
            (att("x", "c1", 2, "user", "inform"), "polarity"),
            (att("x", "c1", 2, "assistant", "inform", polarity=Polarity.NEGATIVE),
             "speaker_or_function"),
            (att("x", "c1", 2, "user", "inform", mode=ReportMode.QUOTE,
                 polarity=Polarity.NEGATIVE), "report_mode"),
        ]:
            with self.subTest(reason=reason):
                d = Guard().removal(state, "c1", a, kind=SupersessionKind.CHANGE, valid_end=None)
                self.assertEqual((d.supersede, d.blocked), ((), reason))


if __name__ == "__main__":
    unittest.main()
