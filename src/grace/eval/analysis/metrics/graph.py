"""Graph quality of a writer run against claim-level gold labels (experiment E006, plan 6.7).

Inputs are files only (structure.md: `analysis/` reads run directories; gold arrives as files):

- a writer run directory: `updates.jsonl` (one record per extraction unit) and per graph
  `graphs/<graph_id>/store/changesets.jsonl` and `graphs/<graph_id>/writer.json` (entity labels).
  A graph is either one sampled segment written on its own (`graph_id` = segment key with `:` as
  `__`, written by `eval/runner/probes/extract.py`) or a whole history (`graph_id` = history ID,
  written by `grace.cli.writer_smoke`); the scorer takes the segment graph when it exists;
- the segment texts of task T024 (`segments.jsonl`, `annotation.graph_quality.read_segments`);
- gold label files in the format of `docs/research/graph-quality-annotation.md` (section 6).

**Gold units.** With one label file (for example the human-reviewed reference), every claim is a
`core` unit. With two files, claims are paired one to one with T024's own matching
(`annotation.graph_quality.match`, the pairs of the merged review file); a pair is a `core` unit
with both variants, an unpaired claim an `uncertain` unit. A unit's messages are its claim
messages plus the messages of stance records that name it (restatements).

**Writer claims.** A writer claim on a segment is a claim ID with at least one attribution on a
segment message; its messages are those attributions' messages. Subjects and entity objects are
compared through the writer's entity labels (`writer.json`).

**Matching** is one to one within a segment, greedy in descending score like T024's matching:

- `anchor`: the messages overlap, and subject and object agree after T024's normalisation
  (`same_name`) with any variant of the unit;
- `strict`: anchor and the normalised predicates are equal (T024's strict level);
- `loose`: anchor and the predicates are equivalent under the configured predicate matcher
  (`PredicateMatcher`: `normalised`, `lexical`, or `judge` = lexical, then an LLM judgement).

**Bounds.** Precision against all units (core + uncertain) is the upper bound and against core
units the lower bound; recall against core units is the upper bound and against all units the lower
bound. F1 bounds pair the upper (lower) precision with the upper (lower) recall. With one gold file
the bounds coincide.

Attribution and time fields are compared on loose matches with core units, per field only where the
unit's variants agree on that field. Span entailment, entity labels, per-predicate quality and the
writer's ending-evidence drops are described at their functions.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grace.eval.analysis.annotation.graph_quality import (
    SegmentText,
    match,
    norm_predicate,
    norm_text,
    read_jsonl,
    same_name,
)

CATCH_ALL = ("said", "mentioned", "talkedAbout", "experienced", "hasExperience", "hasFeeling",
             "felt", "hasPlan")
ATTRIBUTE_FIELDS = ("function", "polarity", "report_mode", "certainty", "derived", "speaker")
TIME_FIELDS = ("time_expression", "valid_from", "valid_until")
LEVELS = ("anchor", "strict", "loose")
PRONOUNS = {"i", "me", "my", "mine", "you", "your", "yours", "he", "him", "his", "she", "her",
            "hers", "we", "us", "our", "they", "them", "their", "it", "its", "this", "that"}
LIGHT_WORDS = {"has", "have", "had", "having", "is", "are", "was", "were", "be", "been", "being",
               "do", "does", "did", "to", "of", "for", "with", "in", "on", "at", "by", "from",
               "as", "the", "a", "an", "about", "into"}


# ---- writer run -------------------------------------------------------------------------------

@dataclass
class WriterGraph:
    graph_id: str
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    attributions: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[tuple[str, str], dict[str, int]] = field(default_factory=dict)
    supersessions: list[dict[str, Any]] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)

    def label(self, entity_id: str) -> str:
        return self.labels.get(entity_id) or entity_id.replace("_", " ")

    def object_text(self, claim: Mapping[str, Any]) -> str:
        obj = claim["object"]
        if "entity" in obj:
            return self.label(obj["entity"])
        return str(obj.get("value"))


def read_graph(graph_dir: Path) -> WriterGraph:
    graph = WriterGraph(Path(graph_dir).name)
    for cs in read_jsonl(Path(graph_dir) / "store" / "changesets.jsonl"):
        entries = cs["entries"]
        for c in entries.get("claims", []):
            graph.claims[c["claim_id"]] = c
        graph.attributions += entries.get("attributions", [])
        for e in entries.get("evidence_links", []):
            key = (e["claim_id"], e["message_id"])
            if not graph.evidence.get(key):     # keep the first anchored span of a message
                graph.evidence[key] = e.get("span") or {}
        graph.supersessions += entries.get("supersessions", [])
    state_path = Path(graph_dir) / "writer.json"
    if state_path.exists():
        graph.labels = dict(json.loads(state_path.read_text(encoding="utf-8"))
                            .get("entity_labels", {}))
    return graph


@dataclass
class WriterRun:
    run_dir: Path
    graphs: dict[str, WriterGraph]
    updates: list[dict[str, Any]]

    def graph_for(self, segment_key: str, history_id: str) -> WriterGraph | None:
        return self.graphs.get(segment_key.replace(":", "__")) or self.graphs.get(history_id)


def read_writer_run(run_dir: Path) -> WriterRun:
    run_dir = Path(run_dir)
    graphs = {p.name: read_graph(p) for p in sorted((run_dir / "graphs").iterdir())
              if (p / "store" / "changesets.jsonl").exists()}
    updates = read_jsonl(run_dir / "updates.jsonl") if (run_dir / "updates.jsonl").exists() \
        else []
    return WriterRun(run_dir, graphs, updates)


def writer_claims(graph: WriterGraph, segment: SegmentText) -> list[dict[str, Any]]:
    """Writer claims with an attribution on a segment message, in message order."""
    order = {mid: n for n, mid in enumerate(segment.messages)}
    by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in graph.attributions:
        if a["message_id"] in order and a["claim_id"] in graph.claims:
            by_claim[a["claim_id"]].append(a)
    out = []
    for cid, atts in by_claim.items():
        atts.sort(key=lambda a: (order[a["message_id"]], a.get("version", 0)))
        claim, first = graph.claims[cid], atts[0]
        span = graph.evidence.get((cid, first["message_id"]))
        vt = claim.get("valid_time") or {}
        out.append({
            "segment": segment.key, "graph_id": graph.graph_id, "claim_id": cid,
            "message_id": first["message_id"], "messages": [a["message_id"] for a in atts],
            "subject": graph.label(claim["subject"]), "subject_id": claim["subject"],
            "predicate": claim["predicate"], "object": graph.object_text(claim),
            "object_entity": claim["object"].get("entity"),
            "function": first.get("function"), "polarity": first.get("polarity"),
            "report_mode": first.get("report_mode"), "certainty": first.get("certainty"),
            "derived": first.get("derived"), "speaker": first.get("speaker"),
            "time_expression": vt.get("expression"), "valid_from": vt.get("start"),
            "valid_until": vt.get("end"), "span": span,
            "restatements": [{"message_id": a["message_id"], "derived": a.get("derived")}
                             for a in atts[1:]],
        })
    out.sort(key=lambda c: (order[c["message_id"]], c["claim_id"]))
    return out


def judge_candidates(ws: Sequence[Mapping[str, Any]], units: Sequence[GoldUnit]
                     ) -> list[tuple[str, str, str, str, str]]:
    """Every anchor-matched (gold subject, gold predicate, writer predicate, gold object, gold
    quote) of one segment: the pairs a judging predicate matcher may have to decide."""
    out = []
    for w in ws:
        for u in units:
            for v in _anchor(w, u):
                out.append((v["subject"], v["predicate"], w["predicate"], v["object"],
                            v.get("quote") or ""))
    return out


# ---- gold ------------------------------------------------------------------------------------

@dataclass
class GoldUnit:
    segment: str
    uid: str
    tier: str                                   # core | uncertain
    variants: list[dict[str, Any]]              # one claim per annotator that found it
    messages: set[str]
    stances: list[dict[str, Any]] = field(default_factory=list)

    def agreed(self, name: str) -> tuple[bool, Any]:
        values = [v.get(name) for v in self.variants]
        same = all(_field_equal(name, values[0], x) for x in values[1:])
        return same, values[0]


def _claims_and_stances(labels: Iterable[Mapping[str, Any]]):
    claims: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stances: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in labels:
        if r.get("kind") == "claim":
            claims[r["segment"]].append(dict(r))
        elif r.get("kind") == "stance":
            stances[(r["segment"], r["claim"])].append(dict(r))
    return claims, stances


def gold_units(files: Sequence[Sequence[Mapping[str, Any]]],
               segments: Mapping[str, SegmentText]) -> dict[str, list[GoldUnit]]:
    """Gold units per segment from one label file (all core) or two (paired = core)."""
    if len(files) not in (1, 2):
        raise ValueError("gold needs one label file (reference) or two (independent annotators)")
    parsed = [_claims_and_stances(f) for f in files]
    out: dict[str, list[GoldUnit]] = {}
    for key in sorted(segments):
        units: list[GoldUnit] = []

        def unit(tier, members, n, key=key):
            variants, msgs, sts = [], set(), []
            for (_claims, stances), c in members:
                variants.append(c)
                msgs.add(c["message_id"])
                for s in stances.get((key, c["id"]), []):
                    msgs.add(s["message_id"])
                    sts.append(s)
            return GoldUnit(key, f"{key}#{n}", tier, variants, msgs, sts)

        if len(parsed) == 1:
            xs = parsed[0][0].get(key, [])
            units = [unit("core", [(parsed[0], c)], n) for n, c in enumerate(xs)]
        else:
            xs, ys = parsed[0][0].get(key, []), parsed[1][0].get(key, [])
            pairs = match(xs, ys)
            seen_a = {i for i, _, _ in pairs}
            seen_b = {j for _, j, _ in pairs}
            for i, j, _ in pairs:
                units.append(unit("core", [(parsed[0], xs[i]), (parsed[1], ys[j])], len(units)))
            for i, c in enumerate(xs):
                if i not in seen_a:
                    units.append(unit("uncertain", [(parsed[0], c)], len(units)))
            for j, c in enumerate(ys):
                if j not in seen_b:
                    units.append(unit("uncertain", [(parsed[1], c)], len(units)))
        out[key] = units
    return out


# ---- predicate matching ----------------------------------------------------------------------

def _stem(word: str) -> str:
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    return word[:-1] if word.endswith("e") and len(word) > 4 else word


def predicate_stems(predicate: str) -> set[str]:
    return {_stem(w) for w in norm_predicate(predicate).split() if w not in LIGHT_WORDS}


def lexical_equivalent(a: str, b: str) -> bool:
    """Normalised predicates equal, or they share a content stem after light words are removed
    (`considersTrying` / `plansToTry`, `hasDuration` / `duration`)."""
    if norm_predicate(a) == norm_predicate(b):
        return True
    sa, sb = predicate_stems(a), predicate_stems(b)
    return bool(sa and sb and sa & sb)


JudgeFn = Callable[[Mapping[str, Any]], str]   # inputs -> "same" | "different" | "invalid"


class PredicateMatcher:
    """Decides whether two predicates of an anchor-matched pair are equivalent; caches verdicts.

    `normalised`: T024's strict level. `lexical`: `lexical_equivalent`. `judge`: lexical, and an
    LLM judgement (`judge(inputs)`) for the pairs lexical rejects; an invalid verdict counts as not
    equivalent and is counted."""

    def __init__(self, method: str, judge: JudgeFn | None = None):
        if method not in ("normalised", "lexical", "judge"):
            raise ValueError(f"unknown predicate matcher {method!r}")
        if method == "judge" and judge is None:
            raise ValueError("the judge matcher needs a judge function")
        self.method, self.judge = method, judge
        self.cache: dict[tuple, str] = {}
        self.log: list[dict[str, Any]] = []

    def _needs_judge(self, a: str, b: str) -> bool:
        return self.method == "judge" and norm_predicate(a) != norm_predicate(b) and \
            not lexical_equivalent(a, b)

    @staticmethod
    def _key(subject: str, a: str, b: str, obj: str) -> tuple:
        return (norm_text(subject), norm_predicate(a), norm_predicate(b), norm_text(obj))

    def prefetch(self, items: Iterable[tuple[str, str, str, str, str]],
                 run_many: Callable[[Callable, list], list] | None = None) -> None:
        """Judge the given (subject, a, b, object, quote) pairs ahead of matching, optionally in
        parallel (`run_many(fn, inputs)` returns the results in order)."""
        todo: dict[tuple, dict[str, Any]] = {}
        for subject, a, b, obj, quote in items:
            key = self._key(subject, a, b, obj)
            if self._needs_judge(a, b) and key not in self.cache and key not in todo:
                todo[key] = {"subject": subject, "predicate_a": a, "predicate_b": b,
                             "object": obj, "quote": quote}
        inputs = list(todo.values())
        verdicts = (run_many or (lambda fn, xs: [fn(x) for x in xs]))(self.judge, inputs)
        for key, x, v in zip(todo, inputs, verdicts, strict=True):
            self.cache[key] = v
            self.log.append({"check": "predicate", **x, "verdict": v})

    def equivalent(self, subject: str, a: str, b: str, obj: str, quote: str) -> bool:
        if norm_predicate(a) == norm_predicate(b):
            return True
        if self.method == "normalised":
            return False
        if lexical_equivalent(a, b):
            return True
        if self.method == "lexical":
            return False
        key = self._key(subject, a, b, obj)
        if key not in self.cache:
            self.prefetch([(subject, a, b, obj, quote)])
        return self.cache[key] == "same"


# ---- matching --------------------------------------------------------------------------------

def _anchor(w: Mapping[str, Any], unit: GoldUnit) -> list[dict[str, Any]]:
    """Variants of `unit` that anchor-match writer claim `w`."""
    if not set(w["messages"]) & unit.messages:
        return []
    return [v for v in unit.variants
            if same_name(w["subject"], v["subject"]) and same_name(w["object"], v["object"])]


def _score(w: Mapping[str, Any], v: Mapping[str, Any]) -> float:
    pw, pv = norm_predicate(w["predicate"]), norm_predicate(v["predicate"])
    tw, tv = set(pw.split()), set(pv.split())
    exact = (norm_text(w["subject"]) == norm_text(v["subject"])) + \
        (norm_text(w["object"]) == norm_text(v["object"]))
    return 10.0 * (pw == pv) + len(tw & tv) / max(1, len(tw | tv)) + 0.5 * exact + \
        0.25 * (w["message_id"] == v["message_id"])


def _passes(level: str, w: Mapping[str, Any], v: Mapping[str, Any],
            matcher: PredicateMatcher) -> bool:
    if level == "anchor":
        return True
    if level == "strict":
        return norm_predicate(w["predicate"]) == norm_predicate(v["predicate"])
    return matcher.equivalent(v["subject"], v["predicate"], w["predicate"], v["object"],
                              v.get("quote") or "")


def match_segment(ws: Sequence[Mapping[str, Any]], units: Sequence[GoldUnit], level: str,
                  matcher: PredicateMatcher) -> list[tuple[int, int, int]]:
    """One-to-one matches (writer index, unit index, variant index) at `level`."""
    candidates = []
    for i, w in enumerate(ws):
        for j, u in enumerate(units):
            for v in _anchor(w, u):
                if _passes(level, w, v, matcher):
                    k = u.variants.index(v)
                    candidates.append((-_score(w, v), i, j, k))
    candidates.sort()
    used_w: set[int] = set()
    used_u: set[int] = set()
    out = []
    for _, i, j, k in candidates:
        if i in used_w or j in used_u:
            continue
        used_w.add(i)
        used_u.add(j)
        out.append((i, j, k))
    return sorted(out)


# ---- metrics ---------------------------------------------------------------------------------

def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None:
        return None
    return round(2 * p * r / (p + r), 4) if p + r else 0.0


def _field_equal(name: str, x: Any, y: Any) -> bool:
    if name == "time_expression":
        return norm_text(x) == norm_text(y)
    if name == "speaker":
        return norm_text(x) == norm_text(y)
    return x == y


@dataclass
class Counts:
    writer: int = 0
    core: int = 0
    units: int = 0
    matched_union: Counter = field(default_factory=Counter)   # level -> matched pairs vs all
    matched_core: Counter = field(default_factory=Counter)    # level -> matched pairs vs core
    duplicates: Counter = field(default_factory=Counter)      # level -> unmatched writer claims
                                                              # that match a matched unit

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {"writer_claims": self.writer, "gold_core": self.core,
                               "gold_all": self.units, "gold_uncertain": self.units - self.core}
        for level in LEVELS:
            pu = _ratio(self.matched_union[level], self.writer)
            pl = _ratio(self.matched_core[level], self.writer)
            ru = _ratio(self.matched_core[level], self.core)
            rl = _ratio(self.matched_union[level], self.units)
            out[level] = {
                "matched_vs_all": self.matched_union[level],
                "matched_vs_core": self.matched_core[level],
                "precision": {"lower": pl, "upper": pu},
                "recall": {"lower": rl, "upper": ru},
                "f1": {"lower": _f1(pl, rl), "upper": _f1(pu, ru)},
                "duplicates_of_matched_units": self.duplicates[level],
            }
        return out


def score(run: WriterRun, segments: Mapping[str, SegmentText],
          units_by_segment: Mapping[str, Sequence[GoldUnit]], matcher: PredicateMatcher,
          history_of: Mapping[str, str], run_many: Callable[[Callable, list], list] | None = None
          ) -> tuple[dict[str, Any], list[dict], list[dict]]:
    """Claim precision, recall and F1 (bounds), per benchmark, with per-item records."""
    counts: dict[str, Counts] = defaultdict(Counts)
    claim_rows: list[dict] = []
    gold_rows: list[dict] = []
    fields_ok: dict[str, Counter] = defaultdict(Counter)
    fields_n: dict[str, Counter] = defaultdict(Counter)
    missing_graphs = []
    writer_by_segment = {}
    for key in sorted(segments):
        graph = run.graph_for(key, history_of[key])
        if graph is None:
            missing_graphs.append(key)
        writer_by_segment[key] = writer_claims(graph, segments[key]) if graph else []
    matcher.prefetch([c for key, ws in writer_by_segment.items()
                      for c in judge_candidates(ws, units_by_segment.get(key, []))], run_many)
    for key in sorted(segments):
        seg = segments[key]
        ws = writer_by_segment[key]
        units = list(units_by_segment.get(key, []))
        core_idx = [j for j, u in enumerate(units) if u.tier == "core"]
        core_units = [units[j] for j in core_idx]
        result = {}
        for level in LEVELS:
            vs_all = match_segment(ws, units, level, matcher)
            vs_core = [(i, core_idx[j], k) for i, j, k in
                       match_segment(ws, core_units, level, matcher)]
            result[level] = (vs_all, vs_core)
            for bucket in ("all", seg.benchmark):
                c = counts[bucket]
                c.matched_union[level] += len(vs_all)
                c.matched_core[level] += len(vs_core)
                matched_units = {j for _, j, _ in vs_all}
                matched_w = {i for i, _, _ in vs_all}
                c.duplicates[level] += sum(
                    1 for i, w in enumerate(ws) if i not in matched_w
                    and any(_anchor(w, units[j]) for j in matched_units))
        for bucket in ("all", seg.benchmark):
            c = counts[bucket]
            c.writer += len(ws)
            c.units += len(units)
            c.core += len(core_units)
        loose_all = {i: (j, k) for i, j, k in result["loose"][0]}
        unit_hit = {lvl: {j: i for i, j, _ in result[lvl][0]} for lvl in LEVELS}
        for i, w in enumerate(ws):
            row = dict(w)
            row["match"] = {lvl: next(({"unit": units[j].uid, "tier": units[j].tier,
                                        "variant": k} for ii, j, k in result[lvl][0]
                                       if ii == i), None) for lvl in LEVELS}
            claim_rows.append(row)
        for j, u in enumerate(units):
            gold_rows.append({"segment": key, "unit": u.uid, "tier": u.tier,
                              "messages": sorted(u.messages),
                              "variants": [{k: v.get(k) for k in ("annotator", "id",
                                            "message_id", "subject", "predicate", "object")}
                                           for v in u.variants],
                              "matched": {lvl: (ws[unit_hit[lvl][j]]["claim_id"]
                                                if j in unit_hit[lvl] else None)
                                          for lvl in LEVELS}})
        # attribution and time fields on loose matches with core units
        for i, (j, _) in loose_all.items():
            u = units[j]
            if u.tier != "core":
                continue
            for name in ATTRIBUTE_FIELDS + TIME_FIELDS:
                agreed, value = u.agreed(name)
                if not agreed:
                    continue
                for bucket in ("all", seg.benchmark):
                    fields_n[bucket][name] += 1
                    fields_ok[bucket][name] += _field_equal(name, ws[i].get(name), value)
                    if name in TIME_FIELDS:
                        fields_n[bucket][f"{name}:gold_set"] += value is not None
                        fields_ok[bucket][f"{name}:gold_set"] += (
                            value is not None and _field_equal(name, ws[i].get(name), value))
                        fields_n[bucket][f"{name}:writer_set"] += ws[i].get(name) is not None
                        fields_ok[bucket][f"{name}:writer_set"] += (
                            ws[i].get(name) is not None
                            and _field_equal(name, ws[i].get(name), value))
    metrics = {b: counts[b].summary() for b in ["all"] + sorted(set(counts) - {"all"})}
    for b in metrics:
        metrics[b]["fields_on_loose_core_matches"] = {
            name: {"accuracy": _ratio(fields_ok[b][name], fields_n[b][name]),
                   "n": fields_n[b][name]} for name in sorted(fields_n[b])}
    metrics["missing_graphs"] = missing_graphs
    return metrics, claim_rows, gold_rows


def per_predicate(claim_rows: Sequence[Mapping[str, Any]], min_count: int = 3) -> dict[str, Any]:
    """Writer predicates: count and loose precision bounds; catch-all predicates aggregated.

    Both bounds come from the loose matching against all units (the lower bound counts matches
    whose unit is core), so the lower bound can differ slightly from the claim-level lower bound,
    which matches against core units only."""
    stats: dict[str, Counter] = defaultdict(Counter)
    for r in claim_rows:
        m = r["match"]["loose"]
        for name in (r["predicate"], "*catch-all*" if r["predicate"] in CATCH_ALL else None,
                     "*all*"):
            if name is None:
                continue
            stats[name]["n"] += 1
            stats[name]["matched_all"] += m is not None
            stats[name]["matched_core"] += m is not None and m["tier"] == "core"
    total = stats["*all*"]["n"]
    out = {}
    for name, s in sorted(stats.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        if s["n"] < min_count and name not in CATCH_ALL and not name.startswith("*"):
            continue
        out[name] = {"n": s["n"], "share": _ratio(s["n"], total),
                     "precision": {"lower": _ratio(s["matched_core"], s["n"]),
                                   "upper": _ratio(s["matched_all"], s["n"])}}
    return {"min_count": min_count, "predicates": out,
            "distinct_predicates": len([k for k in stats if not k.startswith("*")])}


# ---- spans -----------------------------------------------------------------------------------

def span_text(row: Mapping[str, Any], segment: SegmentText) -> str | None:
    span = row.get("span")
    msg = segment.messages.get(row["message_id"])
    if not span or msg is None:
        return None
    start, end = span.get("start"), span.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end \
            or end > len(msg["text"]):
        return None
    return msg["text"][start:end]


def span_checks(claim_rows: Sequence[Mapping[str, Any]], segments: Mapping[str, SegmentText],
                units_by_id: Mapping[str, GoldUnit],
                entail_many: Callable[[list], list] | None) -> dict[str, Any]:
    """Cited span of each writer claim (first attribution): valid offsets; overlap with the gold
    quote of its loose match; and, with `entail_many` (a list of judge inputs -> a list of
    verdicts), an LLM judgement whether the span entails the claim (`entailed` | `not_entailed`
    | `invalid`), split by match status."""
    c: Counter = Counter()
    verdicts: Counter = Counter()
    by_status: dict[str, Counter] = defaultdict(Counter)
    log = []
    asks: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for r in claim_rows:
        seg = segments[r["segment"]]
        text = span_text(r, seg)
        c["claims"] += 1
        if text is None:
            c["no_valid_span"] += 1
            continue
        c["valid_span"] += 1
        m = r["match"]["loose"]
        if m is not None:
            unit = units_by_id[m["unit"]]
            v = unit.variants[m["variant"]]
            msg = seg.messages.get(r["message_id"], {}).get("text", "")
            q = v.get("quote") or ""
            at = msg.find(q) if q and v["message_id"] == r["message_id"] else -1
            c["matched_same_message"] += at >= 0
            if at >= 0:
                s, e = r["span"]["start"], r["span"]["end"]
                c["overlaps_gold_quote"] += max(0, min(e, at + len(q)) - max(s, at)) > 0
        if entail_many is not None:
            asks.append((r, {"speaker": r.get("speaker") or "", "span": text,
                             "message": seg.messages[r["message_id"]]["text"],
                             "subject": r["subject"], "predicate": r["predicate"],
                             "object": r["object"]}))
    if entail_many is not None:
        results = entail_many([x for _, x in asks])
        for (r, inputs), verdict in zip(asks, results, strict=True):
            verdicts[verdict] += 1
            status = "matched" if r["match"]["loose"] is not None else "unmatched"
            by_status[status][verdict] += 1
            log.append({"check": "entailment", "segment": r["segment"],
                        "claim_id": r["claim_id"], **inputs, "verdict": verdict})
    out: dict[str, Any] = {
        "claims": c["claims"], "valid_span": c["valid_span"],
        "no_valid_span": c["no_valid_span"],    # the writer's quote did not anchor in the text
        "valid_span_rate": _ratio(c["valid_span"], c["claims"]),
        "loose_matched_same_message": c["matched_same_message"],
        "overlaps_gold_quote_rate": _ratio(c["overlaps_gold_quote"], c["matched_same_message"]),
    }
    if entail_many is not None:
        judged = verdicts["entailed"] + verdicts["not_entailed"]
        out["entailment"] = {
            "judged": judged, "invalid": verdicts["invalid"],
            "entailed_rate": _ratio(verdicts["entailed"], judged),
            "by_match": {k: {"judged": v["entailed"] + v["not_entailed"],
                             "invalid": v["invalid"],
                             "entailed_rate": _ratio(v["entailed"],
                                                     v["entailed"] + v["not_entailed"])}
                         for k, v in sorted(by_status.items())}}
    return {"metrics": out, "log": log}


# ---- entity labels ---------------------------------------------------------------------------

def _words(text: str) -> list[str]:
    return norm_text(text).split()


def entity_labels(run: WriterRun, segments: Mapping[str, SegmentText],
                  claim_rows: Sequence[Mapping[str, Any]],
                  units_by_id: Mapping[str, GoldUnit],
                  context_texts: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """First-mention entity labels of the entities named by writer claims on segment messages.

    Entity labels are immutable (T014), so a wrong first-mention label stays. Per entity (one per
    graph and entity ID): the label is a pronoun or starts with a first- or second-person
    possessive (`pronoun`); not every content word of the label occurs in the messages the
    graph's writer saw for this segment (context and segment texts and the speaker names;
    `not_in_text`, a surface-name check that is only exact for segment graphs). Per loose match:
    the writer's subject or entity object equals the gold name after normalisation (`exact`)
    or only contains or is contained in it."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for r in claim_rows:
        for eid, label in ((r["subject_id"], r["subject"]), (r["object_entity"], r["object"])):
            if not eid:
                continue
            seen.setdefault((r["graph_id"], eid), {"segment": r["segment"], "label": label})
    c: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for e in seen.values():
        words = _words(e["label"])
        c["entities"] += 1
        raw = e["label"].strip().lower()
        if not words or raw in PRONOUNS or raw.split()[0] in {"my", "your", "our"}:
            c["pronoun"] += 1
            examples["pronoun"].append(e["label"])
            continue
        text = " ".join(norm_text(t) for t in context_texts.get(e["segment"], []))
        vocab = set(text.split())
        if not all(w in vocab for w in words):
            c["not_in_text"] += 1
            if len(examples["not_in_text"]) < 25:
                examples["not_in_text"].append(e["label"])
    names: Counter = Counter()
    for r in claim_rows:
        m = r["match"]["loose"]
        if m is None:
            continue
        v = units_by_id[m["unit"]].variants[m["variant"]]
        for role, wl, gl in (("subject", r["subject"], v["subject"]),
                             ("object", r["object"], v["object"])):
            if role == "object" and not r["object_entity"]:
                continue
            names[f"{role}:n"] += 1
            names[f"{role}:exact"] += norm_text(wl) == norm_text(gl)
    return {"entities": c["entities"], "pronoun": c["pronoun"],
            "pronoun_rate": _ratio(c["pronoun"], c["entities"]),
            "not_in_text": c["not_in_text"],
            "not_in_text_rate": _ratio(c["not_in_text"], c["entities"]),
            "examples": dict(examples),
            "name_vs_gold_on_loose_matches": {
                role: {"n": names[f"{role}:n"],
                       "exact_rate": _ratio(names[f"{role}:exact"], names[f"{role}:n"])}
                for role in ("subject", "object")}}


# ---- ending stances --------------------------------------------------------------------------

ENDING_DROPS = ("ended_without_evidence", "ended_without_quote")


def ending_drops(run: WriterRun, segments: Mapping[str, SegmentText],
                 units_by_segment: Mapping[str, Sequence[GoldUnit]],
                 history_of: Mapping[str, str]) -> dict[str, Any]:
    """The writer's ending-evidence check against gold endings.

    A dropped ending (update record `dropped`, reason in `ENDING_DROPS`, `detail` = the claim it
    would have ended) on a unit with segment messages is a false drop when a gold stance with
    `ends` set, on one of the unit's messages, names a gold claim whose subject and object match
    the writer claim's. Committed endings (supersessions whose attribution is on a segment
    message) are checked the same way. Gold endings that no committed writer ending matches are
    counted as missed."""
    msg_segment = {}
    for key, seg in segments.items():
        for mid in seg.messages:
            msg_segment[(history_of[key], mid)] = key
    gold_end: dict[str, list[tuple[dict, GoldUnit]]] = defaultdict(list)
    for key, units in units_by_segment.items():
        for u in units:
            for s in u.stances:
                if s.get("ends"):
                    gold_end[key].append((s, u))
    c: Counter = Counter()
    rows = []
    for upd in run.updates:
        hist = upd.get("source_history_id") or upd["history_id"]
        keys = {msg_segment.get((hist, m)) for m in upd["message_ids"]} - {None}
        if not keys:
            continue
        key = sorted(keys)[0]
        graph = run.graph_for(key, history_of[key])
        for d in upd.get("dropped", []):
            if d.get("item") != "stance" or d.get("reason") not in ENDING_DROPS:
                continue
            c[f"drops:{d['reason']}"] += 1
            claim = graph.claims.get(d.get("detail")) if graph else None
            legit = False
            if claim is not None:
                subj, obj = graph.label(claim["subject"]), graph.object_text(claim)
                legit = any(s["message_id"] in upd["message_ids"] and
                            any(same_name(subj, v["subject"]) and same_name(obj, v["object"])
                                for v in u.variants) for s, u in gold_end[key])
                rows.append({"segment": key, "message_ids": upd["message_ids"],
                             "reason": d["reason"], "claim_id": d.get("detail"),
                             "claim": [subj, claim["predicate"], obj], "false_drop": legit})
            c["false_drops"] += legit
    committed = 0
    for key, seg in segments.items():
        graph = run.graph_for(key, history_of[key])
        if graph is None:
            continue
        att = {a["attribution_id"]: a for a in graph.attributions}
        for s in graph.supersessions:
            a = att.get(s.get("attribution_id"))
            if a is not None and a["message_id"] in seg.messages:
                committed += 1
    drops = sum(v for k, v in c.items() if k.startswith("drops:"))
    gold_total = sum(len(v) for v in gold_end.values())
    return {"gold_endings": gold_total,
            "gold_endings_core": sum(1 for v in gold_end.values() for _, u in v
                                     if u.tier == "core"),
            "drops": drops, **{k: v for k, v in sorted(c.items()) if k.startswith("drops:")},
            "false_drops": c["false_drops"], "false_drop_rate": _ratio(c["false_drops"], drops),
            "committed_endings_on_segment_messages": committed,
            "dropped": rows}


# ---- restatements ----------------------------------------------------------------------------

def restatements(claim_rows: Sequence[Mapping[str, Any]],
                 units_by_id: Mapping[str, GoldUnit]) -> dict[str, Any]:
    """Restatements on loose-matched claims: gold stances (restating the unit) against the writer's
    later attributions on the same claim. `echo_as_independent`: a gold stance marked `derived`
    (an echo) whose message carries a writer attribution with `derived: false`, i.e. the echo
    counts as independent evidence in the graph."""
    c: Counter = Counter()
    for r in claim_rows:
        m = r["match"]["loose"]
        if m is None:
            continue
        unit = units_by_id[m["unit"]]
        writer_at = {x["message_id"]: x["derived"] for x in r["restatements"]}
        writer_at.setdefault(r["message_id"], r["derived"])
        c["writer_restatements"] += len(r["restatements"])
        for s in unit.stances:
            c["gold_stances"] += 1
            if s["message_id"] in writer_at:
                c["gold_stance_attributed"] += 1
                if s.get("derived"):
                    c["gold_echo_attributed"] += 1
                    c["echo_as_independent"] += writer_at[s["message_id"]] is False
    return {**dict(c), "stance_recall": _ratio(c["gold_stance_attributed"], c["gold_stances"]),
            "echo_as_independent_rate": _ratio(c["echo_as_independent"],
                                               c["gold_echo_attributed"])}


# ---- LLM judges ------------------------------------------------------------------------------

def llm_judge(client: Any, prompt: Any, decoding: Mapping[str, Any],
              verdicts: Mapping[str, str]) -> Callable[[Mapping[str, Any]], str]:
    """A one-word judge through `grace.llm` (`client.chat`; call type `judge`, trigger
    `evaluation`): the reply, upper-cased without a final period, is looked up in `verdicts`;
    anything else is `invalid`."""
    from grace.llm.records import CallContext

    def parse(text: str | None) -> str:
        return verdicts.get((text or "").strip().rstrip(".").strip().upper(), "invalid")

    def judge(inputs: Mapping[str, Any]) -> str:
        messages = prompt.render(**{k: str(inputs[k]) for k in prompt.variables})
        result = client.chat(messages, CallContext(call_type="judge", trigger="evaluation"),
                             prompt_sha256=prompt.sha256, decoding=dict(decoding),
                             validate=lambda t: None if parse(t) != "invalid" else "unparsable")
        return parse(result.text)

    return judge


PREDICATE_VERDICTS = {"SAME": "same", "DIFFERENT": "different"}
ENTAILMENT_VERDICTS = {"ENTAILED": "entailed", "NOT_ENTAILED": "not_entailed"}


# ---- predicate-matcher check on two annotators' labels ---------------------------------------

def predicate_check_pairs(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]],
                          segments: Mapping[str, SegmentText], n_negative: int,
                          seed: str = "E006-predicate-check-v1") -> list[dict[str, Any]]:
    """Predicate pairs for checking a predicate matcher on two annotators' labels.

    - `differing`: every anchor-matched pair of the two files (same message, subject and object)
      whose normalised predicates differ: the cases a matcher looser than string equality decides;
    - `cross`: seeded negatives-by-construction: the subject, object and quote of one anchor pair
      with annotator B's predicate taken from another anchor pair of the same segment and subject
      whose normalised predicate differs (mostly different relations; labelled like the rest).
    Pair IDs are stable; the order of `cross` pairs is the SHA-256 of `seed:pair_id`."""
    import hashlib

    ca, _ = _claims_and_stances(a)
    cb, _ = _claims_and_stances(b)
    differing, cross = [], []
    for key in sorted(segments):
        xs, ys = ca.get(key, []), cb.get(key, [])
        pairs = match(xs, ys)
        for i, j, strict in pairs:
            x, y = xs[i], ys[j]
            if not strict:
                differing.append({"pair_id": f"{key}|{x['id']}|{y['id']}", "kind": "differing",
                                  "subject": x["subject"], "object": x["object"],
                                  "quote": x["quote"], "predicate_a": x["predicate"],
                                  "predicate_b": y["predicate"]})
        for i, j, _ in pairs:
            for i2, j2, _ in pairs:
                x, y2 = xs[i], ys[j2]
                if (i2, j2) == (i, j) or not same_name(x["subject"], y2["subject"]):
                    continue
                if norm_predicate(x["predicate"]) == norm_predicate(y2["predicate"]) or \
                        norm_predicate(ys[j]["predicate"]) == norm_predicate(y2["predicate"]):
                    continue
                pid = f"{key}|{x['id']}|x{y2['id']}"
                cross.append({"pair_id": pid, "kind": "cross", "subject": x["subject"],
                              "object": x["object"], "quote": x["quote"],
                              "predicate_a": x["predicate"], "predicate_b": y2["predicate"]})
    cross.sort(key=lambda p: hashlib.sha256(f"{seed}:{p['pair_id']}".encode()).hexdigest())
    seen, picked = set(), []
    for p in cross:                       # one cross pair per source claim
        src = p["pair_id"].rsplit("|", 1)[0]
        if src in seen:
            continue
        seen.add(src)
        picked.append(p)
        if len(picked) >= n_negative:
            break
    return differing + picked


def predicate_check(pairs: Sequence[Mapping[str, Any]], reference: Mapping[str, str],
                    judge: Callable[[Mapping[str, Any]], str] | None) -> dict[str, Any]:
    """Accuracy of the `normalised`, `lexical` and `judge` matchers against reference labels
    (`pair_id` -> `same` | `different`), per pair kind; returns metrics and per-pair verdicts."""
    rows = []
    for p in pairs:
        ref = reference.get(p["pair_id"])
        if ref is None:
            continue
        lex = lexical_equivalent(p["predicate_a"], p["predicate_b"])
        jv = judge(p) if judge is not None else None
        rows.append({**p, "reference": ref, "normalised": "different",
                     "lexical": "same" if lex else "different",
                     "judge_only": jv, "judge": "same" if lex else jv})
    out: dict[str, Any] = {}
    for method in ("normalised", "lexical", "judge_only", "judge"):
        if judge is None and method.startswith("judge"):
            continue
        cm: Counter = Counter()
        for r in rows:
            cm[(r["reference"], r[method])] += 1
        tp, fp = cm[("same", "same")], cm[("different", "same")]
        fn = cm[("same", "different")] + cm[("same", "invalid")]
        tn = cm[("different", "different")] + cm[("different", "invalid")]
        out[method] = {"accuracy": _ratio(tp + tn, len(rows)),
                       "precision_same": _ratio(tp, tp + fp), "recall_same": _ratio(tp, tp + fn),
                       "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                       "invalid": sum(v for (_, m), v in cm.items() if m == "invalid")}
    out["n"] = len(rows)
    out["reference"] = dict(Counter(r["reference"] for r in rows))
    out["by_kind"] = dict(Counter(r["kind"] for r in rows))
    return {"metrics": out, "rows": rows}
