"""Baseline kinds by the `engine` key of a config in configs/engines/."""

from __future__ import annotations

from grace.eval.engines.baselines.graphiti import GraphitiEngine
from grace.eval.engines.baselines.mem0 import Mem0
from grace.eval.engines.baselines.raw import RawText
from grace.eval.engines.baselines.retrieval import Retrieval
from grace.eval.engines.baselines.slots import SlotTable
from grace.eval.engines.baselines.summary import RollingSummary
from grace.eval.engines.baselines.tagged import TaggedRetrieval

ENGINES = {cls.kind: cls for cls in (RawText, Retrieval, TaggedRetrieval, RollingSummary,
                                       SlotTable, Mem0, GraphitiEngine)}
