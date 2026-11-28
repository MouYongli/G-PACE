"""Graph-quality annotation: label checks, claim-level agreement and merge (task T024).

Guideline: docs/research/graph-quality-annotation.md. Label files are JSON Lines, one record per
claim, stance, entity alignment or segment end (guideline section 6). The segments file is the
`segments.jsonl` written next to the sample in the T024 run directory; it holds the message IDs
and texts the checks need. This module reads only those files and imports no engine code.

Matching (guideline section 7) is one to one within a segment and deterministic: candidate pairs
on the same message whose subjects and objects agree after normalisation (`anchor` level) are
taken in order of descending score, then by claim IDs; `strict` pairs also have the same
normalised predicate.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KINDS = ("claim", "stance", "same_as", "segment_done")
OBJECT_TYPES = ("entity", "string", "integer", "boolean", "date", "dateTime", "time")
FUNCTIONS = ("request", "offer", "accept", "reject", "confirm", "inform", "commit", "question")
REPORT_MODES = ("own", "quote", "hypothetical")
POLARITIES = ("positive", "negative")
CERTAINTIES = ("certain", "probable", "possible", "underspecified")
ENDS = (None, "change", "correction")
CLAIM_FIELDS = ("id", "message_id", "subject", "predicate", "object", "object_type", "speaker",
                "function", "report_mode", "polarity", "certainty", "derived", "correction",
                "time_expression", "valid_from", "valid_until", "quote")
STANCE_FIELDS = ("message_id", "claim", "speaker", "function", "polarity", "derived", "ends",
                 "valid_until", "quote")
COMPARED = ("predicate", "object_type", "function", "report_mode", "polarity", "certainty",
            "derived", "correction", "time_expression", "valid_from", "valid_until")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PREDICATE = re.compile(r"^[a-z][A-Za-z0-9]*$")
ARTICLES = {"a", "an", "the"}


class LabelError(ValueError):
    """A label file does not follow the guideline."""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise LabelError(f"{path}:{n}: not JSON: {exc}") from exc
    return rows


@dataclass
class SegmentText:
    key: str
    benchmark: str
    messages: dict[str, dict[str, Any]]      # message_id -> message row


def read_segments(path: Path) -> dict[str, SegmentText]:
    out = {}
    for row in read_jsonl(path):
        out[row["key"]] = SegmentText(row["key"], row["benchmark"],
                                      {m["message_id"]: m for m in row["messages"]})
    return out


# ---- checks -----------------------------------------------------------------------------------

def check(labels: Sequence[Mapping[str, Any]], segments: Mapping[str, SegmentText]) -> list[str]:
    """Problems of one label file against the segments; an empty list when it is valid."""
    problems: list[str] = []
    done: Counter[str] = Counter()
    ids: dict[str, set[str]] = defaultdict(set)
    stances = []
    for n, r in enumerate(labels, start=1):
        where = f"record {n}"
        seg = segments.get(r.get("segment"))
        kind = r.get("kind")
        if seg is None:
            problems.append(f"{where}: unknown segment {r.get('segment')!r}")
            continue
        if kind not in KINDS:
            problems.append(f"{where}: unknown kind {kind!r}")
            continue
        if kind == "segment_done":
            done[seg.key] += 1
            continue
        msg = seg.messages.get(r.get("message_id"))
        if msg is None:
            problems.append(f"{where}: message {r.get('message_id')!r} is not in {seg.key}")
            continue
        if kind == "same_as":
            if not r.get("name") or not r.get("same_as"):
                problems.append(f"{where}: same_as needs name and same_as")
            continue
        quote = r.get("quote")
        if not isinstance(quote, str) or not quote or quote not in msg["text"]:
            problems.append(f"{where}: quote does not occur verbatim in {msg['message_id']}")
        if r.get("function") not in FUNCTIONS:
            problems.append(f"{where}: function {r.get('function')!r}")
        if r.get("polarity") not in POLARITIES:
            problems.append(f"{where}: polarity {r.get('polarity')!r}")
        if not isinstance(r.get("derived"), bool):
            problems.append(f"{where}: derived must be a boolean")
        if kind == "stance":
            if r.get("ends") not in ENDS:
                problems.append(f"{where}: ends {r.get('ends')!r}")
            stances.append((where, seg.key, r.get("claim")))
            continue
        missing = [f for f in CLAIM_FIELDS if f not in r]
        if missing:
            problems.append(f"{where}: missing fields {missing}")
        cid = r.get("id")
        if not cid or cid in ids[seg.key]:
            problems.append(f"{where}: claim id {cid!r} missing or repeated in {seg.key}")
        ids[seg.key].add(cid)
        for name in ("subject", "object"):
            if not isinstance(r.get(name), str) or not r[name].strip():
                problems.append(f"{where}: empty {name}")
        if not isinstance(r.get("predicate"), str) or not PREDICATE.match(r["predicate"]):
            problems.append(f"{where}: predicate {r.get('predicate')!r} is not lowerCamelCase")
        if r.get("object_type") not in OBJECT_TYPES:
            problems.append(f"{where}: object_type {r.get('object_type')!r}")
        if r.get("report_mode") not in REPORT_MODES:
            problems.append(f"{where}: report_mode {r.get('report_mode')!r}")
        if r.get("certainty") not in CERTAINTIES:
            problems.append(f"{where}: certainty {r.get('certainty')!r}")
        if not isinstance(r.get("correction"), bool):
            problems.append(f"{where}: correction must be a boolean")
        for name in ("valid_from", "valid_until"):
            value = r.get(name)
            if value is not None and not (isinstance(value, str) and DATE.match(value)):
                problems.append(f"{where}: {name} {value!r} is not YYYY-MM-DD or null")
    for where, key, cid in stances:
        if cid not in ids[key]:
            problems.append(f"{where}: stance names unknown claim {cid!r} in {key}")
    for key in segments:
        if done[key] == 0:
            problems.append(f"segment {key}: no segment_done record")
        elif done[key] > 1:
            problems.append(f"segment {key}: {done[key]} segment_done records")
    return problems


# ---- normalisation and matching ---------------------------------------------------------------

def norm_text(value: Any) -> str:
    text = str(value or "").lower().replace("’", "'")
    text = re.sub(r"'s\b", "", text)
    text = re.sub(r"[^\w\s:]", " ", text)
    return " ".join(t for t in text.split() if t not in ARTICLES)


def norm_predicate(value: Any) -> str:
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or "")).lower().split()
    return " ".join(words)


def head_tokens(value: Any) -> set[str]:
    """Tokens of the head of a name: what follows its last possessive ("Caroline's necklace"
    -> {necklace}); the whole name when it has none."""
    text = str(value or "").lower().replace("’", "'")
    parts = re.split(r"'s\b|s'(?=\s)", text)
    return set(norm_text(parts[-1]).split()) or set(norm_text(text).split())


def same_name(a: Any, b: Any) -> bool:
    """Equal after normalisation, or the tokens of one name contained in the other's, provided
    the shorter name shares a token with the longer one's head: "Caroline" does not match
    "Caroline's necklace" (the possessor is not the thing), "necklace" does."""
    x, y = norm_text(a), norm_text(b)
    if not x or not y:
        return False
    if x == y:
        return True
    tx, ty = set(x.split()), set(y.split())
    if tx <= ty:
        return bool(tx & head_tokens(b))
    if ty <= tx:
        return bool(ty & head_tokens(a))
    return False


def _tokens(value: str) -> set[str]:
    return set(value.split())


def pair_score(a: Mapping[str, Any], b: Mapping[str, Any]) -> float | None:
    """Score of a candidate pair, or None when the two claims cannot match (anchor level)."""
    if a["message_id"] != b["message_id"]:
        return None
    if not (same_name(a["subject"], b["subject"]) and same_name(a["object"], b["object"])):
        return None
    pa, pb = norm_predicate(a["predicate"]), norm_predicate(b["predicate"])
    overlap = len(_tokens(pa) & _tokens(pb)) / max(1, len(_tokens(pa) | _tokens(pb)))
    exact = (norm_text(a["subject"]) == norm_text(b["subject"])) + \
        (norm_text(a["object"]) == norm_text(b["object"]))
    return 10.0 * (pa == pb) + overlap + 0.5 * exact


def match(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]]
          ) -> list[tuple[int, int, bool]]:
    """One-to-one matching of two claim lists of one segment: (index in a, index in b, strict)."""
    candidates = []
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            score = pair_score(x, y)
            if score is not None:
                candidates.append((-score, str(x.get("id")), str(y.get("id")), i, j))
    candidates.sort()
    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs = []
    for _, _, _, i, j in candidates:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        strict = norm_predicate(a[i]["predicate"]) == norm_predicate(b[j]["predicate"])
        pairs.append((i, j, strict))
    return sorted(pairs)


def _claims(labels: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in labels:
        if r.get("kind") == "claim":
            out[r["segment"]].append(dict(r))
    return out


def _same(field_name: str, x: Any, y: Any) -> bool:
    if field_name == "predicate":
        return norm_predicate(x) == norm_predicate(y)
    if field_name == "time_expression":
        return norm_text(x) == norm_text(y)
    return x == y


@dataclass
class Tally:
    n_a: int = 0
    n_b: int = 0
    anchor: int = 0
    strict: int = 0
    fields: Counter = field(default_factory=Counter)
    stances_a: int = 0
    stances_b: int = 0
    empty_both: int = 0
    empty_one: int = 0
    segments: int = 0

    def summary(self) -> dict[str, Any]:
        def dice(m: int) -> float | None:
            total = self.n_a + self.n_b
            return round(2 * m / total, 4) if total else None
        return {
            "segments": self.segments, "claims_a": self.n_a, "claims_b": self.n_b,
            "matched_anchor": self.anchor, "matched_strict": self.strict,
            "dice_anchor": dice(self.anchor), "dice_strict": dice(self.strict),
            "field_agreement_on_anchor_pairs": {
                f: round(self.fields[f] / self.anchor, 4) if self.anchor else None
                for f in COMPARED},
            "stances_a": self.stances_a, "stances_b": self.stances_b,
            "segments_empty_both": self.empty_both, "segments_empty_one": self.empty_one,
        }


def agreement(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]],
              segments: Mapping[str, SegmentText]) -> dict[str, Any]:
    """Claim-level agreement between two label files, overall and per benchmark."""
    ca, cb = _claims(a), _claims(b)
    stance_a = Counter(r["segment"] for r in a if r.get("kind") == "stance")
    stance_b = Counter(r["segment"] for r in b if r.get("kind") == "stance")
    tallies: dict[str, Tally] = defaultdict(Tally)
    for key, seg in sorted(segments.items()):
        xs, ys = ca.get(key, []), cb.get(key, [])
        pairs = match(xs, ys)
        for bucket in ("all", seg.benchmark):
            t = tallies[bucket]
            t.segments += 1
            t.n_a += len(xs)
            t.n_b += len(ys)
            t.anchor += len(pairs)
            t.strict += sum(1 for _, _, s in pairs if s)
            for i, j, _ in pairs:
                for f in COMPARED:
                    t.fields[f] += _same(f, xs[i].get(f), ys[j].get(f))
            t.stances_a += stance_a[key]
            t.stances_b += stance_b[key]
            t.empty_both += not xs and not ys
            t.empty_one += bool(xs) != bool(ys)
    return {k: tallies[k].summary() for k in ["all"] + sorted(set(tallies) - {"all"})}


def merge(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]],
          segments: Mapping[str, SegmentText], name_a: str, name_b: str) -> list[dict[str, Any]]:
    """Merged claim list for review: matched pairs and unmatched claims of either file."""
    ca, cb = _claims(a), _claims(b)
    out = []
    for key in sorted(segments):
        xs, ys = ca.get(key, []), cb.get(key, [])
        pairs = match(xs, ys)
        seen_a = {i for i, _, _ in pairs}
        seen_b = {j for _, j, _ in pairs}
        for i, j, strict in pairs:
            diff = [f for f in COMPARED if not _same(f, xs[i].get(f), ys[j].get(f))]
            out.append({"segment": key, "message_id": xs[i]["message_id"],
                        "agreement": "both", "strict": strict, "differs": diff,
                        name_a: _strip(xs[i]), name_b: _strip(ys[j])})
        for i, x in enumerate(xs):
            if i not in seen_a:
                out.append({"segment": key, "message_id": x["message_id"],
                            "agreement": f"{name_a}_only", name_a: _strip(x), name_b: None})
        for j, y in enumerate(ys):
            if j not in seen_b:
                out.append({"segment": key, "message_id": y["message_id"],
                            "agreement": f"{name_b}_only", name_a: None, name_b: _strip(y)})
    order = {key: {mid: n for n, mid in enumerate(seg.messages)} for key, seg in segments.items()}
    out.sort(key=lambda r: (r["segment"], order[r["segment"]].get(r["message_id"], 0)))
    return out


def _strip(record: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in ("segment", "annotator", "kind")}


def counts(labels: Sequence[Mapping[str, Any]], segments: Mapping[str, SegmentText]
           ) -> dict[str, Any]:
    """Descriptive counts of one label file per benchmark."""
    per: dict[str, Counter] = defaultdict(Counter)
    for r in labels:
        seg = segments.get(r.get("segment"))
        if seg is None:
            continue
        for bucket in ("all", seg.benchmark):
            per[bucket][r.get("kind")] += 1
            if r.get("kind") == "claim":
                per[bucket][f"function:{r.get('function')}"] += 1
                per[bucket][f"role:{seg.messages[r['message_id']].get('role')}"] += 1
    messages = Counter()
    for seg in segments.values():
        messages["all"] += len(seg.messages)
        messages[seg.benchmark] += len(seg.messages)
    return {k: {"messages": messages[k], "claims_per_message":
                round(per[k]["claim"] / messages[k], 3) if messages[k] else None,
                **dict(sorted(per[k].items()))}
            for k in ["all"] + sorted(set(per) - {"all"})}
