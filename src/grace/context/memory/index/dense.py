"""Exact cosine search over chunk embeddings, searchable at a cut-off version.

Minimal first version written by T003 for the retrieval baselines (package owned by T025). The
index stores vectors only; embeddings are computed by the caller through the model client, so the
embedding calls are recorded in the cost ledger (plan 7.1: exact cosine, no approximate index).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from grace.context.memory.index.chunking import Chunk


class DenseIndex:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self._vectors: list[np.ndarray] = []

    def add(self, chunk: Chunk, vector: Sequence[float]) -> None:
        if self.chunks and chunk.version < self.chunks[-1].version:
            raise ValueError(f"chunk {chunk.chunk_id} added out of version order")
        v = np.asarray(vector, dtype=np.float64)
        norm = np.linalg.norm(v)
        self.chunks.append(chunk)
        self._vectors.append(v / norm if norm else v)

    def search(self, query_vector: Sequence[float], version: int,
               k: int | None = None) -> list[tuple[Chunk, float]]:
        """Chunks with version <= `version` ranked by cosine similarity (ties by version)."""
        visible = [i for i, c in enumerate(self.chunks) if c.version <= version]
        if not visible:
            return []
        q = np.asarray(query_vector, dtype=np.float64)
        norm = np.linalg.norm(q)
        q = q / norm if norm else q
        scores = np.stack([self._vectors[i] for i in visible]) @ q
        ranked = sorted(zip(visible, scores.tolist(), strict=True),
                        key=lambda item: (-item[1], self.chunks[item[0]].version))
        out = [(self.chunks[i], float(s)) for i, s in ranked]
        return out[:k] if k is not None else out

    def vectors(self) -> list[list[float]]:
        return [v.tolist() for v in self._vectors]
