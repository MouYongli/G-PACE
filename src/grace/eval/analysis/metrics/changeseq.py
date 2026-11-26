"""Answer accuracy on the controlled change sequences: normalised set match (E005).

Primary scorer of the change sequences (docs/research/change-sequences.md section 9: "Acc,
normalised set match as primary scorer, the blind judge as secondary"). Deterministic; no judge.
Registered in `configs/common/scorers.yaml` (`change-seq`: `set-match` and
`set-match-historical`, 2026-11-26). Reads only what reaches it as run files: predictions, read
tasks and gold records.

**Normalisation.** Case-folded; number words zero to twenty become digits; every run of
characters other than a-z and 0-9 is a token boundary. A phrase is *mentioned* in a text when its
token sequence occurs contiguously in the text's token sequence ("EC 175" and "EC175" differ:
the gold surface form `answer_text` is used, which is how the dialogue names things).

**Items.** A gold answer is a set of items (`reference`). The strings an item requires: the value
of a requested constraint (V4 items are `[predicate, value]`; the predicate is an internal name),
both the option and its time for a current choice (V6 `[item, value]`), the value otherwise.

**Candidate pool** of a question: every string any gold item or outdated value requires, over the
questions of the same history and view template (the values a confused answer could state).

**Rule** (`set_match`), per read, value 0 or 1:

- `invalid` -> 0 (`count_as_wrong`, D002); `unknown` -> 1 exactly when the task expects
  abstention (the Evaluation section's abstention rule);
- an answer to an abstention task is correct when it mentions no string of the candidate pool
  ("you have not chosen one yet");
- otherwise every string of every gold item must be mentioned, and no other pool string may be
  (set equality up to the pool). A pool string that occurs inside a gold string is not checked.
  On a presupposition question (`premise_outdated`) the outdated values may be mentioned, so that
  rejecting the premise ("no, journalism, not education any more") is correct while adopting it
  is not (design section 3.4).

Paired comparisons (`paired_bootstrap`) follow decision D002: the micro mean over reads, a 95%
percentile interval from a cluster bootstrap (10,000 resamples) over the cluster unit of the
benchmark (scenario family), the same clusters drawn for both systems.
"""

from __future__ import annotations

import random
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from grace.eval.analysis.metrics.align import align, gold_index
from grace.eval.analysis.metrics.record import MetricRecord, aggregate

BENCHMARK = "change-seq"
METRIC = "set-match"
SCORER = f"{BENCHMARK}/{METRIC}"
_SPLIT = re.compile(r"[^0-9a-z]+")
_NUMBERS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
_FAMILY = re.compile(r"^(?P<family>.+)-rho\d+-L\d+-\d+$")


def tokens(text: str) -> tuple[str, ...]:
    return tuple(_NUMBERS.get(t, t) for t in _SPLIT.split(str(text).casefold()) if t)


def mentions(text_tokens: Sequence[str], phrase: str) -> bool:
    want = tokens(phrase)
    if not want:
        return False
    n = len(want)
    return any(tuple(text_tokens[i:i + n]) == want for i in range(len(text_tokens) - n + 1))


def prediction_text(prediction: Any) -> str:
    if prediction is None:
        return ""
    if isinstance(prediction, str):
        return prediction
    if isinstance(prediction, Mapping):
        return "; ".join(f"{k} {v}" for k, v in prediction.items())
    if isinstance(prediction, Sequence):
        return "; ".join(prediction_text(p) for p in prediction)
    return str(prediction)


def item_strings(template: str, item: Any) -> tuple[str, ...]:
    """The strings a gold item requires (module docstring, "Items")."""
    if isinstance(item, (list, tuple)):
        parts = [str(x) for x in item]
        return (parts[-1],) if template == "V4" else tuple(parts)
    return (str(item),)


def family_of(history_id: str) -> str:
    match = _FAMILY.match(history_id)
    return match.group("family") if match else history_id


def candidate_pools(gold: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], frozenset[str]]:
    """(history_id, template) -> the candidate pool (module docstring)."""
    pools: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in gold:
        template = row["labels"]["template"]
        key = (row["history_id"], template)
        for item in list(row["reference"] or []) + list(row["metadata"].get("outdated_text")
                                                         or []):
            pools[key].update(s for s in item_strings(template, item) if tokens(s))
    return {k: frozenset(v) for k, v in pools.items()}


def set_match(output: str, prediction: Any, gold: Mapping[str, Any],
              pool: Iterable[str]) -> float:
    """Normalised set match of one read (module docstring, "Rule")."""
    labels = gold["labels"]
    abstain = bool(labels["expected_abstention"])
    if output == "invalid":
        return 0.0
    if output == "unknown":
        return 1.0 if abstain else 0.0
    text = tokens(prediction_text(prediction))
    pool = set(pool)
    if abstain:
        return 0.0 if any(mentions(text, s) for s in pool) else 1.0
    template = labels["template"]
    required = [s for item in gold["reference"] for s in item_strings(template, item)]
    if not all(mentions(text, s) for s in required):
        return 0.0
    forbidden = pool - set(required)
    if labels.get("premise_outdated"):
        forbidden -= {s for item in gold["metadata"].get("outdated_text") or []
                      for s in item_strings(template, item)}
    forbidden = {f for f in forbidden if not any(mentions(tokens(r), f) for r in required)}
    return 0.0 if any(mentions(text, f) for f in forbidden) else 1.0


# ---------------------------------------------------------------------------------------------
# A score run


@dataclass(frozen=True)
class Scored:
    read_id: str
    task_id: str
    history_id: str
    family: str
    question_type: str
    template: str
    change_type: str
    output: str
    value: float

    def to_record(self) -> dict[str, Any]:
        return dict(self.__dict__)


def score_reads(read_tasks: list[dict], messages: list[dict], gold: list[dict],
                predictions: list[dict], *, annotation: str = "generator") -> list[Scored]:
    """Align (aborting on any evaluator obligation) and score every read."""
    aligned = align(read_tasks, messages, gold, predictions)
    index = gold_index(gold, annotation)
    pools = candidate_pools(index.values())
    out = []
    for read_id, a in aligned.items():
        g = index[a.read_task["task_id"]]
        labels = g["labels"]
        value = set_match(a.output, a.prediction["prediction"], g,
                          pools.get((g["history_id"], labels["template"]), frozenset()))
        out.append(Scored(read_id, g["task_id"], g["history_id"], family_of(g["history_id"]),
                          labels["question_type"], labels["template"], labels["change_type"],
                          a.output, value))
    return out


def metric_records(scored: Sequence[Scored], *, split: str, schedule: str, annotation: str,
                   seed: int, evaluator_version: str, include_types: Sequence[str],
                   descriptive_types: Sequence[str], strata: Sequence[str],
                   invalid_policy: str = "count_as_wrong") -> list[MetricRecord]:
    """metrics.json records: `set-match` over the population with its strata, and
    `set-match-historical` over the descriptive question types."""
    def record(metric, rows, stratum):
        tally = aggregate({r.read_id: r.value for r in rows}, {r.read_id: r.output for r in rows},
                          invalid_policy)
        return MetricRecord(BENCHMARK, split, schedule, annotation, metric, "higher", stratum,
                            seed, tally.value, tally.n_total, tally.n_scored, tally.n_invalid,
                            tally.n_unknown, tally.n_judge_invalid, invalid_policy, SCORER,
                            evaluator_version)

    population = [r for r in scored if r.question_type in include_types]
    out = [record(METRIC, population, None)]
    for label in strata:
        for value in sorted({getattr(r, label) for r in population}):
            rows = [r for r in population if getattr(r, label) == value]
            out.append(record(METRIC, rows, f"{label}={value}"))
    historical = [r for r in scored if r.question_type in descriptive_types]
    if historical:
        out.append(record(f"{METRIC}-historical", historical, None))
    return out


# ---------------------------------------------------------------------------------------------
# Uncertainty (D002)


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Percentile with linear interpolation between order statistics."""
    if not sorted_values:
        raise ValueError("no values")
    pos = q * (len(sorted_values) - 1)
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low)


def _grouped(values: Mapping[str, float], clusters: Mapping[str, str]
             ) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for read_id in sorted(values):
        groups[clusters[read_id]].append(read_id)
    return dict(sorted(groups.items()))


def cluster_bootstrap(values: Mapping[str, float], clusters: Mapping[str, str], *,
                      resamples: int = 10_000, seed: int = 0) -> dict[str, Any]:
    """Micro mean and its 95% cluster-bootstrap percentile interval."""
    groups = _grouped(values, clusters)
    names = list(groups)
    sums = {c: sum(values[r] for r in groups[c]) for c in names}
    sizes = {c: len(groups[c]) for c in names}
    rng = random.Random(seed)
    stats = []
    for _ in range(resamples):
        draw = [rng.choice(names) for _ in names]
        stats.append(sum(sums[c] for c in draw) / sum(sizes[c] for c in draw))
    stats.sort()
    n = sum(sizes.values())
    return {"mean": sum(sums.values()) / n, "ci95": [_quantile(stats, 0.025),
                                                     _quantile(stats, 0.975)],
            "n_reads": n, "n_clusters": len(names),
            "macro_mean": sum(sums[c] / sizes[c] for c in names) / len(names)}


def paired_bootstrap(a: Mapping[str, float], b: Mapping[str, float],
                     clusters: Mapping[str, str], *, resamples: int = 10_000,
                     seed: int = 0) -> dict[str, Any]:
    """Paired difference a - b of micro means over the same reads, with a 95% cluster-bootstrap
    percentile interval (the same clusters drawn for both), per-cluster differences, the macro
    mean of cluster differences and the discordant counts."""
    if set(a) != set(b):
        raise ValueError(f"paired comparison over different reads: {len(set(a) ^ set(b))} differ")
    diff = {r: a[r] - b[r] for r in a}
    boot = cluster_bootstrap(diff, clusters, resamples=resamples, seed=seed)
    groups = _grouped(diff, clusters)
    per_cluster = {c: {"n_reads": len(ids), "a": sum(a[r] for r in ids) / len(ids),
                       "b": sum(b[r] for r in ids) / len(ids),
                       "difference": sum(diff[r] for r in ids) / len(ids)}
                   for c, ids in groups.items()}
    loo = {c: (sum(diff[r] for r in diff if clusters[r] != c)
               / sum(1 for r in diff if clusters[r] != c)) for c in groups if len(groups) > 1}
    return {"difference": boot["mean"], "ci95": boot["ci95"], "n_reads": boot["n_reads"],
            "n_clusters": boot["n_clusters"], "macro_difference": boot["macro_mean"],
            "a_only_correct": sum(1 for r in a if a[r] > b[r]),
            "b_only_correct": sum(1 for r in a if b[r] > a[r]),
            "per_cluster": per_cluster, "leave_one_cluster_out": loo,
            "resamples": resamples, "seed": seed}
