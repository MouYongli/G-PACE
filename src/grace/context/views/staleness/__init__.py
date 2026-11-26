"""Staleness strategies of resident views (plan 5.4; T019).

The eight strategies of plan 5.4 are interchangeable modules over one claim graph and one view
store (`base.Strategy`). `STRATEGIES` maps each name to its class; `make_strategy` builds one, and
`load_arms` reads the configured arms of ablation A from `configs/views/staleness.yaml` (the
claim-pattern push appears there twice, without and with local filters, the two rungs of plan
3.4's ladder).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT
from grace.context.views.staleness.base import Strategy, StrategyError
from grace.context.views.staleness.citation import UsedClaims, UsedClaimsPlusPatterns
from grace.context.views.staleness.pattern import ClaimPatternPush, PredicateLevel
from grace.context.views.staleness.requery import PushConfirm, Requery
from grace.context.views.staleness.trivial import NeverInvalidate, RebuildEveryTurn
from grace.context.views.store import ViewStore

STRATEGIES: dict[str, type[Strategy]] = {cls.name: cls for cls in (
    NeverInvalidate, RebuildEveryTurn, UsedClaims, UsedClaimsPlusPatterns, PredicateLevel,
    ClaimPatternPush, Requery, PushConfirm)}
# The strategies on plan 3.4's ladder (plus the trivial reference): no false negatives.
SOUND = ("rebuild_every_turn", "predicate_level", "claim_pattern_push", "requery",
         "push_confirm")
STALENESS_CONFIG = REPO_ROOT / "configs" / "views" / "staleness.yaml"


def make_strategy(name: str, store: ViewStore, **options: Any) -> Strategy:
    if name not in STRATEGIES:
        raise StrategyError(f"unknown staleness strategy {name!r}; expected one of "
                            f"{sorted(STRATEGIES)}")
    return STRATEGIES[name](store, **options)


def load_arms(path: Path = STALENESS_CONFIG) -> dict[str, tuple[str, dict[str, Any]]]:
    """Arm name -> (strategy name, options), validated against the strategy classes."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"arms"} or not isinstance(data["arms"], dict):
        raise StrategyError(f"{path}: expected a mapping with the single key `arms`")
    arms = {}
    for arm, spec in data["arms"].items():
        if not isinstance(spec, dict) or "strategy" not in spec:
            raise StrategyError(f"{path}: arm {arm} needs a `strategy`")
        options = {k: v for k, v in spec.items() if k != "strategy"}
        name = spec["strategy"]
        if name not in STRATEGIES:
            raise StrategyError(f"{path}: arm {arm}: unknown strategy {name!r}")
        if unknown := sorted(set(options) - set(STRATEGIES[name].option_names)):
            raise StrategyError(f"{path}: arm {arm}: unknown options {unknown}")
        arms[arm] = (name, options)
    return arms


def make_arm(arm: str, store: ViewStore, path: Path = STALENESS_CONFIG) -> Strategy:
    name, options = load_arms(path)[arm]
    return make_strategy(name, store, **options)


__all__ = ["SOUND", "STRATEGIES", "Strategy", "StrategyError", "load_arms", "make_arm",
           "make_strategy"]
