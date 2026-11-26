"""Answer-level metrics: the official LoCoMo token F1 and accuracy from judgements.

LoCoMo F1 follows `task_eval/evaluation.py` of snap-research/locomo (the revision pinned in
`configs/common/scorers.yaml`): answers are lower-cased, commas and punctuation removed, the
articles a/an/the and the word "and" dropped, tokens Porter-stemmed (NLTK) and compared as bags.

- Category 1 (multi-hop): reference and prediction are split on commas; the score is the mean over
  reference parts of the best F1 against any prediction part.
- Categories 2, 3, 4: plain token F1; for category 3 only the part of the reference before the
  first ";" counts.
- Category 5 (adversarial): 1 if the output says "no information available" or "not mentioned",
  else 0.

GRACE predictions are structured, so the output text is the `prediction` value: a string as is, a
list joined with ", " (so that category 1 splits it back into its items). An `unknown` prediction
is an empty output for categories 1 to 4 (F1 0) and a correct abstention for category 5.
"""

from __future__ import annotations

import string
from collections import Counter
from collections.abc import Mapping
from functools import lru_cache

import numpy as np
import regex
from nltk.stem import PorterStemmer

# The third-party `regex` module, as upstream: its \b treats combining marks (\p{M}) as word
# characters, unlike `re`, so "\u0301the" keeps "the" (found by the T004 upstream comparison).
_ARTICLES = regex.compile(r"\b(a|an|the|and)\b")
_PUNCTUATION = set(string.punctuation)
_STEMMER = PorterStemmer()
LOCOMO_ABSTAIN = ("no information available", "not mentioned")


@lru_cache(maxsize=65536)
def _stem(word: str) -> str:
    return _STEMMER.stem(word)


def normalize_answer(text: str) -> str:
    text = text.replace(",", "").lower()
    text = "".join(ch for ch in text if ch not in _PUNCTUATION)
    text = _ARTICLES.sub(" ", text)
    return " ".join(text.split())


def token_f1(prediction: str, reference: str) -> float:
    pred = [_stem(w) for w in normalize_answer(prediction).split()]
    gold = [_stem(w) for w in normalize_answer(reference).split()]
    same = sum((Counter(pred) & Counter(gold)).values())
    if same == 0:
        return 0.0
    precision, recall = same / len(pred), same / len(gold)
    return 2 * precision * recall / (precision + recall)


def multi_answer_f1(prediction: str, reference: str) -> float:
    """Mean over reference parts of the best F1 against any prediction part.

    The mean is `numpy.mean`, as upstream: numpy's pairwise summation can differ from `sum()`
    in the last bit, and the scores are compared with upstream exactly."""
    preds = [p.strip() for p in prediction.split(",")]
    golds = [g.strip() for g in reference.split(",")]
    return float(np.mean([max(token_f1(p, g) for p in preds) for g in golds]))


def output_text(prediction) -> str:
    """Text of a structured prediction as the official scorers see it."""
    if prediction is None:
        return ""
    if isinstance(prediction, list):
        return ", ".join(str(item) for item in prediction)
    return str(prediction)


def reference_text(reference) -> str:
    if isinstance(reference, list):
        return ", ".join(str(item) for item in reference)
    return str(reference)


def locomo_score(category: int, output: str, prediction, reference) -> float:
    """Score of one LoCoMo read under the official rule of its category."""
    if category == 5:
        if output == "unknown":
            return 1.0
        text = output_text(prediction).lower()
        return 1.0 if any(phrase in text for phrase in LOCOMO_ABSTAIN) else 0.0
    if category not in (1, 2, 3, 4):
        raise ValueError(f"unknown LoCoMo category {category!r}")
    if output == "unknown":
        return 0.0
    answer, gold = output_text(prediction), reference_text(reference)
    if category == 3:
        gold = gold.split(";")[0].strip()
    if category == 1:
        return multi_answer_f1(answer, gold)
    return token_f1(answer, gold)


def judged_values(verdicts: Mapping[str, str], outputs: Mapping[str, str],
                  abstention: Mapping[str, bool]) -> tuple[dict[str, float | None], frozenset]:
    """Per-read accuracy from judge verdicts.

    `answer` reads take the judge's verdict (correct 1, incorrect 0; invalid leaves the
    denominator). `unknown` reads are not judged: correct exactly when the gold marks the task as
    an abstention task. `invalid` reads are left to the invalid-output policy.
    """
    values: dict[str, float | None] = {}
    judge_invalid = set()
    for read_id, output in outputs.items():
        if output == "unknown":
            values[read_id] = 1.0 if abstention[read_id] else 0.0
        elif output == "invalid":
            values[read_id] = None
        else:
            verdict = verdicts.get(read_id)
            if verdict is None:
                raise ValueError(f"read {read_id} has an answer but no judgement")
            if verdict == "invalid":
                judge_invalid.add(read_id)
                values[read_id] = None
            else:
                values[read_id] = 1.0 if verdict == "correct" else 0.0
    return values, frozenset(judge_invalid)
