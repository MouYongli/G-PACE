"""Retrieval channels, routing and fusion (T025): unified IDs, RRF and weighted fusion, routing
signals, and channel switches with the total number of candidates held fixed."""

from __future__ import annotations

import hashlib
import itertools
import unittest
from dataclasses import dataclass, replace

from grace.config.paths import REPO_ROOT
from grace.context.api import Message
from grace.context.memory.history.spans import message_of
from grace.context.memory.index.bm25 import BM25Index
from grace.context.memory.index.chunking import Chunk, chunk_message, tokenize
from grace.context.memory.index.dense import DenseIndex
from grace.context.pipeline.retrieval.candidates import (
    CHANNELS,
    RetrievalCandidate,
    message_id_of,
    ranked,
)
from grace.context.pipeline.retrieval.fuse import fuse, rrf, weighted
from grace.context.pipeline.retrieval.graph import graph_candidates
from grace.context.pipeline.retrieval.retrieve import RetrievalConfig, Retriever
from grace.context.pipeline.retrieval.route import route, signals
from grace.context.pipeline.retrieval.text import BM25Channel, DenseChannel, instructed

DIM = 64


def fake_embed(text: str) -> list[float]:
    """Deterministic bag-of-words vector: hashed token counts."""
    v = [0.0] * DIM
    for token in tokenize(text):
        v[int(hashlib.sha256(token.encode()).hexdigest(), 16) % DIM] += 1.0
    return v


def message(i: int, text: str) -> Message:
    return Message(benchmark="t", split="dev", history_id="h", version=i, message_id=f"m{i}",
                   segment_id=None, speaker="user", role="user", text=text, timestamp=None,
                   timestamp_raw=None)


TEXTS = ["I booked the train AX-1043 to Bremen", "The hotel in Hamburg has a pool",
         "My sister lives in Munich", "We changed the train to the later one",
         "The museum opens at nine", "I like green tea in the morning",
         "The flight was cancelled yesterday", "Our budget is two hundred euros",
         "The car rental desk closes at six", "I prefer a window seat on trains",
         "Lunch was a vegetable soup", "The meeting moved to Thursday",
         "My dog is called Bruno", "I started learning Spanish", "The rent went up again",
         "Bremen has a lovely old town", "The concert starts at eight",
         "Please book a table for four", "The bike needs a new tyre",
         "We visited Hamburg last spring", "I read a novel about trains",
         "The garden needs water", "My phone battery died", "The bakery sells rye bread",
         "Grandma turns ninety in May"]


def build(texts=TEXTS):
    bm25, dense = BM25Index(), DenseIndex()
    for i, text in enumerate(texts, start=1):
        for chunk in chunk_message(message(i, text)):
            bm25.add(chunk)
            dense.add(chunk, fake_embed(chunk.text))
    return BM25Channel(bm25), DenseChannel(dense, fake_embed, "find it")


@dataclass
class _Answer:
    evidence: tuple[str, ...]


@dataclass
class _Result:
    answers: tuple[_Answer, ...]


def cand(eid, channel, rank, score=1.0):
    return RetrievalCandidate(eid, channel, rank, score)


class UnifiedIdTest(unittest.TestCase):
    def test_message_id_of_agrees_with_spans(self):
        for eid in ("D1:3", "m0004", "answer_355c48bb:4", "m7#char=0,12", "a#b#char=3,9",
                    "m1#char=x,2"):
            self.assertEqual(message_id_of(eid), message_of(eid), eid)

    def test_ranked_maps_spans_to_messages_and_deduplicates(self):
        out = ranked("graph", [(("m2#char=0,5", "m3"), 1.0), (("m2", "m4#char=1,2"), 0.5)], k=10)
        self.assertEqual([c.evidence_id for c in out], ["m2", "m3", "m4"])
        self.assertEqual([c.rank for c in out], [1, 2, 3])
        self.assertEqual(out[0].spans, ("m2#char=0,5",))
        self.assertEqual(out[2].score, 0.5)

    def test_ranked_cuts_at_k(self):
        out = ranked("bm25", [((f"m{i}",), 1.0 / i) for i in range(1, 9)], k=3)
        self.assertEqual([c.evidence_id for c in out], ["m1", "m2", "m3"])

    def test_multi_message_chunk_gives_one_candidate_per_message(self):
        index = BM25Index()
        index.add(Chunk("c1", ("m1", "m2"), 2, "alpha beta"))
        out = BM25Channel(index).search("alpha", 2, 5)
        self.assertEqual([(c.evidence_id, c.rank) for c in out], [("m1", 1), ("m2", 2)])

    def test_unknown_channel_rejected(self):
        with self.assertRaises(ValueError):
            RetrievalCandidate("m1", "rerank", 1, 1.0)


class FusionTest(unittest.TestCase):
    def test_rrf_scores(self):
        fused = rrf({"bm25": [cand("a", "bm25", 1), cand("b", "bm25", 2)],
                     "dense": [cand("b", "dense", 1), cand("c", "dense", 2)]}, k=60)
        scores = {c.evidence_id: c.score for c in fused}
        self.assertAlmostEqual(scores["b"], 1 / 62 + 1 / 61)
        self.assertAlmostEqual(scores["a"], 1 / 61)
        self.assertEqual([c.evidence_id for c in fused], ["b", "a", "c"])
        self.assertEqual(fused[0].ranks, (("bm25", 2), ("dense", 1)))

    def test_rrf_ties_are_deterministic(self):
        rankings = {"dense": [cand("x", "dense", 1)], "bm25": [cand("y", "bm25", 1)]}
        self.assertEqual([c.evidence_id for c in rrf(rankings)], ["y", "x"])  # bm25 before dense

    def test_rrf_weights_and_total(self):
        rankings = {"bm25": [cand("a", "bm25", 1)], "graph": [cand("g", "graph", 1)]}
        fused = rrf(rankings, weights={"bm25": 1.0, "graph": 2.0}, total=1)
        self.assertEqual([c.evidence_id for c in fused], ["g"])

    def test_weighted_minmax(self):
        rankings = {"bm25": [cand("a", "bm25", 1, 10.0), cand("b", "bm25", 2, 5.0),
                             cand("c", "bm25", 3, 0.0)],
                    "dense": [cand("c", "dense", 1, 0.9), cand("a", "dense", 2, 0.1)]}
        fused = weighted(rankings, weights={"bm25": 1.0, "dense": 1.0})
        scores = {c.evidence_id: c.score for c in fused}
        self.assertAlmostEqual(scores["a"], 1.0 + 0.0)
        self.assertAlmostEqual(scores["c"], 0.0 + 1.0)
        self.assertAlmostEqual(scores["b"], 0.5)
        self.assertEqual([c.evidence_id for c in fused], ["a", "c", "b"])

    def test_weighted_constant_scores_give_one(self):
        fused = weighted({"graph": [cand("g1", "graph", 1), cand("g2", "graph", 2)]})
        self.assertEqual([c.score for c in fused], [1.0, 1.0])

    def test_duplicate_in_one_channel_rejected(self):
        with self.assertRaises(ValueError):
            rrf({"bm25": [cand("a", "bm25", 1), cand("a", "bm25", 2)]})

    def test_unknown_method(self):
        with self.assertRaises(ValueError):
            fuse("max", {}, total=3)


class RoutingTest(unittest.TestCase):
    ALL = CHANNELS

    def test_identifier_favours_bm25(self):
        r = route("Which seat did I get on AX-1043?", self.ALL)
        self.assertIn("identifier", r.signals)
        self.assertEqual(r.channels, ("bm25",))
        self.assertEqual(r.reason, "rules")

    def test_time_and_paraphrase(self):
        r = route("When did Caroline go to the support group?", self.ALL)
        self.assertEqual(r.channels, ("dense", "graph"))

    def test_correction_and_count(self):
        self.assertIn("correction", signals("Which hotel did I change to instead?"))
        self.assertIn("count", signals("How many languages does Jonas speak?"))

    def test_low_confidence_uses_all_channels(self):
        r = route("What is Melanie's favourite book?", self.ALL)
        self.assertEqual(r.confidence, 0)
        self.assertEqual((r.channels, r.reason), (self.ALL, "low_confidence"))

    def test_graph_unavailable_widens_or_narrows(self):
        r = route("When did Caroline go to the support group?", ("bm25", "dense"))
        self.assertEqual(r.channels, ("dense",))

    def test_graph_alone_is_widened(self):
        r = route("How many trains are booked for ticket #A7?", ("dense", "graph"))
        # identifier favours bm25, which is off; the graph alone is widened to all available.
        self.assertEqual((r.channels, r.reason), (("dense", "graph"), "widened"))

    def test_mode_all(self):
        r = route("Which seat on AX-1043?", ("bm25", "dense"), mode="all")
        self.assertEqual((r.channels, r.reason), (("bm25", "dense"), "all_channels"))

    def test_unknown_inputs(self):
        with self.assertRaises(ValueError):
            route("q", ("bm25", "web"))
        with self.assertRaises(ValueError):
            route("q", ("bm25",), mode="smart")


class GraphChannelTest(unittest.TestCase):
    def test_newest_first_and_deduplicated(self):
        result = _Result((_Answer(("m2", "m5#char=0,4")), _Answer(("m5", "m9"))))
        out = graph_candidates(result, 10, version_of=lambda m: int(m[1:]))
        self.assertEqual([c.evidence_id for c in out], ["m9", "m5", "m2"])
        self.assertTrue(all(c.channel == "graph" and c.score == 1.0 for c in out))

    def test_none_result(self):
        self.assertEqual(graph_candidates(None, 5), [])


class TextChannelTest(unittest.TestCase):
    def test_dense_uses_query_instruction(self):
        seen = []
        bm25, dense = build()
        channel = DenseChannel(dense.index, lambda t: seen.append(t) or fake_embed(t), "find it")
        channel.search("train", 25, 3)
        self.assertEqual(seen, [instructed("train", "find it")])
        self.assertEqual(seen[0], "Instruct: find it\nQuery: train")

    def test_version_cut_off(self):
        bm25, dense = build()
        for channel in (bm25, dense):
            out = channel.search("Bremen train", 3, 10)
            self.assertTrue(out)
            self.assertTrue(all(int(c.evidence_id[1:]) <= 3 for c in out))

    def test_dense_before_first_message(self):
        _, dense = build()
        calls = []
        channel = DenseChannel(dense.index, lambda t: calls.append(t) or fake_embed(t))
        self.assertEqual(channel.search("x", 0, 5), [])
        self.assertEqual(calls, [])


class ChannelSwitchTest(unittest.TestCase):
    """Ablation D: every channel can be switched off and the total stays fixed."""

    QUESTION = "What did we do about the train?"  # low confidence: all available channels
    GRAPH = _Result((_Answer(("m4",)), _Answer(("m1#char=0,10",))))

    def setUp(self):
        self.bm25, self.dense = build()
        self.base = RetrievalConfig(total=6, depth=8, routing="all")

    def run_config(self, config, graph=GRAPH):
        retriever = Retriever(config, bm25=self.bm25 if "bm25" in config.channels else None,
                              dense=self.dense if "dense" in config.channels else None)
        return retriever.retrieve(self.QUESTION, 25, graph_result=graph,
                                  version_of=lambda m: int(m[1:]))

    def test_every_channel_subset_keeps_total(self):
        for n in (1, 2, 3):
            for channels in itertools.combinations(CHANNELS, n):
                if channels == ("graph",):
                    continue  # the graph alone cannot fill the list; covered below
                with self.subTest(channels=channels):
                    result = self.run_config(replace(self.base, channels=channels))
                    self.assertEqual(len(result.fused), self.base.total)
                    self.assertEqual(set(result.rankings), set(channels))
                    used = {ch for c in result.fused for ch in c.channels}
                    self.assertLessEqual(used, set(channels))
                    self.assertEqual(len(set(result.evidence_ids)), len(result.fused))

    def test_without_removes_channel_and_keeps_total(self):
        full = self.run_config(self.base)
        self.assertEqual(set(full.rankings), set(CHANNELS))
        self.assertIn("m4", full.evidence_ids)
        for channel in CHANNELS:
            with self.subTest(off=channel):
                config = self.base.without(channel)
                self.assertNotIn(channel, config.channels)
                self.assertEqual(config.total, self.base.total)
                result = self.run_config(config)
                self.assertNotIn(channel, result.rankings)
                self.assertEqual(len(result.fused), self.base.total)
        with self.assertRaises(ValueError):
            self.base.only("bm25").without("bm25")

    def test_graph_skipped_without_query_result(self):
        result = self.run_config(self.base, graph=None)
        self.assertNotIn("graph", result.rankings)
        self.assertEqual(len(result.fused), self.base.total)

    def test_graph_only_returns_what_it_has(self):
        result = self.run_config(self.base.only("graph"))
        self.assertEqual(result.evidence_ids, ("m4", "m1"))

    def test_backfill_from_other_channels(self):
        config = replace(self.base, routing="rules", channels=("bm25", "dense"))
        retriever = Retriever(config, bm25=self.bm25, dense=self.dense)
        # identifier signal -> bm25 only; BM25 matches few messages, dense fills the list.
        result = retriever.retrieve("Is AX-1043 on time?", 25)
        self.assertEqual(result.route.channels, ("bm25",))
        self.assertEqual(result.backfilled, ("dense",))
        self.assertEqual(len(result.fused), config.total)
        self.assertEqual(result.fused[0].evidence_id, "m1")
        no_fill = Retriever(replace(config, backfill=False), bm25=self.bm25, dense=self.dense)
        self.assertLess(len(no_fill.retrieve("Is AX-1043 on time?", 25).fused), config.total)

    def test_precomputed_rankings_match_search(self):
        retriever = Retriever(self.base, bm25=self.bm25, dense=self.dense)
        direct = retriever.retrieve(self.QUESTION, 25, graph_result=self.GRAPH)
        deep = {"bm25": tuple(self.bm25.search(self.QUESTION, 25, 50)),
                "dense": tuple(self.dense.search(self.QUESTION, 25, 50))}
        cached = retriever.retrieve(self.QUESTION, 25, graph_result=self.GRAPH, rankings=deep)
        self.assertEqual(direct.fused, cached.fused)

    def test_trace_candidates(self):
        result = self.run_config(self.base)
        trace = result.trace_candidates()
        self.assertEqual(sum(c.channel == "fused" for c in trace), self.base.total)
        self.assertTrue({c.channel for c in trace} <= {*CHANNELS, "fused"})

    def test_enabled_channel_needs_index(self):
        with self.assertRaises(ValueError):
            Retriever(self.base, bm25=self.bm25)


class ConfigTest(unittest.TestCase):
    def test_default_config_loads(self):
        config = RetrievalConfig.load(REPO_ROOT / "configs" / "retrieval" / "default.yaml")
        self.assertEqual(config.channels, CHANNELS)
        self.assertEqual(config.fusion, "rrf")
        self.assertGreaterEqual(config.depth, config.total)
        self.assertEqual(RetrievalConfig.from_dict(config.to_record()), config)

    def test_invalid_configs(self):
        for bad in ({"version": 1, "total": 10, "depth": 5}, {"version": 1, "channels": []},
                    {"version": 1, "channels": ["bm25", "bm25"]}, {"version": 1, "fusion": "x"},
                    {"version": 1, "routing": "x"}, {"version": 1, "weights": {"bm25": -1}},
                    {"version": 1, "extra": 1}, {"version": 2}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                RetrievalConfig.from_dict(bad)


if __name__ == "__main__":
    unittest.main()
