"""Staleness strategies over one claim graph (T019; plan 3.4, 5.4).

Acceptance of T019:

- claim-pattern strategies report no miss against re-querying on fixtures for all seven change
  types (`WorkedExampleTest`, `GeneratedSequenceTest`): the worked example of
  docs/research/change-sequences.md section 6.5 and generated development sequences, read at
  every version and at every third, on the gold graph as stored and on its own-positive
  projection (finding F1);
- each strategy logs dirty marks, rebuilds and database time separately (`LogTest`).

Also covered: the expected misses of the two citation-based strategies (plan 3.4, "Observation"),
the over-marking ladder predicate level >= claim pattern >= claim pattern with local filters,
equal repairs of pull and hybrid, and whole-history invalidation on an entity merge or a
vocabulary change.

Misses are counted against read-time re-query with fingerprints (`fingerprint_staleness`) of the
views themselves, so they do not depend on whether the views agree with the generator's
reference; `OwnPositiveAgreementTest` checks that agreement separately where F1 does not apply.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path

from grace.cli.data.changeseq_crosscheck import own_positive
from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entities import EntityEquivalence
from grace.context.views.dependencies import NEGATED
from grace.context.views.staleness import (
    SOUND,
    STRATEGIES,
    StrategyError,
    load_arms,
    make_arm,
    make_strategy,
)
from grace.context.views.staleness.base import REBUILDS
from grace.context.views.staleness.pattern import ClaimPatternPush
from grace.context.views.store import CITATION_REPAIR, FULL_REBUILD, ViewStore
from grace.eval.datasets.changeseq.build import generate_sequence
from grace.eval.datasets.changeseq.template_families import CellConfig, load_split
from tests.integration.staleness_replay import CHANGE_TYPES, Sequence, replay
from tests.integration.views_fixture import HISTORY, build_store
from tests.unit.test_changeseq_worked_example import BINDINGS, WORLD, worked_example

ARMS = tuple(load_arms())
SOUND_ARMS = tuple(a for a in ARMS if load_arms()[a][0] in SOUND)
CLAIM_PATTERN_ARMS = ("claim_pattern", "claim_pattern_filters", "push_confirm")


def worked() -> Sequence:
    return Sequence.from_log(worked_example(), WORLD, BINDINGS, "t019-worked")


def generated(family: str, seed: int) -> tuple[Sequence, object]:
    cell = CellConfig(family=family, length=60, density=30.0, mention_rate=20.0)
    bundle = generate_sequence(family, cell, seed, f"t019-{family}-{seed}", validate=None)
    seq = Sequence.from_log(bundle.plan.log, bundle.plan.world, bundle.plan.bindings(),
                            f"t019-{family}-{seed}", labels=bundle.gold.labels)
    return seq, bundle


def projected(seq: Sequence, bundle) -> Sequence:
    graph = own_positive(bundle.store)
    return Sequence(seq.history_id, tuple(graph.changesets()), seq.bindings, seq.gold_ids,
                    seq.types, seq.config)


def marked(result) -> set[tuple[int, str]]:
    return {(w.version, m.view_id) for w in result.strategy.log.writes() for m in w.marks}


def repairs(result) -> list[set[tuple[str, str]]]:
    return [{(c.view_id, c.action) for c in r.checks if c.action in (*REBUILDS, CITATION_REPAIR)}
            for r in result.strategy.log.reads()]


class RegistryTest(unittest.TestCase):
    def test_eight_strategies_and_their_arms(self):
        self.assertEqual(len(STRATEGIES), 8)
        self.assertEqual({name for name, _ in load_arms().values()}, set(STRATEGIES))

    def test_unknown_names_and_options_are_refused(self):
        store = ViewStore("x")
        with self.assertRaises(StrategyError):
            make_strategy("nope", store)
        with self.assertRaises(StrategyError):
            make_strategy("requery", store, local_filters=True)

    def test_write_before_commit_is_refused(self):
        graph = build_store(upto=3)
        strategy = make_arm("push_confirm", ViewStore(HISTORY))
        with self.assertRaises(StrategyError):
            strategy.write(ChangeSet(HISTORY, 4), graph)


class WorkedExampleTest(unittest.TestCase):
    """Section 6.5: eight messages, every change type C1-C7 once or more."""

    @classmethod
    def setUpClass(cls):
        cls.seq = worked()
        cls.runs = {(arm, every, mode): replay(cls.seq, arm, read_every=every, mode=mode)
                    for arm in ARMS for every in (1, 3) for mode in ("rdf11", "rdf12")}

    def test_fixture_has_all_seven_change_types(self):
        self.assertEqual(set(self.seq.types.values()), set(CHANGE_TYPES))

    def test_sound_strategies_never_miss(self):
        for (arm, every, mode), run in self.runs.items():
            if arm in SOUND_ARMS:
                with self.subTest(arm=arm, every=every, mode=mode):
                    self.assertEqual(run.misses(), [])
                    self.assertEqual(run.types_seen(), set(CHANGE_TYPES))
                    if arm != "rebuild_every_turn":  # it repairs at write time
                        self.assertEqual(run.types_stale(), set(CHANGE_TYPES) - {"C7"})

    def test_negative_control_push_without_negated_patterns_misses(self):
        """The miss count is not vacuous: dropping the patterns inside NOT EXISTS is caught."""

        class NoNegation(ClaimPatternPush):
            def _marks(self, changeset, views):
                views = [replace(v, dependencies=tuple(d for d in v.dependencies
                                                       if d.role != NEGATED)) for v in views]
                return super()._marks(changeset, views)

        run = replay(self.seq, NoNegation)
        self.assertIn((4, "pending:k1"), {(i.version, i.view_id) for i in run.misses()})

    def test_never_invalidate_misses(self):
        run = self.runs[("never_invalidate", 1, "rdf11")]
        self.assertTrue(run.misses())
        self.assertEqual(run.strategy.log.summary()["maintenance"], {})

    def step(self, arm, t, **options):
        """Views built at t - 1, one write, one read at t: (reference, maintained) per view."""
        from grace.context.views.staleness import make_strategy as make
        name, base = load_arms()[arm]
        run = replay(self.seq, lambda store: make(name, store, **{**base, **options}),
                     start=t - 1, stop=t)
        return {i.view_id: (i.reference, i.maintained) for i in run.instances}

    def test_used_claims_only_misses_new_matches_negation_hits_and_members(self):
        # C2 new match (t=1), C3 negation hit by an acceptance (t=4), C4 count (t=5).
        self.assertEqual(self.step("used_claims", 1)["current:user:livesIn"], ("answer", False))
        self.assertEqual(self.step("used_claims", 4)["pending:k1"], ("answer", False))
        self.assertEqual(self.step("used_claims", 5)["count:user:playsInstrument"],
                         ("answer", False))
        # C1 (t=7) and C5 (t=8) supersede a used claim and are caught.
        self.assertEqual(self.step("used_claims", 7)["current:user:livesIn"], ("answer", True))
        self.assertEqual(self.step("used_claims", 8)["current:user:livesIn"],
                         ("citation", True))

    def test_negation_and_aggregation_patterns_close_two_of_the_gaps(self):
        self.assertEqual(self.step("used_claims_patterns", 4)["pending:k1"], ("answer", True))
        self.assertEqual(self.step("used_claims_patterns", 5)["count:user:playsInstrument"],
                         ("answer", True))
        # Still misses the new match of a view without aggregation (t=5, list).
        self.assertEqual(self.step("used_claims_patterns", 5)["list:user:playsInstrument"],
                         ("answer", False))

    def test_repeated_mention_needs_watch_mentions(self):
        self.assertEqual(self.step("used_claims", 6)["current:user:livesIn"],
                         ("citation", False))
        self.assertEqual(self.step("used_claims", 6, watch_mentions=True)[
            "current:user:livesIn"], ("citation", True))

    def test_join_without_partner_is_over_marked_by_push_only(self):
        """t=3: the offer carries no acceptance and the arrival has no partner (C7a, C7c)."""
        push = self.step("claim_pattern_filters", 3)["choice:k1"]
        hybrid = self.step("push_confirm", 3)["choice:k1"]
        pull = self.step("requery", 3)["choice:k1"]
        self.assertEqual(push, ("none", True))      # regenerated without confirmation
        self.assertEqual(hybrid, ("none", True))    # re-queried, then only advanced
        self.assertEqual(pull, ("none", True))
        run = replay(self.seq, "push_confirm", start=2, stop=3)
        (check,) = [c for c in run.strategy.log.reads()[0].checks if c.view_id == "choice:k1"]
        self.assertEqual((check.flagged, check.fingerprint, check.action),
                         ("answer", "none", "advance"))


class GeneratedSequenceTest(unittest.TestCase):
    """Development-family sequences with a high revision density (no held-out family)."""

    @classmethod
    def setUpClass(cls):
        split = load_split()
        cls.sequences = []
        for family, seed in ((split.development[0], 11), (split.development[2], 12),
                             (split.development[4], 13)):
            seq, bundle = generated(family, seed)
            cls.sequences.append((family, seed, seq, bundle))

    def test_claim_pattern_strategies_never_miss(self):
        seen, stale = Counter(), set()
        for family, seed, seq, bundle in self.sequences:
            for graph, s in (("full", seq), ("own-positive", projected(seq, bundle))):
                for arm in (*CLAIM_PATTERN_ARMS, "predicate_level", "requery"):
                    for every in (1, 3):
                        run = replay(s, arm, read_every=every)
                        with self.subTest(family=family, seed=seed, graph=graph, arm=arm,
                                          every=every):
                            self.assertEqual(run.misses(), [])
                        if every == 1:
                            seen.update(t for i in run.instances for t in i.change_types)
                            stale |= run.types_stale()
        self.assertEqual(set(seen), set(CHANGE_TYPES))
        self.assertTrue(set(CHANGE_TYPES) - {"C7"} <= stale)

    def test_citation_strategies_miss(self):
        family, seed, seq, _ = self.sequences[0]
        for arm in ("used_claims", "used_claims_patterns", "never_invalidate"):
            with self.subTest(arm=arm):
                self.assertTrue(replay(seq, arm).misses())

    def test_over_marking_ladder(self):
        for family, seed, seq, _ in self.sequences:
            with self.subTest(family=family, seed=seed):
                predicate = marked(replay(seq, "predicate_level"))
                pattern = marked(replay(seq, "claim_pattern"))
                filters = marked(replay(seq, "claim_pattern_filters"))
                self.assertLess(pattern, predicate)
                self.assertLessEqual(filters, pattern)
                self.assertEqual(marked(replay(seq, "push_confirm")), filters)
        # The m-past probe separates the two claim-pattern rungs on at least one sequence.
        self.assertTrue(any(marked(replay(s, "claim_pattern_filters"))
                            < marked(replay(s, "claim_pattern"))
                            for _, _, s, _ in self.sequences))

    def test_marks_ignore_what_the_default_constraint_rejects(self):
        """F1: with the default constraint (own, positive, not derived), the claim-pattern
        strategies mark the same views on the full graph as on its own-positive projection."""
        for family, seed, seq, bundle in self.sequences:
            for arm in CLAIM_PATTERN_ARMS:
                with self.subTest(family=family, seed=seed, arm=arm):
                    self.assertEqual(marked(replay(seq, arm)),
                                     marked(replay(projected(seq, bundle), arm)))

    def test_pull_and_hybrid_make_the_same_repairs(self):
        for family, seed, seq, _ in self.sequences:
            for every in (1, 3):
                with self.subTest(family=family, seed=seed, every=every):
                    pull, hybrid = replay(seq, "requery", read_every=every), replay(
                        seq, "push_confirm", read_every=every)
                    self.assertEqual(repairs(pull), repairs(hybrid))
                    p, h = pull.strategy.log.summary(), hybrid.strategy.log.summary()
                    self.assertEqual(p["units_rendered"], h["units_rendered"])
                    self.assertLess(h["checks"], p["checks"])


class OwnPositiveAgreementTest(unittest.TestCase):
    """Where F1 does not apply, the views' re-query staleness equals the generator's labels."""

    def test_reference_equals_gold_labels(self):
        family = load_split().development[1]
        seq, bundle = generated(family, 21)
        labels = {(x["binding_id"], x["version"]): x for x in bundle.gold.labels}
        run = replay(projected(seq, bundle), "requery")
        for i in run.instances:
            x = labels[(i.binding_id, i.version)]
            gold = "answer" if x["answer_stale"] else "citation" if x["citation_stale"] else "none"
            with self.subTest(view=i.view_id, version=i.version):
                self.assertEqual(i.reference, gold)


class LogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seq = worked()
        cls.runs = {arm: replay(seq, arm) for arm in ARMS}

    def test_summary_keeps_marks_rebuilds_and_times_apart(self):
        keys = {"marks_answer", "marks_citation", "rebuilds", "citation_repairs", "match_ms",
                "check_db_ms", "maintain_db_ms", "maintenance", "checks", "llm_calls"}
        for arm, run in self.runs.items():
            with self.subTest(arm=arm):
                self.assertLessEqual(keys, set(run.strategy.log.summary()))
        s = {arm: run.strategy.log.summary() for arm, run in self.runs.items()}
        # Pull pays its database time in checks; the maintenance reuses the evaluation.
        self.assertGreater(s["requery"]["check_db_ms"], 0)
        self.assertEqual(s["requery"]["maintain_db_ms"], 0)
        self.assertEqual(s["requery"]["marks_answer"] + s["requery"]["marks_citation"], 0)
        # Push pays in maintenance; it never re-queries for a check.
        self.assertEqual(s["claim_pattern_filters"]["checks"], 0)
        self.assertGreater(s["claim_pattern_filters"]["maintain_db_ms"], 0)
        self.assertGreater(s["claim_pattern_filters"]["marks_answer"], 0)
        # Rebuild every turn rebuilds at write time: one full rebuild per view and write.
        self.assertEqual(s["rebuild_every_turn"]["maintenance"],
                         {FULL_REBUILD: 6 * 8})

    def test_marks_name_their_triggers(self):
        writes = self.runs["claim_pattern_filters"].strategy.log.writes()
        (mark,) = [m for m in writes[3].marks if m.view_id == "pending:k1"]   # t = 4
        self.assertEqual(mark.level, "answer")
        self.assertIn("attribution:a6@1/negated", mark.triggers)

    def test_log_is_saved_as_jsonl(self):
        log = self.runs["push_confirm"].strategy.log
        with tempfile.TemporaryDirectory() as tmp:
            path = log.save(Path(tmp) / "staleness.jsonl")
            records = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(Counter(r["kind"] for r in records),
                         {"write": 8, "read": 8, "summary": 1})
        self.assertEqual(records[-1]["strategy"], "push_confirm")
        read = next(r for r in records if r["kind"] == "read")
        self.assertLessEqual({"flagged", "checked", "fingerprint", "check_db_ms", "action",
                              "maintain_db_ms"}, set(read["checks"][0]))


class InvalidationTest(unittest.TestCase):
    """A vocabulary change or an entity merge invalidates every resident view (plan 5.2)."""

    def setup(self, arm):
        graph = build_store()
        store = ViewStore(HISTORY)
        store.materialise(graph)
        strategy = make_arm(arm, store)
        strategy.prime(graph.changesets())
        return graph, store, strategy

    def commit_and_read(self, graph, strategy, cs):
        graph.commit(cs)
        record = strategy.write(cs, graph)
        return record, strategy.read(graph, cs.version, read_id=f"r{cs.version}")

    def test_entity_merge(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                graph, store, strategy = self.setup(arm)
                merge = ChangeSet(HISTORY, 16, entity_merges=(
                    EntityEquivalence("q_mel", "melanie", "mel", 16),))
                write, read = self.commit_and_read(graph, strategy, merge)
                self.assertTrue(write.invalidated)
                actions = {c.action for c in read.checks} | {
                    e.action for e in write.maintenance}
                if arm == "never_invalidate":
                    self.assertEqual(actions, {None})
                    self.assertTrue(all(store.flags(v.view_id).invalid for v in store.views()))
                elif arm == "rebuild_every_turn":
                    self.assertEqual(len(write.maintenance), len(store))
                else:
                    self.assertEqual(actions, {FULL_REBUILD})
                    self.assertEqual(len(read.maintained()), len(store))

    def test_vocabulary_change(self):
        graph, store, strategy = self.setup("push_confirm")
        first, _ = self.commit_and_read(graph, strategy,
                                        ChangeSet(HISTORY, 16, vocabulary_version="v1"))
        self.assertFalse(first.invalidated)
        second, read = self.commit_and_read(graph, strategy,
                                            ChangeSet(HISTORY, 17, vocabulary_version="v2"))
        self.assertTrue(second.invalidated)
        self.assertEqual({c.action for c in read.checks}, {FULL_REBUILD})


if __name__ == "__main__":
    unittest.main()
