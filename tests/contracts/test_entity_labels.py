"""Entity labels in the claim graph (contracts.md, "Claim graph", version 0.3).

User decision of 2026-11-26 (T014 follow-up): the surface name an entity ID was made from is part
of the claim graph, as a versioned `EntityLabel` entry. Covered here:

- the entry and change-set records, and backward compatibility (a change set without labels is
  stored byte for byte as before 0.3; a record without `entity_labels` is valid);
- the RDF mapping (`gx:label/<id> g:labelOf <entity> ; rdfs:label "name"`), exact both ways in
  both serialisations;
- version stability (a read at a cut-off before the label sees none), write-once labels, save and
  restore, SHACL;
- entity merges (`display_name` follows the representative; labels are never rewritten);
- labels are display data: compiled query results and their answer, witness and evidence
  fingerprints are identical with and without labels, on the worked example and on a generated
  change sequence (the gold graphs of E004 and E005), and a labels-only change set invalidates or
  marks no view under any staleness arm;
- generated change sequences carry no labels, so their stored graphs need no regeneration.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pyoxigraph as ox

from grace.cli.data.changeseq_crosscheck import canonical, view_query
from grace.context.memory.graph import rdf
from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entities import (
    EntityEquivalence,
    EntityLabel,
    display_name,
    labels_at,
)
from grace.context.memory.graph.entries import Entity, EntryError
from grace.context.memory.graph.store import ClaimStore, CommitError
from grace.context.pipeline.query.compile import compile_query
from grace.context.pipeline.query.execute import execute
from grace.eval.datasets.changeseq import gold
from grace.eval.datasets.changeseq.build import generate_sequence
from grace.eval.datasets.changeseq.template_families import CellConfig, load_split
from tests.unit.test_changeseq_worked_example import BINDINGS, WORLD, worked_example

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "graph"
WORKED = FIXTURE / "worked-example"
LABELS = FIXTURE / "entity-labels"
MODES = ("rdf11", "rdf12")


def named(cs: ChangeSet) -> set[str]:
    out = {c.subject for c in cs.claims}
    out |= {c.object.id for c in cs.claims if isinstance(c.object, Entity)}
    out |= {a.speaker for a in cs.attributions}
    out |= {e for q in cs.entity_merges for e in (q.entity_a, q.entity_b)}
    return out


def labelled(store: ClaimStore) -> ClaimStore:
    """The same change sets, each with a label for every entity it names first."""
    out = ClaimStore(store.history_id, store.mode)
    seen: set[str] = set()
    for cs in store.changesets():
        new = sorted(named(cs) - seen)
        seen |= set(new)
        labels = tuple(EntityLabel(f"l{cs.version}.{i}", e, f"Name of {e}!", cs.version)
                       for i, e in enumerate(new, start=1))
        out.commit(replace(cs, entity_labels=labels))
    return out


def worked_store(mode: str = "rdf11") -> ClaimStore:
    store = ClaimStore("change-seq-worked-example", mode)
    for line in (WORKED / "changesets.jsonl").read_text(encoding="utf-8").splitlines():
        store.commit(ChangeSet.from_json(line))
    return store


def fixture_store(mode: str = "rdf11") -> ClaimStore:
    store = ClaimStore("entity-labels", mode)
    for line in (LABELS / "changesets.jsonl").read_text(encoding="utf-8").splitlines():
        store.commit(ChangeSet.from_json(line))
    return store


class EntryRecordTest(unittest.TestCase):
    def test_round_trip_and_field_checks(self):
        x = EntityLabel("l1.1", "Carolines_mom", "Caroline's mom", 1)
        self.assertEqual(x.to_record(), {"label_id": "l1.1", "entity": "Carolines_mom",
                                         "label": "Caroline's mom", "version": 1})
        self.assertEqual(EntityLabel.from_record(x.to_record()), x)
        self.assertEqual(x.entry_id, "l1.1")
        for bad in ({**x.to_record(), "extra": 1}, {"label_id": "l", "entity": "e",
                                                     "version": 1}):
            with self.assertRaises(EntryError):
                EntityLabel.from_record(bad)
        for label in ("", " padded", "padded ", 3):
            with self.assertRaises(EntryError):
                EntityLabel("l1", "e", label, 1)
        with self.assertRaises(EntryError):
            EntityLabel("l1", "e", "E", 0)


class ChangeSetTest(unittest.TestCase):
    def test_change_sets_without_labels_serialise_as_before(self):
        for line in (WORKED / "changesets.jsonl").read_text(encoding="utf-8").splitlines():
            cs = ChangeSet.from_json(line)
            self.assertEqual(cs.entity_labels, ())
            self.assertEqual(cs.to_json(), line)
            self.assertNotIn("entity_labels", cs.to_record())

    def test_labels_round_trip_and_sort(self):
        cs = ChangeSet("h", 2, entity_labels=(EntityLabel("l2.2", "b", "B", 2),
                                              EntityLabel("l2.1", "a", "A", 2)))
        record = cs.to_record()
        self.assertEqual([x["label_id"] for x in record["entity_labels"]], ["l2.1", "l2.2"])
        self.assertEqual(ChangeSet.from_record(record), cs.canonical())
        self.assertFalse(cs.empty)
        self.assertEqual(cs.touched_claim_ids(), frozenset())
        # an explicit empty list is accepted and dropped on output
        bare = {**ChangeSet("h", 3).to_record(), "entity_labels": []}
        self.assertEqual(ChangeSet.from_record(bare).to_record(), ChangeSet("h", 3).to_record())

    def test_change_set_checks(self):
        with self.assertRaises(EntryError):       # stamp differs from the change set
            ChangeSet("h", 2, entity_labels=(EntityLabel("l", "a", "A", 1),))
        with self.assertRaises(EntryError):       # two labels for one entity
            ChangeSet("h", 2, entity_labels=(EntityLabel("l1", "a", "A", 2),
                                             EntityLabel("l2", "a", "A2", 2)))
        with self.assertRaises(EntryError):       # IDs unique across kinds
            ChangeSet("h", 2, entity_merges=(EntityEquivalence("x", "a", "b", 2),),
                      entity_labels=(EntityLabel("x", "a", "A", 2),))
        with self.assertRaises(EntryError):
            ChangeSet.from_record({**ChangeSet("h", 2).to_record(), "entity_labels": {}})


class RdfMappingTest(unittest.TestCase):
    def test_triples(self):
        x = EntityLabel("l 1", "José", "José Pérez", 4)
        triples = rdf.entry_triples(x)
        node = rdf.entry_iri(EntityLabel, "l 1")
        self.assertEqual(node.value, "https://example.org/grace/entry/label/l%201")
        self.assertEqual(set(triples), {
            ox.Triple(node, rdf.A, rdf.G["EntityLabel"]),
            ox.Triple(node, rdf.KNOWN_FROM, ox.Literal("4", datatype=ox.NamedNode(
                "http://www.w3.org/2001/XMLSchema#integer"))),
            ox.Triple(node, rdf.G["labelOf"], rdf.entity_iri("José")),
            ox.Triple(node, rdf.RDFS_LABEL, ox.Literal("José Pérez"))})
        self.assertEqual(rdf.entry_triples(x, "rdf12"), triples)
        self.assertEqual(rdf.entries_from_triples(triples), [x])

    def test_fixture_round_trip_is_exact_in_both_modes(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                store = fixture_store(mode)
                text = rdf.to_ntriples(store.triples())
                self.assertEqual(text, (LABELS / f"{mode}.nt").read_text(encoding="utf-8"))
                parsed = rdf.changesets_from_triples(
                    rdf.parse(text), store.history_id,
                    {cs.version: cs.vocabulary_version for cs in store.changesets()})
                self.assertEqual(parsed, [cs.canonical() for cs in store.changesets()])
                other = "rdf12" if mode == "rdf11" else "rdf11"
                back = rdf.convert(rdf.convert(rdf.parse(text), other), mode)
                self.assertEqual(rdf.to_ntriples(back), text)

    def test_parsing_rejects_what_the_mapping_never_produces(self):
        x = EntityLabel("l1", "e", "E", 1)
        node = rdf.entry_iri(EntityLabel, "l1")
        base = rdf.entry_triples(x)
        bad = {
            "language tag": [t for t in base if t.predicate != rdf.RDFS_LABEL]
            + [ox.Triple(node, rdf.RDFS_LABEL, ox.Literal("E", language="en"))],
            "no label": [t for t in base if t.predicate != rdf.RDFS_LABEL],
            "no entity": [t for t in base if t.predicate != rdf.G["labelOf"]],
            "two labels": base + [ox.Triple(node, rdf.RDFS_LABEL, ox.Literal("F"))],
            "literal entity": [t for t in base if t.predicate != rdf.G["labelOf"]]
            + [ox.Triple(node, rdf.G["labelOf"], ox.Literal("e"))],
            "extra triple": base + [ox.Triple(node, rdf.G["scope"], ox.Literal("s"))],
            "label on the entity node": base + [
                ox.Triple(rdf.entity_iri("e"), rdf.RDFS_LABEL, ox.Literal("E"))],
        }
        for name, triples in bad.items():
            with self.subTest(name), self.assertRaises(rdf.RdfError):
                rdf.entries_from_triples(triples)


class StoreTest(unittest.TestCase):
    def test_reads_at_earlier_cutoffs_are_stable(self):
        plain, store = worked_store(), labelled(worked_store())
        for v in range(store.head + 1):
            expected = {e: f"Name of {e}!" for cs in plain.changesets(upto=v) for e in named(cs)}
            self.assertEqual(store.state(v).entity_labels(), expected)
            self.assertEqual(plain.state(v).entity_labels(), {})
            # every other entry is unchanged
            for kind in ("claims", "attributions", "evidence_links", "supersessions",
                         "equivalences"):
                self.assertEqual(dict(getattr(store.state(v), kind)),
                                 dict(getattr(plain.state(v), kind)))
        self.assertNotIn("Cologne", store.state(6).entity_labels())
        self.assertEqual(store.state(7).entity_labels()["Cologne"], "Name of Cologne!")

    def test_sparql_at_a_cutoff(self):
        store = fixture_store()
        sparql = """SELECT ?e ?name WHERE { ?l a g:EntityLabel ; g:labelOf ?e ; rdfs:label ?name ;
                    g:knownFrom ?v . FILTER(?v <= %r%) }"""
        got = {v: {(r["e"].value.rsplit("/", 1)[1], r["name"].value)
                   for r in store.query(sparql, v)} for v in range(store.head + 1)}
        for v in range(store.head + 1):
            self.assertEqual(dict(got[v]), store.state(v).entity_labels())

    def test_labels_are_written_once(self):
        store = fixture_store()
        head, triples = store.head, rdf.to_ntriples(store.triples())
        entity = next(iter(store.state(head).entity_labels()))
        for label in ("Another name", store.state(head).entity_labels()[entity]):
            with self.subTest(label=label), self.assertRaises(CommitError):
                store.commit(ChangeSet(store.history_id, head + 1, entity_labels=(
                    EntityLabel("l-again", entity, label, head + 1),)))
        self.assertEqual((store.head, rdf.to_ntriples(store.triples())), (head, triples))

    def test_save_restore_and_shacl(self):
        store = fixture_store()
        with tempfile.TemporaryDirectory() as tmp:
            store.save(Path(tmp) / "s")
            again = ClaimStore.restore(Path(tmp) / "s")
        self.assertEqual(again.state(again.head).entity_labels(),
                         store.state(store.head).entity_labels())
        for cs in store.changesets():
            self.assertTrue(store.validate(cs).conforms, cs.version)
        fresh = ClaimStore("entity-labels")
        for cs in store.changesets():
            fresh.commit(cs, validate=True)


class MergeTest(unittest.TestCase):
    """An entity merge never rewrites a label; `display_name` follows the representative."""

    def test_display_name(self):
        labels = {"Mel": "Mel", "melanie_2": "Melanie (sister)"}
        reps = {"Mel": "Mel", "melanie": "Mel", "melanie_2": "Mel", "zed": "Mel"}
        self.assertEqual(display_name("melanie_2", labels, reps), "Melanie (sister)")  # own
        self.assertEqual(display_name("melanie", labels, reps), "Mel")   # representative
        self.assertEqual(display_name("nobody", labels, reps), "nobody")
        reps2 = {"a": "a", "b": "a", "c": "a"}
        self.assertEqual(display_name("a", {"c": "C", "b": "B"}, reps2), "B")  # smallest member

    def test_merge_in_the_store(self):
        store = ClaimStore("merge")
        store.commit(ChangeSet("merge", 1, entity_labels=(
            EntityLabel("l1.1", "melanie", "Melanie", 1),)))
        store.commit(ChangeSet("merge", 2, entity_labels=(
            EntityLabel("l2.1", "Mel", "Mel B.", 2),)))
        store.commit(ChangeSet("merge", 3, entity_merges=(
            EntityEquivalence("q3.1", "melanie", "Mel", 3),)))
        before, after = store.state(2), store.state(3)
        self.assertEqual(before.entity_labels(), after.entity_labels())   # nothing rewritten
        self.assertEqual(before.display_name("melanie"), "Melanie")
        self.assertEqual(after.display_name("melanie"), "Melanie")        # own label first
        self.assertEqual(after.representatives()["melanie"], "Mel")
        self.assertEqual(after.display_name("Mel"), "Mel B.")
        self.assertEqual(store.state(1).display_name("Mel"), "Mel")       # not yet labelled

    def test_labels_at_is_deterministic(self):
        items = [EntityLabel("l3", "e", "late", 3), EntityLabel("l2b", "e", "b", 2),
                 EntityLabel("l2a", "e", "a", 2)]
        self.assertEqual(labels_at(items, 1), {})
        self.assertEqual(labels_at(items, 9), {"e": "a"})
        self.assertEqual(labels_at(reversed(items), 9), {"e": "a"})


def compare_results(test: unittest.TestCase, plain: ClaimStore, store: ClaimStore,
                    bindings, world) -> int:
    n = 0
    for b in bindings:
        compiled = compile_query(view_query(b, world), plain.mode)
        for t in range(plain.head + 1):
            r0, r1 = execute(compiled, plain, t), execute(compiled, store, t)
            test.assertEqual(r1.fingerprints(), r0.fingerprints(), (b.binding_id, t))
            test.assertEqual(canonical(r1), canonical(r0), (b.binding_id, t))
            n += 1
    return n


class FingerprintTest(unittest.TestCase):
    """Labels enter no answer, witness, evidence or fingerprint (they are display data)."""

    def test_worked_example(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                plain = gold.build_store(worked_example(), "fp-worked", validate=None)
                if mode != plain.mode:
                    plain2 = ClaimStore(plain.history_id, mode)
                    for cs in plain.changesets():
                        plain2.commit(cs)
                    plain = plain2
                store = labelled(plain)
                self.assertTrue(any(cs.entity_labels for cs in store.changesets()))
                self.assertEqual(compare_results(self, plain, store, BINDINGS, WORLD),
                                 len(BINDINGS) * (plain.head + 1))

    def test_generated_sequence(self):
        family = load_split().development[0]
        cell = CellConfig(family=family, length=40, density=30.0, mention_rate=20.0)
        bundle = generate_sequence(family, cell, 11, "labels-dev", validate=None)
        # generated graphs carry no labels: their stored form is unchanged by version 0.3
        for cs in bundle.store.changesets():
            self.assertEqual(cs.entity_labels, ())
            self.assertNotIn("entity_labels", json.loads(cs.to_json()))
        store = labelled(bundle.store)
        self.assertGreater(len(store.state(store.head).entity_labels()), 3)
        self.assertGreater(compare_results(self, bundle.store, store,
                                           bundle.plan.bindings(), bundle.plan.world), 0)


class StalenessTest(unittest.TestCase):
    """A labels-only change set invalidates and marks no view under any arm."""

    def test_labels_only_change_set(self):
        from grace.context.views.staleness import load_arms, make_arm
        from grace.context.views.staleness.base import fingerprint_staleness
        from grace.context.views.store import ViewStore
        from tests.integration.views_fixture import HISTORY, build_store

        for arm in load_arms():
            with self.subTest(arm=arm):
                graph = build_store()
                store = ViewStore(HISTORY)
                store.materialise(graph)
                before = {v.view_id: dict(v.fingerprints) for v in store.views()}
                strategy = make_arm(arm, store)
                strategy.prime(graph.changesets())
                entity = sorted({c.subject for c in graph.state(graph.head).claims.values()})[0]
                version = graph.head + 1
                cs = ChangeSet(HISTORY, version, entity_labels=(
                    EntityLabel(f"l{version}.1", entity, "A display name", version),))
                graph.commit(cs)
                write = strategy.write(cs, graph)
                self.assertFalse(write.invalidated)
                if arm == "rebuild_every_turn":   # rebuilds every view on every write by design
                    self.assertEqual({m.triggers for m in write.marks}, {("every-turn",)})
                    continue
                self.assertEqual(write.marks, [])
                for view_id, fps in before.items():
                    flags = store.flags(view_id)
                    self.assertFalse(flags.invalid or flags.answer_stale or flags.citation_stale)
                    self.assertFalse(fingerprint_staleness(store, view_id, graph, version).stale)
                    self.assertEqual(dict(store.get(view_id).fingerprints), fps)


if __name__ == "__main__":
    unittest.main()
