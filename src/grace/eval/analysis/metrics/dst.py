"""Dialogue-state metrics for MultiWOZ: joint goal accuracy (JGA) and turn-level slot F1.

The registered definition (configs/common/scorers.yaml), applied identically to the 2.4, 2.2 and
2.1 annotations of the same predictions:

- A state is a mapping `domain-slot -> value`. Slot names and values are lower-cased and stripped;
  slots whose value is empty or `none` are dropped (they mean "not mentioned"); `dontcare` is a
  value like any other.
- JGA of a turn is 1 when the normalised predicted state equals the normalised gold state.
- Slot F1 of a turn is 2·TP / (|predicted| + |gold|) over (slot, value) pairs, and 1 when both
  states are empty.
- An `unknown` prediction is the empty state.

Offer-turn metrics (T028, plan 6.5): retention of original constraints and paired correctness of
"original constraint" and "current choice", on the items of the derived annotation
`2.4-current-choice` (see the functions at the end of this module).

The per-version value normalisation of published MultiWOZ evaluators (label variants such as
"guest house" / "guesthouse") is not applied; whether to add one is recorded as an open item in
the T004 PR.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

_EMPTY = {"", "none"}


def normalise_state(state: Mapping | None) -> dict[str, str]:
    if state is None:
        return {}
    if not isinstance(state, Mapping):
        raise ValueError(f"a state is a mapping, got {type(state).__name__}")
    out = {}
    for slot, value in state.items():
        if not isinstance(value, str):
            raise ValueError(f"slot {slot!r}: value must be a string")
        value = " ".join(value.lower().split())
        if value not in _EMPTY:
            out[" ".join(str(slot).lower().split())] = value
    return out


def joint_goal(predicted: Mapping | None, gold: Mapping) -> float:
    return 1.0 if normalise_state(predicted) == normalise_state(gold) else 0.0


def slot_f1(predicted: Mapping | None, gold: Mapping) -> float:
    pred, ref = set(normalise_state(predicted).items()), set(normalise_state(gold).items())
    if not pred and not ref:
        return 1.0
    return 2 * len(pred & ref) / (len(pred) + len(ref))


# ---------------------------------------------------------------------------------------------
# Offer turns (plan 6.5; T028). Gold items come from the derived annotation `2.4-current-choice`
# (grace.eval.datasets.benchmarks.multiwoz_derived). Values are compared after `normalise_state`
# normalisation, or by a lenient `match(a, b)` the caller passes (sensitivity analysis).

Match = Callable[[str, str], bool]


def _same(a: str | None, b: str | None, match: Match | None) -> bool:
    if a is None or b is None:
        return False
    a, b = " ".join(a.lower().split()), " ".join(b.lower().split())
    return a == b or (match is not None and match(a, b))


def current_choice(state: Mapping | None, choices: Mapping | None, domain: str,
                   entity_slot: str) -> str | None:
    """The predicted current choice of `domain`: `metadata.current_choice[domain]` when the
    prediction states one (also `null`), else the entity slot of the predicted state."""
    if choices is not None and domain in choices:
        value = choices[domain]
        return value if isinstance(value, str) and value.strip() else None
    return normalise_state(state).get(entity_slot)


def retained(state: Mapping | None, item: Mapping, match: Match | None = None) -> float:
    """1 when the predicted state still holds the original value of a retention item."""
    return 1.0 if _same(normalise_state(state).get(item["slot"]), item["original"], match) \
        else 0.0


def choice_correct(choice: str | None, item: Mapping, match: Match | None = None) -> bool:
    hit = any(_same(choice, v, match) for v in item["offered_entity"])
    return hit if item["response"] == "accept" else not hit


def paired_correct(state: Mapping | None, choices: Mapping | None, item: Mapping,
                   originals: Mapping[str, str], match: Match | None = None) -> float:
    """1 when every original constraint of the item is kept and the current choice is right."""
    pred = normalise_state(state)
    kept = all(_same(pred.get(slot), value, match) for slot, value in originals.items())
    choice = current_choice(state, choices, item["domain"], item["entity_slot"])
    return 1.0 if kept and choice_correct(choice, item, match) else 0.0
