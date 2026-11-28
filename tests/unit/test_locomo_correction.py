"""Manual correction of an extraction (E009 preparation): review items, correction records and
the corrected change sets, on the synthetic ingest in tests/fixtures/locomo-correction/."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from grace.cli.annotate import locomo_correction as cli
from grace.context.memory.graph.changeset import ChangeSet
from grace.eval.runner.probes import extraction_correction as xc

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "locomo-correction"
INGEST = FIXTURE / "ingest"
CORRECTIONS = FIXTURE / "corrections.jsonl"


def record(**fields):
    return {"history_id": "h1", "item_id": None, "add_id": None, "message_id": None,
            "fields": None, "reason": "", "annotator": "test", "basis": "human", **fields}


class ItemsTest(unittest.TestCase):
    def setUp(self):
        self.history = xc.load_ingest(INGEST)["h1"]
        self.items = {i["item_id"]: i for i in xc.history_items(self.history)}

    def test_items_are_claims_mentions_and_supersessions(self):
        kinds = {k: i["kind"] for k, i in self.items.items()}
        self.assertEqual(kinds, {"c1.1": "claim", "c1.2": "claim", "c1.3": "claim",
                                 "c2.1": "claim", "c3.1": "claim", "a3.2": "attribution",
                                 "a3.3": "attribution", "s3.1": "supersession",
                                 "c4.1": "claim"})
        self.assertEqual(self.items["c1.1"]["message_id"], "D1:1")
        self.assertEqual(self.items["s3.1"]["message_id"], "D1:3")
        self.assertEqual([a["attribution_id"] for a in self.items["c3.1"]["attributions"]],
                         ["a3.1"])

    def test_change_tags(self):
        self.assertEqual(self.items["s3.1"]["change"], ["ending"])
        self.assertEqual(self.items["a3.2"]["change"], ["negative"])
        self.assertEqual(self.items["c3.1"]["change"], [])

    def test_bundle_carries_messages_items_and_flags_agent_change_events(self):
        proposal = record(item_id="c3.1", message_id="D1:3", decision="accept",
                          change_event=True)
        bundle = xc.build_bundle(INGEST, [proposal])
        (h,) = bundle["histories"]
        self.assertEqual([m["message_id"] for m in h["messages"]],
                         ["D1:1", "D1:2", "D1:3", "D1:4"])
        self.assertEqual(h["segments"][0]["timestamp"], "2023-05-01T10:00")
        flagged = {i["item_id"] for i in h["items"] if "agent" in i["change"]}
        self.assertEqual(flagged, {"c3.1"})
        with self.assertRaises(xc.CorrectionError):
            xc.build_bundle(INGEST, [{**proposal, "history_id": "nope"}])


class RecordsTest(unittest.TestCase):
    def test_bad_records_are_refused(self):
        bad = [record(decision="maybe", item_id="c1.1"),
               record(decision="reject"),
               record(decision="edit", item_id="c1.1"),
               record(decision="add_claim", add_id="x1", message_id="D1:1", fields={}),
               record(decision="add_ending", add_id="h1.1", fields={"claim_id": "c1.1"})]
        for r in bad:
            with self.assertRaises(xc.CorrectionError, msg=r):
                xc.check_record(r, "test")

    def test_human_decisions_override_the_fallback(self):
        fallback = [record(item_id="c1.1", decision="reject")]
        human = [record(item_id="c1.1", decision="accept")]
        merged = xc.merge_decisions(human, fallback)
        self.assertEqual(merged[("h1", "c1.1")]["decision"], "accept")
        self.assertEqual(merged[("h1", "c1.1")]["_source"], "human")
        merged = xc.merge_decisions([], fallback)
        self.assertEqual(merged[("h1", "c1.1")]["_source"], "fallback")


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.history = xc.load_ingest(INGEST)["h1"]

    def apply(self, records):
        report = xc.Report()
        changesets, store = xc.apply_corrections(self.history, xc.merge_decisions(records),
                                                 report)
        return changesets, store, report

    def test_corrections_are_applied(self):
        changesets, store, report = self.apply(xc.read_records([CORRECTIONS]))
        self.assertEqual([cs.version for cs in changesets], [1, 2, 3, 4])
        state = store.state(4)
        self.assertNotIn("c1.3", state.claims)                    # rejected
        self.assertNotIn("c2.1", state.claims)                    # rejected
        self.assertEqual(state.claims["c1.2"].predicate, "playsInstrument")   # edited
        self.assertNotIn("a3.3", state.attributions)              # rejected mention
        self.assertFalse(state.is_current("c1.1"))                # added supersession
        (sup,) = [s for s in state.supersessions.values() if s.supersession_id == "h3.1"]
        self.assertEqual((sup.claim_id, sup.replacing_claim_id), ("c1.1", "c3.1"))
        self.assertEqual(state.attributions[sup.attribution_id].claim_id, "c3.1")
        self.assertFalse(state.is_current("c1.2"))                # accepted ending
        # The added claim repeats the current claim c3.1: folded into a mention of it.
        self.assertNotIn("h4.1", state.claims)
        self.assertEqual(state.attributions["h4.1.a"].claim_id, "c3.1")
        self.assertEqual(state.evidence_links["h4.1.e"].span.start, 35)
        self.assertEqual(report.counts["claim_folded"], 1)
        self.assertEqual(report.counts["dismissed"], 1)
        # The corrected change sets round-trip through the contract format.
        for cs in changesets:
            self.assertEqual(ChangeSet.from_json(cs.to_json()), cs)

    def test_no_decision_keeps_the_extraction(self):
        changesets, _, report = self.apply([])
        original = [ChangeSet.from_record(r) for r in self.history.changesets.values()]
        self.assertEqual(changesets, [cs.canonical() for cs in original])
        self.assertEqual(sum(report.counts.values()), 0)

    def test_rejecting_a_claim_cascades(self):
        _, store, report = self.apply([record(item_id="c1.2", decision="reject")])
        state = store.state(4)
        self.assertNotIn("a3.2", state.attributions)
        self.assertNotIn("s3.1", state.supersessions)
        self.assertEqual(report.counts["mention_cascaded"], 1)
        self.assertEqual(report.counts["supersession_cascaded"], 1)

    def test_added_ending_is_licensed_by_a_negative_own_stance(self):
        _, store, _ = self.apply([
            record(add_id="h4.1", message_id="D1:4", decision="add_ending",
                   fields={"claim_id": "c3.1", "kind": "change", "valid_end": None})])
        state = store.state(4)
        sup = state.supersessions["h4.1"]
        licence = state.attributions[sup.attribution_id]
        self.assertEqual((licence.claim_id, licence.polarity, licence.report_mode,
                          licence.speaker), ("c3.1", "negative", "own", "Bob"))
        self.assertFalse(state.is_current("c3.1"))

    def test_impossible_corrections_fail_loudly(self):
        cases = [
            [record(item_id="c9.9", decision="reject")],
            [record(item_id="a3.3", decision="edit", fields={"predicate": "x"})],
            [record(item_id="c2.1", decision="reject"),
             record(add_id="h3.1", message_id="D1:3", decision="add_ending",
                    fields={"claim_id": "c2.1"})],
            [record(add_id="h1.1", message_id="D9:9", decision="add_claim",
                    fields={"subject": "Ann", "predicate": "p", "object": {"entity": "x"}})],
            [record(item_id="c1.1", decision="edit", fields={"speaker": "Bob"})],
        ]
        for records in cases:
            with self.assertRaises(xc.CorrectionError, msg=records):
                self.apply(records)


class CliTest(unittest.TestCase):
    def test_apply_writes_a_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            cli.main(["apply", "--ingest", str(INGEST), "--corrections", str(CORRECTIONS),
                      "--run-root", tmp])
            (run_dir,) = (Path(tmp) / "E009").iterdir()
            run = json.loads((run_dir / "run.json").read_text())
            self.assertEqual(run["stage"], "probe")
            self.assertEqual(run["upstream"][0]["run_id"], "E000-20260101T000000Z-0000")
            self.assertIn(run["status"], {"completed", "failed"})   # failed when code is dirty
            self.assertEqual(run["n_records"], 4)
            lines = (run_dir / "changesets.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 4)
            applied = (run_dir / "corrections.jsonl").read_text().splitlines()
            self.assertEqual(len(applied), 8)
            report = json.loads((run_dir / "correction-report.json").read_text())
            self.assertEqual(report["items_without_human_decision"], {"h1": 4})
            manifest = json.loads((run_dir / "snapshot" / "manifest.json").read_text())
            paths = [f["path"] for f in manifest["histories"][0]["files"]]
            self.assertIn("h1/store/changesets.jsonl", paths)
            self.assertIn("h1/log/messages.jsonl", paths)

    def test_bundle_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) \
                as out:
            target = Path(tmp) / "bundle.json"
            cli.main(["bundle", "--ingest", str(INGEST), "--proposals", str(CORRECTIONS),
                      "--out", str(target)])
            bundle = json.loads(target.read_text())
            self.assertEqual(len(bundle["proposals"]), 8)
            cli.main(["summary", str(CORRECTIONS)])
        self.assertIn('"reject": 3', out.getvalue())


if __name__ == "__main__":
    unittest.main()
