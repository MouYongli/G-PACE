"""Derived MultiWOZ gold for offer turns: retention of original constraints and paired correctness
(plan 6.5; the second half of the derived "current choice" gold, on top of the T006 offer rule).

The offer rule of T006 (`multiwoz_offers.identify`, 2.1 acts) finds the user turns that follow a
system offer and labels the user's response `accept`, `reject` or `none`. On those turns
(definitions follow the wording of plan 6.5; s00-super decision of 2026-11-28 on PR #149):

- **Retention item** (`retained`; official 2.4 gold only): an offered slot of the 30 evaluated
  slots whose 2.4 value after the previous user turn (the user's constraint before the offer)
  exists, and for which the user turn itself informs no value (a value the user states is the
  user's own revision, not a retained constraint). The reference is that earlier 2.4 value: the
  predicted state must still hold it. Items on every offer turn (`accept`, `reject`, `none`).
  `conflict` marks items whose original value is not `dontcare` and matches none of the offered
  values (`values_match`): the diagnostic stratum where writing the offer loses the constraint.
- **Paired item** (`paired_correct`), per offered domain with an entity slot (`name`, train
  `trainid`) whose response is `accept` or `reject` and which has at least one retention item:
  correct only when every original constraint of the domain (`originals`) is kept and the current
  choice is right. The current choice is the offered entity after `accept`, and anything but the
  offered entity after `reject`.
- **Conflict-only paired item** (`paired_correct_conflict`, descriptive diagnostic): the paired
  items with at least one conflicting constraint, scored over those constraints only
  (`conflict_slots`).

Gold records use the annotation `2.4-current-choice` (contracts.md, "Gold"; it covers only offer
turns). `reference` holds `retention` and `paired` (items); `labels.response` holds the turn
label. User acts come from 2.1 (2.4 keeps none, T006 report).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from grace.eval.datasets.benchmarks.multiwoz import SLOTS
from grace.eval.datasets.benchmarks.multiwoz_offers import (
    ENTITY_SLOT,
    DialogueInput,
    any_match,
    canon,
    identify,
    parse_acts,
)
from grace.eval.datasets.benchmarks.records import Gold

ANNOTATION = "2.4-current-choice"
ACT_SOURCE = "2.1"
STATE_VERSION = "2.4"


def derive(dialogue: DialogueInput, benchmark: str, split: str) -> list[Gold]:
    """Derived gold records of one dialogue (one per offer turn with at least one item)."""
    states = dialogue.states[STATE_VERSION]
    out = []
    for record in identify(dialogue, ACT_SOURCE):
        turn = record["turn_index"] // 2
        if turn == 0:
            continue
        before = states[turn - 1]
        user_acts = parse_acts(dialogue.acts[ACT_SOURCE][record["turn_index"]], ACT_SOURCE)
        informed = {f"{a.domain}-{a.slot}" for a in user_acts if a.intent == "inform"}
        retention, paired = [], []
        for domain, offered in sorted(record["offered"].items()):
            items = []
            for slot, values in sorted(offered.items()):
                name = f"{domain}-{slot}"
                original = sorted(before.get(name, ()))
                if name not in SLOTS or not original or name in informed:
                    continue
                conflict = not any(canon(v) == "dontcare" or any_match(v, values)
                                   for v in original)
                items.append({"slot": name, "original": original[0], "offered": list(values),
                              "conflict": conflict})
            retention += items
            label = record["domains"].get(domain, {}).get("label")
            entity = ENTITY_SLOT.get(domain)
            if items and entity and entity in offered and label in ("accept", "reject"):
                paired.append({"domain": domain, "response": label,
                               "entity_slot": f"{domain}-{entity}",
                               "offered_entity": list(offered[entity]),
                               "originals": {i["slot"]: i["original"] for i in items},
                               "conflict_slots": [i["slot"] for i in items if i["conflict"]]})
        if not retention:
            continue
        out.append(Gold(
            benchmark=benchmark, split=split, history_id=dialogue.dialogue_id,
            task_id=record["task_id"], annotation=ANNOTATION,
            reference={"retention": retention, "paired": paired},
            evidence_ids=None, evidence_segment_ids=None, evidence_unresolved=(),
            labels={"response": record["label"]},
            metadata={"offer_kinds": record["offer_kinds"], "act_source": ACT_SOURCE}))
    return out


def derive_all(dialogues: Iterable[DialogueInput], benchmark: str, split: str) -> list[Gold]:
    return [g for d in dialogues for g in derive(d, benchmark, split)]


def summary(gold: Iterable[Gold]) -> dict[str, Any]:
    """Counts of the derived gold (turns, items, by response label and domain)."""
    rows = list(gold)
    by_label: dict[str, int] = {}
    for g in rows:
        by_label[g.labels["response"]] = by_label.get(g.labels["response"], 0) + 1
    retention = [r for g in rows for r in g.reference["retention"]]
    paired = [p for g in rows for p in g.reference["paired"]]
    conflict = [p for p in paired if p["conflict_slots"]]

    def by(items, key):
        return {k: sum(p[key] == k for p in items) for k in sorted({p[key] for p in items})}
    return {"turns": len(rows), "dialogues": len({g.history_id for g in rows}),
            "turns_by_response": dict(sorted(by_label.items())),
            "retention_items": len(retention),
            "retention_items_conflict": sum(r["conflict"] for r in retention),
            "paired_items": len(paired),
            "paired_by_response": by(paired, "response"),
            "paired_by_domain": by(paired, "domain"),
            "paired_items_conflict": len(conflict),
            "paired_conflict_by_domain": by(conflict, "domain")}
