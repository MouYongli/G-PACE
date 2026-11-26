"""Import rules of docs/work/plan/structure.md (decision D013), checked on src/grace/.

Every module under src/grace/ is assigned to the most specific unit listed in RULES; each unit may
import only the units listed for it (and itself, including its subpackages). An import that is not
listed is forbidden, as in the diagrams of structure.md ("an arrow that is not drawn is an import
that is not allowed"). Packages that do not exist yet need no rule to pass; the test fails on the
first forbidden import that appears.

Simplifications, stated so that a change to structure.md updates them deliberately:
- `config` and `llm` may be imported by every layer above them (the omitted arrows to `llm/`).
- Importing a package's `__init__` counts as importing that package itself, not its subpackages:
  code must name the subpackage it uses (`grace.context.memory.graph`, not `grace.context.memory`).
- The model client libraries in MODEL_CLIENTS may be imported only by `llm/` (AGENTS.md: "Send
  every model call through `src/grace/llm/`").
"""

from __future__ import annotations

import ast
import tempfile
import textwrap
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
BASE = ("config", "llm")
MODEL_CLIENTS = ("openai",)
# Unit -> units it may import. A unit may always import itself and its own subpackages.
RULES: dict[str, tuple[str, ...]] = {
    "grace": (),
    "cli": ("grace", "config", "llm", "context", "eval"),
    "config": (),
    "llm": ("config",),
    # context/: api <- memory <- pipeline <- views <- engine
    "context": BASE,
    "context.api": BASE,
    "context.memory": (*BASE, "context.api"),
    "context.memory.history": (*BASE, "context.api"),
    "context.memory.index": (*BASE, "context.api"),
    "context.memory.graph": (*BASE, "context.api"),
    "context.pipeline": (*BASE, "context.api"),
    "context.pipeline.query": (*BASE, "context.api", "context.memory.graph"),
    "context.pipeline.update": (*BASE, "context.api", "context.memory.graph",
                                "context.memory.history"),
    "context.pipeline.retrieval": (*BASE, "context.api", "context.memory.index"),
    "context.pipeline.assembly": (*BASE, "context.api", "context.memory.history"),
    "context.views": (*BASE, "context.api", "context.pipeline.query", "context.memory.graph"),
    "context.engine": (*BASE, "context"),
    # eval/: datasets <- engines <- runner; analysis reads files only
    "eval": BASE,
    "eval.datasets": BASE,
    "eval.datasets.benchmarks": (*BASE, "context.api", "eval.datasets"),
    "eval.datasets.changeseq": (*BASE, "context.memory.graph", "eval.datasets"),
    "eval.engines": BASE,
    "eval.engines.baselines": (*BASE, "context.api", "context.memory.index"),
    "eval.engines.oracles": (*BASE, "context", "eval.datasets.benchmarks"),
    "eval.runner": BASE,
    "eval.runner.harness": (*BASE, "context.api", "eval.engines", "eval.datasets.benchmarks",
                            "eval.runner"),
    "eval.runner.probes": (*BASE, "context", "eval.engines", "eval.datasets", "eval.runner"),
    "eval.analysis": BASE,
}


def within(name: str, unit: str) -> bool:
    return name == unit or name.startswith(unit + ".")


def unit_of(module: str) -> str | None:
    """Most specific unit of a dotted module name under `grace`; None if it is not listed."""
    if module == "grace":
        return "grace"
    if not module.startswith("grace."):
        return None
    name = module[len("grace."):]
    matches = [unit for unit in RULES if unit != "grace" and within(name, unit)]
    return max(matches, key=len) if matches else None


def module_name(path: Path, src: Path) -> str:
    parts = list(path.relative_to(src).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(tree: ast.AST, module: str, is_package: bool):
    """Yield (line, absolute dotted name) for every import; `from a import b` yields `a.b`."""
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                prefix = ".".join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module or ""
            for alias in node.names:
                yield node.lineno, prefix if alias.name == "*" else f"{prefix}.{alias.name}"


def violations(src: Path) -> list[str]:
    """All forbidden imports and unlisted modules under src/grace, as readable strings."""
    found = []
    for path in sorted((src / "grace").rglob("*.py")):
        module = module_name(path, src)
        importer = unit_of(module)
        where = path.relative_to(src).as_posix()
        if importer is None:
            found.append(f"{where}: module {module} belongs to no package of structure.md")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, name in imported_modules(tree, module, path.name == "__init__.py"):
            if importer != "llm" and any(within(name, lib) for lib in MODEL_CLIENTS):
                found.append(f"{where}:{line}: only llm may import {name}")
                continue
            target = unit_of(name)
            if not name.startswith("grace") or target is None and not within(name, "grace"):
                continue
            own = within(target or "", importer) and importer != "grace"
            allowed = own or any(within(target or "", unit) for unit in RULES[importer])
            if target is None or not allowed:
                found.append(f"{where}:{line}: {importer} must not import {name}")
    return found


def write_tree(root: Path, files: dict[str, str]) -> Path:
    for relative, source in files.items():
        path = root / "grace" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")
    return root


class ImportRulesTest(unittest.TestCase):
    def test_src_follows_the_import_rules(self):
        self.assertEqual(violations(SRC), [])

    def check(self, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            return violations(write_tree(Path(tmp), {"__init__.py": "", **files}))

    def test_allowed_imports_pass(self):
        self.assertEqual(self.check({
            "config/paths.py": "import os\nimport yaml\n",
            "llm/client.py": "import openai\nfrom grace.config import paths\n",
            "context/api.py": "from grace.llm import client\n",
            "context/memory/graph/store.py": "from grace.context.api import Message\n",
            "context/pipeline/update/guard.py": (
                "from grace.context.memory.graph import store\n"
                "from grace.context.memory.history import log\nfrom . import patch\n"),
            "context/views/staleness/pattern.py": (
                "from grace.context.memory.graph import changeset\n"),
            "context/views/render.py": (
                "from ..pipeline.query import result\n"
                "from .staleness import base\n"),
            "context/engine.py": (
                "from grace.context.views import store\n"
                "from grace.context.pipeline.update import guard\n"),
            "eval/engines/baselines/retrieval.py": "from grace.context.memory.index import bm25\n",
            "eval/engines/oracles/graph.py": "from grace.eval.datasets.benchmarks import records\n",
            "eval/runner/harness/drive.py": (
                "from grace.context.api import ContextEngine\n"
                "from grace.eval.engines.baselines import raw\n"
                "from grace.eval.datasets.benchmarks import splits\n"),
            "eval/analysis/metrics/cost.py": "from grace.eval.analysis.judging import judge\n",
            "cli/run/system.py": "from grace.eval.runner.harness import drive\n",
        }), [])

    def test_forbidden_imports_fail(self):
        cases = {
            "context/api.py": "from grace.context.memory.graph import store\n",
            "context/engine.py": "from grace.eval.datasets.benchmarks import records\n",
            "config/registry.py": "import grace.context.engine\n",
            "llm/client.py": "from grace.eval.analysis import judging\n",
            "context/pipeline/update/guard.py": "from grace.context.views import store\n",
            "context/pipeline/retrieval/graph.py": (
                "from grace.context.pipeline.query import execute\n"),
            "context/pipeline/query/compile.py": "from ..retrieval import fuse\n",
            "context/views/render.py": "from grace.context.pipeline.assembly import layout\n",
            "context/memory/graph/store.py": "from grace.context.pipeline import query\n",
            "eval/engines/baselines/raw.py": "from grace.eval.datasets.benchmarks import records\n",
            "eval/engines/baselines/summary.py": (
                "from grace.context.pipeline.update import extract\n"),
            "eval/runner/harness/answer.py": "from grace.context.memory.graph import store\n",
            "eval/analysis/metrics/answer.py": "from grace.eval.runner.harness import outputs\n",
            "eval/datasets/changeseq/gold.py": "from grace.context.pipeline.query import compile\n",
            "eval/datasets/benchmarks/records.py": "from grace.eval.engines import oracles\n",
            "context/memory/index/bm25.py": "from grace.cli.data import download\n",
            "paths.py": "import os\n",
            "eval/engines/baselines/mem0.py": "from openai import OpenAI\n",
        }
        for relative, source in cases.items():
            with self.subTest(module=relative):
                found = self.check({relative: source})
                self.assertEqual(len(found), 1, found)

    def test_first_forbidden_import_fails_the_real_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in (SRC / "grace").rglob("*.py"):
                target = root / path.relative_to(SRC)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(violations(root), [])
            write_tree(root, {"context/__init__.py": "", "context/api.py": "import grace.eval\n"})
            self.assertEqual(len(violations(root)), 1)


if __name__ == "__main__":
    unittest.main()
