"""Sequence audit (task T016): label files, mismatch rates per family, Cohen's kappa.

Protocol: docs/research/change-sequences.md section 8; guideline: docs/research/sequence-audit.md.
Reads files only (the sheet and label files), as every module under `eval/analysis/` does.

A label file is a CSV with the columns `item_id`, `annotator`, `label` and optionally `subclass`
and `note`; other columns (for example those of the sheet) are ignored, so an annotator can fill a
copy of the sheet. Rows with an empty `label` are unlabelled and skipped. One file holds one
annotator. An annotator whose name starts with `agent-` is a model or agent pre-annotation, never
a human annotator; the name `adjudicated` marks the adjudicated labels. Every statistic is computed
on the `audit` part of the sheet only; `pilot` rows are calibration and `context` rows are never
labelled.
"""

from __future__ import annotations

import csv
import math
import random
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grace.eval.analysis.judging.human import cohen_kappa

AGREE = "agree"
MISMATCH_LABELS = ("missing", "extra", "wrong-value", "wrong-attribution", "wrong-time")
MESSAGE_LABELS = (AGREE, *MISMATCH_LABELS, "unnatural")
QUESTION_LABELS = (AGREE, "gold-wrong", "ambiguous", "anchor-unidentifiable")
# Optional finer class of a label (guideline section 4); each is allowed under the labels listed.
SUBCLASSES: dict[str, tuple[str, ...]] = {
    "partial": ("missing",),
    "filler-state": ("extra",),
    "foreshadowing": ("extra",),
    "contradiction": ("extra",),
    "alias": ("wrong-value",),
    "speaker": ("wrong-attribution",),
    "function": ("wrong-attribution",),
    "report-mode": ("wrong-attribution",),
    "polarity": ("wrong-attribution",),
    "missing-signal": ("wrong-time",),
    "swapped-kind": ("wrong-time",),
    "valid-time": ("wrong-time",),
}
REQUIRED_COLUMNS = ("item_id", "annotator", "label")
SHEET_REQUIRED = ("item_id", "kind", "part", "window", "family", "skeleton")
AGENT_PREFIX = "agent-"
ADJUDICATED = "adjudicated"
# Decision rule of design section 8 [assumption there]: a family is flagged when its mismatch rate
# exceeds this share of audited messages, or one (label, skeleton) mismatch occurs this often.
RATE_LIMIT = 0.05
REPEAT_LIMIT = 3
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261125


class LabelError(ValueError):
    """A label file or sheet violates the format of the guideline."""


@dataclass(frozen=True)
class Label:
    item_id: str
    label: str
    subclass: str = ""
    note: str = ""


@dataclass
class LabelSet:
    annotator: str
    labels: dict[str, Label] = field(default_factory=dict)
    unlabelled: int = 0
    path: str = ""

    @property
    def kind(self) -> str:
        if self.annotator == ADJUDICATED:
            return "adjudicated"
        return "agent" if self.annotator.startswith(AGENT_PREFIX) else "human"


def is_mismatch(label: str) -> bool:
    return label in MISMATCH_LABELS


def read_sheet(path: Path) -> dict[str, dict[str, str]]:
    """item_id -> sheet row."""
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in SHEET_REQUIRED if c not in (reader.fieldnames or ())]
        if missing:
            raise LabelError(f"{path}: missing columns {missing}")
        rows = list(reader)
    sheet = {r["item_id"]: r for r in rows}
    if len(sheet) != len(rows):
        raise LabelError(f"{path}: duplicate item_id")
    return sheet


def parse_label(row: Mapping[str, str], kind: str, where: str) -> Label:
    item = (row.get("item_id") or "").strip()
    label = (row.get("label") or "").strip()
    allowed = MESSAGE_LABELS if kind == "message" else QUESTION_LABELS
    if label not in allowed:
        raise LabelError(f"{where}: label {label!r} not allowed for a {kind}; allowed {allowed}")
    subclass = (row.get("subclass") or "").strip()
    if subclass:
        if subclass not in SUBCLASSES:
            raise LabelError(f"{where}: unknown subclass {subclass!r}")
        if label not in SUBCLASSES[subclass]:
            raise LabelError(f"{where}: subclass {subclass} goes only with "
                             f"{SUBCLASSES[subclass]}, not {label}")
    return Label(item, label, subclass, (row.get("note") or "").strip())


def read_labels(path: Path, sheet: Mapping[str, Mapping[str, str]]) -> LabelSet:
    """Read and check one label file against the sheet."""
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or ())]
        if missing:
            raise LabelError(f"{path}: missing columns {missing}")
        annotators: set[str] = set()
        result = LabelSet(annotator="", path=str(path))
        for number, row in enumerate(reader, start=2):
            where = f"{path}:{number}"
            if not (row.get("label") or "").strip():
                result.unlabelled += 1
                continue
            item = (row.get("item_id") or "").strip()
            if item not in sheet:
                raise LabelError(f"{where}: item {item!r} is not in the sheet")
            if sheet[item]["part"] == "context":
                raise LabelError(f"{where}: {item} is read-only context and takes no label")
            annotator = (row.get("annotator") or "").strip()
            if not annotator:
                raise LabelError(f"{where}: empty annotator")
            annotators.add(annotator)
            label = parse_label(row, sheet[item]["kind"], where)
            if item in result.labels:
                raise LabelError(f"{where}: duplicate label of {item}")
            result.labels[item] = label
    if len(annotators) > 1:
        raise LabelError(f"{path}: one annotator per file, found {sorted(annotators)}")
    if not annotators:
        raise LabelError(f"{path}: no labelled rows")
    result.annotator = annotators.pop()
    return result


def audit_items(sheet: Mapping[str, Mapping[str, str]], kind: str) -> list[str]:
    return [i for i, r in sheet.items() if r["part"] == "audit" and r["kind"] == kind]


def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval of a proportion (95 % by default)."""
    if n == 0:
        raise ValueError("empty sample")
    p = successes / n
    centre = p + z * z / (2 * n)
    half = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5
    denominator = 1 + z * z / n
    return (centre - half) / denominator, (centre + half) / denominator


def bootstrap(items: Iterable[str], sheet: Mapping[str, Mapping[str, str]],
              statistic: Callable[[list[str]], float | None], draws: int = BOOTSTRAP_DRAWS,
              seed: int = BOOTSTRAP_SEED) -> dict:
    """Percentile 95 % interval of `statistic` over a bootstrap of windows (the sampling unit).

    Each draw resamples the windows of `items` with replacement and passes the items of the
    drawn windows (repeated as drawn). Draws where the statistic is undefined are counted, not
    used."""
    by_window: dict[str, list[str]] = {}
    for item in items:
        by_window.setdefault(sheet[item]["window"], []).append(item)
    windows = sorted(by_window)
    if not windows:
        return {"low": None, "high": None, "draws": 0, "undefined": 0}
    rng = random.Random(seed)
    values: list[float] = []
    undefined = 0
    for _ in range(draws):
        sample: list[str] = []
        for w in rng.choices(windows, k=len(windows)):
            sample.extend(by_window[w])
        value = statistic(sample)
        if value is None:
            undefined += 1
        else:
            values.append(value)
    if not values:
        return {"low": None, "high": None, "draws": draws, "undefined": undefined}
    values.sort()
    low = values[math.floor(0.025 * (len(values) - 1))]
    high = values[math.ceil(0.975 * (len(values) - 1))]
    return {"low": low, "high": high, "draws": draws, "undefined": undefined}


# ---------------------------------------------------------------- one label set


def _families(sheet: Mapping[str, Mapping[str, str]], items: Iterable[str]) -> list[str]:
    return sorted({sheet[i]["family"] for i in items})


def mismatch_report(labels: LabelSet, sheet: Mapping[str, Mapping[str, str]],
                    draws: int = BOOTSTRAP_DRAWS) -> dict:
    """Mismatch counts and rates per family and overall, the decision-rule flags, and the
    question labels; audit part only."""
    messages = audit_items(sheet, "message")
    questions = audit_items(sheet, "question")
    labelled_m = [i for i in messages if i in labels.labels]
    labelled_q = [i for i in questions if i in labels.labels]

    def rate(items: list[str]) -> float | None:
        return (sum(is_mismatch(labels.labels[i].label) for i in items) / len(items)
                if items else None)

    def block(items: list[str]) -> dict:
        counts = Counter(labels.labels[i].label for i in items)
        mism = sum(counts[c] for c in MISMATCH_LABELS)
        repeats = Counter((labels.labels[i].label, sheet[i]["skeleton"]) for i in items
                          if is_mismatch(labels.labels[i].label))
        out: dict[str, Any] = {
            "n": len(items), "labels": {c: counts[c] for c in MESSAGE_LABELS},
            "mismatches": mism, "rate": mism / len(items) if items else None,
            "unnatural": counts["unnatural"],
            "subclasses": dict(sorted(Counter(labels.labels[i].subclass for i in items
                                              if labels.labels[i].subclass).items())),
            "repeats": {f"{lab} / {sk}": n for (lab, sk), n in sorted(repeats.items())},
        }
        out["wilson95"] = list(wilson(mism, len(items))) if items else None
        out["bootstrap95"] = bootstrap(items, sheet, rate, draws)
        reasons = []
        if items and out["rate"] > RATE_LIMIT:
            reasons.append(f"mismatch rate {out['rate']:.3f} > {RATE_LIMIT}")
        reasons += [f"{lab} on skeleton {sk} {n} times" for (lab, sk), n in
                    sorted(repeats.items()) if n >= REPEAT_LIMIT]
        out["flag_reasons"] = reasons
        out["flagged"] = bool(reasons)
        return out

    def question_block(items: list[str]) -> dict:
        counts = Counter(labels.labels[i].label for i in items)
        bad = len(items) - counts[AGREE]
        return {"n": len(items), "labels": {c: counts[c] for c in QUESTION_LABELS},
                "not_agree": bad, "rate": bad / len(items) if items else None}

    families = _families(sheet, messages + questions)
    report = {
        "annotator": labels.annotator, "annotator_kind": labels.kind,
        "audit_messages": len(messages), "audit_questions": len(questions),
        "unlabelled_audit_messages": len(messages) - len(labelled_m),
        "unlabelled_audit_questions": len(questions) - len(labelled_q),
        "overall": block(labelled_m),
        "families": {f: block([i for i in labelled_m if sheet[i]["family"] == f])
                     for f in families},
        "questions": {"overall": question_block(labelled_q),
                      "families": {f: question_block([i for i in labelled_q
                                                      if sheet[i]["family"] == f])
                                   for f in families}},
        "mismatched_items": [
            {"item_id": i, "label": labels.labels[i].label,
             "subclass": labels.labels[i].subclass, "skeleton": sheet[i]["skeleton"],
             "note": labels.labels[i].note}
            for i in labelled_m if is_mismatch(labels.labels[i].label)],
    }
    report["flagged_families"] = sorted(f for f, b in report["families"].items() if b["flagged"])
    return report


# ---------------------------------------------------------------- two label sets


def specific_agreement(a: Mapping[str, str], b: Mapping[str, str],
                       items: Iterable[str]) -> dict:
    """Positive (mismatch) and negative (agree) specific agreement on the binary label."""
    n11 = n10 = n01 = n00 = 0
    for k in items:
        x, y = is_mismatch(a[k]), is_mismatch(b[k])
        n11 += x and y
        n10 += x and not y
        n01 += y and not x
        n00 += not x and not y
    pos = 2 * n11 + n10 + n01
    neg = 2 * n00 + n10 + n01
    return {"both_mismatch": n11, "only_a": n10, "only_b": n01, "both_agree": n00,
            "positive": (2 * n11 / pos) if pos else None,
            "negative": (2 * n00 / neg) if neg else None}


def _kappa(a: Mapping[str, str], b: Mapping[str, str], items: list[str]) -> dict:
    if not items:
        return {"n": 0, "observed": None, "disagreement": None, "kappa": None}
    result = cohen_kappa({k: a[k] for k in items}, {k: b[k] for k in items})
    return {"n": result.n, "observed": result.observed, "disagreement": 1 - result.observed,
            "kappa": result.kappa}


def _binary(labels: Mapping[str, str]) -> dict[str, str]:
    return {k: ("mismatch" if is_mismatch(v) else "agree") for k, v in labels.items()}


def _kappa_stat(a: Mapping[str, str], b: Mapping[str, str]) -> Callable[[list[str]], Any]:
    def stat(items: list[str]) -> float | None:
        # Resampled items repeat; give each copy its own key so it counts as drawn.
        ka = {f"{k}#{i}": a[k] for i, k in enumerate(items)}
        kb = {f"{k}#{i}": b[k] for i, k in enumerate(items)}
        return cohen_kappa(ka, kb).kappa if items else None
    return stat


def _disagreement_stat(a: Mapping[str, str], b: Mapping[str, str]) -> Callable[[list[str]], Any]:
    return lambda items: (sum(a[k] != b[k] for k in items) / len(items)) if items else None


def agreement(a: LabelSet, b: LabelSet, sheet: Mapping[str, Mapping[str, str]],
              draws: int = BOOTSTRAP_DRAWS) -> dict:
    """Cohen's kappa (binary and full label set), raw disagreement, mismatch prevalence and
    specific agreement on the audit messages both label, per family and overall, with bootstrap
    intervals over windows; kappa and disagreement on the audit questions."""
    if a.annotator == b.annotator:
        raise LabelError(f"both label sets are by {a.annotator!r}")
    la = {k: v.label for k, v in a.labels.items()}
    lb = {k: v.label for k, v in b.labels.items()}
    ba, bb = _binary(la), _binary(lb)
    messages = [i for i in audit_items(sheet, "message") if i in la and i in lb]
    questions = [i for i in audit_items(sheet, "question") if i in la and i in lb]
    if not messages and not questions:
        raise LabelError("the two label sets share no audit item")

    def block(items: list[str]) -> dict:
        prevalence = (sum(is_mismatch(la[k]) + is_mismatch(lb[k]) for k in items)
                      / (2 * len(items))) if items else None
        return {
            "binary": _kappa(ba, bb, items) | {
                "kappa_bootstrap95": bootstrap(items, sheet, _kappa_stat(ba, bb), draws),
                "disagreement_bootstrap95": bootstrap(items, sheet,
                                                      _disagreement_stat(ba, bb), draws)},
            "full": _kappa(la, lb, items) | {
                "kappa_bootstrap95": bootstrap(items, sheet, _kappa_stat(la, lb), draws),
                "disagreement_bootstrap95": bootstrap(items, sheet,
                                                      _disagreement_stat(la, lb), draws)},
            "prevalence": prevalence,
            "specific": specific_agreement(la, lb, items),
        }

    families = _families(sheet, messages + questions)
    confusion = {r: {c: 0 for c in MESSAGE_LABELS} for r in MESSAGE_LABELS}
    for k in messages:
        confusion[la[k]][lb[k]] += 1
    return {
        "annotators": [a.annotator, b.annotator], "kinds": [a.kind, b.kind],
        "human_agreement": a.kind == "human" and b.kind == "human",
        "missing": {"a": len(audit_items(sheet, "message")) - sum(i in la for i in
                                                                  audit_items(sheet, "message")),
                    "b": len(audit_items(sheet, "message")) - sum(i in lb for i in
                                                                  audit_items(sheet, "message"))},
        "messages": {"overall": block(messages),
                     "families": {f: block([i for i in messages if sheet[i]["family"] == f])
                                  for f in families}},
        "questions": _kappa(la, lb, questions),
        "confusion": confusion,
        "disagreements": sorted(k for k in messages + questions if la[k] != lb[k]),
    }


# ---------------------------------------------------------------- text output


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _num(x: float | None) -> str:
    return "undefined" if x is None else f"{x:.3f}"


def _ci(ci: Mapping[str, Any] | None, pct: bool = True) -> str:
    if not ci or ci.get("low") is None:
        return "n/a"
    f = _pct if pct else _num
    return f"{f(ci['low'])} to {f(ci['high'])}"


def render_mismatch(report: Mapping[str, Any]) -> str:
    lines = [f"Annotator: {report['annotator']} ({report['annotator_kind']}); audit messages "
             f"{report['audit_messages']} ({report['unlabelled_audit_messages']} unlabelled), "
             f"questions {report['audit_questions']} "
             f"({report['unlabelled_audit_questions']} unlabelled)"]
    if report["annotator_kind"] == "agent":
        lines.append("NOTE: agent pre-annotation, not a human annotator; preliminary only.")
    lines += ["", "| Family | Messages | Mismatches | Rate | Bootstrap 95% (windows) | "
                  "Unnatural | Flag |", "| --- | ---: | ---: | ---: | --- | ---: | --- |"]
    rows = list(report["families"].items()) + [("overall", report["overall"])]
    for name, b in rows:
        flag = "; ".join(b["flag_reasons"]) if name != "overall" and b["flagged"] else ""
        lines.append(f"| {name} | {b['n']} | {b['mismatches']} | {_pct(b['rate'])} | "
                     f"{_ci(b['bootstrap95'])} | {b['unnatural']} | {flag} |")
    lines += ["", "| Family | " + " | ".join(MESSAGE_LABELS) + " |",
              "| --- | " + " | ".join("---:" for _ in MESSAGE_LABELS) + " |"]
    for name, b in rows:
        lines.append(f"| {name} | " + " | ".join(str(b["labels"][c]) for c in MESSAGE_LABELS)
                     + " |")
    q = report["questions"]
    lines += ["", "| Questions | n | " + " | ".join(QUESTION_LABELS) + " |",
              "| --- | ---: | " + " | ".join("---:" for _ in QUESTION_LABELS) + " |"]
    for name, b in list(q["families"].items()) + [("overall", q["overall"])]:
        lines.append(f"| {name} | {b['n']} | " + " | ".join(str(b["labels"][c])
                                                          for c in QUESTION_LABELS) + " |")
    lines.append("")
    lines.append("Flagged families: " + (", ".join(report["flagged_families"]) or "none"))
    return "\n".join(lines)


def render_agreement(report: Mapping[str, Any]) -> str:
    lines = [f"Annotators: {report['annotators'][0]} ({report['kinds'][0]}) vs "
             f"{report['annotators'][1]} ({report['kinds'][1]})"]
    if not report["human_agreement"]:
        lines.append("NOTE: at least one label set is not a human annotator; this is not "
                     "inter-annotator agreement between humans.")
    lines += ["", "| Scope | n | Binary kappa (95%) | Full kappa (95%) | Disagreement (95%) | "
                  "Prevalence | Pos. / neg. specific |",
              "| --- | ---: | --- | --- | --- | ---: | --- |"]
    m = report["messages"]
    for name, b in list(m["families"].items()) + [("overall", m["overall"])]:
        bi, fu, sp = b["binary"], b["full"], b["specific"]
        lines.append(
            f"| {name} | {bi['n']} | {_num(bi['kappa'])} ({_ci(bi['kappa_bootstrap95'], False)})"
            f" | {_num(fu['kappa'])} ({_ci(fu['kappa_bootstrap95'], False)}) | "
            f"{_pct(fu['disagreement'])} ({_ci(fu['disagreement_bootstrap95'])}) | "
            f"{_pct(b['prevalence'])} | {_num(sp['positive'])} / {_num(sp['negative'])} |")
    q = report["questions"]
    lines += ["", f"Questions: n={q['n']}, kappa {_num(q['kappa'])}, disagreement "
                  f"{_pct(q['disagreement'])}",
              f"Unlabelled audit messages: {report['missing']}",
              f"Disagreeing items: {len(report['disagreements'])}"]
    return "\n".join(lines)
