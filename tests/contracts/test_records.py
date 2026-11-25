"""Contract tests for the benchmark records and predictions (docs/research/contracts.md)."""

import copy
import random
import re
import unittest
from pathlib import Path

from tests.contracts.records import (
    ContractError,
    align_predictions,
    check_gold,
    check_histories,
    check_messages,
    check_read_tasks,
    load_benchmark,
    read_jsonl,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "benchmarks"
CONTRACTS = ROOT / "docs" / "research" / "contracts.md"
BENCHMARKS = ROOT / "docs" / "research" / "benchmarks.md"


def evaluated_slugs() -> list[str]:
    """Slugs in the registry of benchmarks.md that are evaluated (one slug per table row)."""
    text = BENCHMARKS.read_text(encoding="utf-8").split("## Registry", 1)[1].split("\n## ", 1)[0]
    slugs = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) > 5 and cells[0].startswith("`") and cells[-1] != "not evaluated":
            slugs.append(cells[0].strip("`"))
    return slugs


def mapping_slugs() -> list[str]:
    text = CONTRACTS.read_text(encoding="utf-8").split("## Benchmark mapping", 1)[1]
    text = text.split("\n## ", 1)[0]
    return re.findall(r"^\| `([a-z0-9-]+)` \|", text, flags=re.M)


class Fixture:
    def __init__(self, slug: str):
        self.dir = FIXTURES / slug
        self.records = load_benchmark(self.dir)
        self.read_tasks = self.records["schedules"]["read_tasks.jsonl"]
        self.predictions = read_jsonl(self.dir / "predictions.jsonl")

    def align(self, predictions=None):
        return align_predictions(self.read_tasks, self.records["messages"], self.records["gold"],
                                 self.predictions if predictions is None else predictions)


class MappingTest(unittest.TestCase):
    def test_every_evaluated_benchmark_has_a_mapping_row_and_a_fixture(self):
        slugs = evaluated_slugs()
        self.assertEqual(len(slugs), 6, slugs)
        self.assertEqual(sorted(mapping_slugs()), sorted(slugs))
        for slug in slugs:
            with self.subTest(slug=slug):
                Fixture(slug).align()

    def test_fixtures_carry_the_fields_the_plan_relies_on(self):
        # History unit, segment, message, timestamps and evidence IDs (plan 3.1, 6.2, 6.7).
        segmented = {"change-seq", "locomo", "longmemeval-s", "halumem-medium", "memoryagentbench"}
        timed = {"change-seq", "locomo", "longmemeval-s", "halumem-medium"}
        with_evidence = {"change-seq", "locomo", "longmemeval-s"}  # HaluMem: memory points
        for slug in evaluated_slugs():
            with self.subTest(slug=slug):
                records = Fixture(slug).records
                histories = list(records["histories"].values())
                messages = [m for h in records["messages"].values() for m in h.values()]
                self.assertTrue(histories and messages)
                self.assertEqual(slug in segmented, all(h["segments"] for h in histories))
                times = [m["timestamp"] for m in messages]
                times += [s["timestamp"] for h in histories for s in h["segments"]]
                self.assertEqual(slug in timed, any(times))
                evidence = [g["evidence_ids"] for g in records["gold"].values()]
                self.assertEqual(slug in with_evidence, any(evidence))

    def test_longmemeval_keeps_question_date_and_session_evidence(self):
        records = Fixture("longmemeval-s").records
        (task,) = records["schedules"]["read_tasks.jsonl"].values()
        self.assertIsNotNone(task["asked_at"])
        (gold,) = records["gold"].values()
        self.assertEqual(gold["evidence_segment_ids"], ["sess_b"])
        for message in records["messages"][task["history_id"]].values():
            self.assertNotIn("has_answer", message.get("metadata", {}))

    def test_multiwoz_annotations_share_task_ids(self):
        gold = Fixture("multiwoz").records["gold"]
        annotations = {annotation for annotation, _ in gold}
        self.assertTrue({"2.4", "2.2", "2.1"} <= annotations)

    def test_locomo_keeps_unresolved_evidence(self):
        gold = Fixture("locomo").records["gold"]
        self.assertTrue(any(g["evidence_unresolved"] for g in gold.values()))


class ProtocolTest(unittest.TestCase):
    """Per-turn reading (MultiWOZ) and end-of-history reading (LoCoMo) on the same records."""

    @staticmethod
    def drive(records, schedule):
        """Write messages in version order; answer each read on the prefix it may see."""
        seen = {}
        for history_id, history in records["histories"].items():
            messages = sorted(records["messages"][history_id].values(), key=lambda m: m["version"])
            reads = sorted((t for t in schedule.values() if t["history_id"] == history_id),
                           key=lambda t: t["version"])
            log = []
            for message in messages:
                log.append(message["message_id"])  # write: commit version len(log)
                for task in reads:
                    if task["version"] == len(log):
                        seen[task["read_id"]] = list(log)
            assert len(log) == history["n_messages"]
        return seen

    def test_multiwoz_per_turn_state_reads(self):
        fixture = Fixture("multiwoz")
        seen = self.drive(fixture.records, fixture.read_tasks)
        n = {h: r["n_messages"] for h, r in fixture.records["histories"].items()}
        for read_id, task in fixture.read_tasks.items():
            self.assertEqual(task["kind"], "state")
            message = next(m for m in fixture.records["messages"][task["history_id"]].values()
                           if m["version"] == task["version"])
            self.assertEqual(message["role"], "user")
            self.assertEqual(len(seen[read_id]), task["version"])
        self.assertTrue(any(t["version"] < n[t["history_id"]] for t in fixture.read_tasks.values()))

    def test_locomo_end_of_history_and_streaming(self):
        fixture = Fixture("locomo")
        n = {h: r["n_messages"] for h, r in fixture.records["histories"].items()}
        end = fixture.read_tasks
        self.assertTrue(all(t["version"] == n[t["history_id"]] for t in end.values()))
        self.assertTrue(all(t["kind"] == "question" for t in end.values()))
        self.assertEqual(len(self.drive(fixture.records, end)), len(end))
        streaming = fixture.records["schedules"]["read_tasks.streaming.jsonl"]
        tasks = [t["task_id"] for t in streaming.values()]
        self.assertGreater(len(tasks), len(set(tasks)))  # one task read at v(q) and at N
        self.assertEqual(len(self.drive(fixture.records, streaming)), len(streaming))


class PredictionAlignmentTest(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture("locomo")

    def assertProblem(self, category, predictions):
        with self.assertRaises(ContractError) as caught:
            self.fixture.align(predictions)
        self.assertIn(category, caught.exception.problems)

    def test_shuffled_order_is_accepted(self):
        predictions = list(self.fixture.predictions)
        self.assertNotEqual([p["read_id"] for p in predictions], list(self.fixture.read_tasks))
        for seed in range(3):
            random.Random(seed).shuffle(predictions)
            self.assertEqual(self.fixture.align(predictions).keys(), self.fixture.read_tasks.keys())

    def test_duplicate_key(self):
        self.assertProblem("duplicate_key", self.fixture.predictions + self.fixture.predictions[:1])

    def test_missing_key(self):
        self.assertProblem("missing_key", self.fixture.predictions[1:])

    def test_extra_key(self):
        extra = copy.deepcopy(self.fixture.predictions[0])
        extra["read_id"] = "conv-syn-1:q99@5"
        self.assertProblem("extra_key", self.fixture.predictions + [extra])

    def test_empty_prediction_file(self):
        self.assertProblem("missing_key", [])

    def test_snapshot_mismatch_on_version(self):
        predictions = copy.deepcopy(self.fixture.predictions)
        predictions[0]["version"] = 3
        self.assertProblem("snapshot_mismatch", predictions)

    def test_snapshot_mismatch_on_history(self):
        predictions = copy.deepcopy(self.fixture.predictions)
        predictions[0]["history_id"] = "conv-syn-2"
        self.assertProblem("snapshot_mismatch", predictions)

    def test_snapshot_mismatch_on_future_context(self):
        fixture = Fixture("locomo")
        schedule = fixture.records["schedules"]["read_tasks.streaming.jsonl"]
        read = schedule["conv-syn-1:q1@3"]
        prediction = {key: read[key] for key in
                      ("benchmark", "split", "history_id", "read_id", "task_id", "version")}
        prediction.update(output="answer", prediction="Pip", cited_ids=["D1:2"],
                          context_ids=["D1:2"], further_retrieval=False, raw_output="Pip")
        others = []
        for other in schedule.values():
            if other["read_id"] != read["read_id"]:
                p = dict(prediction, read_id=other["read_id"], task_id=other["task_id"],
                         version=other["version"])
                others.append(p)
        messages, gold = fixture.records["messages"], fixture.records["gold"]
        align_predictions(schedule, messages, gold, [prediction] + others)  # valid
        prediction["context_ids"] = ["D1:2", "D2:1"]  # D2:1 is version 4 > 3
        with self.assertRaises(ContractError) as caught:
            align_predictions(schedule, messages, gold, [prediction] + others)
        self.assertIn("snapshot_mismatch", caught.exception.problems)

    def test_mixed_splits(self):
        predictions = copy.deepcopy(self.fixture.predictions)
        predictions[0]["split"] = "dev"
        self.assertProblem("mixed_scope", predictions)

    def test_unknown_and_invalid_outputs_are_not_missing(self):
        outputs = {p["output"] for p in self.fixture.align().values()}
        self.assertIn("unknown", outputs)
        outputs = {p["output"] for p in Fixture("halumem-medium").align().values()}
        self.assertIn("invalid", outputs)

    def test_missing_and_extra_fields(self):
        predictions = copy.deepcopy(self.fixture.predictions)
        del predictions[0]["context_ids"]
        self.assertProblem("missing_field", predictions)
        predictions = copy.deepcopy(self.fixture.predictions)
        predictions[0]["reference"] = "leak"
        self.assertProblem("unknown_field", predictions)


class RecordCheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = FIXTURES / "locomo"
        self.histories = check_histories(read_jsonl(self.dir / "histories.jsonl"))
        self.messages = read_jsonl(self.dir / "messages.jsonl")
        self.reads = read_jsonl(self.dir / "read_tasks.jsonl")
        self.gold = read_jsonl(self.dir / "gold.jsonl")

    def assertProblem(self, category, call, *args):
        with self.assertRaises(ContractError) as caught:
            call(*args)
        self.assertIn(category, caught.exception.problems)

    def test_duplicate_message_version(self):
        messages = copy.deepcopy(self.messages)
        messages[1]["version"] = 1
        self.assertProblem("duplicate_version", check_messages, self.histories, messages)

    def test_duplicate_message_id(self):
        messages = copy.deepcopy(self.messages)
        messages[1]["message_id"] = messages[0]["message_id"]
        self.assertProblem("duplicate_key", check_messages, self.histories, messages)

    def test_missing_message(self):
        self.assertProblem("version_gap", check_messages, self.histories, self.messages[:-1])

    def test_shuffled_messages_are_accepted(self):
        messages = list(self.messages)
        random.Random(0).shuffle(messages)
        check_messages(self.histories, messages)

    def test_message_outside_its_segment(self):
        messages = copy.deepcopy(self.messages)
        messages[0]["segment_id"] = "session_2"
        self.assertProblem("segment_mismatch", check_messages, self.histories, messages)

    def test_gold_field_in_a_message_is_rejected(self):
        messages = copy.deepcopy(self.messages)
        messages[0]["evidence"] = ["D1:1"]
        self.assertProblem("unknown_field", check_messages, self.histories, messages)

    def test_read_after_the_end_of_history(self):
        reads = copy.deepcopy(self.reads)
        reads[0]["version"] = 6
        reads[0]["read_id"] = f"{reads[0]['task_id']}@6"
        self.assertProblem("snapshot_mismatch", check_read_tasks, self.histories, reads)

    def test_duplicate_read_id(self):
        self.assertProblem("duplicate_key", check_read_tasks, self.histories,
                           self.reads + self.reads[:1])

    def test_read_before_its_evidence(self):
        messages = check_messages(self.histories, self.messages)
        reads = copy.deepcopy(self.reads)
        reads[0]["version"] = 2  # q0 cites D2:1 at version 4
        reads[0]["read_id"] = f"{reads[0]['task_id']}@2"
        schedule = check_read_tasks(self.histories, reads)
        self.assertProblem("snapshot_mismatch", check_gold, self.histories, messages,
                           [schedule], self.gold)

    def test_duplicate_gold_key(self):
        messages = check_messages(self.histories, self.messages)
        schedule = check_read_tasks(self.histories, self.reads)
        self.assertProblem("duplicate_key", check_gold, self.histories, messages, [schedule],
                           self.gold + self.gold[:1])

    def test_missing_required_history_field(self):
        rows = read_jsonl(self.dir / "histories.jsonl")
        del rows[0]["segments"]
        self.assertProblem("missing_field", check_histories, rows)


if __name__ == "__main__":
    unittest.main()
