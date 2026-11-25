"""MultiWOZ adapter: 2.4 main, 2.2 and 2.1 as further annotations of the same turns (card:
docs/research/benchmarks.md#multiwoz).

One dialogue is one history (`dialogue_id` with its `.json` suffix, as in the source lists); each
turn is a message whose ID is its turn index (0-based, as a string); USER -> `user`, SYSTEM ->
`agent`. Visible text is the 2.4 text (identical to 2.1; 2.2 edits some utterances). One `state`
read follows every user turn (task `<dialogue_id>:<turn index>`, version = turn index + 1).

Gold: the cumulative state after the user turn under annotations `2.4`, `2.2` and `2.1` on the
same task IDs, as an object slot -> value over the slot inventory `multiwoz-slots` (the 30 slots
of the five evaluated domains, named as in 2.2: `hotel-bookday`, `train-leaveat`, ...).
2.1/2.4 states come from the metadata of the following system turn; values `""`,
`not mentioned` and `none` mean "not set". A 2.2 slot with several acceptable values has a list.
Slots outside the inventory (bus, hospital, police, train-ticket) are dropped and counted.
Dialogue acts of the user turn and the preceding system turn are kept in gold `metadata`.
The user goal (`goal`) is excluded and counted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from grace.eval.datasets.benchmarks.base import Adapter, HistoryBuilder, Records, SplitSpec
from grace.eval.datasets.benchmarks.records import Gold, ReadTask, RecordError

STATE_SCHEMA = "multiwoz-slots"
SLOTS = frozenset({
    "attraction-area", "attraction-name", "attraction-type",
    "hotel-area", "hotel-bookday", "hotel-bookpeople", "hotel-bookstay", "hotel-internet",
    "hotel-name", "hotel-parking", "hotel-pricerange", "hotel-stars", "hotel-type",
    "restaurant-area", "restaurant-bookday", "restaurant-bookpeople", "restaurant-booktime",
    "restaurant-food", "restaurant-name", "restaurant-pricerange",
    "taxi-arriveby", "taxi-departure", "taxi-destination", "taxi-leaveat",
    "train-arriveby", "train-bookpeople", "train-day", "train-departure", "train-destination",
    "train-leaveat",
})
UNSET = {"", "not mentioned", "none"}
ROLES = {0: ("USER", "user"), 1: ("SYSTEM", "agent")}
DATA = {"2.4": "MULTIWOZ2.4/data.json", "2.1": "MultiWOZ_2.1/data.json"}
ACTS_24 = "MULTIWOZ2.4/dialogue_acts.json"
ACTS_22 = "dialog_acts.json"


def legacy_state(metadata: Mapping[str, Any], dropped: dict[str, int]) -> dict[str, str]:
    """2.1/2.4 system-turn metadata -> slot -> value in the 2.2 naming."""
    state = {}
    for domain, parts in metadata.items():
        for part in ("semi", "book"):
            for slot, value in parts.get(part, {}).items():
                if slot == "booked" or not isinstance(value, str) or value.strip() in UNSET:
                    continue
                name = f"{domain}-{'book' if part == 'book' else ''}{slot}".lower()
                if name not in SLOTS:
                    dropped[name] = dropped.get(name, 0) + 1
                    continue
                state[name] = value
    return state


def state_22(turn: Mapping[str, Any], dropped: dict[str, int]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for frame in turn["frames"]:
        for name, values in frame["state"]["slot_values"].items():
            if name not in SLOTS:
                dropped[name] = dropped.get(name, 0) + 1
                continue
            values = [v for v in values if v.strip() not in UNSET]
            if values:
                state[name] = values[0] if len(values) == 1 else values
    return state


class MultiWOZAdapter(Adapter):
    slug = "multiwoz"

    def convert(self, source_dirs: Mapping[str, Path], split: SplitSpec,
                options: Mapping[str, Any]) -> Records:
        for version in ("2.4", "2.2", "2.1"):
            if version not in source_dirs:
                raise RecordError(f"multiwoz: data version {version} is not configured")
        split_22 = (options.get("split_dirs_22") or {}).get(split.name)
        if split_22 is None:
            raise RecordError(f"multiwoz: no 2.2 directory configured for split {split.name}")
        wanted = sorted(split.histories or ())
        data = {v: json.loads((source_dirs[v] / path).read_text(encoding="utf-8"))
                for v, path in DATA.items()}
        d22 = {}
        for path in sorted((source_dirs["2.2"] / split_22).glob("dialogues_*.json")):
            for dialogue in json.loads(path.read_text(encoding="utf-8")):
                if dialogue["dialogue_id"] in split.histories:
                    d22[dialogue["dialogue_id"]] = dialogue
        acts24 = json.loads((source_dirs["2.4"] / ACTS_24).read_text(encoding="utf-8"))
        acts22 = json.loads((source_dirs["2.2"] / ACTS_22).read_text(encoding="utf-8"))
        records = Records(self.slug, split.name)
        dropped: dict[str, int] = {}
        for did in wanted:
            missing = [v for v, d in (("2.4", data["2.4"]), ("2.1", data["2.1"]), ("2.2", d22))
                       if did not in d]
            if missing:
                raise RecordError(f"multiwoz: dialogue {did} missing in {missing}")
            self._convert(records, did, data["2.4"][did], data["2.1"][did], d22[did],
                          acts24.get(did.removesuffix(".json"), {}), acts22.get(did, {}),
                          dropped)
        for name, count in sorted(dropped.items()):
            records.exclusions[f"slot_outside_inventory:{name}"] += count
        return records

    def _convert(self, records: Records, did: str, d24: dict, d21: dict, d22: dict,
                 acts24: Mapping, acts22: Mapping, dropped: dict[str, int]) -> None:
        log, log21, turns22 = d24["log"], d21["log"], d22["turns"]
        if not len(log) == len(log21) == len(turns22) or len(log) % 2:
            raise RecordError(f"multiwoz: {did}: turn counts differ or end on a user turn")
        if d24.get("goal"):
            records.exclusions["goal"] += 1
        builder = HistoryBuilder(self.slug, records.split, did)
        for index, turn in enumerate(log):
            speaker, role = ROLES[index % 2]
            if turns22[index]["speaker"] != speaker:
                raise RecordError(f"multiwoz: {did}[{index}]: 2.2 speaker differs")
            builder.message(str(index), speaker, role, turn["text"])
        records.add(builder)
        for index in range(0, len(log), 2):
            task_id = f"{did}:{index}"
            records.read_tasks.append(ReadTask.from_record({
                "benchmark": self.slug, "split": records.split, "history_id": did,
                "read_id": f"{task_id}@{index + 1}", "task_id": task_id, "version": index + 1,
                "kind": "state", "question": None, "state_schema": STATE_SCHEMA,
                "asked_at": None, "asked_at_raw": None}))
            system = index - 1
            acts = {
                "2.4": {"user": None,
                        "system": acts24.get(str((system + 1) // 2)) if system > 0 else None},
                "2.1": {"user": log21[index].get("dialog_act"),
                        "system": log21[system].get("dialog_act") if system > 0 else None},
                "2.2": {"user": (acts22.get(str(index)) or {}).get("dialog_act"),
                        "system": ((acts22.get(str(system)) or {}).get("dialog_act")
                                   if system > 0 else None)},
            }
            states = {"2.4": legacy_state(log[index + 1]["metadata"], dropped),
                      "2.1": legacy_state(log21[index + 1]["metadata"], dropped),
                      "2.2": state_22(turns22[index], dropped)}
            for annotation, state in states.items():
                records.gold.append(Gold(
                    benchmark=self.slug, split=records.split, history_id=did, task_id=task_id,
                    annotation=annotation, reference=state, evidence_ids=None,
                    evidence_segment_ids=None, evidence_unresolved=(), labels={},
                    metadata={"dialogue_acts": acts[annotation]}))
