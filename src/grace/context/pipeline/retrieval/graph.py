"""The graph channel: maps a claim-graph query result to candidates (plan 5.5).

The engine runs the planner and the query (`pipeline/query/`) and passes the result in; this
module never calls `query/` (structure.md: "`retrieval/graph.py` ... receives results from the
engine"). The result is duck-typed: anything with `answers`, each answer with `evidence` (the
unified evidence IDs of its witness claims), as `pipeline/query/result.QueryResult` provides.

Every evidence message of every answer is a candidate with score 1.0: the graph returns evidence
of exact matches, not a graded similarity. Ranks order the candidates for rank fusion: newest
message first (by `version_of`, when given), then in the order of the answers. A missing or empty
result (the planner fell back to text retrieval, or the query matched nothing) gives no
candidates.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from grace.context.pipeline.retrieval.candidates import (
    RetrievalCandidate,
    message_id_of,
    ranked,
)

GRAPH_SCORE = 1.0


def graph_candidates(result: Any | None, k: int,
                     version_of: Callable[[str], int | None] | None = None
                     ) -> list[RetrievalCandidate]:
    """At most `k` candidates from the evidence of a query result."""
    if result is None:
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for answer in result.answers:
        for evidence_id in answer.evidence:
            if evidence_id not in seen:
                seen.add(evidence_id)
                ordered.append(evidence_id)
    if version_of is not None:
        position = {e: i for i, e in enumerate(ordered)}

        def key(evidence_id: str) -> tuple[int, int]:
            version = version_of(message_id_of(evidence_id))
            return (-(version if version is not None else -1), position[evidence_id])
        ordered.sort(key=key)
    return ranked("graph", (((e,), GRAPH_SCORE) for e in ordered), k)
