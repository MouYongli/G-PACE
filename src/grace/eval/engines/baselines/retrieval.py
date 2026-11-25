"""Text-retrieval baselines (plan 7.2): BM25, dense, and their RRF fusion.

Chunks are messages (`context/memory/index/chunking.py`), so every retrieved fragment cites one
`message_id`. Messages are embedded at write time (`embed`, trigger `write`) and the query at read
time (trigger `read`); both go to the `embedding` ledger. Candidates are ranked, the top `top_k`
are packed into the budget in rank order, and the kept fragments are shown in chronological order
(`order: chronological`) or rank order (`order: rank`).

Further retrieval: the request is searched like a question (another `top_k`), and its ranking is
fused by RRF with the ranking of the original query; the budget, not `top_k`, limits the union.
"""

from __future__ import annotations

from collections import defaultdict

from grace.context import api
from grace.context.memory.index.bm25 import BM25Index
from grace.context.memory.index.chunking import Chunk, chunk_message
from grace.context.memory.index.dense import DenseIndex
from grace.eval.engines.baselines.base import BaselineEngine, CallTag, query_text

CHANNELS = ("bm25", "dense", "rrf")


def rrf(rankings: list[list[Chunk]], k: int) -> list[tuple[Chunk, float]]:
    """Reciprocal rank fusion: score = sum 1 / (k + rank), rank from 1; ties by version."""
    scores: dict[str, float] = defaultdict(float)
    chunks: dict[str, Chunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            scores[chunk.chunk_id] += 1.0 / (k + rank)
            chunks[chunk.chunk_id] = chunk
    return sorted(((chunks[i], s) for i, s in scores.items()),
                  key=lambda item: (-item[1], item[0].version))


class Retrieval(BaselineEngine):
    kind = "retrieval"

    def __init__(self, model, *, channel: str, top_k: int = 20, rrf_k: int = 60,
                 bm25_k1: float = 1.5, bm25_b: float = 0.75, order: str = "chronological"):
        super().__init__(model)
        if channel not in CHANNELS:
            raise ValueError(f"channel {channel!r} not in {CHANNELS}")
        if order not in ("chronological", "rank"):
            raise ValueError(f"order {order!r} must be chronological or rank")
        self.channel, self.top_k, self.rrf_k, self.order = channel, top_k, rrf_k, order
        self.bm25 = BM25Index(bm25_k1, bm25_b) if channel in ("bm25", "rrf") else None
        self.dense = DenseIndex() if channel in ("dense", "rrf") else None

    def _on_write(self, message):
        call_ids: list[str] = []
        chunks = chunk_message(message)
        if self.bm25:
            for chunk in chunks:
                self.bm25.add(chunk)
        if self.dense:
            tag = CallTag("embed", "write", message.history_id, message.version)
            result = self.model.embed([c.text for c in chunks], tag)
            call_ids += result.call_ids
            for chunk, vector in zip(chunks, result.vectors, strict=True):
                self.dense.add(chunk, vector)
        return call_ids

    def _search(self, query: str, task: api.ReadTask):
        """Ranked chunks of the configured channel, every channel's candidates, call IDs."""
        candidates: list[api.Candidate] = []
        call_ids: list[str] = []
        rankings: list[list[Chunk]] = []
        if self.bm25:
            hits = self.bm25.search(query, task.version, self.top_k)
            candidates += [api.Candidate(c.chunk_id, "bm25", s) for c, s in hits]
            rankings.append([c for c, _ in hits])
        if self.dense:
            tag = CallTag("embed", "read", task.history_id, task.version, task.read_id)
            result = self.model.embed([query], tag)
            call_ids += result.call_ids
            hits = self.dense.search(result.vectors[0], task.version, self.top_k)
            candidates += [api.Candidate(c.chunk_id, "dense", s) for c, s in hits]
            rankings.append([c for c, _ in hits])
        if self.channel == "rrf":
            fused = rrf(rankings, self.rrf_k)[: self.top_k]
            candidates += [api.Candidate(c.chunk_id, "rrf", s) for c, s in fused]
            return [c for c, _ in fused], candidates, call_ids
        return rankings[0], candidates, call_ids

    def _build(self, task, budget, request):
        ranked, candidates, call_ids = self._search(query_text(task, self.messages), task)
        if request is not None:
            extra, more, more_ids = self._search(request, task)
            ranked = [c for c, _ in rrf([ranked, extra], self.rrf_k)]
            candidates += more
            call_ids += more_ids
        by_id = {m.message_id: m for m in self.messages}
        packer = self._packer()
        fragments = [self._message_fragment(packer, by_id[c.chunk_id], kind="retrieved")
                     for c in ranked]
        rank = {f.fragment_id: i for i, f in enumerate(fragments)}
        order = (lambda f: by_id[f.fragment_id].version) if self.order == "chronological" else (
            lambda f: rank[f.fragment_id])
        return packer.pack(task, budget, fragments, order=order), candidates, call_ids

    def _state(self):
        return {"vectors": self.dense.vectors() if self.dense else None}

    def _load_state(self, state):
        vectors = state["vectors"]
        for i, message in enumerate(self.messages):
            for chunk in chunk_message(message):
                if self.bm25:
                    self.bm25.add(chunk)
                if self.dense:
                    self.dense.add(chunk, vectors[i])
