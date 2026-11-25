"""MultiWOZ offer turns: the deterministic rule of T006 and the census built on it.

The rule is model-free and reads annotations only (dialogue acts and dialogue states). It is
the first half of the derived "current choice" gold of plan 6.5: the offered entity and values
come from the dialogue acts of a system turn, acceptance or rejection from the acts of the next
user turn. Report: docs/research/multiwoz-offer-turns.md.

Definitions (one dialogue, act source `2.1` or `2.2`; 2.4 keeps system acts only, the same as
2.1 up to normalisation on almost every turn, so the 2.1 acts stand for 2.4):

- Acts are normalised to `(domain, intent, slot, value)` with lower-case domains, slots in the
  2.2 naming (`pricerange`, `bookday`, `trainid`, ...) and normalised values. `Booking-*` acts
  are assigned to the active domain: the single domain of the other acts of the same turn, else
  of the preceding turn, else the last domain any earlier act named.
- Values are compared with `values_match` (lenient: `the`, punctuation, plural and spacing
  variants, times as HH:MM, one value covering the other's tokens, near-identical spellings).
- **Offer.** A system turn offers in domain `d` when it carries `d-Recommend`, `d-Select`,
  `d-OfferBook` or (after domain resolution) `Booking-Inform`, or a `d-Inform` that names an
  entity (`name`, train `trainid`) that neither speaker has named earlier in the dialogue. The
  offered values are the `(slot, value)` pairs of those acts in `d`, plus, for an entity
  `Inform`, the other `Inform` pairs of `d` in the same turn. Values `none`, `?` and empty are
  dropped.
- **Response of the next user turn**, per offered domain `d`:
  - `reject`: the user informs a value for an offered slot that matches none of the offered
    values (`dontcare` excluded);
  - `accept`, explicit: the user informs an offered value again, or informs booking details
    (`bookpeople`, `bookday`, `bookstay`, `booktime`) in `d`;
  - `accept`, implicit: the user requests an attribute in `d` (address, phone, ...) after an
    offer that proposes an entity or value (`recommend`, `select`, `inform-entity`), or the
    booking reference after any offer;
  - `none` otherwise. A turn is `reject` if any domain is, else `accept` if any domain is.
- **State evidence**, per annotation version: an offered slot of the 30 evaluated slots is
  `offered` when its value after the user turn matches an offered value, `other` when it holds
  another value and `unset` otherwise; it is `new` when it was not `offered` after the previous
  user turn. 2.2 matches on any of its acceptable values.
"""

from __future__ import annotations

import difflib
import json
import math
import random
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grace.eval.datasets.benchmarks.multiwoz import (
    ACTS_22,
    ACTS_24,
    DATA,
    SLOTS,
    UNSET,
    legacy_state,
)

DOMAINS = ("attraction", "hotel", "restaurant", "taxi", "train")
ENTITY_SLOT = {"attraction": "name", "hotel": "name", "restaurant": "name", "train": "trainid"}
OFFER_INTENTS = {"recommend": "recommend", "select": "select", "offerbook": "offerbook"}
ENTITY_KINDS = {"recommend", "select", "inform-entity"}   # kinds that propose an entity/value
BOOK_SLOTS = ("bookpeople", "bookday", "bookstay", "booktime")
VERSIONS = ("2.1", "2.2", "2.4")
ACT_SOURCES = ("2.1", "2.2")
NULL_VALUES = {"", "none", "?", "not mentioned"}

# 2.1 act slot -> 2.2 slot name; `Day` and `Time` depend on the domain (see `slot_21`).
SLOT_21 = {
    "area": "area", "price": "pricerange", "type": "type", "name": "name", "food": "food",
    "stars": "stars", "internet": "internet", "parking": "parking", "leave": "leaveat",
    "arrive": "arriveby", "depart": "departure", "dest": "destination", "people": "bookpeople",
    "stay": "bookstay", "id": "trainid", "addr": "address", "post": "postcode",
    "phone": "phone", "ref": "ref", "fee": "entrancefee", "choice": "choice",
    "ticket": "price", "car": "car", "open": "openhours", "none": "none",
}


def norm_value(value: Any) -> str:
    """Lower-case, strip and collapse whitespace (stored form of every value)."""
    return re.sub(r"\s+", " ", str(value).strip().lower())


DONTCARE = {"dontcare", "dont care", "do nt care", "don't care", "do n't care", "any",
            "doesn't matter", "does not matter"}
STOP_TOKENS = {"the", "a", "an", "and", "or", "lastly", "of", "in", "at", "to"}


def canon(value: str) -> str:
    """Comparison form: `dontcare` variants unified, times as HH:MM, punctuation dropped."""
    value = norm_value(value)
    if value in DONTCARE:
        return "dontcare"
    time = re.fullmatch(r"(\d{1,2})[:.](\d{2})\s*(am|pm|a\.m\.|p\.m\.)?", value)
    if time:
        hour, suffix = int(time.group(1)), time.group(3)
        if suffix:
            hour = hour % 12 + (12 if suffix.startswith("p") else 0)
        return f"{hour:02d}:{time.group(2)}"
    return re.sub(r"\s+", " ", re.sub(r"[^\w:& ]", " ", value)).strip()


def _token_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True   # moderate/moderately, hotel/hotels
    return min(len(a), len(b)) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _covered(small: Sequence[str], big: Sequence[str]) -> bool:
    return all(any(_token_match(s, b) for b in big) for s in small)


def values_match(a: str, b: str) -> bool:
    """Lenient value identity used by the rule: equal comparison forms, equal without spaces
    (`guest house`/`guesthouse`), or the content tokens of one covered by the other's
    (`west`/`west of town`, `mediterranean`/`italian or mediterranean`), where tokens match
    when equal, one is a prefix of the other (both >= 4 characters) or they are near-identical
    spellings (`ashely`/`ashley`)."""
    ca, cb = canon(a), canon(b)
    if ca == cb or ca.replace(" ", "") == cb.replace(" ", ""):
        return True
    if "dontcare" in (ca, cb) or re.fullmatch(r"[\d: ]+", ca) or re.fullmatch(r"[\d: ]+", cb):
        return False   # numbers and times only match exactly
    ta = [t for t in ca.split() if t not in STOP_TOKENS]
    tb = [t for t in cb.split() if t not in STOP_TOKENS]
    if not ta or not tb:
        return False
    return _covered(ta, tb) or _covered(tb, ta)


def any_match(value: str, values: Iterable[str]) -> bool:
    return any(values_match(value, v) for v in values)


def slot_21(domain: str, intent: str, slot: str) -> str:
    slot = slot.lower()
    if slot == "day":
        return "day" if domain == "train" and intent != "book" else "bookday"
    if slot == "time":
        return "duration" if domain == "train" else "booktime"
    return SLOT_21.get(slot, slot)


@dataclass(frozen=True)
class Act:
    domain: str
    intent: str
    slot: str
    value: str


def parse_acts(raw: Mapping[str, Any] | None, source: str) -> list[Act]:
    """Raw `dialog_act` mapping (`"Hotel-Inform": [[slot, value], ...]`) -> normalised acts.

    `Booking` acts keep the domain `booking` until `resolve_booking` assigns them."""
    acts = []
    for key, pairs in sorted((raw or {}).items()):
        domain, _, intent = key.partition("-")
        domain, intent = domain.lower(), intent.lower()
        for slot, value in pairs or []:
            name = slot_21(domain, intent, slot) if source == "2.1" else str(slot).lower()
            acts.append(Act(domain, intent, name, norm_value(value)))
    return acts


def act_domains(acts: Iterable[Act]) -> set[str]:
    return {a.domain for a in acts if a.domain in DOMAINS}


def resolve_booking(acts: list[Act], previous: list[Act], last_domain: str | None) -> list[Act]:
    """Assign `booking` acts to the active domain (module docstring) with the intent
    `booking-<intent>`; acts whose domain cannot be resolved stay in domain `booking`."""
    if not any(a.domain == "booking" for a in acts):
        return acts
    own, prev = act_domains(acts), act_domains(previous)
    domain = (next(iter(own)) if len(own) == 1 else next(iter(prev)) if len(prev) == 1
              else last_domain)
    if domain is None:
        return acts
    return [Act(domain, f"booking-{a.intent}", "bookday" if a.slot == "day" else a.slot,
                a.value) if a.domain == "booking" else a for a in acts]


@dataclass
class Offer:
    """What one system turn offers: domain -> slot -> offered values, and the offer kinds."""

    values: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    kinds: dict[str, set[str]] = field(default_factory=dict)

    def add(self, domain: str, kind: str, pairs: Iterable[tuple[str, str]]) -> None:
        self.kinds.setdefault(domain, set()).add(kind)
        slots = self.values.setdefault(domain, {})
        for slot, value in pairs:
            if value not in NULL_VALUES and slot != "none":
                slots.setdefault(slot, set()).add(value)

    def __bool__(self) -> bool:
        return bool(self.kinds)


def find_offer(acts: Sequence[Act], named_before: set[tuple[str, str]]) -> Offer:
    """Offer of one system turn (acts already resolved); `named_before` holds the
    `(domain, entity)` pairs the system named in earlier turns."""
    offer = Offer()
    by_domain: dict[str, list[Act]] = defaultdict(list)
    for act in acts:
        if act.domain in DOMAINS:
            by_domain[act.domain].append(act)
    for domain, dacts in sorted(by_domain.items()):
        for act in dacts:
            if act.intent in OFFER_INTENTS:
                offer.add(domain, OFFER_INTENTS[act.intent], [(act.slot, act.value)])
        booking = [a for a in dacts if a.intent == "booking-inform"]
        if booking:
            offer.add(domain, "booking-inform", [(a.slot, a.value) for a in booking])
        entity = ENTITY_SLOT.get(domain)
        informs = [a for a in dacts if a.intent == "inform"]
        new_entities = [a for a in informs if a.slot == entity and a.value not in NULL_VALUES
                        and (domain, canon(a.value)) not in named_before]
        if new_entities:
            offer.add(domain, "inform-entity", [(a.slot, a.value) for a in informs])
    return offer


def response(offer: Offer, user_acts: Sequence[Act]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Label of the user turn after an offer, and per offered domain its label and evidence."""
    per_domain: dict[str, dict[str, Any]] = {}
    for domain, offered in sorted(offer.values.items()):
        informs = [a for a in user_acts if a.domain == domain and a.intent == "inform"]
        requests = [a for a in user_acts if a.domain == domain and a.intent == "request"]
        conflicts = [f"{a.slot}={a.value}" for a in informs
                     if a.slot in offered and not any_match(a.value, offered[a.slot])
                     and canon(a.value) != "dontcare" and a.value not in NULL_VALUES]
        confirms = [f"{a.slot}={a.value}" for a in informs
                    if a.slot in offered and any_match(a.value, offered[a.slot])]
        books = [f"{a.slot}={a.value}" for a in informs if a.slot in BOOK_SLOTS]
        proposes = bool(offer.kinds.get(domain, set()) & ENTITY_KINDS)
        asks = sorted({a.slot for a in requests if proposes or a.slot == "ref"})
        if conflicts:
            label, how = "reject", "counter-value"
        elif confirms or books:
            label, how = "accept", "explicit"
        elif asks:
            label, how = "accept", "implicit"
        else:
            label, how = "none", None
        per_domain[domain] = {"label": label, "how": how, "conflicts": conflicts,
                              "confirms": confirms, "book": books, "requests": asks}
    for domain in offer.kinds:
        per_domain.setdefault(domain, {"label": "none", "how": None, "conflicts": [],
                                       "confirms": [], "book": [], "requests": []})
    labels = {d["label"] for d in per_domain.values()}
    turn = "reject" if "reject" in labels else "accept" if "accept" in labels else "none"
    return turn, per_domain


# ---------------------------------------------------------------------------------------------
# States


def states_legacy(log: Sequence[Mapping[str, Any]]) -> list[dict[str, set[str]]]:
    """2.1/2.4: state after each user turn (index i -> metadata of system turn i + 1)."""
    out = []
    for index in range(0, len(log), 2):
        state = legacy_state(log[index + 1]["metadata"], {})
        out.append({slot: {norm_value(value)} for slot, value in state.items()})
    return out


def states_22(turns: Sequence[Mapping[str, Any]]) -> list[dict[str, set[str]]]:
    """2.2: state after each user turn, every acceptable value kept."""
    out = []
    for index in range(0, len(turns), 2):
        state: dict[str, set[str]] = {}
        for frame in turns[index]["frames"]:
            for name, values in frame["state"]["slot_values"].items():
                kept = {norm_value(v) for v in values if v.strip() not in UNSET}
                if name in SLOTS and kept:
                    state[name] = kept
        out.append(state)
    return out


def slot_status(state: Mapping[str, set[str]], slot: str, offered: set[str]) -> str:
    values = state.get(slot)
    if not values:
        return "unset"
    return "offered" if any(any_match(v, offered) for v in values) else "other"


# ---------------------------------------------------------------------------------------------
# One dialogue


@dataclass
class DialogueInput:
    """Annotations of one dialogue in the three versions (texts are optional and never needed)."""

    dialogue_id: str
    acts: Mapping[str, Sequence[Mapping[str, Any] | None]]   # act source -> raw acts per turn
    states: Mapping[str, Sequence[Mapping[str, set[str]]]]   # version -> state per user turn
    texts: Sequence[str] | None = None


def identify(dialogue: DialogueInput, source: str) -> list[dict[str, Any]]:
    """One record per user turn that follows a system offer (act source `source`)."""
    raw = dialogue.acts[source]
    records = []
    named: set[tuple[str, str]] = set()
    last_domain: str | None = None
    previous: list[Act] = []
    for index, raw_acts in enumerate(raw):
        acts = parse_acts(raw_acts, source)
        if index % 2 == 1:   # system turn
            acts = resolve_booking(acts, previous, last_domain)
            offer = find_offer(acts, named)
            if offer and index + 1 < len(raw):
                user_acts = parse_acts(raw[index + 1], source)
                records.append(_record(dialogue, source, index + 1, offer, user_acts))
        for act in acts:   # entities named by either speaker are no longer new
            entity = ENTITY_SLOT.get(act.domain)
            if entity and act.slot == entity and act.value not in NULL_VALUES:
                named.add((act.domain, canon(act.value)))
        doms = act_domains(acts)
        if doms:
            last_domain = sorted(doms)[-1] if len(doms) > 1 else next(iter(doms))
        previous = acts
    return records


def _record(dialogue: DialogueInput, source: str, user_index: int, offer: Offer,
            user_acts: Sequence[Act]) -> dict[str, Any]:
    label, per_domain = response(offer, user_acts)
    turn = user_index // 2
    slots = []
    for domain, offered in sorted(offer.values.items()):
        for slot, values in sorted(offered.items()):
            name = f"{domain}-{slot}"
            if name not in SLOTS:
                continue
            entry: dict[str, Any] = {"slot": name, "offered": sorted(values)}
            for version in VERSIONS:
                states = dialogue.states[version]
                now = slot_status(states[turn], name, values)
                before = slot_status(states[turn - 1], name, values) if turn else "unset"
                entry[version] = now
                entry[f"{version}_new"] = now == "offered" and before != "offered"
                entry[f"{version}_value"] = sorted(states[turn].get(name, ()))
            v22, v24 = (dialogue.states[v][turn].get(name) for v in ("2.2", "2.4"))
            entry["agree_22_24"] = _agree(v22, v24, lenient=True)
            entry["agree_22_24_strict"] = _agree(v22, v24, lenient=False)
            slots.append(entry)
    return {
        "dialogue_id": dialogue.dialogue_id, "turn_index": user_index,
        "task_id": f"{dialogue.dialogue_id}:{user_index}", "act_source": source,
        "offer_domains": sorted(offer.kinds),
        "offer_kinds": {d: sorted(k) for d, k in sorted(offer.kinds.items())},
        "offered": {d: {s: sorted(v) for s, v in sorted(o.items())}
                    for d, o in sorted(offer.values.items())},
        "label": label, "domains": per_domain, "slots": slots,
        "disagree_22_24": any(not s["agree_22_24"] for s in slots),
        "disagree_22_24_strict": any(not s["agree_22_24_strict"] for s in slots),
        "state_signal": {v: _state_signal(slots, v) for v in VERSIONS},
    }


def _agree(v22: set[str] | None, v24: set[str] | None, lenient: bool) -> bool:
    """Both unset, or a shared value: exactly (`lenient=False`) or under `values_match`."""
    if not v22 and not v24:
        return True
    if not (v22 and v24):
        return False
    if lenient:
        return any(any_match(a, v24) for a in v22)
    return bool(v22 & v24)


def _state_signal(slots: Sequence[Mapping[str, Any]], version: str) -> str:
    """State-based reading of the turn in one version: an offered value newly enters the state
    (`adopt`), an offered slot holds another value (`other`), or neither (`none`)."""
    if any(s[f"{version}_new"] for s in slots):
        return "adopt"
    if any(s[version] == "other" for s in slots):
        return "other"
    return "none"


# ---------------------------------------------------------------------------------------------
# Census


def half_width(n: int, accuracy: float = 0.7, z: float = 1.959964) -> float | None:
    """95% normal-approximation interval half-width, in percentage points, for `n` items."""
    if n <= 0:
        return None
    return 100 * z * math.sqrt(accuracy * (1 - accuracy) / n)


THRESHOLD_POINTS = 5.0   # plan 6.5: above 5 points MultiWOZ becomes support


def recommendation(n: int) -> dict[str, Any]:
    hw = half_width(n)
    primary = hw is not None and hw <= THRESHOLD_POINTS
    return {"n": n, "accuracy": 0.7, "half_width_points": None if hw is None else round(hw, 2),
            "threshold_points": THRESHOLD_POINTS,
            "min_n_for_threshold": math.ceil((1.959964 / (THRESHOLD_POINTS / 100)) ** 2 * 0.21),
            "recommendation": ("MultiWOZ offer turns remain the primary evidence for the role "
                               "claim" if primary else
                               "primary evidence moves to the controlled sequences; MultiWOZ "
                               "becomes support")}


def census(records: Sequence[Mapping[str, Any]], n_dialogues: int,
           n_user_turns: int) -> dict[str, Any]:
    """Counts over the records of one act source."""
    labels = Counter(r["label"] for r in records)
    how = Counter(f"{d['label']}:{d['how']}" for r in records for d in r["domains"].values()
                  if d["label"] != "none")
    by_domain: dict[str, Counter] = defaultdict(Counter)
    by_slot: dict[str, Counter] = defaultdict(Counter)
    kinds: Counter = Counter()
    for r in records:
        for domain, info in r["domains"].items():
            by_domain[domain][info["label"]] += 1
            by_domain[domain]["offers"] += 1
        for ks in r["offer_kinds"].values():
            for k in ks:
                kinds[k] += 1
        for s in r["slots"]:
            by_slot[s["slot"]]["offered"] += 1
            by_slot[s["slot"]][r["label"]] += 1
            if not s["agree_22_24"]:
                by_slot[s["slot"]]["disagree_22_24"] += 1
    decided = [r for r in records if r["label"] in ("accept", "reject")]
    with_slots = [r for r in decided if r["slots"]]
    disagree = sum(r["disagree_22_24"] for r in with_slots)
    state = {v: Counter(r["state_signal"][v] for r in records) for v in VERSIONS}
    state_by_label = {v: {lab: dict(Counter(r["state_signal"][v] for r in records
                                            if r["label"] == lab))
                          for lab in ("accept", "reject", "none")} for v in VERSIONS}
    return {
        "dialogues": n_dialogues, "user_turns": n_user_turns,
        "offer_turns": len(records),
        "dialogues_with_offer_turn": len({r["dialogue_id"] for r in records}),
        "labels": dict(sorted(labels.items())),
        "label_how": dict(sorted(how.items())),
        "accept_or_reject": len(decided),
        "dialogues_with_accept_or_reject": len({r["dialogue_id"] for r in decided}),
        "offer_kinds": dict(sorted(kinds.items())),
        "by_domain": {d: dict(sorted(c.items())) for d, c in sorted(by_domain.items())},
        "by_slot": {s: dict(sorted(c.items())) for s, c in sorted(by_slot.items())},
        "disagree_22_24": {
            "turns_accept_or_reject_with_state_slot": len(with_slots),
            "turns_disagree": disagree,
            "share": round(disagree / len(with_slots), 4) if with_slots else None,
            "strict": _share(with_slots, "disagree_22_24_strict"),
            "by_domain": {d: _share([r for r in with_slots if d in r["offer_domains"]])
                          for d in DOMAINS},
            "by_label": {lab: _share([r for r in with_slots if r["label"] == lab])
                         for lab in ("accept", "reject")},
            "all_offer_turns": _share([r for r in records if r["slots"]]),
        },
        "state_signal": {v: dict(sorted(c.items())) for v, c in state.items()},
        "state_signal_by_label": state_by_label,
        "convention_22_24": convention(records),
        "interval": recommendation(len(decided)),
    }


def _share(records: Sequence[Mapping[str, Any]], key: str = "disagree_22_24"
           ) -> dict[str, Any]:
    n = len(records)
    k = sum(r[key] for r in records)
    return {"turns": n, "disagree": k, "share": round(k / n, 4) if n else None}


def convention(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Does 2.2 write system-offered values into the state where 2.4 does not?

    Over offered (turn, slot) pairs whose value is new in at least one of the two versions:
    cross-table of 2.2 and 2.4 status, overall and by response label."""
    table: Counter = Counter()
    by_label: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        for s in r["slots"]:
            if not (s["2.2_new"] or s["2.4_new"]):
                continue
            key = f"2.2={s['2.2']}|2.4={s['2.4']}"
            table[key] += 1
            by_label[r["label"]][key] += 1
    only22 = sum(v for k, v in table.items() if k.startswith("2.2=offered") and
                 not k.endswith("2.4=offered"))
    only24 = sum(v for k, v in table.items() if k.endswith("2.4=offered") and
                 not k.startswith("2.2=offered"))
    both = table.get("2.2=offered|2.4=offered", 0)
    total = sum(table.values())
    return {"pairs_new_in_22_or_24": total, "both_offered": both, "only_22_offered": only22,
            "only_24_offered": only24,
            "share_only_22": round(only22 / total, 4) if total else None,
            "table": dict(sorted(table.items())),
            "by_label": {lab: dict(sorted(c.items())) for lab, c in sorted(by_label.items())}}


# ---------------------------------------------------------------------------------------------
# Loading annotation files (the caller verifies manifests first)


def split_ids(source_dir_24: Path, list_file: str) -> list[str]:
    return sorted((source_dir_24 / list_file).read_text(encoding="utf-8").split())


def load_dialogues(source_dirs: Mapping[str, Path], ids: Sequence[str], dir_22: str,
                   keep_text: bool) -> tuple[list[DialogueInput], dict[str, Any]]:
    """Dialogue inputs of one split, and which version files of the split keep dialogue acts.

    Reads the 2.4 and 2.1 `data.json`, the 2.4 `dialogue_acts.json`, the 2.2 dialogues of
    `dir_22` and the 2.2 `dialog_acts.json`. Texts are kept only when `keep_text` is set."""
    wanted = set(ids)
    d24 = json.loads((source_dirs["2.4"] / DATA["2.4"]).read_text(encoding="utf-8"))
    d21 = json.loads((source_dirs["2.1"] / DATA["2.1"]).read_text(encoding="utf-8"))
    acts24 = json.loads((source_dirs["2.4"] / ACTS_24).read_text(encoding="utf-8"))
    acts22 = json.loads((source_dirs["2.2"] / ACTS_22).read_text(encoding="utf-8"))
    d22: dict[str, Any] = {}
    for path in sorted((source_dirs["2.2"] / dir_22).glob("dialogues_*.json")):
        for dialogue in json.loads(path.read_text(encoding="utf-8")):
            if dialogue["dialogue_id"] in wanted:
                d22[dialogue["dialogue_id"]] = dialogue
    presence: dict[str, Counter] = defaultdict(Counter)
    out = []
    for did in ids:
        missing = [v for v, d in (("2.4", d24), ("2.1", d21), ("2.2", d22)) if did not in d]
        if missing:
            raise ValueError(f"multiwoz: dialogue {did} missing in {missing}")
        log24, log21, turns22 = d24[did]["log"], d21[did]["log"], d22[did]["turns"]
        if not len(log24) == len(log21) == len(turns22) or len(log24) % 2:
            raise ValueError(f"multiwoz: {did}: turn counts differ or end on a user turn")
        a24 = acts24.get(did.removesuffix(".json"), {})
        a22 = acts22.get(did, {})
        raw21, raw22 = [], []
        for index in range(len(log24)):
            speaker = "user" if index % 2 == 0 else "system"
            raw21.append(log21[index].get("dialog_act") or None)
            raw22.append((a22.get(str(index)) or {}).get("dialog_act") or None)
            sys24 = a24.get(str((index + 1) // 2)) if speaker == "system" else None
            for name, present in (
                    ("2.4 data.json dialog_act", bool(log24[index].get("dialog_act"))),
                    ("2.4 dialogue_acts.json", bool(sys24) and sys24 != "No Annotation"),
                    ("2.1 data.json dialog_act", bool(raw21[-1])),
                    ("2.2 dialog_acts.json", bool(raw22[-1])),
                    ("2.2 dialogues frames.actions",
                     any(f.get("actions") for f in turns22[index]["frames"]))):
                presence[name][f"{speaker}_turns_with_acts"] += present
            presence["all"][f"{speaker}_turns"] += 1
            if speaker == "system":
                same = (set(parse_acts(sys24 if isinstance(sys24, dict) else None, "2.1"))
                        == set(parse_acts(raw21[-1], "2.1")))
                presence["2.4 dialogue_acts.json vs 2.1 data.json system acts (normalised)"][
                    "identical" if same else "different"] += 1
        out.append(DialogueInput(
            dialogue_id=did, acts={"2.1": raw21, "2.2": raw22},
            states={"2.4": states_legacy(log24), "2.1": states_legacy(log21),
                    "2.2": states_22(turns22)},
            texts=[t["text"] for t in log24] if keep_text else None))
    return out, {k: dict(sorted(v.items())) for k, v in sorted(presence.items())}


def sample(records: Sequence[Mapping[str, Any]], per_label: Mapping[str, int],
           seed: int) -> list[Mapping[str, Any]]:
    """Seeded sample of identified turns, `per_label[label]` of each label, in a fixed order."""
    rng = random.Random(seed)
    out: list[Mapping[str, Any]] = []
    for label, k in sorted(per_label.items()):
        pool = sorted((r for r in records if r["label"] == label), key=lambda r: r["task_id"])
        out.extend(rng.sample(pool, min(k, len(pool))))
    return out
