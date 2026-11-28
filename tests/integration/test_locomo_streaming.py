"""LoCoMo streaming on the shared harness (T031). Acceptance: two question orders give the same
index version and evidence input for every read.

Each engine is run twice on the same streaming schedule, once with the reads of every version in
schedule order and once reversed. The state probe records, per read, the engine version, the
fingerprint of the saved engine state the read used (after the read, so after any flush it
triggered) and the digest of the working context; all three, and the predictions, must agree
between the two orders. A GRACE engine with a scripted writer and planner builds a real claim
graph and resident views, flushes an open extraction unit inside the first read of a version and
discards each read's temporary state at `end_read`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grace.config.paths import REPO_ROOT, project_root
from grace.context import api
from grace.context.engine import GraceEngine
from grace.eval.datasets.benchmarks.base import load_config
from grace.eval.datasets.benchmarks.locomo import STREAMING_SCHEDULE
from grace.eval.runner.harness import drive
from grace.eval.runner.harness.inputs import HistoryInputs, Inputs, load_fixture
from grace.eval.runner.harness.models import FakeBackend, RecordingModel, fake_responder
from grace.eval.runner.harness.outputs import RunWriter
from grace.eval.runner.harness.rundir import CodeState
from grace.eval.runner.harness.streaming import ProbeError, StateProbe, select_reads
from grace.llm.records import CallLedger

LOCOMO = REPO_ROOT / "tests" / "fixtures" / "benchmarks" / "locomo"
ENGINES = REPO_ROOT / "configs" / "engines"
CODE = CodeState("0" * 40, False)
COMPARED = ("version", "state_sha256", "evidence_sha256", "final_evidence_sha256",
            "context_ids", "unchanged")


def by_read(records) -> dict[str, tuple]:
    return {r.read_id: tuple(getattr(r, f) for f in COMPARED) for r in records}


def predictions(run_dir: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in
            (run_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    return {r["read_id"]: r for r in rows}


class HarnessOrderTest(unittest.TestCase):
    """Baselines and default GRACE (fake backend) on the LoCoMo streaming fixture."""

    def run_order(self, config: Path, order: str, root: Path):
        probes = []
        result = drive.run_system(
            engine_config=config, records=LOCOMO, schedule="streaming", budget=256,
            experiment="T031", run_root=root, code=CODE, command="test", read_order=order,
            engine_wrapper=lambda engine: StateProbe(engine, probes))
        self.assertEqual(result.status, "completed", result.failure)
        return probes, result.run_dir

    def test_two_orders_give_the_same_version_state_and_evidence(self):
        for name in ("bm25", "rrf", "full-history", "summary-rewrite", "grace"):
            with self.subTest(engine=name), tempfile.TemporaryDirectory() as tmp:
                config = ENGINES / f"{name}.yaml"
                first, run_a = self.run_order(config, "schedule", Path(tmp))
                second, run_b = self.run_order(config, "reversed", Path(tmp))
                self.assertNotEqual([r.read_id for r in first], [r.read_id for r in second])
                self.assertEqual(by_read(first), by_read(second))
                for r in first:
                    self.assertEqual(r.version, int(r.read_id.rpartition("@")[2]))
                self.assertEqual(predictions(run_a), predictions(run_b))

    def test_the_schedule_reads_a_question_at_v_and_n(self):
        item = load_fixture(LOCOMO, "streaming").histories[0]
        versions = {}
        for task in item.reads:
            versions.setdefault(task.task_id, []).append(task.version)
        n = item.history.n_messages
        self.assertTrue(all(v[-1] == n for v in versions.values()))
        self.assertTrue(any(len(v) == 2 for v in versions.values()))

    def test_state_probe_run_logs_every_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = drive.run_system(
                engine_config=ENGINES / "bm25.yaml", records=LOCOMO, schedule="streaming",
                budget=256, experiment="T031", run_root=Path(tmp), code=CODE, command="test",
                state_probe=True, task_ids=["conv-syn-1:q1"])
            self.assertEqual(result.status, "completed", result.failure)
            self.assertEqual(result.n_reads, 2)
            log = (result.run_dir / "run.log").read_text(encoding="utf-8")
            self.assertEqual(log.count("state_after_end_read=same"), 2)
            self.assertIn("probe summary", log)
            self.assertIn("task_ids", (result.run_dir / "resolved-config.yaml").read_text())

    def test_select_reads_refuses_unknown_tasks(self):
        inputs = load_fixture(LOCOMO, "streaming")
        with self.assertRaises(ValueError):
            select_reads(inputs, ["conv-syn-1:q99"])


class LeakyEngine(api.ContextEngine):
    """Writes into its resident state while answering: the probe must fail the read."""

    def __init__(self, inner):
        self.inner = inner

    def open(self, history):
        self.inner.open(history)

    @property
    def version(self):
        return self.inner.version

    def write(self, message):
        return self.inner.write(message)

    def read(self, task, budget_tokens):
        return self.inner.read(task, budget_tokens)

    def further_retrieval(self, task, request, budget_tokens):
        return self.inner.further_retrieval(task, request, budget_tokens)

    def end_read(self, task):
        self.inner.end_read(task)
        self.leaked = task.read_id

    def save(self, directory):
        files = self.inner.save(directory)
        path = Path(directory) / "leak.txt"
        path.write_text(getattr(self, "leaked", ""), encoding="utf-8")
        return [*files, path]

    def restore(self, directory):
        self.inner.restore(directory)


class ProbeTest(unittest.TestCase):
    def test_state_changed_by_end_read_fails_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProbeError):
                drive.run_system(
                    engine_config=ENGINES / "bm25.yaml", records=LOCOMO, schedule="streaming",
                    budget=256, experiment="T031", run_root=Path(tmp), code=CODE,
                    command="test", state_probe=True, engine_wrapper=LeakyEngine)


# ---------------------------------------------------------------------------------------------
# GRACE with a claim graph and views


class QuestionPlanner:
    """A compiled plan per question (or a fallback plan for unknown questions)."""

    QUERIES = {"Where do I live?": "SELECT ?x WHERE { (user, livesIn, ?x) }",
               "What do I drink?": "SELECT ?x WHERE { (user, prefersDrink, ?x) }"}

    def plan(self, ctx):
        from grace.context.pipeline.query.compile import compile_query
        from grace.context.pipeline.query.grammar import parse
        from grace.context.pipeline.query.planner import Plan
        text = self.QUERIES.get(ctx.request.removeprefix("Question: "))
        if text is None:
            return Plan(ctx.read_id, "fallback")
        q = parse(text)
        return Plan(ctx.read_id, "llm", query=q, compiled=compile_query(q, "rdf11"),
                    variables=(("?x", "the value asked for"),))


class GraceOrderTest(unittest.TestCase):
    QUESTIONS = (("live", "Where do I live?"), ("drink", "What do I drink?"),
                 ("other", "What is my name?"))

    def engine(self, tmp: Path, ledger: CallLedger) -> GraceEngine:
        from grace.context.engine import Components, Views
        from grace.context.pipeline.assembly.assemble import AssemblyConfig
        from grace.context.pipeline.retrieval.retrieve import RetrievalConfig
        from grace.context.pipeline.update.updater import WriterConfig, llm_writer
        from grace.context.views.store import ViewStore
        from grace.llm.client import ChatClient, Endpoint
        from tests.integration.test_grace_engine import WRITER_SCRIPT
        from tests.integration.writer_fixture import ScriptedTransport
        from tests.llm.fakes import WordCounter

        client = ChatClient(Endpoint("http://fake/v1", "writer", "writer@1"), ledger,
                            WordCounter(), max_attempts=1, backoff_s=0.0,
                            transport=ScriptedTransport(WRITER_SCRIPT), sleep=lambda s: None)
        writer = WriterConfig()
        return GraceEngine(Components(
            count=lambda t: len(t.split()),
            extractor=lambda h: llm_writer(writer, client, h),
            planner=QuestionPlanner(), retrieval=RetrievalConfig(channels=("bm25", "graph")),
            assembly=AssemblyConfig(), writer=writer,
            views=lambda h, v: Views(ViewStore(h.history_id, vocabulary=v), "push_confirm",
                                     local_filters=True)))

    def item(self) -> HistoryInputs:
        from tests.integration.test_grace_engine import CITY, city_messages
        from tests.integration.writer_fixture import history_info
        messages = city_messages()
        info = history_info(CITY, messages)
        reads = []
        # v(q) = 1 for every question (inside the open unit: the first read flushes it), and N.
        for key, question in self.QUESTIONS:
            for version in (1, len(messages)):
                reads.append(api.ReadTask("fixture", "dev", CITY, f"{key}@{version}", key,
                                          version, "question", question, None, None, None))
        reads.sort(key=lambda t: t.version)
        return HistoryInputs(info, tuple(messages), tuple(reads))

    def drive(self, order: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        ledger = CallLedger(root / "calls.jsonl", "T031-20261128T000000Z-0000")
        item = self.item()
        inputs = Inputs("fixture", "dev", STREAMING_SCHEDULE, "fixture", "0", root, (item,))
        item = select_reads(inputs, None, order).histories[0]
        probes = []
        engine = StateProbe(self.engine(root, ledger), probes)
        model = RecordingModel(FakeBackend(fake_responder), ledger)
        run_dir = root / "run"
        run_dir.mkdir()
        answered = drive.drive_history(engine, item, 256, model, RunWriter(run_dir))
        self.assertEqual(answered, len(item.reads))
        return engine.inner, probes, run_dir

    def test_two_orders_give_the_same_version_state_and_evidence(self):
        engine_a, first, run_a = self.drive("schedule")
        engine_b, second, run_b = self.drive("reversed")
        self.assertNotEqual([r.read_id for r in first], [r.read_id for r in second])
        self.assertEqual(by_read(first), by_read(second))
        self.assertEqual(predictions(run_a), predictions(run_b))
        # The graph and the views exist, and the first read at v = 1 flushed the open unit.
        self.assertEqual(engine_a.store.head, 4)
        self.assertTrue(engine_a.views.store.views())
        at_one = {r.read_id: r for r in first if r.version == 1}
        self.assertEqual(len({r.state_sha256 for r in at_one.values()}), 1)
        # The temporary state of every read is gone after end_read.
        self.assertEqual(engine_a._reads, {})
        self.assertEqual(engine_b._reads, {})
        contexts = [json.loads(line)["text"] for line in
                    (run_a / "contexts.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any("Berlin" in text for text in contexts))


def locomo_present() -> bool:
    try:
        config = load_config("locomo")
        return config.source_dir(project_root()).is_dir()
    except RuntimeError:
        return False


@unittest.skipUnless(locomo_present(), "no LoCoMo data under PROJECT_ROOT")
class DevelopmentScheduleTest(unittest.TestCase):
    """The streaming schedule of the development split equals the committed T007 list."""

    def test_dev_schedule_matches_the_read_point_list(self):
        from grace.eval.datasets.benchmarks.locomo_read_points import load_committed
        from grace.eval.runner.harness.inputs import load_dev

        listed = load_committed(
            REPO_ROOT / load_config("locomo").options["streaming_read_points"])
        inputs = load_dev("locomo", "dev", "streaming")
        self.assertEqual(inputs.schedule, STREAMING_SCHEDULE)
        for item in inputs.histories:
            hid = item.history.history_id
            entry = listed["histories"][hid]
            self.assertEqual(entry["split"], "dev")
            got: dict[str, list[int]] = {}
            for task in item.reads:
                got.setdefault(task.task_id, []).append(task.version)
            self.assertEqual(set(got), set(entry["v"]))
            for task_id, versions in got.items():
                self.assertEqual(versions, sorted({entry["v"][task_id], entry["n_messages"]}))
            self.assertFalse(set(got) & set(listed["excluded"]))
        self.assertEqual(inputs.n_reads, 595)


if __name__ == "__main__":
    unittest.main()
