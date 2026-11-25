"""Okapi BM25 over chunks, append-only, searchable at a cut-off version.

Minimal first version written by T003 for the retrieval baselines (package owned by T025). Pure
Python and exact: document frequencies are recomputed for the chunks visible at the cut-off, so a
read at version r scores exactly as if only messages 1..r had been indexed.
"""

from __future__ import annotations

import math
from collections import Counter

from grace.context.memory.index.chunking import Chunk, tokenize


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.chunks: list[Chunk] = []
        self._terms: list[Counter] = []

    def add(self, chunk: Chunk) -> None:
        if self.chunks and chunk.version < self.chunks[-1].version:
            raise ValueError(f"chunk {chunk.chunk_id} added out of version order")
        self.chunks.append(chunk)
        self._terms.append(Counter(tokenize(chunk.text)))

    def search(self, query: str, version: int, k: int | None = None) -> list[tuple[Chunk, float]]:
        """Chunks with version <= `version` ranked by BM25 score (ties by version); score > 0."""
        visible = [i for i, c in enumerate(self.chunks) if c.version <= version]
        if not visible:
            return []
        n = len(visible)
        lengths = {i: sum(self._terms[i].values()) for i in visible}
        avgdl = sum(lengths.values()) / n or 1.0
        query_terms = tokenize(query)
        df = {t: sum(1 for i in visible if t in self._terms[i]) for t in set(query_terms)}
        scored = []
        for i in visible:
            terms, score = self._terms[i], 0.0
            for t in query_terms:
                tf = terms.get(t, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf * (self.k1 + 1) / (
                    tf + self.k1 * (1 - self.b + self.b * lengths[i] / avgdl))
            if score > 0:
                scored.append((self.chunks[i], score))
        scored.sort(key=lambda item: (-item[1], item[0].version))
        return scored[:k] if k is not None else scored

    def state(self) -> dict:
        return {"k1": self.k1, "b": self.b}
