"""Validate docs/work/plan/plan.yaml against the work folders (schema: docs/work/plan/README.md)."""

import datetime
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLAN_DIR = ROOT / "docs" / "work" / "plan"
WORK = ROOT / "docs" / "work"
FOLDERS = {
    "task": ("tasks", "T"),
    "experiment": ("experiments", "E"),
    "decision": ("decisions", "D"),
}
STATUSES = {
    "task": {"planned", "active", "review", "done", "blocked", "dropped"},
    "experiment": {"planned", "active", "review", "done", "blocked", "dropped"},
    "decision": {"proposed", "accepted", "superseded", "rejected"},
}
NODE_FIELDS = {
    "id",
    "type",
    "title",
    "milestone",
    "status",
    "depends_on",
    "issue",
    "owner",
    "start",
    "finish",
    "file",
}


def find_cycle(graph):
    """Return a node on a cycle in {node: [deps]}, or None."""
    state = {}

    def visit(n):
        state[n] = 1
        for d in graph.get(n, []):
            if state.get(d) == 1 or (d not in state and visit(d)):
                return True
        state[n] = 2
        return False

    for n in graph:
        if n not in state and visit(n):
            return n
    return None


def is_date(value):
    return value is None or isinstance(value, datetime.date)


class PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = yaml.safe_load((PLAN_DIR / "plan.yaml").read_text(encoding="utf-8"))
        cls.milestones = {m["id"]: m for m in cls.plan["milestones"]}
        cls.nodes = {n["id"]: n for n in cls.plan["nodes"]}

    def test_unique_ids(self):
        ids = [m["id"] for m in self.plan["milestones"]] + [n["id"] for n in self.plan["nodes"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate IDs")

    def test_milestones(self):
        for mid, m in self.milestones.items():
            with self.subTest(milestone=mid):
                self.assertRegex(mid, r"^M\d+$")
                self.assertTrue(m.get("title"))
                for d in m.get("depends_on", []):
                    self.assertIn(d, self.milestones)
                self.assertTrue(is_date(m.get("due")))
        self.assertIsNone(
            find_cycle({k: m.get("depends_on", []) for k, m in self.milestones.items()})
        )

    def test_nodes(self):
        for nid, n in self.nodes.items():
            with self.subTest(node=nid):
                self.assertEqual(set(n), NODE_FIELDS)
                self.assertIn(n["type"], FOLDERS)
                folder, prefix = FOLDERS[n["type"]]
                self.assertRegex(nid, rf"^{prefix}\d{{3}}$")
                self.assertIn(n["status"], STATUSES[n["type"]])
                self.assertTrue(n["milestone"] is None or n["milestone"] in self.milestones)
                for d in n["depends_on"]:
                    self.assertIn(d, self.nodes)
                self.assertTrue(is_date(n["start"]) and is_date(n["finish"]))
                path = (PLAN_DIR / n["file"]).resolve()
                self.assertTrue(path.is_file(), f"missing file {n['file']}")
                self.assertEqual(path.parent, WORK / folder)
                self.assertTrue(path.name.startswith(nid + "-"))
                front = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
                self.assertIsNotNone(front, "missing front matter")
                meta = yaml.safe_load(front.group(1))
                self.assertEqual(meta["id"], nid)
                self.assertEqual(meta["title"], n["title"])
        self.assertIsNone(find_cycle({k: n["depends_on"] for k, n in self.nodes.items()}))

    def test_every_work_file_has_a_node(self):
        listed = {(PLAN_DIR / n["file"]).resolve() for n in self.nodes.values()}
        for folder, prefix in FOLDERS.values():
            for path in (WORK / folder).glob(f"{prefix}[0-9][0-9][0-9]-*.md"):
                with self.subTest(file=path.name):
                    self.assertIn(path.resolve(), listed)


if __name__ == "__main__":
    unittest.main()
