"""Evidence-anchored read points of LoCoMo (plan 6.5, task T007). Deterministic and model-free.

For each category 1-4 question q, v(q) is the version that ends the session containing the latest
turn of its annotated evidence. A question whose evidence is missing or does not resolve to a turn
(`metadata.evidence_status` of the adapter is not `complete`) gets no read point and is excluded
from streaming. A question on the independent audit's evidence-error list (`WRONG_CITATION`) keeps
its read point from the annotated evidence but is reported separately; the audit's corrected
evidence gives a second read point, `v_audit`, for comparison. The audit's answer-error list (the
other error types) is carried as a label only: plan 6.5 reports all questions and the remainder
after removing those.

Read points of a history are the distinct v(q) of its streaming questions plus N, because every
question is also asked at N. The writes between two adjacent read points are the messages with
version in (r_i, r_{i+1}]; tokens are counted on the message text with the counter passed in.

Quantiles use linear interpolation between order statistics (`statistics.quantiles`, method
`inclusive`), so the median of an even sample is the mean of the two middle values.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from grace.eval.datasets.benchmarks.base import Records

ANSWER_ERROR_TYPES = ("HALLUCINATION", "TEMPORAL_ERROR", "ATTRIBUTION_ERROR", "INCOMPLETE",
                      "AMBIGUOUS")
EVIDENCE_ERROR_TYPE = "WRONG_CITATION"
STREAMING = "streaming"                  # included in the main streaming analysis
SEPARATE = "reported_separately"         # read at v(q) but reported apart (audit evidence error)
EXCLUDED = "excluded"                    # no read point

QUANTILES = (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)


class ReadPointError(ValueError):
    """The records or the audit lists do not fit together."""


# ---------------------------------------------------------------------------------------------
# Audit lists


@dataclass(frozen=True)
class AuditEntry:
    task_id: str
    error_type: str
    cited_evidence: tuple[str, ...]
    correct_evidence: tuple[str, ...]


def load_audit(audit_dir: Path, sample_ids: Sequence[str],
               questions: Mapping[str, str] | None = None,
               include: Iterable[str] | None = None) -> dict[str, AuditEntry]:
    """Read `errors_conv_<i>.json` for every sample in source order (only the samples in
    `include` when given, so a development run never opens a held-out audit file).

    The audit names questions `locomo_<i>_qa<k>`, where i is the index of the sample in
    `locomo10.json` and k the 0-based index in its `qa` list, i.e. task `<sample_id>:q<k>`.
    When `questions` (task ID -> question text) is given, every entry must name the same question.
    """
    include = None if include is None else set(include)
    entries: dict[str, AuditEntry] = {}
    for index, sid in enumerate(sample_ids):
        if include is not None and sid not in include:
            continue
        path = audit_dir / f"errors_conv_{index}.json"
        if not path.is_file():
            raise ReadPointError(f"missing audit file {path}")
        for row in json.loads(path.read_text(encoding="utf-8")):
            prefix, _, k = row["question_id"].rpartition("_qa")
            if prefix != f"locomo_{index}" or not k.isdigit():
                raise ReadPointError(f"{path}: unexpected question_id {row['question_id']!r}")
            task_id = f"{sid}:q{int(k)}"
            if questions is not None and questions.get(task_id) != row["question"]:
                raise ReadPointError(f"{path}: {row['question_id']} does not match {task_id}")
            if task_id in entries:
                raise ReadPointError(f"{path}: duplicate audit entry for {task_id}")
            entries[task_id] = AuditEntry(task_id, row["error_type"],
                                          tuple(map(str, row.get("cited_evidence") or ())),
                                          tuple(map(str, row.get("correct_evidence") or ())))
    unknown = sorted({e.error_type for e in entries.values()}
                     - {EVIDENCE_ERROR_TYPE, *ANSWER_ERROR_TYPES})
    if unknown:
        raise ReadPointError(f"unknown audit error types {unknown}")
    return entries


# ---------------------------------------------------------------------------------------------
# Per-question read points


@dataclass(frozen=True)
class ReadPoint:
    task_id: str
    history_id: str
    split: str
    category: int
    evidence_status: str
    evidence_ids: tuple[str, ...]
    evidence_unresolved: tuple[str, ...]
    n_messages: int
    n_sessions: int
    status: str                       # STREAMING, SEPARATE or EXCLUDED
    reason: str | None                # why a question is excluded or reported separately
    latest_evidence: str | None
    session: str | None               # segment that holds the latest evidence turn
    session_index: int | None         # 1-based position of that session
    v: int | None                     # v(q)
    before_final: bool | None         # v(q) < N
    audit_error: str | None
    v_audit: int | None               # v(q) from the audit's corrected evidence (WRONG_CITATION)

    @property
    def relative(self) -> float | None:
        return None if self.v is None else self.v / self.n_messages

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["evidence_ids"] = list(self.evidence_ids)
        record["evidence_unresolved"] = list(self.evidence_unresolved)
        record["relative"] = None if self.v is None else round(self.relative, 6)
        return record


@dataclass
class HistoryIndex:
    history_id: str
    split: str
    n_messages: int
    segments: list[tuple[str, int, int]]          # (segment_id, first, last) in order
    version_of: dict[str, int]                     # message_id -> version
    texts: list[str]                               # texts[v - 1] is the text of version v

    def session_of(self, version: int) -> tuple[int, str, int]:
        """(1-based index, segment ID, last version) of the session holding `version`."""
        for index, (segment_id, first, last) in enumerate(self.segments, start=1):
            if first <= version <= last:
                return index, segment_id, last
        raise ReadPointError(f"{self.history_id}: version {version} lies in no segment")

    def read_point_of(self, evidence: Iterable[str]) -> tuple[str, int, str, int] | None:
        """(latest evidence ID, session index, session ID, session end) or None if any ID is
        not a turn of this history or the evidence is empty."""
        evidence = list(evidence)
        if not evidence or any(e not in self.version_of for e in evidence):
            return None
        latest = max(evidence, key=self.version_of.__getitem__)
        index, segment_id, end = self.session_of(self.version_of[latest])
        return latest, index, segment_id, end


def index_histories(records: Records) -> dict[str, HistoryIndex]:
    indexes: dict[str, HistoryIndex] = {}
    for history in records.histories:
        if not history.segments:
            raise ReadPointError(f"{history.history_id}: LoCoMo histories must have segments")
        indexes[history.history_id] = HistoryIndex(
            history.history_id, history.split, history.n_messages,
            [(s.segment_id, s.first_version, s.last_version) for s in history.segments],
            {}, [""] * history.n_messages)
    for message in records.messages:
        index = indexes[message.history_id]
        if message.message_id in index.version_of:
            raise ReadPointError(f"{message.history_id}: duplicate message {message.message_id}")
        index.version_of[message.message_id] = message.version
        index.texts[message.version - 1] = message.text
    return indexes


def compute_read_points(records: Records, audit: Mapping[str, AuditEntry]) -> list[ReadPoint]:
    """One ReadPoint per gold record of `records` (categories 1-4 after the adapter)."""
    indexes = index_histories(records)
    points = []
    for gold in records.gold:
        history = indexes[gold.history_id]
        status_raw = gold.metadata.get("evidence_status")
        entry = audit.get(gold.task_id)
        audit_error = entry.error_type if entry else None
        evidence = tuple(gold.evidence_ids or ())
        located = history.read_point_of(evidence) if status_raw == "complete" else None
        if status_raw == "complete" and located is None:
            raise ReadPointError(f"{gold.task_id}: evidence marked complete does not resolve")
        v_audit = None
        if entry is not None and entry.error_type == EVIDENCE_ERROR_TYPE:
            corrected = history.read_point_of(entry.correct_evidence)
            v_audit = corrected[3] if corrected else None
        if located is None:
            status = EXCLUDED
            reason = ("evidence_missing" if status_raw == "missing"
                      else "evidence_unresolved")
            latest = session = index = v = before = None
        else:
            latest, index, session, v = located
            before = v < history.n_messages
            if audit_error == EVIDENCE_ERROR_TYPE:
                status, reason = SEPARATE, "audit_wrong_citation"
            else:
                status, reason = STREAMING, None
        points.append(ReadPoint(
            task_id=gold.task_id, history_id=gold.history_id, split=history.split,
            category=int(gold.labels["category"]), evidence_status=str(status_raw),
            evidence_ids=evidence, evidence_unresolved=tuple(gold.evidence_unresolved),
            n_messages=history.n_messages, n_sessions=len(history.segments), status=status,
            reason=reason, latest_evidence=latest, session=session, session_index=index, v=v,
            before_final=before, audit_error=audit_error, v_audit=v_audit))
    return points


# ---------------------------------------------------------------------------------------------
# Statistics


def quantiles(values: Sequence[float]) -> dict[str, float] | None:
    """min, p10, p25, median, p75, p90, max (linear interpolation, inclusive method)."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        cuts = [ordered[0]] * 5
    else:
        cuts = statistics.quantiles(ordered, n=20, method="inclusive")
        cuts = [cuts[1], cuts[4], cuts[9], cuts[14], cuts[17]]  # 10, 25, 50, 75, 90 percent
    names = ("min", "p10", "p25", "median", "p75", "p90", "max")
    return {n: round(float(x), 4) for n, x in zip(names, [ordered[0], *cuts, ordered[-1]],
                                                      strict=True)}


@dataclass
class HistoryStats:
    history_id: str
    split: str
    n_messages: int
    n_sessions: int
    n_tokens: int
    n_questions: int                     # streaming questions of this history
    n_before_final: int
    read_points: list[int]               # distinct v(q) of streaming questions, plus N
    questions_per_read_point: dict[int, int]
    prefix_messages: int                 # messages before the first read point (inclusive)
    prefix_tokens: int
    gaps_messages: list[int]             # messages written between adjacent read points
    gaps_tokens: list[int]
    gaps_sessions: list[int]
    share_written_after_first_read: float
    session_lengths: list[int] = field(default_factory=list)


def history_stats(history: HistoryIndex, points: Sequence[ReadPoint],
                  count_tokens: Callable[[str], int]) -> HistoryStats:
    """Read-point spacing of one history over its STREAMING questions."""
    tokens = [count_tokens(t) for t in history.texts]
    cumulative = [0]
    for t in tokens:
        cumulative.append(cumulative[-1] + t)
    mine = [p for p in points if p.history_id == history.history_id and p.status == STREAMING]
    per_point = Counter(p.v for p in mine)
    reads = sorted({*per_point, history.n_messages})
    ends = [last for _, _, last in history.segments]
    gaps_m, gaps_t, gaps_s = [], [], []
    for a, b in zip(reads, reads[1:], strict=False):
        gaps_m.append(b - a)
        gaps_t.append(cumulative[b] - cumulative[a])
        gaps_s.append(sum(1 for e in ends if a < e <= b))
    first = reads[0]
    return HistoryStats(
        history_id=history.history_id, split=history.split, n_messages=history.n_messages,
        n_sessions=len(history.segments), n_tokens=cumulative[-1], n_questions=len(mine),
        n_before_final=sum(1 for p in mine if p.before_final),
        read_points=reads, questions_per_read_point={v: per_point.get(v, 0) for v in reads},
        prefix_messages=first, prefix_tokens=cumulative[first], gaps_messages=gaps_m,
        gaps_tokens=gaps_t, gaps_sessions=gaps_s,
        share_written_after_first_read=round((history.n_messages - first) / history.n_messages, 6),
        session_lengths=[last - first_v + 1 for _, first_v, last in history.segments])


def _share(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 4)


def summarize(points: Sequence[ReadPoint], stats: Sequence[HistoryStats]) -> dict[str, Any]:
    """Summary over one group of histories (a split, or all of them)."""
    streaming = [p for p in points if p.status == STREAMING]
    separate = [p for p in points if p.status == SEPARATE]
    by_category: dict[int, list[ReadPoint]] = defaultdict(list)
    for p in streaming:
        by_category[p.category].append(p)
    gaps_m = [g for s in stats for g in s.gaps_messages]
    gaps_t = [g for s in stats for g in s.gaps_tokens]
    gaps_s = [g for s in stats for g in s.gaps_sessions]
    deciles = Counter(min(int(p.relative * 10), 9) for p in streaming)
    return {
        "histories": len(stats),
        "questions": len(points),
        "status_counts": dict(sorted(Counter(p.status for p in points).items())),
        "streaming": {
            "questions": len(streaming),
            "before_final": sum(1 for p in streaming if p.before_final),
            "share_before_final": _share(sum(1 for p in streaming if p.before_final),
                                         len(streaming)),
            "relative_v": quantiles([p.relative for p in streaming]),
            "relative_v_deciles": {f"{k / 10:.1f}-{(k + 1) / 10:.1f}": deciles.get(k, 0)
                                   for k in range(10)},
            "by_category": {
                str(c): {"questions": len(ps),
                         "share_before_final": _share(sum(1 for p in ps if p.before_final),
                                                      len(ps)),
                         "median_relative_v": quantiles([p.relative for p in ps])["median"]}
                for c, ps in sorted(by_category.items())},
        },
        "reported_separately": {
            "questions": len(separate),
            "share_before_final": _share(sum(1 for p in separate if p.before_final),
                                         len(separate)),
            "v_audit_later_than_v": sum(1 for p in separate
                                        if p.v_audit is not None and p.v_audit > p.v),
            "v_audit_earlier_than_v": sum(1 for p in separate
                                          if p.v_audit is not None and p.v_audit < p.v),
            "v_audit_unresolved": sum(1 for p in separate if p.v_audit is None),
        },
        "read_points": {
            "distinct_per_history": quantiles([len(s.read_points) for s in stats]),
            "distinct_before_final_per_history": quantiles([len(s.read_points) - 1
                                                            for s in stats]),
            "share_written_after_first_read": quantiles(
                [s.share_written_after_first_read for s in stats]),
            "gaps": len(gaps_m),
            "gap_messages": quantiles(gaps_m),
            "gap_tokens": quantiles(gaps_t),
            "gap_sessions": quantiles(gaps_s),
            "gaps_with_no_message": sum(1 for g in gaps_m if g == 0),
            "session_messages": quantiles([n for s in stats for n in s.session_lengths]),
        },
        "answer_error_label": {
            "questions": sum(1 for p in points if p.audit_error in ANSWER_ERROR_TYPES),
            "streaming": sum(1 for p in streaming if p.audit_error in ANSWER_ERROR_TYPES),
        },
    }


def exclusions(points: Sequence[ReadPoint]) -> dict[str, Any]:
    """Questions without a read point and questions reported separately, with reasons."""
    def rows(selected: Iterable[ReadPoint]) -> list[dict[str, Any]]:
        return [{"task_id": p.task_id, "split": p.split, "category": p.category,
                 "reason": p.reason, "evidence_ids": list(p.evidence_ids),
                 "evidence_unresolved": list(p.evidence_unresolved), "v": p.v,
                 "v_audit": p.v_audit} for p in selected]

    excluded = [p for p in points if p.status == EXCLUDED]
    separate = [p for p in points if p.status == SEPARATE]
    answer = [p for p in points if p.audit_error in ANSWER_ERROR_TYPES]
    return {
        "excluded": {"count": len(excluded),
                     "by_reason": dict(sorted(Counter(p.reason for p in excluded).items())),
                     "questions": rows(excluded)},
        "reported_separately": {"count": len(separate),
                                "by_reason": dict(sorted(Counter(p.reason
                                                                 for p in separate).items())),
                                "questions": rows(separate)},
        "audit_answer_error_label": {
            "count": len(answer),
            "by_type": dict(sorted(Counter(p.audit_error for p in answer).items())),
            "task_ids": [p.task_id for p in answer]},
    }


# ---------------------------------------------------------------------------------------------
# Promotion threshold (plan 6.5): fixed on the development histories before held-out statistics


@dataclass(frozen=True)
class Threshold:
    min_share_before_final: float           # of held-out streaming questions
    min_median_distinct_read_points: float  # per held-out history, N included
    min_median_gap_tokens: float            # tokens written between adjacent read points

    @classmethod
    def from_config(cls, raw: Mapping[str, Any]) -> Threshold:
        try:
            return cls(float(raw["min_share_before_final"]),
                       float(raw["min_median_distinct_read_points"]),
                       float(raw["min_median_gap_tokens"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ReadPointError(f"promotion threshold incomplete: {exc}") from exc


def evaluate_threshold(summary: Mapping[str, Any], threshold: Threshold) -> dict[str, Any]:
    """Apply the threshold to a summary; every criterion must hold for promotion."""
    observed = {
        "share_before_final": summary["streaming"]["share_before_final"],
        "median_distinct_read_points": summary["read_points"]["distinct_per_history"]["median"],
        "median_gap_tokens": (summary["read_points"]["gap_tokens"] or {}).get("median", 0.0),
    }
    checks = {
        "share_before_final": observed["share_before_final"] is not None
        and observed["share_before_final"] >= threshold.min_share_before_final,
        "median_distinct_read_points": observed["median_distinct_read_points"]
        >= threshold.min_median_distinct_read_points,
        "median_gap_tokens": observed["median_gap_tokens"] >= threshold.min_median_gap_tokens,
    }
    return {"threshold": asdict(threshold), "observed": observed, "checks": checks,
            "promote_to_main_text": all(checks.values())}


def whitespace_tokens(text: str) -> int:
    """Fallback counter: whitespace-separated words (not model tokens)."""
    return len(text.split())


# ---------------------------------------------------------------------------------------------
# The streaming schedule (task T031)


def streaming_tasks(records: Records, points: Sequence[ReadPoint]) -> list[dict[str, Any]]:
    """Read tasks of the `streaming` schedule (contracts.md, Read task): every question with a
    read point is asked at v(q) and at N; excluded questions are not in the schedule. A question
    with v(q) = N has one read, at N."""
    by_id = {t.task_id: t for t in records.read_tasks}
    rows = []
    for p in points:
        if p.v is None:
            continue
        task = by_id[p.task_id].to_record()
        for version in sorted({p.v, p.n_messages}):
            rows.append({**task, "read_id": f"{p.task_id}@{version}", "version": version})
    return rows


def load_committed(path: Path) -> dict[str, Any]:
    """The committed read-point list (`configs/benchmarks/read-points/locomo.yaml`)."""
    import yaml

    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("benchmark") != "locomo":
        raise ReadPointError(f"{path}: not a LoCoMo read-point list")
    return config


def streaming_schedule(records: Records, committed: Mapping[str, Any],
                       version: str | None = None) -> list[dict[str, Any]]:
    """The `streaming` schedule of the histories in `records`, from the committed T007 list.

    The read points are recomputed from the records and must equal the committed list for every
    history of the split: the same N, the same v(q) for every question with a read point, the same
    excluded questions with the same reason, and no question the records do not have. Only the
    entries of the histories in `records` are read, so a development load never uses a held-out
    entry. `version` is the data version the records were converted from."""
    if version is not None and committed.get("version") != version:
        raise ReadPointError(f"read-point list is for data version {committed.get('version')!r}, "
                             f"the records are {version!r}")
    points = compute_read_points(records, {})
    listed = committed.get("histories") or {}
    excluded = committed.get("excluded") or {}
    problems: list[str] = []
    for history in records.histories:
        entry = listed.get(history.history_id)
        if entry is None:
            problems.append(f"{history.history_id}: not in the read-point list")
            continue
        if entry.get("n_messages") != history.n_messages:
            problems.append(f"{history.history_id}: N {history.n_messages} != listed "
                            f"{entry.get('n_messages')}")
        mine = [p for p in points if p.history_id == history.history_id]
        expected_v = {p.task_id: p.v for p in mine if p.v is not None}
        if dict(entry.get("v") or {}) != expected_v:
            diff = sorted(set((entry.get("v") or {}).items()) ^ set(expected_v.items()))
            problems.append(f"{history.history_id}: v(q) differs from the list, e.g. {diff[:5]}")
        expected_x = {p.task_id: p.reason for p in mine if p.v is None}
        listed_x = {t: r for t, r in excluded.items()
                    if t.rpartition(":")[0] == history.history_id}
        if listed_x != expected_x:
            problems.append(f"{history.history_id}: excluded questions differ from the list "
                            f"({sorted(listed_x.items())} != {sorted(expected_x.items())})")
    if problems:
        raise ReadPointError("; ".join(problems))
    return streaming_tasks(records, points)
