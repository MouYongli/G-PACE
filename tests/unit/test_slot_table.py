"""Slot table of ablation B (T027): guard on/off x time single/bitemporal, read at cut-offs."""

import tempfile
import unittest
from pathlib import Path

from grace.context.memory.graph.slots import SlotRow, SlotTable, load_inventory


def row(n, version, slot, value, speaker="user", function="inform", *, subject="user",
        report_mode="own", polarity="positive", correction=False, valid_from=None,
        valid_until=None):
    return SlotRow(f"r{n}", slot, subject, value, speaker, function, report_mode, polarity,
                   correction, valid_from, valid_until, f"m{version}", version)


class SlotTableTest(unittest.TestCase):
    def setUp(self):
        self.inventory = load_inventory()

    def table(self, rows, **kwargs):
        table = SlotTable("h", self.inventory, **kwargs)
        by_version = {}
        for r in rows:
            by_version.setdefault(r.version, []).append(r)
        for version in sorted(by_version):
            table.append(by_version[version])
        return table

    def values(self, table, version=None, as_of=None):
        return sorted(v.value for v in table.state(version).current(as_of))

    def test_inventory_is_the_pilot_config(self):
        self.assertIn("item.choice", self.inventory.slots)
        self.assertIn("correct", self.inventory.functions)
        self.assertIn("item.choice", self.inventory.exclusive)

    def test_same_speaker_and_function_supersedes(self):
        table = self.table([row(1, 1, "person.location", "Lisbon"),
                            row(2, 2, "person.location", "Porto")])
        self.assertEqual(self.values(table), ["Porto"])
        self.assertEqual(self.values(table, 1), ["Lisbon"])

    def test_offer_does_not_replace_a_request_under_the_guard(self):
        rows = [row(1, 1, "item.choice", "TP1940", function="request"),
                row(2, 2, "item.choice", "TP1950", speaker="agent", function="offer")]
        guarded = self.table(rows)
        self.assertEqual(self.values(guarded), ["TP1940", "TP1950"])
        self.assertEqual(guarded.state().conflicts[0]["reason"], "speaker_or_function")
        unguarded = self.table(rows, guard=False)
        self.assertEqual(self.values(unguarded), ["TP1950"])

    def test_quote_and_hypothetical_do_not_supersede(self):
        rows = [row(1, 1, "person.location", "Lisbon"),
                row(2, 2, "person.location", "Rome", report_mode="hypothetical")]
        self.assertEqual(self.values(self.table(rows)), ["Lisbon", "Rome"])
        self.assertEqual(self.table(rows).state().conflicts[0]["reason"], "report_mode")

    def test_non_exclusive_slots_accumulate_and_repeats_merge(self):
        table = self.table([row(1, 1, "person.activity", "piano"),
                            row(2, 2, "person.activity", "cello"),
                            row(3, 3, "person.activity", " Piano ")])
        state = table.state()
        self.assertEqual(self.values(table), ["cello", "piano"])
        piano = next(v for v in state.values if v.value == "piano")
        self.assertEqual(piano.evidence_ids, ("m1", "m3"))

    def test_negative_own_statement_ends_a_value(self):
        rows = [row(1, 1, "person.activity", "piano"),
                row(2, 2, "person.activity", "piano", polarity="negative")]
        self.assertEqual(self.values(self.table(rows)), [])
        other = [rows[0], row(2, 2, "person.activity", "piano", speaker="agent",
                              polarity="negative")]
        self.assertEqual(self.values(self.table(other)), ["piano"])
        self.assertEqual(self.values(self.table(other, guard=False)), [])

    def test_correction_function_matches_inform_and_marks_correction(self):
        table = self.table([row(1, 1, "event.time", "20:15"),
                            row(2, 2, "event.time", "21:15", function="correct")])
        state = table.state()
        self.assertEqual(self.values(table), ["21:15"])
        old = next(v for v in state.values if v.value == "20:15")
        self.assertEqual(old.kind, "correction")

    def test_bitemporal_valid_end_and_as_of(self):
        rows = [row(1, 1, "person.location", "Lisbon", valid_from="2020-01-01"),
                row(2, 2, "person.location", "Porto", valid_from="2024-03-01")]
        table = self.table(rows)
        lisbon = next(v for v in table.state().values if v.value == "Lisbon")
        self.assertEqual(lisbon.valid_until, "2024-03-01")
        self.assertEqual(self.values(table, as_of="2023-06-01"), ["Lisbon"])
        self.assertEqual(self.values(table, as_of="2024-06-01"), ["Porto"])
        single = self.table(rows, time="single")
        self.assertIsNone(next(v for v in single.state().values
                               if v.value == "Lisbon").valid_until)

    def test_closed_past_interval_competes_with_nothing_only_when_bitemporal(self):
        rows = [row(1, 1, "person.location", "Porto"),
                row(2, 2, "person.location", "Hamburg", valid_from="2010-01-01",
                    valid_until="2015-01-01")]
        self.assertEqual(self.values(self.table(rows)), ["Hamburg", "Porto"])
        self.assertEqual(self.values(self.table(rows, time="single")), ["Hamburg"])

    def test_append_only_checks_and_round_trip(self):
        table = self.table([row(1, 1, "person.location", "Lisbon")])
        with self.assertRaises(ValueError):
            table.append([row(2, 1, "person.location", "Porto")])  # not after the head
        with self.assertRaises(ValueError):
            table.append([row(3, 2, "no.such.slot", "x")])
        with self.assertRaises(ValueError):
            table.append([row(4, 2, "person.location", "x", function="greet")])
        table.append([row(5, 2, "person.location", "Porto")])
        with tempfile.TemporaryDirectory() as tmp:
            table.save(Path(tmp))
            restored = SlotTable.restore(Path(tmp), self.inventory)
        self.assertEqual(restored.rows, table.rows)
        self.assertEqual(self.values(restored), ["Porto"])


if __name__ == "__main__":
    unittest.main()
