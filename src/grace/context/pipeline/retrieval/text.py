"""The BM25 and dense channels (plan 5.5, 7.1).

Both search the indexes of `memory/index/` at the version of the read and return candidates in
the unified evidence ID space (`candidates.py`). The indexes are filled by the caller at write
time; a channel only searches.

The dense channel embeds the query through an `embed_query` callable that the caller wires to
`grace.llm.embeddings.EmbeddingClient`, so every embedding call is recorded in the cost ledger
(category `embedding`, plan 8.1). A configured query instruction is put in front of the query in
Qwen3-Embedding's form (`Instruct: ...\\nQuery: ...`); messages are embedded as they are, as in the
retrieval baselines (`eval/engines/baselines/retrieval.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from grace.context.memory.index.bm25 import BM25Index
from grace.context.memory.index.dense import DenseIndex
from grace.context.pipeline.retrieval.candidates import RetrievalCandidate, ranked

EmbedQuery = Callable[[str], Sequence[float]]


def instructed(query: str, instruction: str | None) -> str:
    """The text embedded for a query: Qwen3-Embedding's instruction form, or the query alone."""
    return f"Instruct: {instruction}\nQuery: {query}" if instruction else query


class BM25Channel:
    name = "bm25"

    def __init__(self, index: BM25Index):
        self.index = index

    def search(self, query: str, version: int, k: int) -> list[RetrievalCandidate]:
        hits = self.index.search(query, version)
        return ranked(self.name, ((chunk.evidence_ids, score) for chunk, score in hits), k)


class DenseChannel:
    name = "dense"

    def __init__(self, index: DenseIndex, embed_query: EmbedQuery,
                 query_instruction: str | None = None):
        self.index, self.embed_query = index, embed_query
        self.query_instruction = query_instruction

    def search(self, query: str, version: int, k: int) -> list[RetrievalCandidate]:
        if not any(c.version <= version for c in self.index.chunks):
            return []
        vector = self.embed_query(instructed(query, self.query_instruction))
        hits = self.index.search(vector, version)
        return ranked(self.name, ((chunk.evidence_ids, score) for chunk, score in hits), k)
