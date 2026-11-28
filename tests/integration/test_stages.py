"""The `ingest` and `read` stages (contracts.md, "Experiment run", "Stages and upstream runs"):
one ingest run serves several read runs, a read from the snapshot gives the same working contexts
as a `system` run with the same engine config, and a read run refuses an upstream that differs on
the write side.

GRACE runs with the deterministic fake backend plus a fake writer endpoint (`WriterTransport`: one
claim per new message, a pure function of the prompt), so the snapshot carries a real claim graph.
The planner gets one fixed graph query, so claims reach the working context."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from grace.config.paths import REPO_ROOT
from grace.eval.runner.harness import drive, stages
from grace.eval.runner.harness.models import FakeBackend
from grace.eval.runner.harness.rundir import CodeState
from grace.llm.client import ChatClient, Endpoint
from tests.contracts.records import read_jsonl
from tests.contracts.test_experiment_run import check_run
from tests.integration.writer_fixture import completion
from tests.llm.fakes import WordCounter

LOCOMO = REPO_ROOT / "tests" / "fixtures" / "benchmarks" / "locomo"
CONFIGS = REPO_ROOT / "configs" / "engines"
GRACE = CONFIGS / "grace.yaml"
CODE = CodeState("0123456789abcdef0123456789abcdef01234567", False)
NEW = re.compile(r"^\[(\d+)\] (\w+)[^:]*: (.*)$")


PLAN = {"ir": "SELECT ?o WHERE { (mel, mentions, ?o) [_, inform] }", "time_window": None,
        "anchor": None, "variables": [{"var": "?o", "describes": "what Mel mentioned"}],
        "fallback_channels": ["bm25"], "reason": None}


class WriterTransport:
    """A fake OpenAI-compatible server: the writer gets one claim per new message (subject the
    speaker, object the message's last word), the planner one graph query; every other call gets
    an unparsable reply."""

    def __init__(self):
        self.writer_calls = 0

    def __call__(self, url, payload, headers, timeout):
        system, user = payload["messages"][0]["content"], payload["messages"][-1]["content"]
        if "fallback_channels" in system:  # the planner: what Mel mentioned
            return completion(json.dumps(PLAN))
        if not system.startswith("You maintain the long-term memory"):
            return completion("not json")
        self.writer_calls += 1
        claims = []
        for line in user.split("New messages:\n", 1)[1].splitlines():
            match = NEW.match(line)
            if match:
                words = re.findall(r"[A-Za-z]+", match[3])
                claims.append({"message": int(match[1]), "subject": match[2],
                               "predicate": "mentions", "object": words[-1],
                               "object_type": "entity", "function": "inform",
                               "quote": words[-1]})
        return completion(json.dumps({"claims": claims, "stances": []}))


def with_writer(transport: WriterTransport):
    """`on_model` hook: give the fake port a chat client (writer and planner) on `transport`."""
    def attach(model) -> None:
        model.client = ChatClient(Endpoint("http://fake/v1", "writer", "writer@1"), model.ledger,
                                  WordCounter(), max_attempts=1, backoff_s=0.0,
                                  transport=transport, sleep=lambda s: None)
    return attach


def comparable(run_dir: Path) -> list[dict]:
    """Read traces without call IDs and timings, candidate scores to 6 decimals: the dense
    index renormalises restored vectors, which moves scores in the last float digits."""
    out = []
    for t in read_jsonl(run_dir / "traces" / "read.jsonl"):
        t = {k: v for k, v in t.items() if k not in ("call_ids", "timings_ms")}
        t["candidates"] = [{**c, "score": round(c["score"], 6)} for c in t["candidates"]]
        out.append(t)
    return out


def fake(caching: bool) -> FakeBackend:
    return FakeBackend(prefix_caching=caching)


class StagesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def ingest(self, config=GRACE, transport=None):
        transport = transport or WriterTransport()
        result = stages.run_ingest(engine_config=config, records=LOCOMO, experiment="E000",
                                   run_root=self.root, code=CODE, command="test",
                                   backend_factory=fake, on_model=with_writer(transport))
        self.assertEqual(result.status, "completed", result.failure)
        return result

    def read(self, upstream, budget, config=GRACE, workers=1):
        return stages.run_read(engine_config=config, upstream=upstream.run_dir, budget=budget,
                               experiment="E000", run_root=self.root, code=CODE,
                               command="test", backend_factory=fake,
                               on_model=with_writer(WriterTransport()), workers=workers)

    def variant(self, name: str, **params) -> Path:
        config = yaml.safe_load(GRACE.read_text(encoding="utf-8"))
        for key, value in params.items():
            if key in config:
                config[key] = value
            else:
                config["params"][key] = value
        path = self.root / f"{name}.yaml"
        path.write_text(yaml.safe_dump(config), encoding="utf-8")
        return path

    def test_ingest_writes_its_files_and_a_checked_snapshot(self):
        transport = WriterTransport()
        run = self.ingest(transport=transport)
        self.assertGreater(transport.writer_calls, 0)
        files = {p.relative_to(run.run_dir).as_posix() for p in run.run_dir.rglob("*")
                 if p.is_file() and not p.relative_to(run.run_dir).parts[0] == "snapshot"}
        self.assertEqual(files, {"run.json", "resolved-config.yaml", "run.log", "calls.jsonl",
                                 "traces/write.jsonl", "changesets.jsonl"})
        record = check_run(run.run_dir)
        self.assertEqual((record["stage"], record["n_records"]), ("ingest", 5))
        manifest = json.loads((run.run_dir / "snapshot" / "manifest.json").read_text())
        (entry,) = manifest["histories"]
        self.assertEqual((entry["history_id"], entry["version"]), ("conv-syn-1", 5))
        on_disk = {p.relative_to(run.run_dir / "snapshot").as_posix()
                   for p in (run.run_dir / "snapshot").rglob("*")
                   if p.is_file() and p.name != "manifest.json"}
        self.assertEqual(on_disk, {f["path"] for f in entry["files"]})
        writes = read_jsonl(run.run_dir / "traces" / "write.jsonl")
        self.assertEqual([w["trigger"] for w in writes].count("write"), 5)
        versions = sorted(c["version"] for c in read_jsonl(run.run_dir / "changesets.jsonl"))
        self.assertEqual(versions, [1, 2, 3, 4, 5])
        claims = sum(len(c["entries"]["claims"])
                     for c in read_jsonl(run.run_dir / "changesets.jsonl"))
        self.assertEqual(claims, 5)

    def test_read_from_the_snapshot_equals_the_system_run(self):
        ingest = self.ingest()
        for budget in (256, None):
            with self.subTest(budget=budget):
                system = drive.run_system(
                    engine_config=GRACE, records=LOCOMO, budget=budget, experiment="E000",
                    run_root=self.root, code=CODE, command="test", backend_factory=fake,
                    on_model=with_writer(WriterTransport()))
                self.assertEqual(system.status, "completed", system.failure)
                read = self.read(ingest, budget)
                self.assertEqual(read.status, "completed", read.failure)
                record = check_run(read.run_dir)
                self.assertEqual(record["upstream"][0]["run_id"], ingest.run_id)
                self.assertEqual(record["n_records"], 3)
                files = {p.relative_to(read.run_dir).as_posix()
                         for p in read.run_dir.rglob("*") if p.is_file()}
                self.assertEqual(files, {"run.json", "resolved-config.yaml", "run.log",
                                         "calls.jsonl", "predictions.jsonl", "contexts.jsonl",
                                         "traces/read.jsonl"})
                a = read_jsonl(system.run_dir / "contexts.jsonl")
                b = read_jsonl(read.run_dir / "contexts.jsonl")
                self.assertTrue(any(f["kind"] == "claim" for c in a for f in c["fragments"]),
                                "the fixture graph should reach the context")
                self.assertEqual(a, b)
                self.assertEqual(comparable(system.run_dir), comparable(read.run_dir))
                self.assertEqual(read_jsonl(system.run_dir / "predictions.jsonl"),
                                 read_jsonl(read.run_dir / "predictions.jsonl"))
                calls = read_jsonl(read.run_dir / "calls.jsonl")
                self.assertFalse([c for c in calls if c["category"] == "write"])

    def test_read_side_variants_are_accepted_and_write_side_ones_refused(self):
        ingest = self.ingest()
        accepted = {
            "assembly": self.variant("truncate", assembly="configs/assembly/truncate.yaml"),
            "open items": self.variant(
                "no-open", assembly="configs/experiments/E013-dev/assembly-no-open.yaml"),
            "view source": self.variant("template", components={
                "views": {"factory": "serialised-views"}}),
            "no views": self.variant("no-views", views=None),
            "description": self.variant("described", description="another name"),
        }
        for name, config in accepted.items():
            with self.subTest(accepted=name):
                read = self.read(ingest, 256, config=config)
                self.assertEqual(read.status, "completed", read.failure)
        refused = {
            "writer model": self.variant("w8b", writer_model="configs/models/qwen3-8b.yaml"),
            "writer config": self.variant("seg8", writer="configs/common/writer-segment8.yaml"),
            "extension": self.variant("slots", views=None, components={
                "extension": {"factory": "slot-table", "guard": True, "time": "bitemporal"}}),
            "staleness": self.variant("stale", staleness={"strategy": "rebuild_on_read"}),
            "engine": CONFIGS / "bm25.yaml",
        }
        for name, config in refused.items():
            with self.subTest(refused=name):
                before = set(self.root.rglob("run.json"))
                with self.assertRaisesRegex(ValueError, "write side"):
                    self.read(ingest, 256, config=config)
                self.assertEqual(set(self.root.rglob("run.json")), before)  # no run created

    def test_template_ingest_cannot_serve_resident_views(self):
        template = self.variant("template", components={"views": {"factory": "serialised-views"}})
        ingest = self.ingest(config=template)
        with self.assertRaisesRegex(ValueError, "resident_views"):
            self.read(ingest, 256)

    def test_upstream_must_be_a_completed_ingest_with_intact_files(self):
        ingest = self.ingest()
        system = drive.run_system(engine_config=GRACE, records=LOCOMO, budget=256,
                                  experiment="E000", run_root=self.root, code=CODE,
                                  command="test", backend_factory=fake,
                                  on_model=with_writer(WriterTransport()))
        with self.assertRaisesRegex(ValueError, "must be an ingest run"):
            self.read(system, 256)
        manifest = json.loads((ingest.run_dir / "snapshot" / "manifest.json").read_text())
        victim = ingest.run_dir / "snapshot" / manifest["histories"][0]["files"][0]["path"]
        victim.write_bytes(victim.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "does not match the manifest"):
            self.read(ingest, 256)
        failed = sorted((self.root / "E000").iterdir())[-1]
        self.assertEqual(json.loads((failed / "run.json").read_text())["status"], "failed")
        run = json.loads((ingest.run_dir / "run.json").read_text())
        run["status"] = "failed"
        (ingest.run_dir / "run.json").write_text(json.dumps(run))
        with self.assertRaisesRegex(ValueError, "not completed"):
            self.read(ingest, 256)

    def test_baseline_ingest_and_parallel_read(self):
        config = CONFIGS / "bm25.yaml"
        ingest = stages.run_ingest(engine_config=config, records=LOCOMO, experiment="E000",
                                   run_root=self.root, code=CODE, command="test",
                                   backend_factory=fake, workers=2)
        self.assertEqual(ingest.status, "completed", ingest.failure)
        read = stages.run_read(engine_config=config, upstream=ingest.run_dir, budget=None,
                               experiment="E000", run_root=self.root, code=CODE,
                               command="test", backend_factory=fake, workers=2)
        self.assertEqual(read.status, "completed", read.failure)
        system = drive.run_system(engine_config=config, records=LOCOMO, budget=None,
                                  experiment="E000", run_root=self.root, code=CODE,
                                  command="test", backend_factory=fake)
        self.assertEqual(read_jsonl(system.run_dir / "contexts.jsonl"),
                         read_jsonl(read.run_dir / "contexts.jsonl"))

    def test_write_side_rule(self):
        base = drive.load_engine_config(GRACE)
        side = stages.write_side(base)
        self.assertEqual(stages.incompatibilities(side, side), [])
        dense_off = {**base, "params": {**base["params"],
                                        "retrieval": "configs/retrieval/rules.yaml"}}
        off = stages.write_side(dense_off)
        if off["dense"] is None:  # an ingest without the dense index cannot serve dense reads
            self.assertTrue(stages.incompatibilities(off, side))
            self.assertEqual(stages.incompatibilities(side, off), [])


if __name__ == "__main__":
    unittest.main()
