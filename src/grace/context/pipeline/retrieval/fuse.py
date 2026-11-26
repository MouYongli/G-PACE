"""Fusion of channel rankings into one list of unified evidence IDs (plan 5.5, "Fusion").

- `rrf`: reciprocal rank fusion, the main configuration. A candidate scores
  `sum_c w_c / (k + rank_c)` over the channels c that returned it (rank from 1); with all
  weights 1 this is plain RRF (Cormack et al. 2009).
- `weighted`: weighted score fusion, the alternative. Each channel's scores are min-max normalised
  to [0, 1] over the candidates it returned (a channel whose scores are all equal gives 1.0 to
  each), and a candidate scores `sum_c w_c * norm_c`.

Both cut the fused list at `total`. Ties are broken by the best rank in any channel, then by the
channel order of that rank, then by evidence ID, so the result is deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from grace.context.pipeline.retrieval.candidates import (
    CHANNELS,
    FusedCandidate,
    RetrievalCandidate,
)

METHODS = ("rrf", "weighted")
Rankings = Mapping[str, Sequence[RetrievalCandidate]]


def _weight(weights: Mapping[str, float] | None, channel: str) -> float:
    if weights is None:
        return 1.0
    w = float(weights.get(channel, 0.0))
    if w < 0:
        raise ValueError(f"negative weight for {channel}")
    return w


def _collect(rankings: Rankings, contribution) -> list[FusedCandidate]:
    scores: dict[str, float] = {}
    ranks: dict[str, list[tuple[str, int]]] = {}
    spans: dict[str, list[str]] = {}
    for channel in sorted(rankings, key=lambda c: CHANNELS.index(c)):
        for cand in rankings[channel]:
            if cand.channel != channel:
                raise ValueError(f"candidate of {cand.channel} listed under {channel}")
            eid = cand.evidence_id
            if any(ch == channel for ch, _ in ranks.get(eid, ())):
                raise ValueError(f"{eid} appears twice in channel {channel}")
            scores[eid] = scores.get(eid, 0.0) + contribution(channel, cand)
            ranks.setdefault(eid, []).append((channel, cand.rank))
            for s in cand.spans:
                if s not in spans.setdefault(eid, []):
                    spans[eid].append(s)
    return [FusedCandidate(eid, scores[eid], tuple(ranks[eid]), tuple(spans.get(eid, ())))
            for eid in scores]


def _order(fused: list[FusedCandidate], total: int | None) -> list[FusedCandidate]:
    def key(c: FusedCandidate):
        best = min(c.ranks, key=lambda r: (r[1], CHANNELS.index(r[0])))
        return (-c.score, best[1], CHANNELS.index(best[0]), c.evidence_id)
    fused.sort(key=key)
    return fused[:total] if total is not None else fused


def rrf(rankings: Rankings, *, k: int = 60, weights: Mapping[str, float] | None = None,
        total: int | None = None) -> list[FusedCandidate]:
    if k < 0:
        raise ValueError("rrf k must be >= 0")
    return _order(_collect(rankings, lambda ch, c: _weight(weights, ch) / (k + c.rank)), total)


def weighted(rankings: Rankings, *, weights: Mapping[str, float] | None = None,
             total: int | None = None) -> list[FusedCandidate]:
    bounds = {}
    for channel, cands in rankings.items():
        if cands:
            values = [c.score for c in cands]
            bounds[channel] = (min(values), max(values))

    def norm(channel: str, cand: RetrievalCandidate) -> float:
        lo, hi = bounds[channel]
        value = 1.0 if hi == lo else (cand.score - lo) / (hi - lo)
        return _weight(weights, channel) * value
    return _order(_collect(rankings, norm), total)


def fuse(method: str, rankings: Rankings, *, total: int | None, rrf_k: int = 60,
         weights: Mapping[str, float] | None = None) -> list[FusedCandidate]:
    if method == "rrf":
        return rrf(rankings, k=rrf_k, weights=weights, total=total)
    if method == "weighted":
        return weighted(rankings, weights=weights, total=total)
    raise ValueError(f"unknown fusion method {method!r}; known: {METHODS}")
