"""Sequence audit (task T016): label files, mismatch rates, Cohen's kappa, sample and sheet.

Kappa and specific-agreement values are hand-computed on small synthetic label files. The sample
tests build a synthetic generated dataset in a temporary directory; no real data is read. The last
class checks the committed sheet and the agent pre-annotation against each other.
"""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from grace.eval.analysis.annotation import sequence_sheet as ss
from grace.eval.analysis.annotation.sequence import (
    LabelError,
    agreement,
    bootstrap,
    mismatch_report,
    read_labels,
    read_sheet,
    render_agreement,
    render_mismatch,
)

REPO = Path(__file__).resolve().parents[2]
ANNOTATIONS = REPO / "docs" / "research" / "annotations" / "sequence-audit"
LABEL_COLUMNS = ("item_id", "annotator", "label", "subclass", "note")


def write_csv(path: Path, rows: list[dict], columns) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    return path


def synthetic_sheet(directory: Path) -> Path:
    """Two families x one window x five audit messages, one context message per window and one
    audit question per window; plus one pilot message."""
    rows = []
    for family in ("fam-a", "fam-b"):
        window = f"{family}-s0:w010"
        rows.append({"item_id": f"{family}-s0:m0009", "kind": "message", "part": "context",
                     "window": window, "family": family, "skeleton": "filler"})
        for i in range(5):
            rows.append({"item_id": f"{family}-s0:m{10 + i:04d}", "kind": "message",
                         "part": "audit", "window": window, "family": family,
                         "skeleton": "past" if i < 3 else "filler"})
        rows.append({"item_id": f"{family}-s0:U10:r01:q1", "kind": "question", "part": "audit",
                     "window": window, "family": family, "skeleton": "uniform"})
    rows.append({"item_id": "fam-a-s1:m0050", "kind": "message", "part": "pilot",
                 "window": "pilot-1", "family": "fam-a", "skeleton": "filler"})
    return write_csv(directory / "sheet.csv", rows, ss.SHEET_COLUMNS)


def label_rows(annotator: str, labels: dict[str, str], subclasses: dict | None = None) -> list:
    return [{"item_id": k, "annotator": annotator, "label": v,
             "subclass": (subclasses or {}).get(k, "")} for k, v in labels.items()]


AUDIT = [f"fam-a-s0:m{10 + i:04d}" for i in range(5)] + \
        [f"fam-b-s0:m{10 + i:04d}" for i in range(5)]
QUESTIONS = ["fam-a-s0:U10:r01:q1", "fam-b-s0:U10:r01:q1"]


class LabelFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.sheet = read_sheet(synthetic_sheet(self.dir))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, rows):
        return write_csv(self.dir / name, rows, LABEL_COLUMNS)

    def test_reads_labels_and_skips_unlabelled(self):
        rows = label_rows("A", {AUDIT[0]: "agree", AUDIT[1]: "missing"})
        rows.append({"item_id": AUDIT[2], "annotator": "A", "label": ""})
        labels = read_labels(self.write("a.csv", rows), self.sheet)
        self.assertEqual(labels.annotator, "A")
        self.assertEqual(labels.kind, "human")
        self.assertEqual(len(labels.labels), 2)
        self.assertEqual(labels.unlabelled, 1)

    def test_kinds(self):
        agent = read_labels(self.write("g.csv", label_rows("agent-x", {AUDIT[0]: "agree"})),
                            self.sheet)
        adjudicated = read_labels(self.write("j.csv", label_rows("adjudicated",
                                                                 {AUDIT[0]: "agree"})),
                                  self.sheet)
        self.assertEqual(agent.kind, "agent")
        self.assertEqual(adjudicated.kind, "adjudicated")

    def test_rejects_malformed_files(self):
        cases = {
            "context": label_rows("A", {"fam-a-s0:m0009": "agree"}),
            "unknown item": label_rows("A", {"nope:m0001": "agree"}),
            "question label on message": label_rows("A", {AUDIT[0]: "gold-wrong"}),
            "message label on question": label_rows("A", {QUESTIONS[0]: "missing"}),
            "unknown label": label_rows("A", {AUDIT[0]: "fine"}),
            "unknown subclass": label_rows("A", {AUDIT[0]: "extra"}, {AUDIT[0]: "odd"}),
            "subclass under wrong label": label_rows("A", {AUDIT[0]: "missing"},
                                                     {AUDIT[0]: "foreshadowing"}),
            "duplicate": label_rows("A", {AUDIT[0]: "agree"}) * 2,
            "two annotators": label_rows("A", {AUDIT[0]: "agree"})
            + label_rows("B", {AUDIT[1]: "agree"}),
            "empty annotator": [{"item_id": AUDIT[0], "annotator": "", "label": "agree"}],
            "no labels": [{"item_id": AUDIT[0], "annotator": "A", "label": ""}],
        }
        for name, rows in cases.items():
            with self.subTest(name), self.assertRaises(LabelError):
                read_labels(self.write(f"{name}.csv", rows), self.sheet)
        path = write_csv(self.dir / "cols.csv", [{"item_id": AUDIT[0]}], ("item_id",))
        with self.assertRaises(LabelError):
            read_labels(path, self.sheet)

    def test_pilot_rows_are_labelled_but_not_counted(self):
        labels = {i: "agree" for i in AUDIT} | {"fam-a-s1:m0050": "missing"}
        report = mismatch_report(read_labels(self.write("a.csv", label_rows("A", labels)),
                                             self.sheet), self.sheet, draws=50)
        self.assertEqual(report["overall"]["n"], 10)
        self.assertEqual(report["overall"]["mismatches"], 0)


class MismatchReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.sheet = read_sheet(synthetic_sheet(self.dir))

    def tearDown(self):
        self.tmp.cleanup()

    def test_rates_flags_and_repeats(self):
        labels = {i: "agree" for i in AUDIT}
        # fam-a: three `missing` on skeleton `past` (repeat rule) and one `unnatural`.
        labels.update({AUDIT[0]: "missing", AUDIT[1]: "missing", AUDIT[2]: "missing",
                       AUDIT[3]: "unnatural"})
        labels.update({QUESTIONS[0]: "agree", QUESTIONS[1]: "ambiguous"})
        path = write_csv(self.dir / "a.csv", label_rows("agent-t", labels), LABEL_COLUMNS)
        report = mismatch_report(read_labels(path, self.sheet), self.sheet, draws=200)
        fam_a, fam_b = report["families"]["fam-a"], report["families"]["fam-b"]
        self.assertEqual((fam_a["n"], fam_a["mismatches"], fam_a["unnatural"]), (5, 3, 1))
        self.assertAlmostEqual(fam_a["rate"], 0.6)
        self.assertEqual(fam_a["repeats"], {"missing / past": 3})
        self.assertTrue(fam_a["flagged"])
        self.assertEqual(len(fam_a["flag_reasons"]), 2)  # rate and repeat
        self.assertFalse(fam_b["flagged"])
        self.assertEqual(report["flagged_families"], ["fam-a"])
        self.assertAlmostEqual(report["overall"]["rate"], 0.3)
        self.assertEqual(report["questions"]["overall"]["not_agree"], 1)
        text = render_mismatch(report)
        self.assertIn("agent pre-annotation", text)
        self.assertIn("Flagged families: fam-a", text)

    def test_unlabelled_items_are_counted(self):
        path = write_csv(self.dir / "a.csv", label_rows("A", {AUDIT[0]: "agree"}),
                         LABEL_COLUMNS)
        report = mismatch_report(read_labels(path, self.sheet), self.sheet, draws=10)
        self.assertEqual(report["unlabelled_audit_messages"], 9)
        self.assertEqual(report["unlabelled_audit_questions"], 2)


class AgreementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.sheet = read_sheet(synthetic_sheet(self.dir))

    def tearDown(self):
        self.tmp.cleanup()

    def pair(self, a_labels, b_labels, a_name="A", b_name="B"):
        a = read_labels(write_csv(self.dir / "a.csv", label_rows(a_name, a_labels),
                                  LABEL_COLUMNS), self.sheet)
        b = read_labels(write_csv(self.dir / "b.csv", label_rows(b_name, b_labels),
                                  LABEL_COLUMNS), self.sheet)
        return a, b

    def test_hand_computed_kappa(self):
        a_labels = {i: "agree" for i in AUDIT} | {AUDIT[0]: "missing", AUDIT[1]: "missing"}
        b_labels = {i: "agree" for i in AUDIT} | {AUDIT[0]: "missing", AUDIT[2]: "extra"}
        a, b = self.pair(a_labels, b_labels)
        report = agreement(a, b, self.sheet, draws=200)
        overall = report["messages"]["overall"]
        # Binary: n11=1, n10=1, n01=1, n00=7; po=0.8, pe=0.2*0.2+0.8*0.8=0.68.
        self.assertAlmostEqual(overall["binary"]["observed"], 0.8)
        self.assertAlmostEqual(overall["binary"]["kappa"], 0.12 / 0.32)
        self.assertAlmostEqual(overall["binary"]["disagreement"], 0.2)
        # Full: po=0.8, pe = agree 0.8*0.8 + missing 0.2*0.1 + extra 0*0.1 = 0.66.
        self.assertAlmostEqual(overall["full"]["kappa"], 0.14 / 0.34)
        self.assertAlmostEqual(overall["prevalence"], 0.2)
        self.assertAlmostEqual(overall["specific"]["positive"], 0.5)
        self.assertAlmostEqual(overall["specific"]["negative"], 14 / 16)
        self.assertEqual(report["confusion"]["missing"]["agree"], 1)
        self.assertEqual(report["confusion"]["agree"]["extra"], 1)
        self.assertEqual(report["disagreements"], sorted([AUDIT[1], AUDIT[2]]))
        self.assertTrue(report["human_agreement"])
        ci = overall["binary"]["kappa_bootstrap95"]
        self.assertEqual(ci["draws"], 200)
        # Only two windows: some draws contain only fam-b (all agree), where kappa is undefined.
        self.assertGreater(ci["undefined"], 0)
        self.assertIn("Binary kappa", render_agreement(report))

    def test_binary_ignores_mismatch_class_differences(self):
        a_labels = {i: "agree" for i in AUDIT} | {AUDIT[0]: "missing", AUDIT[5]: "agree"}
        b_labels = {i: "agree" for i in AUDIT} | {AUDIT[0]: "wrong-value"}
        a, b = self.pair(a_labels, b_labels)
        overall = agreement(a, b, self.sheet, draws=10)["messages"]["overall"]
        self.assertAlmostEqual(overall["binary"]["observed"], 1.0)
        self.assertAlmostEqual(overall["binary"]["kappa"], 1.0)
        self.assertAlmostEqual(overall["full"]["observed"], 0.9)

    def test_unnatural_counts_as_agreement_in_binary(self):
        a_labels = {i: "agree" for i in AUDIT} | {AUDIT[0]: "unnatural"}
        b_labels = {i: "agree" for i in AUDIT}
        a, b = self.pair(a_labels, b_labels)
        overall = agreement(a, b, self.sheet, draws=10)["messages"]["overall"]
        self.assertAlmostEqual(overall["binary"]["observed"], 1.0)
        self.assertIsNone(overall["binary"]["kappa"])  # one class only: chance agreement is 1
        self.assertAlmostEqual(overall["full"]["observed"], 0.9)

    def test_questions_and_per_family(self):
        a_labels = {i: "agree" for i in AUDIT} | {QUESTIONS[0]: "agree",
                                                  QUESTIONS[1]: "gold-wrong"}
        b_labels = {i: "agree" for i in AUDIT} | {QUESTIONS[0]: "agree",
                                                  QUESTIONS[1]: "agree"}
        a, b = self.pair(a_labels, b_labels)
        report = agreement(a, b, self.sheet, draws=10)
        self.assertEqual(report["questions"]["n"], 2)
        self.assertAlmostEqual(report["questions"]["disagreement"], 0.5)
        self.assertEqual(set(report["messages"]["families"]), {"fam-a", "fam-b"})
        self.assertEqual(report["messages"]["families"]["fam-a"]["binary"]["n"], 5)

    def test_agent_and_same_annotator(self):
        a, b = self.pair({AUDIT[0]: "agree"}, {AUDIT[0]: "agree"}, "agent-x", "B")
        self.assertFalse(agreement(a, b, self.sheet, draws=5)["human_agreement"])
        a, b = self.pair({AUDIT[0]: "agree"}, {AUDIT[0]: "agree"}, "A", "A")
        with self.assertRaises(LabelError):
            agreement(a, b, self.sheet)
        a, b = self.pair({AUDIT[0]: "agree"}, {AUDIT[1]: "agree"})
        with self.assertRaises(LabelError):
            agreement(a, b, self.sheet)

    def test_bootstrap_is_seeded(self):
        sheet = self.sheet
        stat = lambda items: len([i for i in items if i.startswith("fam-a")]) / len(items)  # noqa: E731
        first = bootstrap(AUDIT, sheet, stat, draws=100, seed=7)
        self.assertEqual(first, bootstrap(AUDIT, sheet, stat, draws=100, seed=7))
        self.assertLessEqual(first["low"], first["high"])
        self.assertEqual(bootstrap([], sheet, stat)["draws"], 0)


# ---------------------------------------------------------------- synthetic dataset


def _message(v, speaker="user", text="Sounds good."):
    return {"episode": "ep-1", "message_id": f"m{v:04d}", "role": speaker, "speaker": speaker,
            "text": text, "timestamp": "2026-01-01", "version": v}


def _filler(v, speaker):
    return {"cue": {"allowed": [], "discourse": None, "required": [], "skeleton": "filler",
                    "slots": {}}, "episode": "ep-1", "events": [], "macro": None,
            "message_id": f"m{v:04d}", "speaker": speaker, "timestamp": "2026-01-01",
            "version": v}


def make_sequence(root: Path, family: str, density: int, index: int, split="development",
                  n=120, setup=10):
    sid = f"{family}-rho{density}-L{n}-{index:03d}"
    directory = root / "sequences" / sid
    (directory / "schedules").mkdir(parents=True)
    messages, events = [], []
    for v in range(1, n + 1):
        speaker = "user" if v % 2 else "assistant"
        messages.append(_message(v, speaker))
        events.append(_filler(v, speaker))
    # version 1 introduces a claim, version 30 corrects it
    events[0] |= {"cue": {"allowed": [], "discourse": None, "required": ["Bremen"],
                          "skeleton": "first", "slots": {}},
                  "events": [{"type": "NewClaim", "claim_id": "c1", "subject": "user",
                              "predicate": "livesIn", "object": "Bremen", "start": None,
                              "end": None, "object_type": "string"},
                             {"type": "Stance", "claim_id": "c1", "attribution_id": "a1",
                              "function": "inform", "report_mode": "own",
                              "polarity": "positive", "derived": False}],
                  "macro": {"name": "m-first", "intended_type": "C2",
                            "focus": "V2:user:livesIn", "macro_id": "mac1"}}
    events[29] |= {"cue": {"allowed": ["Bremen"], "discourse": "correction",
                           "required": ["Hamburg"], "skeleton": "correct_value", "slots": {}},
                   "events": [{"type": "NewClaim", "claim_id": "c2", "subject": "user",
                               "predicate": "livesIn", "object": "Hamburg",
                               "start": "2026-01-02", "end": None, "object_type": "string"},
                              {"type": "Stance", "claim_id": "c2", "attribution_id": "a2",
                               "function": "inform", "report_mode": "own",
                               "polarity": "positive", "derived": False},
                              {"type": "Supersede", "claim_id": "c1", "kind": "correction",
                               "replacing_claim_id": "c2", "supersession_id": "s1",
                               "attribution_id": "a2"}],
                   "macro": {"name": "m-correct", "intended_type": "C5",
                             "focus": "V2:user:livesIn", "macro_id": "mac2"}}
    questions = []
    for read in range(12, n + 1, 4):
        base = {"answer": ["Bremen"], "answer_text": ["Bremen"], "asked_at": "2026-01-01",
                "binding_id": "V2:user:livesIn", "change_type": "none", "change_types": [],
                "evidence": ["m0001"], "expected_abstention": False, "kappa": None,
                "outdated_text": [], "outdated_values": [], "pair_id": None,
                "pair_kind": None, "pair_role": None, "premise_outdated": False,
                "read_index": read, "read_version": read, "schedule": "U10", "tau": None,
                "template": "V2", "text": "Where do I live?", "type": "uniform",
                "witnesses": []}
        for q in range(1, 4):
            questions.append(base | {"question_id": f"U10:r{read:02d}:q{q}"})
        questions.append(base | {"question_id": f"U10:r{read:02d}:q4", "type": "known_then",
                                 "pair_id": f"U10:r{read:02d}:pair", "pair_role": "known-then",
                                 "pair_kind": "control", "kappa": 1, "tau": "2026-01-01"})
        questions.append(base | {"question_id": f"U10:r{read:02d}:q5",
                                 "type": "seen_from_now", "pair_id": f"U10:r{read:02d}:pair",
                                 "pair_role": "seen-from-now", "pair_kind": "control",
                                 "kappa": read, "tau": "2026-01-01"})
    meta = {"sequence_id": sid, "family": family, "split": split, "primary_schedule": "U10",
            "cell": {"density": density}, "world": {"setup_length": setup, "n_messages": n}}
    files = {"meta.json": json.dumps(meta),
             "messages.jsonl": "\n".join(json.dumps(m) for m in messages) + "\n",
             "events.jsonl": "\n".join(json.dumps(e) for e in events) + "\n",
             "schedules/U10.jsonl": "\n".join(json.dumps(q) for q in questions) + "\n"}
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return sid


def make_dataset(root: Path, families=("fam-a", "fam-b"), split="development") -> Path:
    for family in families:
        for i, density in enumerate((1, 3, 10, 10, 30)):
            make_sequence(root, family, density, i if density == 10 else 0, split)
    (root / "dataset.json").write_text(json.dumps({"dataset": "synthetic", "generator":
                                                   {"version": "g"}, "renderer": {}}))
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(root).as_posix()}")
    (root / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    return root


class SampleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_dataset(Path(self.tmp.name) / "dataset")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sheet_and_record(self):
        data = ss.load_dataset(self.root)
        rows, record = ss.build_sheet(data)
        self.assertEqual(record["families"], ["fam-a", "fam-b"])
        for ids in record["sequences"].values():
            self.assertEqual(len(ids), ss.PER_FAMILY)
            self.assertEqual(len({i.split("-rho")[1].split("-")[0] for i in ids}), 4)
        audit = [w for w in record["windows"] if w["part"] == "audit"]
        pilots = [w for w in record["windows"] if w["part"] == "pilot"]
        self.assertEqual(len(audit), 10)
        self.assertEqual(len(pilots), ss.PILOT_WINDOWS)
        self.assertEqual(len({p["family"] for p in pilots}), ss.PILOT_WINDOWS)
        by_seq = {w["sequence_id"]: w for w in audit}
        for w in audit:
            self.assertGreater(w["start"], 10)  # after the setup episode
            self.assertLessEqual(w["end"], 120)
            self.assertLessEqual(len(w["questions"]), ss.MAX_QUESTIONS)
            pairs = [q for q in w["questions"] if q.endswith(("q4", "q5"))]
            self.assertEqual(len(pairs) % 2, 0)  # pairs stay whole
        for p in pilots:
            a = by_seq[p["sequence_id"]]
            self.assertTrue(p["end"] < a["context_from"] or p["context_from"] > a["end"])
        counts = record["counts"]
        self.assertEqual(counts["audit_messages"], 10 * ss.WINDOW)
        self.assertEqual(counts["pilot_messages"], ss.PILOT_WINDOWS * ss.WINDOW)
        self.assertTrue(all(r["annotator"] == r["label"] == "" for r in rows))
        # deterministic
        self.assertEqual(rows, ss.build_sheet(ss.load_dataset(self.root))[0])

    def test_readable_events_and_gold(self):
        data = ss.load_dataset(self.root)
        seq = next(iter(data.sequences.values()))
        rows = ss._window_rows(seq, 25, "audit", "w")
        by_version = {r["version"]: r for r in rows if r["kind"] == "message"}
        self.assertIn("SUPERSEDE c1 (user, livesIn, Bremen) as correction, replaced by c2",
                      by_version["30"]["events"])
        self.assertIn("NEW c2 (user, livesIn, Hamburg) valid from 2026-01-02",
                      by_version["30"]["events"])
        self.assertIn("must signal that an earlier statement was wrong", by_version["30"]["cue"])
        self.assertEqual(by_version["16"]["events"], "(none)")
        self.assertEqual(by_version["16"]["part"], "context")
        known = [r for r in rows if r["item_id"].endswith("q4")]
        if known:
            self.assertIn("anchor [m0001 | user]", known[0]["gold"])

    def test_refuses_held_out_and_bad_manifest(self):
        make_sequence(self.root, "fam-h", 1, 0, split="held-out")
        with self.assertRaises(ss.SampleError):
            ss.load_dataset(self.root)  # the new files are not in the manifest
        data = ss.load_dataset(self.root, verify=False)
        with self.assertRaises(ss.SampleError):
            ss.select_sequences(data.sequences)
        (self.root / "sequences" / "fam-a-rho1-L120-000" / "messages.jsonl").write_text("x")
        with self.assertRaises(ss.SampleError):
            ss.verify_manifest(self.root)

    def test_too_few_sequences(self):
        data = ss.load_dataset(self.root)
        pool = {k: v for k, v in data.sequences.items() if "rho30" not in k}
        with self.assertRaises(ss.SampleError):
            ss.select_sequences(pool)


class CommittedSheetTest(unittest.TestCase):
    """The committed sheet, sample record and agent pre-annotation agree with each other."""

    def test_committed_files(self):
        sheet_path = ANNOTATIONS / "sheet.csv"
        if not sheet_path.is_file():
            self.skipTest("no committed sheet")
        sheet = read_sheet(sheet_path)
        record = json.loads((ANNOTATIONS / "sample.json").read_text(encoding="utf-8"))
        self.assertEqual(record["seed"], ss.SAMPLE_SEED)
        for family, ids in record["sequences"].items():
            self.assertGreaterEqual(len(ids), 5, family)
        audit = [i for i, r in sheet.items() if r["part"] == "audit"]
        self.assertEqual(len(audit), record["counts"]["audit_messages"]
                         + record["counts"]["audit_questions"])
        self.assertTrue(all(r["label"] == "" and r["annotator"] == "" for r in sheet.values()))
        for path in sorted(ANNOTATIONS.glob("labels-*.csv")):
            labels = read_labels(path, sheet)
            if labels.kind == "agent":
                self.assertEqual(set(audit) - set(labels.labels), set(), path.name)


if __name__ == "__main__":
    unittest.main()
