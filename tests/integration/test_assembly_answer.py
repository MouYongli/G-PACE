"""The assembler on the read path, driven by the shared answering step (T026, plan 5.5 and 5.6).

`AssemblyTextEngine` is a minimal read path for tests and smoke runs: text retrieval (T025, BM25
only) feeds the assembler, a pending query expansion is served by one more restricted text search,
and a further retrieval requested by the answering LLM is served by a search for its request. It
is not GRACE (no claim graph, no views; `context/engine.py` assembles those), but it calls the
assembler exactly as the engine is meant to (`assembly/assemble.py`, "The engine's read path").
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grace.config.paths import REPO_ROOT
from grace.context import api
from grace.context.memory.history.log import MessageLog
from grace.context.memory.index.bm25 import BM25Index
from grace.context.memory.index.chunking import chunk_message
from grace.context.pipeline.assembly.assemble import Assembler, AssemblyConfig
from grace.context.pipeline.assembly.demand import demand_of
from grace.context.pipeline.assembly.items import history_items, message_item
from grace.context.pipeline.retrieval.retrieve import RetrievalConfig, Retriever
from grace.context.pipeline.retrieval.text import BM25Channel
from grace.eval.runner.harness.answer import answer, request_text
from grace.eval.runner.harness.inputs import load_fixture
from grace.eval.runner.harness.models import FakeBackend, RecordingModel
from grace.llm.records import CallLedger

LOCOMO = REPO_ROOT / "tests" / "fixtures" / "benchmarks" / "locomo"
CONFIGS = REPO_ROOT / "configs" / "assembly"


class AssemblyTextEngine(api.ContextEngine):
    """BM25 retrieval -> assembly; one instance per history."""

    def __init__(self, count, config: AssemblyConfig, *, total: int = 20,
                 counter_name: str = "unnamed"):
        self.count, self.config, self.counter_name = count, config, counter_name
        self.retrieval = RetrievalConfig(total=total, depth=total, channels=("bm25",),
                                         routing="all")
        self.log: MessageLog | None = None
        self.index = BM25Index()
        self.assemblies: list = []

    def open(self, history: api.HistoryInfo) -> None:
        self.history = history
        self.log = MessageLog(history.history_id)

    @property
    def version(self) -> int:
        return self.log.head if self.log else 0

    def write(self, message: api.Message) -> api.WriteResult:
        self.log.append(message)
        for chunk in chunk_message(message):
            self.index.add(chunk)
        return api.WriteResult(api.WriteTrace(message.history_id, message.version,
                                              (message.message_id,)))

    def _items(self, query: str, version: int, rank_start: int = 1):
        retriever = Retriever(self.retrieval, bm25=BM25Channel(self.index))
        result = retriever.retrieve(query, version)
        items = [message_item(self.log.by_id(c.evidence_id, version), rank=rank_start + i,
                              history=self.history)
                 for i, c in enumerate(result.fused)]
        return items, result.trace_candidates()

    def _read(self, task: api.ReadTask, budget, request: str | None) -> api.ReadResult:
        api.check_read(self, task)
        assembler = Assembler(self.config, self.count, log=self.log, history=self.history,
                              counter_name=self.counter_name)
        demand = demand_of(request_text(task))
        if budget is None:
            items, candidates = history_items(self.log, task.version, self.history), []
        else:
            items, candidates = self._items(task.question or "", task.version)
        used, spent = 0, False
        if request is not None:
            extra, more = self._items(request, task.version, len(items) + 1)
            items, candidates = extra + items, more + candidates
            used, spent = self.config.max_expansions, True
        result = assembler.assemble(task, demand, items, budget, expansions_used=used,
                                    retrieval_used=spent)
        if result.pending is not None:
            extra, more = self._items(result.pending.query, task.version, len(items) + 1)
            result = assembler.assemble(task, demand, items + extra, budget, expansions_used=1,
                                        retrieval_used=True)
            candidates += more
        self.assemblies.append(result)
        return api.ReadResult(result.context,
                              api.read_trace(result.context, candidates=candidates,
                                             further_retrieval=request is not None))

    def read(self, task, budget_tokens):
        return self._read(task, budget_tokens, None)

    def further_retrieval(self, task, request, budget_tokens):
        return self._read(task, budget_tokens, request)

    def save(self, directory: Path) -> list[Path]:
        return [self.log.save(directory)]

    def restore(self, directory: Path) -> None:
        raise NotImplementedError


class AnswerPathTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = CallLedger(Path(tmp.name) / "calls.jsonl", "T026-20261128T000000Z-0000")
        self.item = load_fixture(LOCOMO).histories[0]

    def run_reads(self, responder, budget, config="default.yaml"):
        backend = FakeBackend(responder)
        model = RecordingModel(backend, self.ledger)
        engine = AssemblyTextEngine(backend.count_tokens,
                                    AssemblyConfig.load(CONFIGS / config))
        engine.open(self.item.history)
        reads, visible, out = list(self.item.reads), set(), []
        for message in self.item.messages:
            engine.write(message)
            visible.add(message.message_id)
            while reads and reads[0].version == message.version:
                task = reads.pop(0)
                out.append((task, answer(engine, task, budget, model, visible)))
        self.assertFalse(reads)
        return engine, out

    def test_every_answer_records_the_evidence_ids_shown(self):
        def cite_first(messages):
            context = messages[-1]["content"]
            ids = [line[1:line.index("]")].split(", ")[0] for line in context.splitlines()
                   if line.startswith("[") and "]" in line and line[1:3] != "no"]
            if not ids:
                return json.dumps({"output": "unknown", "cited_ids": []})
            return json.dumps({"output": "answer", "answer": "x", "cited_ids": ids[:1]})

        for budget in (256, 512, 1024, None):
            for config in ("default.yaml", "truncate.yaml"):
                with self.subTest(budget=budget, config=config):
                    engine, results = self.run_reads(cite_first, budget, config)
                    self.assertTrue(results)
                    for _task, result in results:
                        ctx = result.context
                        shown = [i for f in ctx.fragments for i in f.source_ids]
                        self.assertEqual(list(result.trace.included_ids), ctx.context_ids)
                        self.assertEqual(set(ctx.context_ids), set(shown))
                        self.assertEqual(result.trace.provenance,
                                         {f.fragment_id: f.evidence_ids for f in ctx.fragments})
                        if result.output == "answer":
                            self.assertTrue(set(result.cited_ids) <= set(ctx.context_ids))
                        if budget is not None:
                            self.assertLessEqual(ctx.tokens, budget)
                        self.assertEqual(ctx.tokens, FakeBackend().count_tokens(ctx.text))

    def test_further_retrieval_is_served_once_through_the_assembler(self):
        def retrieve_then_unknown(messages):
            if "Further retrieval results" in messages[-1]["content"]:
                return json.dumps({"output": "unknown", "cited_ids": []})
            return json.dumps({"output": "retrieve", "query": "clarinet"})
        engine, results = self.run_reads(retrieve_then_unknown, 256)
        for _, result in results:
            self.assertEqual(result.output, "unknown")
            self.assertTrue(result.trace.further_retrieval)
            self.assertEqual(result.cited_ids, [])
        further = engine.assemblies[1::2]
        self.assertTrue(all(a.retrieval_used and a.pending is None for a in further))
        answers = [r for r in self.ledger.records if r.call_type == "answer"]
        self.assertEqual(len(answers), 2 * len(results))


if __name__ == "__main__":
    unittest.main()
