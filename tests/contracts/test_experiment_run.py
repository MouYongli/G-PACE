"""Contract tests for the Experiment run section of docs/research/contracts.md (version 0.2)."""

import copy
import hashlib
import json
import os
import re
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from tests.contracts.records import ContractError, check_fields

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
NULL = type(None)
RUN_ID = re.compile(r"^(?P<experiment>[TE]\d{3})-\d{8}T\d{6}Z-[0-9a-f]{4}$")
STAGES = {"system", "ingest", "read", "probe", "judge", "score"}
# stage -> allowed upstream stage combinations (table "Stages and upstream runs").
UPSTREAM = {
    "system": [[]],
    "ingest": [[]],
    "read": [["ingest"]],
    "probe": [[], ["ingest"], ["system"]],
    "judge": [["system"], ["read"]],
    "score": [["system"], ["read"], ["system", "judge"], ["read", "judge"]],
}
RUN_JSON = {"run_id": str, "experiment": str, "stage": str, "upstream": list, "status": str,
            "code_sha": str, "code_dirty": bool, "config_path": str, "config_sha256": str,
            "resources_sha256": str, "data": list, "project_root": str, "seed": int,
            "command": str, "environment": dict, "started_at": str,
            "finished_at": (str, NULL), "n_records": int, "failure": (str, NULL)}
UPSTREAM_ENTRY = {"run_id": str, "stage": str, "path": str, "run_json_sha256": str}
ARTEFACTS = {
    "contexts.jsonl": {"read_id": str, "history_id": str, "version": int,
                       "budget_tokens": (int, NULL), "tokens": int, "text": str, "fragments": list},
    "traces/write.jsonl": {"history_id": str, "version": int, "message_ids": list,
                           "call_ids": list, "stale_marks": list, "timings_ms": dict,
                           "trigger": str},
    "traces/read.jsonl": {"read_id": str, "history_id": str, "version": int, "candidates": list,
                          "included_ids": list, "provenance": dict, "view_hits": list,
                          "staleness_decisions": list, "further_retrieval": bool,
                          "call_ids": list, "timings_ms": dict, "retrieval_used": bool,
                          "utilisation": (float, int, NULL), "expansions_used": int},
    "changesets.jsonl": {"history_id": str, "version": int, "entries": dict,
                         "vocabulary_version": (str, NULL), "entity_merges": list},
    "judgements.jsonl": {"read_id": str, "task_id": str, "annotation": str, "judge": str,
                         "verdict": str, "raw_output": (str, NULL), "call_id": (str, NULL)},
    "snapshot/manifest.json": {"histories": list},
}


def resources_sha256(directory: Path) -> str:
    """Checksum of resources/ as defined in the contract (sha256sum lines, sorted by path)."""
    lines = []
    if directory.exists():
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"symbolic link under resources/: {path}")
            if path.is_file():
                relative = path.relative_to(directory).as_posix()
                lines.append((relative.encode("utf-8"), hashlib.sha256(path.read_bytes())))
    text = b"".join(f"{d.hexdigest()}  ".encode() + rel + b"\n" for rel, d in sorted(lines))
    return hashlib.sha256(text).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_run_dir(parent: Path, experiment: str, run_id: str) -> Path:
    path = parent / experiment / run_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()  # exclusive: fails if the run directory exists
    return path


def check_run(run_dir: Path) -> dict:
    """Check one run.json and its upstream runs; return the parsed run.json."""
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    check_fields([run], RUN_JSON, "run.json")
    check_fields(run["upstream"], UPSTREAM_ENTRY, "run.json.upstream")
    problems = defaultdict(list)
    match = RUN_ID.match(run["run_id"])
    if not match or match["experiment"] != run["experiment"] or run_dir.name != run["run_id"]:
        problems["bad_run_id"].append(run["run_id"])
    if run["stage"] not in STAGES:
        problems["bad_stage"].append(run["stage"])
    elif sorted(u["stage"] for u in run["upstream"]) not in map(sorted, UPSTREAM[run["stage"]]):
        problems["bad_upstream"].append(run["run_id"])
    if run["status"] not in {"running", "completed", "failed"}:
        problems["bad_status"].append(run["status"])
    if run["status"] == "completed" and (run["code_dirty"] or run["finished_at"] is None):
        problems["bad_status"].append(run["run_id"])
    if run["status"] == "failed" and not run["failure"]:
        problems["bad_status"].append(run["run_id"])
    if not re.fullmatch(r"[0-9a-f]{40}", run["code_sha"]):
        problems["bad_value"].append("code_sha")
    for field in ("project_root",):
        if not os.path.isabs(run[field]):
            problems["bad_value"].append(field)
    for entry in run["upstream"]:
        upstream_dir = Path(entry["path"])
        try:
            upstream = json.loads((upstream_dir / "run.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            problems["missing_upstream"].append(entry["run_id"])
            continue
        if upstream["run_id"] != entry["run_id"] or upstream["stage"] != entry["stage"]:
            problems["bad_upstream"].append(entry["run_id"])
        if upstream["status"] != "completed":
            problems["upstream_not_completed"].append(entry["run_id"])
        if file_sha256(upstream_dir / "run.json") != entry["run_json_sha256"]:
            problems["upstream_changed"].append(entry["run_id"])
    if problems:
        raise ContractError(problems)
    return run


class StagedRuns:
    """Materialise the staged-run fixture into a temporary RUN_DIR."""

    def __init__(self, tmp: Path):
        spec = json.loads((FIXTURES / "runs" / "staged-runs.json").read_text(encoding="utf-8"))
        self.project_root = tmp / "project"
        self.run_dir = self.project_root / "runs" / "T001" / "artifacts" / "fixture"
        self.dirs = {}
        common = json.loads(json.dumps(spec["common"]).replace(
            "${PROJECT_ROOT}", self.project_root.as_posix()))
        for item in spec["runs"]:
            run = dict(common, **{k: v for k, v in item.items() if k != "upstream"})
            run["upstream"] = []
            for up in item["upstream"]:
                upstream_json = self.dirs[up] / "run.json"
                run["upstream"].append({
                    "run_id": up,
                    "stage": json.loads(upstream_json.read_text(encoding="utf-8"))["stage"],
                    "path": self.dirs[up].as_posix(),
                    "run_json_sha256": file_sha256(upstream_json),
                })
            path = create_run_dir(self.run_dir, run["experiment"], run["run_id"])
            (path / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
            self.dirs[run["run_id"]] = path

    def rewrite(self, run_id, **changes):
        path = self.dirs[run_id] / "run.json"
        run = json.loads(path.read_text(encoding="utf-8"))
        run.update(changes)
        path.write_text(json.dumps(run, indent=2), encoding="utf-8")


class ExperimentRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runs = StagedRuns(Path(self.tmp.name))
        self.ids = list(self.runs.dirs)

    def tearDown(self):
        self.tmp.cleanup()

    def assertProblem(self, category, run_id):
        with self.assertRaises(ContractError) as caught:
            check_run(self.runs.dirs[run_id])
        self.assertIn(category, caught.exception.problems)

    def test_staged_fixture_is_valid(self):
        stages = [check_run(path)["stage"] for path in self.runs.dirs.values()]
        self.assertEqual(stages, ["ingest", "read", "read", "judge", "score"])

    def test_one_ingestion_serves_several_reads(self):
        ingest = self.ids[0]
        readers = [check_run(p) for p in self.runs.dirs.values()]
        readers = [r for r in readers if r["stage"] == "read"]
        self.assertEqual(len(readers), 2)
        self.assertTrue(all(r["upstream"][0]["run_id"] == ingest for r in readers))

    def test_run_directory_is_created_exclusively(self):
        with self.assertRaises(FileExistsError):
            create_run_dir(self.runs.run_dir, "E000", self.ids[0])

    def test_changed_upstream_is_detected(self):
        self.runs.rewrite(self.ids[0], n_records=6)  # someone wrote into the ingest run
        self.assertProblem("upstream_changed", self.ids[1])

    def test_upstream_must_be_completed(self):
        upstream = self.ids[0]
        self.runs.rewrite(upstream, status="running", finished_at=None)
        reader = self.ids[1]
        path = self.runs.dirs[reader] / "run.json"
        run = json.loads(path.read_text())
        run["upstream"][0]["run_json_sha256"] = file_sha256(self.runs.dirs[upstream] / "run.json")
        path.write_text(json.dumps(run))
        self.assertProblem("upstream_not_completed", reader)

    def test_read_needs_an_ingest_upstream(self):
        judge = self.ids[3]
        path = self.runs.dirs[judge] / "run.json"
        run = json.loads(path.read_text())
        run["stage"] = "read"
        path.write_text(json.dumps(run))
        self.assertProblem("bad_upstream", judge)

    def test_completed_run_needs_clean_code(self):
        self.runs.rewrite(self.ids[4], code_dirty=True)
        self.assertProblem("bad_status", self.ids[4])

    def test_run_json_fields(self):
        self.runs.rewrite(self.ids[0], n_samples=5)
        self.assertProblem("unknown_field", self.ids[0])
        path = self.runs.dirs[self.ids[0]] / "run.json"
        run = json.loads(path.read_text())
        del run["n_samples"], run["resources_sha256"]
        path.write_text(json.dumps(run))
        self.assertProblem("missing_field", self.ids[0])


class ResourcesChecksumTest(unittest.TestCase):
    def test_fixture_tree(self):
        spec = json.loads((FIXTURES / "runs" / "staged-runs.json").read_text(encoding="utf-8"))
        self.assertEqual(resources_sha256(FIXTURES / "resources"), spec["resources_sha256"])

    def test_missing_or_empty_directory(self):
        empty = hashlib.sha256(b"").hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resources_sha256(Path(tmp) / "absent"), empty)
            self.assertEqual(resources_sha256(Path(tmp)), empty)

    def test_any_change_changes_the_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a" / "x.txt").write_text("1")
            before = resources_sha256(root)
            (root / "a" / "x.txt").rename(root / "a" / "y.txt")
            self.assertNotEqual(resources_sha256(root), before)

    def test_symbolic_link_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "x.txt").write_text("1")
            (root / "link.txt").symlink_to(root / "x.txt")
            with self.assertRaises(ValueError):
                resources_sha256(root)


class ArtefactTest(unittest.TestCase):
    def test_every_artefact_has_its_fields(self):
        examples = json.loads((FIXTURES / "runs" / "artefacts.json").read_text(encoding="utf-8"))
        self.assertEqual(set(examples) - {"comment"}, set(ARTEFACTS))
        for name, spec in ARTEFACTS.items():
            with self.subTest(file=name):
                check_fields([examples[name]], spec, name)

    def test_missing_field_is_rejected(self):
        examples = json.loads((FIXTURES / "runs" / "artefacts.json").read_text(encoding="utf-8"))
        record = copy.deepcopy(examples["traces/read.jsonl"])
        del record["provenance"]
        with self.assertRaises(ContractError):
            check_fields([record], ARTEFACTS["traces/read.jsonl"], "traces/read.jsonl")

    def test_contract_lists_every_artefact(self):
        text = (ROOT / "docs" / "research" / "contracts.md").read_text(encoding="utf-8")
        section = text.split("## Experiment run", 1)[1]
        self.assertIn("Version: 0.2", section)
        for name in [*ARTEFACTS, "calls.jsonl", "resources_sha256", "upstream"]:
            self.assertIn(f"`{name}`", section, name)
        self.assertIn("configs/common/paths.yaml", section)


if __name__ == "__main__":
    unittest.main()
