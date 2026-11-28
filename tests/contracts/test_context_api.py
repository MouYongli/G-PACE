"""Contract tests for the ContextEngine interface types in src/grace/context/api.py.

The visible records of every fixture benchmark parse into the interface types and serialise back
unchanged; gold records and gold fields are rejected, so they cannot reach an engine through them.
"""

import unittest
from pathlib import Path

from grace.context import api
from tests.contracts.records import read_jsonl

BENCHMARKS = Path(__file__).resolve().parents[1] / "fixtures" / "benchmarks"


class _Echo(api.ContextEngine):
    """Smallest engine: the context is every message up to the read's version."""

    def open(self, history):
        self.history, self.messages = history, []

    @property
    def version(self):
        return len(self.messages)

    def write(self, message):
        if message.version != self.version + 1:
            raise ValueError("out of order")
        self.messages.append(message)
        return api.WriteResult(api.WriteTrace(message.history_id, message.version,
                                              (message.message_id,)))

    def read(self, task, budget_tokens):
        api.check_read(self, task)
        fragments = tuple(api.Fragment(f"m{m.version}", "message", m.text, (m.message_id,),
                                       (m.message_id,), len(m.text.split()))
                          for m in self.messages)
        text = "\n".join(f.text for f in fragments)
        context = api.WorkingContext(task.read_id, task.history_id, task.version, budget_tokens,
                                     sum(f.tokens for f in fragments), text, fragments)
        return api.ReadResult(context, api.read_trace(context))

    def further_retrieval(self, task, request, budget_tokens):
        result = self.read(task, budget_tokens)
        return api.ReadResult(result.context, api.read_trace(result.context,
                                                             further_retrieval=True))

    def save(self, directory):
        return []

    def restore(self, directory):
        raise NotImplementedError


class RecordTypesTest(unittest.TestCase):
    def test_fixture_records_round_trip(self):
        for directory in sorted(BENCHMARKS.iterdir()):
            with self.subTest(benchmark=directory.name):
                for row in read_jsonl(directory / "histories.jsonl"):
                    self.assertEqual(api.HistoryInfo.from_record(row).to_record(), row)
                for row in read_jsonl(directory / "messages.jsonl"):
                    self.assertEqual(api.Message.from_record(row).to_record(), row)
                for path in directory.glob("read_tasks*.jsonl"):
                    for row in read_jsonl(path):
                        self.assertEqual(api.ReadTask.from_record(row).to_record(), row)

    def test_gold_records_are_rejected(self):
        for directory in sorted(BENCHMARKS.iterdir()):
            for row in read_jsonl(directory / "gold.jsonl"):
                with self.subTest(benchmark=directory.name, task=row["task_id"]):
                    with self.assertRaises(api.RecordError):
                        api.ReadTask.from_record(row)

    def test_invalid_records_are_rejected(self):
        task = read_jsonl(BENCHMARKS / "locomo" / "read_tasks.jsonl")[0]
        message = read_jsonl(BENCHMARKS / "locomo" / "messages.jsonl")[0]
        bad = {
            "gold field": (api.ReadTask, dict(task, reference="violin")),
            "missing field": (api.ReadTask, {k: v for k, v in task.items() if k != "version"}),
            "bool for int": (api.ReadTask, dict(task, version=True)),
            "string for int": (api.Message, dict(message, version="1")),
            "empty string": (api.Message, dict(message, text="")),
            "bad role": (api.Message, dict(message, role="system")),
            "bad read id": (api.ReadTask, dict(task, read_id="x@1")),
            "state without schema": (api.ReadTask, dict(task, kind="state", question=None)),
        }
        for name, (cls, record) in bad.items():
            with self.subTest(case=name), self.assertRaises(api.RecordError):
                cls.from_record(record)


class InterfaceTest(unittest.TestCase):
    def test_traces_follow_the_artefact_records(self):
        directory = BENCHMARKS / "locomo"
        engine = _Echo()
        engine.open(api.HistoryInfo.from_record(read_jsonl(directory / "histories.jsonl")[0]))
        tasks = [api.ReadTask.from_record(r)
                 for r in read_jsonl(directory / "read_tasks.streaming.jsonl")]
        reads = []
        for row in read_jsonl(directory / "messages.jsonl"):
            trace = engine.write(api.Message.from_record(row)).trace.to_record()
            self.assertEqual(set(trace), {"history_id", "version", "message_ids", "call_ids",
                                          "stale_marks", "timings_ms", "trigger"})
            self.assertEqual(trace["trigger"], "write")
            for task in (t for t in tasks if t.version == engine.version):
                reads.append(engine.read(task, None))
        self.assertEqual(len(reads), len(tasks))
        early = reads[0] if reads[0].context.version == 3 else reads[1]
        self.assertEqual(early.context.context_ids, ["D1:1", "D1:2", "D1:3"])
        record = early.trace.to_record()
        self.assertEqual(record["included_ids"], early.context.context_ids)
        self.assertEqual(set(record), {"read_id", "history_id", "version", "candidates",
                                       "included_ids", "provenance", "view_hits",
                                       "staleness_decisions", "further_retrieval", "call_ids",
                                       "timings_ms", "retrieval_used", "utilisation",
                                       "expansions_used"})
        self.assertEqual(set(early.context.to_record()), {"read_id", "history_id", "version",
                                                          "budget_tokens", "tokens", "text",
                                                          "fragments"})

    def test_read_is_bound_to_the_current_version(self):
        directory = BENCHMARKS / "locomo"
        engine = _Echo()
        engine.open(api.HistoryInfo.from_record(read_jsonl(directory / "histories.jsonl")[0]))
        engine.write(api.Message.from_record(read_jsonl(directory / "messages.jsonl")[0]))
        task = api.ReadTask.from_record(read_jsonl(directory / "read_tasks.jsonl")[0])
        with self.assertRaises(ValueError):
            engine.read(task, 256)

    def test_value_checks(self):
        with self.assertRaises(api.RecordError):
            api.Fragment("f", "chunk", "t", (), (), 1)
        with self.assertRaises(api.RecordError):
            api.StaleMark("v", "s", "maybe")
        with self.assertRaises(api.RecordError):
            api.StalenessDecision("v", "s", "fresh", "drop")


class WriteRecordsTest(unittest.TestCase):
    def test_write_trigger_changesets_and_finish(self):
        trace = api.WriteTrace("h", 3, ("m3",))
        self.assertEqual(trace.to_record()["trigger"], "write")
        with self.assertRaises(api.RecordError):
            api.WriteTrace("h", 3, ("m3",), trigger="later")
        one = api.WriteResult(trace, {"version": 3})
        self.assertEqual(one.changesets, ({"version": 3},))
        many = api.WriteResult(trace, changesets=({"version": 2}, {"version": 3}))
        self.assertEqual(many.changeset, {"version": 3})
        self.assertEqual(api.WriteResult(trace).changesets, ())
        with self.assertRaises(api.RecordError):
            api.WriteResult(trace, {"version": 2}, ({"version": 2}, {"version": 3}))
        self.assertEqual(_Echo().finish(), ())


if __name__ == "__main__":
    unittest.main()
