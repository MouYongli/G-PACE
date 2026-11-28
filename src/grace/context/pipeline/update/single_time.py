"""Single-time variant of the claim graph (ablation B, time arm "single"; plan 7.3, B; E011).

The main configuration is bitemporal: every claim carries a valid interval besides the version
(transaction time) at which it was written (plan 3.2, 5.2). The single-time arm keeps only
transaction time. Its extractor wraps the writer and drops every valid-time field the writer
proposes (`valid_from`, `valid_until`, `time_expression` on claims; `valid_until` on stances)
before the updater sees the patch, so every stored claim has an unknown start and an open end.
Everything else is unchanged: the same writer call, the same guard (which then supersedes an
exclusive value without a valid end, plan 3.2), the same read path. This mirrors the slot-table
arm `time: single` (`context/memory/graph/slots.py`), where valid times are not stored either.

It is a component injected through the engine's extension hook (`config/registry.py`, name
`single-time`), not a branch in the engine.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from grace.context.pipeline.update.extract import Extraction, Extractor, WriterInput
from grace.context.pipeline.update.patch import ClaimPatch


def strip_valid_time(patch: ClaimPatch) -> ClaimPatch:
    """`patch` without any valid-time field."""
    return replace(
        patch,
        claims=tuple(replace(c, valid_from=None, valid_until=None, time_expression=None)
                     for c in patch.claims),
        stances=tuple(replace(s, valid_until=None) for s in patch.stances))


class SingleTimeExtractor(Extractor):
    """The wrapped extractor's result with valid times removed from its patch."""

    def __init__(self, inner: Extractor):
        self.inner = inner
        self.name = f"{getattr(inner, 'name', 'extractor')}+single-time"

    def extract(self, request: WriterInput) -> Extraction:
        result = self.inner.extract(request)
        if result.patch is None:
            return result
        return replace(result, patch=strip_valid_time(result.patch))


class SingleTime:
    """Per-history extension (`context/engine.py`, `Extension`): only the extractor differs."""

    deferred = None

    def extractor(self, default: Extractor) -> Extractor:
        return SingleTimeExtractor(default)

    def read_graph(self, store, version: int):
        return store

    def state_facts(self, task, request: str) -> list:
        return []

    def save(self, directory: Path) -> list[Path]:
        return []

    def restore(self, directory: Path) -> None:
        pass


def single_time(*, writer, client=None, view_config=None, **options):
    """Component factory (`config/registry.py`, name `single-time`)."""
    if options:
        raise TypeError(f"single-time takes no options, got {sorted(options)}")
    return lambda history: SingleTime()
