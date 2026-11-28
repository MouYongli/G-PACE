"""E006 graph-quality scorer (eval/analysis/metrics/graph.py) on a synthetic writer run.

Synthetic segments, labels and change sets only; no benchmark data and no model calls.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from grace.eval.analysis.annotation import graph_quality as gq
from grace.eval.analysis.metrics import graph as g

SEG = "locomo:h1:s1:1-3"
TEXT = {"m1": "I moved to Porto last month.", "m2": "My sister Ana plays the cello.",
        "m3": "Yes, Porto is lovely, I live there now."}
SEGMENTS = {SEG: gq.SegmentText(SEG, "locomo", {
    mid: {"message_id": mid, "role": "peer", "text": t} for mid, t in TEXT.items()})}
HISTORY_OF = {SEG: "h1"}


def label(cid, mid, subject, predicate, obj, quote, annotator, **extra):
    record = {"segment": SEG, "annotator": annotator, "kind": "claim", "id": cid,
              "message_id": mid, "subject": subject, "predicate": predicate, "object": obj,
              "object_type": "entity", "speaker": "Ben", "function": "inform",
              "report_mode": "own", "polarity": "positive", "certainty": "certain",
              "derived": False, "correction": False, "time_expression": None,
              "valid_from": None, "valid_until": None, "quote": quote}
    record.update(extra)
    return record


A = [label("c1", "m1", "Ben", "movedTo", "Porto", "I moved to Porto", "A",
           time_expression="last month"),
     label("c2", "m2", "Ben's sister", "plays", "cello", "plays the cello", "A"),
     {"segment": SEG, "annotator": "A", "kind": "stance", "message_id": "m3", "claim": "c1",
      "speaker": "Ben", "function": "confirm", "polarity": "positive", "derived": False,
      "ends": None, "valid_until": None, "quote": "I live there now"}]
B = [label("c1", "m1", "Ben", "relocatedTo", "Porto", "I moved to Porto", "B",
           time_expression="last month"),
     label("c2", "m2", "Ben", "hasSister", "Ana", "My sister Ana", "B")]


def changeset(version, claims=(), attributions=(), evidence=(), supersessions=()):
    return {"history_id": "h1", "version": version, "vocabulary_version": "v1",
            "entity_merges": [], "entries": {"claims": list(claims),
                                             "attributions": list(attributions),
                                             "evidence_links": list(evidence),
                                             "supersessions": list(supersessions)}}


def claim(cid, subject, predicate, entity=None, value=None, expression=None):
    obj = {"entity": entity} if entity else {"datatype": "string", "value": value}
    return {"claim_id": cid, "subject": subject, "predicate": predicate, "object": obj,
            "scope": None, "valid_time": {"start": None, "end": None, "expression": expression}}


def attribution(aid, cid, mid, **extra):
    return {"attribution_id": aid, "claim_id": cid, "message_id": mid, "speaker": "Ben",
            "function": "inform", "report_mode": "own", "polarity": "positive",
            "certainty": "certain", "derived": False, **extra}


def write_run(root: Path) -> Path:
    run = root / "writer-run"
    store = run / "graphs" / "h1" / "store"
    store.mkdir(parents=True)
    sets = [
        changeset(1, [claim("c1.1", "Ben", "livesIn", entity="Porto", expression="last month")],
                  [attribution("a1.1", "c1.1", "m1")],
                  [{"claim_id": "c1.1", "message_id": "m1", "span": {"start": 0, "end": 16}}]),
        changeset(2, [claim("c2.1", "Bens_sister", "plays", entity="cello"),
                      claim("c2.2", "Ben", "felt", value="happy")],
                  [attribution("a2.1", "c2.1", "m2"), attribution("a2.2", "c2.2", "m2")],
                  [{"claim_id": "c2.1", "message_id": "m2", "span": {"start": 16, "end": 30}},
                   {"claim_id": "c2.2", "message_id": "m2", "span": None}]),
        changeset(3, [], [attribution("a3.1", "c1.1", "m3")],
                  [{"claim_id": "c1.1", "message_id": "m3", "span": {"start": 21, "end": 37}}]),
    ]
    store.joinpath("changesets.jsonl").write_text(
        "".join(json.dumps(s) + "\n" for s in sets), encoding="utf-8")
    (run / "graphs" / "h1" / "writer.json").write_text(json.dumps(
        {"entity_labels": {"Porto": "Porto", "Bens_sister": "Ben's sister", "cello": "cello"}}),
        encoding="utf-8")
    update = {"history_id": "h1", "message_ids": ["m1", "m2", "m3"],
              "dropped": [{"item": "stance", "reason": "ended_without_evidence",
                           "detail": "c1.1"}]}
    (run / "updates.jsonl").write_text(json.dumps(update) + "\n", encoding="utf-8")
    return run


class ScorerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = g.read_writer_run(write_run(Path(self.tmp.name)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_gold_units_two_files(self):
        units = g.gold_units([A, B], SEGMENTS)[SEG]
        tiers = sorted(u.tier for u in units)
        self.assertEqual(tiers, ["core", "uncertain", "uncertain"])
        core = next(u for u in units if u.tier == "core")
        self.assertEqual(core.messages, {"m1", "m3"})          # claim message + stance message
        self.assertEqual(len(core.variants), 2)
        one = g.gold_units([A], SEGMENTS)[SEG]
        self.assertTrue(all(u.tier == "core" for u in one))

    def test_writer_claims_group_attributions(self):
        ws = g.writer_claims(self.run.graph_for(SEG, "h1"), SEGMENTS[SEG])
        by_id = {w["claim_id"]: w for w in ws}
        self.assertEqual(by_id["c1.1"]["messages"], ["m1", "m3"])
        self.assertEqual(by_id["c2.1"]["subject"], "Ben's sister")
        self.assertEqual(len(by_id["c1.1"]["restatements"]), 1)

    def test_levels_and_bounds(self):
        units = g.gold_units([A, B], SEGMENTS)
        judge_calls = []

        def judge(inputs):
            judge_calls.append(inputs)
            return "same" if {inputs["predicate_a"], inputs["predicate_b"]} & {"movedTo"} \
                else "different"

        matcher = g.PredicateMatcher("judge", judge)
        metrics, rows, gold_rows = g.score(self.run, SEGMENTS, units, matcher, HISTORY_OF)
        c = metrics["all"]
        self.assertEqual((c["writer_claims"], c["gold_core"], c["gold_all"]), (3, 1, 3))
        # anchor: livesIn~core (Ben/Porto), plays~uncertain (sister/cello); felt matches nothing
        self.assertEqual(c["anchor"]["matched_vs_all"], 2)
        self.assertEqual(c["anchor"]["matched_vs_core"], 1)
        self.assertEqual(c["anchor"]["precision"], {"lower": round(1 / 3, 4),
                                                    "upper": round(2 / 3, 4)})
        self.assertEqual(c["anchor"]["recall"], {"lower": round(2 / 3, 4), "upper": 1.0})
        # strict: only plays = plays
        self.assertEqual(c["strict"]["matched_vs_all"], 1)
        self.assertEqual(c["strict"]["matched_vs_core"], 0)
        # loose: the judge accepts livesIn for movedTo
        self.assertEqual(c["loose"]["matched_vs_all"], 2)
        self.assertEqual(c["loose"]["matched_vs_core"], 1)
        self.assertTrue(judge_calls)
        self.assertEqual(c["fields_on_loose_core_matches"]["time_expression"],
                         {"accuracy": 1.0, "n": 1})
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(gold_rows), 3)
        per = g.per_predicate(rows, min_count=1)["predicates"]
        self.assertEqual(per["*catch-all*"]["n"], 1)
        self.assertEqual(per["*catch-all*"]["precision"]["upper"], 0.0)

    def test_reference_file_gives_equal_bounds(self):
        units = g.gold_units([A], SEGMENTS)
        metrics, _, _ = g.score(self.run, SEGMENTS, units, g.PredicateMatcher("lexical"),
                                HISTORY_OF)
        loose = metrics["all"]["loose"]
        self.assertEqual(loose["precision"]["lower"], loose["precision"]["upper"])
        self.assertEqual(loose["recall"]["lower"], loose["recall"]["upper"])

    def test_spans_labels_drops_restatements(self):
        units = g.gold_units([A, B], SEGMENTS)
        by_id = {u.uid: u for us in units.values() for u in us}
        matcher = g.PredicateMatcher("judge", lambda x: "same")
        _, rows, _ = g.score(self.run, SEGMENTS, units, matcher, HISTORY_OF)
        spans = g.span_checks(rows, SEGMENTS, by_id,
                              lambda xs: ["entailed" for _ in xs])
        self.assertEqual(spans["metrics"]["valid_span"], 2)
        self.assertEqual(spans["metrics"]["no_valid_span"], 1)
        self.assertEqual(spans["metrics"]["entailment"]["entailed_rate"], 1.0)
        labels = g.entity_labels(self.run, SEGMENTS, rows, by_id,
                                 {SEG: [*TEXT.values(), "Ben"]})   # texts and speaker names
        self.assertEqual((labels["entities"], labels["pronoun"], labels["not_in_text"]),
                         (4, 0, 0))
        mine = [dict(rows[0], graph_id="x", subject="my sister", subject_id="my_sister",
                     object_entity=None)]
        self.assertEqual(g.entity_labels(self.run, SEGMENTS, mine, by_id,
                                         {SEG: list(TEXT.values())})["pronoun"], 1)
        drops = g.ending_drops(self.run, SEGMENTS, units, HISTORY_OF)
        self.assertEqual((drops["gold_endings"], drops["drops"], drops["false_drops"]),
                         (0, 1, 0))
        rest = g.restatements(rows, by_id)
        self.assertEqual(rest["gold_stances"], 1)
        self.assertEqual(rest["gold_stance_attributed"], 1)

    def test_lexical_equivalence(self):
        self.assertTrue(g.lexical_equivalent("considersTrying", "plansToTry"))
        self.assertTrue(g.lexical_equivalent("hasDuration", "duration"))
        self.assertFalse(g.lexical_equivalent("hasPet", "owns"))
        self.assertFalse(g.lexical_equivalent("likes", "dislikes"))

    def test_predicate_check_pairs(self):
        pairs = g.predicate_check_pairs(A, B, SEGMENTS, n_negative=5)
        self.assertEqual([p["kind"] for p in pairs], ["differing"])
        result = g.predicate_check(pairs, {pairs[0]["pair_id"]: "same"}, lambda p: "same")
        self.assertEqual(result["metrics"]["judge"]["tp"], 1)


if __name__ == "__main__":
    unittest.main()
