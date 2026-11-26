"""E002 totals: the natural distribution of change types from the event records of a probe run.

Pure functions over the records `grace.eval.runner.probes.natural_staleness` writes
(`events.jsonl`, `histories.jsonl`); nothing here imports the engine (structure.md, analysis
rules). Reported per benchmark (plan 6.5):

- occurrences of each change type C1-C6 per thousand messages, counted two ways: (message, view)
  events, and messages with at least one event of the type;
- the ratio of citation staleness to answer staleness;
- the misses of the two citation-based strategies: stale events they did not mark, by type;
- the three types citation-based dependencies miss by design (C2 new match, C3 negation hit, C4
  count or order) as a rate and as a share of answer staleness, and the decision rule of the
  experiment file applied to them;
- over-marking of the claim-pattern (with local filters) and predicate-level strategies, and the
  type x outcome cross-table with the staleness that received no type C1-C6 (diagnostic).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

TYPES = ("C1", "C2", "C3", "C4", "C5", "C6")
MISSED_BY_DESIGN = ("C2", "C3", "C4")
CITATION_STRATEGIES = ("used_claims", "used_claims_patterns")
SOUND_STRATEGIES = ("claim_pattern_filters", "predicate_level")
STALE = ("answer", "citation")


def per_thousand(count: int, messages: int) -> float | None:
    return round(1000.0 * count / messages, 3) if messages else None


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def summarise(events: Iterable[Mapping[str, Any]], histories: Iterable[Mapping[str, Any]],
              messages: Mapping[str, int], rule: Mapping[str, float]) -> dict[str, Any]:
    """Totals per benchmark. `messages`: benchmark -> number of messages measured; `rule`:
    `max_per_thousand` and `max_share` of the missed-by-design types for "rare"."""
    events = list(events)
    histories = list(histories)
    out: dict[str, Any] = {}
    for benchmark in sorted(messages):
        evs = [e for e in events if e["benchmark"] == benchmark]
        hist = [h for h in histories if h["benchmark"] == benchmark]
        n = messages[benchmark]
        stale = [e for e in evs if e["outcome"] in STALE]
        answer = [e for e in stale if e["outcome"] == "answer"]
        citation = [e for e in stale if e["outcome"] == "citation"]

        crosstab: dict[str, Counter] = defaultdict(Counter)
        for e in evs:
            crosstab[e["type"]][e["outcome"]] += 1
        for h in hist:
            for key, value in h["counters"].items():
                _, _, _, kind, level, _ = key.split("|")
                crosstab[kind][level] += value

        by_type = {}
        for t in TYPES:
            typed = [e for e in stale if e["type"] == t]
            msgs = {(e["history_id"], e["version"]) for e in typed}
            by_type[t] = {
                "events": len(typed),
                "answer": sum(e["outcome"] == "answer" for e in typed),
                "citation": sum(e["outcome"] == "citation" for e in typed),
                "events_per_1k_messages": per_thousand(len(typed), n),
                "messages_with_type": len(msgs),
                "messages_per_1k": per_thousand(len(msgs), n),
                "by_family": dict(sorted(Counter(e["family"] for e in typed).items())),
            }
        empty = sum("empty_to_nonempty" in e["subtypes"] for e in stale if e["type"] == "C2")
        by_type["C2"]["empty_to_nonempty"] = empty

        misses = {}
        for s in CITATION_STRATEGIES:
            missed = [e for e in stale if not e["marks"].get(s)]
            missed_answer = [e for e in missed if e["outcome"] == "answer"]
            misses[s] = {
                "missed_answer": len(missed_answer),
                "missed_answer_share": share(len(missed_answer), len(answer)),
                "missed_answer_per_1k_messages": per_thousand(len(missed_answer), n),
                "missed_citation": sum(e["outcome"] == "citation" for e in missed),
                "missed_answer_by_type": dict(sorted(Counter(
                    e["type"] for e in missed_answer).items())),
            }

        by_design = [e for e in answer if e["type"] in MISSED_BY_DESIGN]
        rate, part = per_thousand(len(by_design), n), share(len(by_design), len(answer))
        rare = (rate is not None and part is not None and rate < rule["max_per_thousand"]
                and part < rule["max_share"])

        over = {}
        for s in SOUND_STRATEGIES:
            marked = [e for e in evs if e["marks"].get(s)]
            over[s] = {"marked": len(marked),
                       "marked_not_stale": sum(e["outcome"] == "none" for e in marked),
                       "stale_not_marked": sum(not e["marks"].get(s) for e in stale)}
            over[s]["over_marking_share"] = share(over[s]["marked_not_stale"], len(marked))

        views = Counter()
        for h in hist:
            views.update(h["views_created"])
        out[benchmark] = {
            "histories": len(hist), "messages": n,
            "views_created": dict(sorted(views.items())),
            "views_created_total": sum(views.values()),
            "answer_stale": len(answer), "citation_stale": len(citation),
            "answer_stale_per_1k_messages": per_thousand(len(answer), n),
            "citation_stale_per_1k_messages": per_thousand(len(citation), n),
            "citation_to_answer_ratio": (round(len(citation) / len(answer), 3)
                                         if answer else None),
            "types": by_type,
            "missed_by_design": {"types": list(MISSED_BY_DESIGN), "answer_events": len(by_design),
                                 "per_1k_messages": rate, "share_of_answer_stale": part,
                                 "rule": dict(rule), "rare": rare},
            "citation_strategy_misses": misses,
            "over_marking": over,
            "untyped_staleness": sum(e["type"] not in TYPES for e in stale),
            "crosstab": {k: dict(sorted(v.items())) for k, v in sorted(crosstab.items())},
            "soundness_violations": sum(len(h["soundness_violations"]) for h in hist),
        }
    return out
