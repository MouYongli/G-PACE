"""Query-time conflict resolution of the append-only baseline (T027): the guard replayed at read."""

import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

from grace.context.memory.graph.entries import (
    Attribution,
    Certainty,
    Claim,
    CommunicativeFunction,
    Entity,
    Polarity,
    ReportMode,
    SupersessionKind,
    ValidTime,
)
from grace.context.memory.graph.store import GraphState
from grace.context.pipeline.update.deferred import ResolutionLog, resolve_at_read
from grace.context.pipeline.update.guard import Guard

F = CommunicativeFunction


def claim(cid, obj, version, predicate="livesIn", start=None):
    return Claim(cid, "Ana", predicate, Entity(obj), None, ValidTime(start), version)


def attribution(aid, cid, version, speaker="Ana", function=F.INFORM, mode=ReportMode.OWN,
                polarity=Polarity.POSITIVE):
    return Attribution(aid, cid, speaker, function, mode, polarity, Certainty.CERTAIN, False,
                       f"m{version}", version)


def state(claims, attributions, supersessions=()):
    empty = MappingProxyType({})
    return GraphState(max(a.version for a in attributions),
                      MappingProxyType({c.claim_id: c for c in claims}),
                      MappingProxyType({a.attribution_id: a for a in attributions}), empty,
                      MappingProxyType({s.supersession_id: s for s in supersessions}), empty)


class DeferredResolutionTest(unittest.TestCase):
    def setUp(self):
        self.claims = [claim("c1", "Lisbon", 1, start="2020-01-01"),
                       claim("c2", "Porto", 2, start="2024-03-01"),
                       claim("c3", "Faro", 3)]
        self.attributions = [attribution("a1", "c1", 1), attribution("a2", "c2", 2),
                             attribution("a3", "c3", 3, speaker="agent", function=F.OFFER),
                             attribution("a4", "c2", 4, polarity=Polarity.NEGATIVE)]
        self.log = ResolutionLog()
        for c in ("c1", "c2", "c3"):
            self.log.note_claim(c, exclusive=True)
        self.log.note_ending("a4", SupersessionKind.CHANGE, "2024-09-01")

    def current(self, resolution):
        return sorted(c for c in resolution.state.claims if resolution.state.is_current(c))

    def test_replacement_conflict_and_removal(self):
        result = resolve_at_read(state(self.claims, self.attributions), self.log, Guard())
        self.assertEqual(self.current(result), ["c3"])
        s1 = result.state.supersessions_of("c1")[0]
        self.assertEqual((s1.kind, s1.replacing_claim_id, s1.valid_end, s1.version),
                         (SupersessionKind.CHANGE, "c2", "2024-03-01", 2))
        self.assertEqual(result.conflicts[0]["reason"], "speaker_or_function")
        s2 = result.state.supersessions_of("c2")[0]
        self.assertEqual((s2.replacing_claim_id, s2.valid_end, s2.version),
                         (None, "2024-09-01", 4))

    def test_cut_off_and_no_guard(self):
        early = state(self.claims, self.attributions[:3])
        self.assertEqual(self.current(resolve_at_read(early, self.log, Guard())), ["c2", "c3"])
        self.assertEqual(self.current(resolve_at_read(early, self.log, Guard(enabled=False))),
                         ["c3"])

    def test_correction_and_non_exclusive(self):
        log = ResolutionLog()
        log.note_claim("c1", exclusive=True)
        log.note_claim("c2", exclusive=True, correction=True)
        result = resolve_at_read(state(self.claims[:2], self.attributions[:2]), log, Guard())
        self.assertTrue(result.state.is_corrected("c1"))
        plain = ResolutionLog()
        result = resolve_at_read(state(self.claims[:2], self.attributions[:2]), plain, Guard())
        self.assertEqual(self.current(result), ["c1", "c2"])

    def test_stored_supersessions_are_refused_and_log_round_trips(self):
        resolved = resolve_at_read(state(self.claims, self.attributions), self.log, Guard())
        with self.assertRaises(ValueError):
            resolve_at_read(resolved.state, self.log, Guard())
        with self.assertRaises(ValueError):
            self.log.note_claim("c1", exclusive=False)
        with tempfile.TemporaryDirectory() as tmp:
            self.log.save(Path(tmp))
            again = ResolutionLog.restore(Path(tmp))
        self.assertEqual(again, self.log)


if __name__ == "__main__":
    unittest.main()
