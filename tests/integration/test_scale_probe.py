"""E004 scale probe: synthetic graphs, the measurement loop, the run driver and its summary.

Checks that the scaled graph is a faithful union of independent generated sequences (a view of a
block has the same answers, witnesses and evidence on the interleaved graph as on its block
alone), that forking a store copies it independently, that pull and hybrid repair exactly the same
views while push repairs at least those, and that a tiny run of `grace.cli.scale` completes and is
summarised without differences between pull and hybrid.
"""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import yaml

from grace.cli import scale as cli
from grace.context.memory.graph.store import ClaimStore
from grace.context.views.rebuild import Compiled, evaluate
from grace.context.views.store import ViewStore
from grace.context.views.template_families import ViewConfig
from grace.eval.analysis.metrics import scale as analysis
from grace.eval.runner.harness.rundir import CodeState
from grace.eval.runner.probes import scale

FAMILIES = ("hotel-stay", "apartment-search", "train-travel", "flight-travel", "car-rental")
CONFIG = Path(__file__).resolve().parents[2] / "configs" / "experiments" / \
    "E004-scale-experiment.yaml"
B, L, P = 3, 60, 30


def blocks(n: int = B, seed: int = 7) -> list[scale.Block]:
    return [scale.generate_block(i, master_seed=seed, length=L, density=30.0, families=FAMILIES)
            for i in range(n)]


class GraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blocks = blocks()
        cls.graph = scale.build_graph(cls.blocks, P, "e004-test")

    def test_blocks_share_no_entity_or_entry(self):
        def ids(block):
            out = set()
            for cs in block.changesets:
                for e in cs.entries():
                    out.add(e.entry_id)
                for c in cs.claims:
                    out.add(c.subject)
            return out
        a, b = ids(self.blocks[0]), ids(self.blocks[1])
        self.assertTrue(a and b)
        self.assertEqual(a & b, set())
        speakers = {a.speaker for cs in self.blocks[0].changesets for a in cs.attributions}
        self.assertLessEqual(speakers, {"user", "assistant"})

    def test_interleaving_and_sizes(self):
        g = self.graph
        self.assertEqual(len(g.prefix), B * P)
        self.assertEqual(len(g.window), B * (L - P))
        self.assertEqual(g.store.head, B * P)
        self.assertEqual([cs.version for cs in g.window], list(range(B * P + 1, B * L + 1)))
        self.assertEqual(g.size()["bindings"], 15 * B)
        self.assertEqual(sum(scale.BINDINGS_PER_BLOCK.values()), 15)
        self.assertEqual(len(scale.admitted(g.bindings, ["list", "current", "count",
                                                         "constraints", "choice"])), 12 * B)

    def test_views_agree_with_the_block_alone(self):
        config = ViewConfig(state_speaker="user")
        views = ViewStore(self.graph.history_id, config=config)
        for index in (0, 2):
            block = self.blocks[index]
            alone = ClaimStore(block.sequence_id)
            for cs in block.changesets[:P]:
                alone.commit(cs)
            for b in block.bindings:
                query, _ = views.bind(b)
                compiled = Compiled.of(query, "rdf11")
                mine = evaluate(compiled, self.graph.store, self.graph.store.head).result
                ref = evaluate(compiled, alone, alone.head).result
                with self.subTest(view=b.view_id):
                    self.assertEqual(mine.fingerprints(), ref.fingerprints())

    def test_fork_is_independent(self):
        g = self.graph
        copy = scale.fork_store(g.store)
        self.assertEqual(copy.head, g.store.head)
        self.assertEqual(len(copy.graph), len(g.store.graph))
        self.assertEqual(copy.changesets(), g.store.changesets())
        copy.commit(g.window[0])
        self.assertEqual(g.store.head, B * P)
        self.assertEqual(copy.head, B * P + 1)
        other = scale.fork_store(g.store)  # the original is still at the prefix head
        other.commit(g.window[0])
        self.assertEqual(len(other.graph), len(copy.graph))

    def test_choose_views_is_nested_and_read_sets_are_seeded(self):
        bindings = self.graph.bindings
        small, large = (scale.choose_views(bindings, n, 3) for n in (5, 20))
        self.assertEqual(large[:5], small)
        with self.assertRaises(scale.ScaleError):
            scale.choose_views(bindings, len(bindings) + 1, 3)
        ids = [b.view_id for b in large]
        self.assertEqual(scale.read_sets(ids, 4, 6, 1), scale.read_sets(ids, 4, 6, 1))
        self.assertEqual(scale.read_sets(ids, "all", 2, 1), [None, None])
        self.assertTrue(all(len(s) == 4 for s in scale.read_sets(ids, 4, 6, 1)))

    def test_inlined_constants_return_the_same_rows(self):
        diagnostics = scale.query_diagnostics(self.graph, self.blocks[0].bindings,
                                              compiled_families=scale.FAMILY.values(),
                                              repeats=1)
        self.assertEqual(len(diagnostics), 15)
        for d in diagnostics:
            with self.subTest(view=d["view_id"]):
                self.assertEqual(d["compiled_rows"], d["inlined_rows"])
        sparql = 'SELECT ?x WHERE {\n  VALUES ?_k0 { <urn:a> }\n  ?x <urn:p> ?_k0 .\n}'
        self.assertEqual(scale.inline_constants(sparql),
                         'SELECT ?x WHERE {\n  ?x <urn:p> <urn:a> .\n}')


class MeasureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = scale.build_graph(blocks(), P, "e004-measure")
        cls.views = scale.choose_views(cls.graph.bindings, 30, 1)

    def run_arms(self, scope, w, reads=6):
        sets = scale.read_sets([b.view_id for b in self.views], scope, reads, 1)
        return {arm: scale.measure(self.graph, self.views, arm, writes_per_read=w, reads=reads,
                                   scope_sets=sets)
                for arm in ("claim_pattern_filters", "requery", "push_confirm")}

    def test_pull_and_hybrid_repair_the_same_views(self):
        for scope, w in (("all", 1), ("all", 8), (4, 4)):
            with self.subTest(scope=scope, w=w):
                m = self.run_arms(scope, w)
                pull = scale.repair_signature(m["requery"].periods)
                self.assertEqual(scale.repair_signature(m["push_confirm"].periods), pull)
                push = [{v for v, _ in p} for p in scale.repair_signature(
                    m["claim_pattern_filters"].periods)]
                for mine, ref in zip(push, pull, strict=True):
                    self.assertLessEqual({v for v, _ in ref}, mine)
                for arm in m.values():
                    self.assertEqual(arm.summary["llm_calls"], 0)
                pull_summary = m["requery"].summary
                self.assertEqual(pull_summary["marks_answer"] + pull_summary["marks_citation"], 0)
                self.assertLess(pull_summary["match_ms"], m["push_confirm"].summary["match_ms"])
                self.assertTrue(any(p.repairs for p in m["requery"].periods) or w == 1)

    def test_pull_checks_every_view_read(self):
        m = self.run_arms("all", 2, reads=3)
        self.assertTrue(all(p.checks == 30 for p in m["requery"].periods))
        self.assertTrue(all(p.checks <= p.views_read for p in m["push_confirm"].periods))
        self.assertTrue(all(p.check_db_ms == 0 for p in m["claim_pattern_filters"].periods))

    def test_window_too_short(self):
        with self.assertRaises(scale.ScaleError):
            scale.measure(self.graph, self.views, "requery", writes_per_read=1000, reads=2,
                          scope_sets=[None, None])


class CrossingTest(unittest.TestCase):
    def test_crossing(self):
        self.assertEqual(analysis.crossing([1, 4, 16], [-1, -0.5, -0.1]),
                         ("cheaper_everywhere", None))
        self.assertEqual(analysis.crossing([1, 4, 16], [1, 2, 3]), ("dearer_everywhere", None))
        kind, x = analysis.crossing([1, 4, 16], [-1, -1, 1])
        self.assertEqual(kind, "crosses")
        self.assertAlmostEqual(x, 8.0)
        kind, x = analysis.crossing([1, 100], [-math.log(2), math.log(2)])
        self.assertAlmostEqual(x, 10.0)


class DriverTest(unittest.TestCase):
    def test_tiny_run_and_summary(self):
        config = cli.load_experiment(CONFIG)
        config.update(
            generator={**config["generator"], "block_length": 60, "prefix_length": 30},
            graphs=[{"mix": "six", "blocks": [2], "views": [6]}], seeds=[5], repetitions=2,
            reads=3, grid={"read_scope": [4, "all"], "writes_per_read": [1, 8, 64]},
            diagnostics={"repeats": 1, "compiled_pending_max_blocks": 16})
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, status = cli.run_one(CONFIG, "six", 2, 5, 6, root=Path(tmp),
                                          code=CodeState("0" * 40, False), command="test",
                                          config=config)
            self.assertEqual(status, "completed")
            run = json.loads((run_dir / "run.json").read_text())
            graph = json.loads((run_dir / "graph.json").read_text())
            self.assertEqual(graph["skipped_cells"], [{"read_scope": 4, "writes_per_read": 64},
                                                      {"read_scope": "all",
                                                       "writes_per_read": 64}])
            self.assertEqual(run["n_records"], 2 * 2 * 2 * 3)
            resolved = yaml.safe_load((run_dir / "resolved-config.yaml").read_text())
            self.assertEqual(resolved["run"], {"mix": "six", "blocks": 2, "seed": 5,
                                               "views": 6})
            machine = json.loads((run_dir / "machine.json").read_text())
            self.assertIn("cpu_model", machine)
            path = analysis.write_summary([run_dir], Path(tmp) / "summary", config)
            summary = json.loads(path.read_text())
            self.assertEqual(summary["n_measurements"], 24)
            self.assertEqual(summary["checks"]["repairs_differ_pull_hybrid"], 0)
            self.assertEqual(summary["checks"]["llm_calls"], 0)
            self.assertEqual(len(summary["cells"]), 4)
            self.assertTrue(summary["crossover_writes_per_read"])
            with self.assertRaises(ValueError):
                cli.run_one(CONFIG, "six", 3, 5, 6, root=Path(tmp), config=config,
                            code=CodeState("0" * 40, False))

    def test_plan_lists_every_run(self):
        lines = cli.plan_lines(CONFIG)
        config = cli.load_experiment(CONFIG)
        self.assertEqual(len(lines), len(cli.runs(config)))
        self.assertEqual(len(lines), 2 * (3 * 4 - 1 + 2 * 2))  # 768 views need 64 blocks


if __name__ == "__main__":
    unittest.main()
