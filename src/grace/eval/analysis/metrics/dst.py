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

The per-version value normalisation of published MultiWOZ evaluators (label variants such as
"guest house" / "guesthouse") is not applied; whether to add one is recorded as an open item in
the T004 PR.
"""

from __future__ import annotations

from collections.abc import Mapping

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
