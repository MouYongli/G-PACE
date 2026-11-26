"""One retrieval step: route, run the channels, fuse to a fixed number of candidates (plan 5.5).

`RetrievalConfig` (file `configs/retrieval/default.yaml`) fixes:

- `total`: the number of fused candidates handed to assembly. It is the same whichever channels
  are switched on, so that ablation D (plan 7.3) compares channel sets at equal candidate counts.
- `depth`: how many candidates each channel contributes before fusion (at least `total`, so one
  channel alone can fill the list).
- `channels`: the enabled channels. Switching a channel off removes it from routing and fusion;
  `total` is unchanged.
- `fusion`: `rrf` (main configuration) or `weighted`, with `rrf_k` and per-channel `weights`.
- `routing`: `rules` (`route.py`) or `all` (always every available channel) and `min_confidence`.
- `backfill`: when the routed channels return fewer than `total` candidates, the other enabled
  channels are searched and their fused candidates fill the list, in their own fused order.

The graph channel is available for a read only when the engine passes a query result (the
planner compiled a query); otherwise it is skipped like a switched-off channel.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from grace.context.pipeline.retrieval.candidates import (
    CHANNELS,
    FusedCandidate,
    RetrievalCandidate,
)
from grace.context.pipeline.retrieval.fuse import METHODS, fuse
from grace.context.pipeline.retrieval.graph import graph_candidates
from grace.context.pipeline.retrieval.route import MODES, Route, route
from grace.context.pipeline.retrieval.text import BM25Channel, DenseChannel

CONFIG_KEYS = {"version", "total", "depth", "channels", "fusion", "rrf_k", "weights", "routing",
               "min_confidence", "backfill", "bm25", "dense"}


@dataclass(frozen=True)
class RetrievalConfig:
    total: int = 20
    depth: int = 20
    channels: tuple[str, ...] = CHANNELS
    fusion: str = "rrf"
    rrf_k: int = 60
    weights: Mapping[str, float] = field(
        default_factory=lambda: {"bm25": 1.0, "dense": 1.0, "graph": 1.0})
    routing: str = "rules"
    min_confidence: int = 1
    backfill: bool = True
    bm25: Mapping[str, float] = field(default_factory=lambda: {"k1": 1.5, "b": 0.75})
    dense: Mapping[str, Any] = field(default_factory=dict)  # query_instruction, embedding pin

    def __post_init__(self) -> None:
        if self.total < 1:
            raise ValueError("total must be >= 1")
        if self.depth < self.total:
            raise ValueError("depth must be >= total, so one channel can fill the list")
        if not self.channels or set(self.channels) - set(CHANNELS):
            raise ValueError(f"channels must be a non-empty subset of {CHANNELS}")
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("channels listed twice")
        if self.fusion not in METHODS:
            raise ValueError(f"fusion must be one of {METHODS}")
        if self.routing not in MODES:
            raise ValueError(f"routing must be one of {MODES}")
        if set(self.weights) - set(CHANNELS) or any(w < 0 for w in self.weights.values()):
            raise ValueError("weights: known channels and non-negative values only")

    def without(self, channel: str) -> RetrievalConfig:
        """The same configuration with one channel switched off (ablation D)."""
        rest = tuple(c for c in self.channels if c != channel)
        if not rest:
            raise ValueError("cannot switch off the last channel")
        return replace(self, channels=rest)

    def only(self, channel: str) -> RetrievalConfig:
        return replace(self, channels=(channel,))

    def to_record(self) -> dict[str, Any]:
        return {"version": 1, "total": self.total, "depth": self.depth,
                "channels": list(self.channels), "fusion": self.fusion, "rrf_k": self.rrf_k,
                "weights": dict(self.weights), "routing": self.routing,
                "min_confidence": self.min_confidence, "backfill": self.backfill,
                "bm25": dict(self.bm25), "dense": dict(self.dense)}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> RetrievalConfig:
        if not isinstance(raw, Mapping) or raw.get("version") != 1:
            raise ValueError("retrieval config: expected a mapping with version: 1")
        if unknown := sorted(set(raw) - CONFIG_KEYS):
            raise ValueError(f"retrieval config: unknown keys {unknown}")
        values = {k: v for k, v in raw.items() if k != "version"}
        if "channels" in values:
            values["channels"] = tuple(values["channels"])
        return cls(**values)

    @classmethod
    def load(cls, path: Path) -> RetrievalConfig:
        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class RetrievalResult:
    route: Route
    rankings: Mapping[str, tuple[RetrievalCandidate, ...]]  # every channel that was searched
    fused: tuple[FusedCandidate, ...]
    backfilled: tuple[str, ...] = ()  # channels searched only to fill the list

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(c.evidence_id for c in self.fused)

    def trace_candidates(self) -> list:
        """`api.Candidate`s for the read trace: every channel's candidates, then the fused list."""
        out = [c.to_api() for ch in CHANNELS for c in self.rankings.get(ch, ())]
        return out + [c.to_api("fused") for c in self.fused]


class Retriever:
    """Runs one configuration of channels, routing and fusion."""

    def __init__(self, config: RetrievalConfig, *, bm25: BM25Channel | None = None,
                 dense: DenseChannel | None = None):
        self.config = config
        self.text = {"bm25": bm25, "dense": dense}
        for name in ("bm25", "dense"):
            if name in config.channels and self.text[name] is None:
                raise ValueError(f"channel {name} is enabled but has no index")

    def available(self, graph_available: bool) -> tuple[str, ...]:
        return tuple(c for c in CHANNELS if c in self.config.channels
                     and (c != "graph" or graph_available))

    def _search(self, channel: str, query: str, version: int, graph_result: Any,
                version_of) -> tuple[RetrievalCandidate, ...]:
        k = self.config.depth
        if channel == "graph":
            return tuple(graph_candidates(graph_result, k, version_of))
        return tuple(self.text[channel].search(query, version, k))

    def _fuse(self, rankings) -> list[FusedCandidate]:
        return fuse(self.config.fusion, rankings, total=self.config.total,
                    rrf_k=self.config.rrf_k, weights=self.config.weights)

    def retrieve(self, query: str, version: int, *, graph_result: Any | None = None,
                 version_of: Callable[[str], int | None] | None = None,
                 rankings: Mapping[str, tuple[RetrievalCandidate, ...]] | None = None
                 ) -> RetrievalResult:
        """Route `query`, search the routed channels at `version` and fuse to `total`.

        `graph_result` is the query result of the planner's compiled query (None when the planner
        fell back). `rankings` may carry precomputed channel rankings (each at least `depth`
        long, or complete); channels missing from it are searched.
        """
        cache = dict(rankings or {})

        def get(channel: str) -> tuple[RetrievalCandidate, ...]:
            if channel not in cache:
                cache[channel] = self._search(channel, query, version, graph_result, version_of)
            return cache[channel][: self.config.depth]

        r = route(query, self.available(graph_result is not None), mode=self.config.routing,
                  min_confidence=self.config.min_confidence)
        searched = {ch: get(ch) for ch in r.channels}
        fused = self._fuse(searched)
        backfilled: list[str] = []
        if self.config.backfill and len(fused) < self.config.total:
            rest = [c for c in self.available(graph_result is not None)
                    if c not in r.channels]
            if rest:
                extra = {ch: get(ch) for ch in rest}
                backfilled = rest
                have = {c.evidence_id for c in fused}
                fused += [c for c in fuse(self.config.fusion, extra, total=None,
                                          rrf_k=self.config.rrf_k, weights=self.config.weights)
                          if c.evidence_id not in have][: self.config.total - len(fused)]
                searched.update(extra)
        return RetrievalResult(r, {ch: searched[ch] for ch in CHANNELS if ch in searched},
                               tuple(fused), tuple(backfilled))
