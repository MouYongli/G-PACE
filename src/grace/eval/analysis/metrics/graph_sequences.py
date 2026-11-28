"""E006 on controlled change sequences: the writer's graph against the gold graph (files only).

A controlled sequence (T015, `docs/research/change-sequences.md`) carries its gold claim graph as a
T014 store snapshot (`graph/changesets.jsonl`): every claim with its attributions (message,
function, polarity, speaker) and every supersession (an ending, with the attribution of the message
that ends it). A writer run over the same messages (`grace.cli.graph_quality extract-sequences`)
has one graph per sequence (`graphs/<sequence_id>/`) and the update records of its units
(`updates.jsonl`, with the items the program dropped).

Units of comparison are claim occurrences: one per attribution (a claim on one message).

- Anchor match: same message and the same object (`same_name` after T024 normalisation), and the
  same subject unless the gold subject is a task entity (`k<n>`: the generator names tasks by ID,
  the writer by a description, which no string rule can pair).
- Loose match: anchor plus an equivalent predicate (`graph.PredicateMatcher`).
- One-to-one matching per message, highest score first (`graph._score` order: equal predicate,
  then exact names). Precision, recall and F1 at both levels; per gold predicate (recall) and per
  writer predicate (precision); on loose matches, agreement of function and polarity.
- Endings. A gold ending is a supersession (its attribution names the ending message). A
  committed writer ending is a writer supersession. They match when on the same message and the
  ended claims' objects (and, for non-task subjects, subjects) match. Recall and precision of
  endings.
- Ending-stance false drops: an ending stance the program dropped (`dropped` item with reason in
  `graph.ENDING_DROPS`, `detail` = the writer claim it would have ended) on a unit is a false drop
  when a gold ending on one of the unit's messages ends a claim that matches the writer claim.
  The false-drop rate is false drops / drops; `gold_endings_lost_to_drops` counts the gold
  endings that only a dropped stance matched.

`answer_coverage` (any benchmark with gold evidence IDs) gives the upper bounds of what a graph can
answer: whether the evidence messages carry claims and whether the reference answer's words occur
in those claims.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from grace.eval.analysis.annotation.graph_quality import norm_predicate, norm_text, same_name
from grace.eval.analysis.metrics.graph import (
    ENDING_DROPS,
    PredicateMatcher,
    WriterGraph,
    WriterRun,
    _f1,
    _ratio,
)

TASK_ENTITY = re.compile(r"^k\d+$")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _object_text(obj: Mapping[str, Any]) -> str:
    if obj.get("entity") is not None:
        return str(obj["entity"])
    return str(obj.get("value", ""))


def gold_occurrences(sequence_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Claim occurrences (one per attribution) and endings of a sequence's gold graph."""
    claims: dict[str, dict] = {}
    atts: list[dict] = []
    sups: list[dict] = []
    for cs in read_jsonl(Path(sequence_dir) / "graph" / "changesets.jsonl"):
        e = cs["entries"]
        for c in e.get("claims", []):
            claims[c["claim_id"]] = c
        atts += e.get("attributions", [])
        sups += e.get("supersessions", [])
    by_att = {a["attribution_id"]: a for a in atts}
    occ = []
    for a in atts:
        c = claims[a["claim_id"]]
        occ.append({"message_id": a["message_id"], "claim_id": c["claim_id"],
                    "subject": c["subject"], "predicate": c["predicate"],
                    "object": _object_text(c["object"]), "function": a.get("function"),
                    "polarity": a.get("polarity"), "speaker": a.get("speaker")})
    endings = []
    for s in sups:
        a = by_att.get(s.get("attribution_id"))
        c = claims.get(s["claim_id"])
        if a is None or c is None:
            continue
        endings.append({"message_id": a["message_id"], "claim_id": c["claim_id"],
                        "kind": s.get("kind"), "subject": c["subject"],
                        "predicate": c["predicate"], "object": _object_text(c["object"])})
    return occ, endings


def writer_occurrences(graph: WriterGraph) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Claim occurrences (one per attribution) and committed endings of a writer graph."""
    occ = []
    for a in graph.attributions:
        c = graph.claims.get(a["claim_id"])
        if c is None:
            continue
        occ.append({"message_id": a["message_id"], "claim_id": c["claim_id"],
                    "subject": graph.label(c["subject"]), "predicate": c["predicate"],
                    "object": graph.object_text(c), "function": a.get("function"),
                    "polarity": a.get("polarity"), "speaker": a.get("speaker")})
    att = {a["attribution_id"]: a for a in graph.attributions}
    endings = []
    for s in graph.supersessions:
        a, c = att.get(s.get("attribution_id")), graph.claims.get(s["claim_id"])
        if a is None or c is None:
            continue
        endings.append({"message_id": a["message_id"], "claim_id": c["claim_id"],
                        "subject": graph.label(c["subject"]), "predicate": c["predicate"],
                        "object": graph.object_text(c)})
    return occ, endings


def names_match(gold: Mapping[str, Any], writer: Mapping[str, Any]) -> bool:
    """Same object, and the same subject unless the gold subject is a task entity."""
    if not same_name(gold["object"], writer["object"]):
        return False
    return bool(TASK_ENTITY.match(str(gold["subject"]))) or \
        same_name(gold["subject"], writer["subject"])


def _pair_score(g: Mapping[str, Any], w: Mapping[str, Any]) -> float:
    return 10.0 * (norm_predicate(g["predicate"]) == norm_predicate(w["predicate"])) + \
        0.5 * (norm_text(g["object"]) == norm_text(w["object"])) + \
        0.5 * (norm_text(g["subject"]) == norm_text(w["subject"]))


def _quote(g: Mapping[str, Any]) -> str:
    return ""


def match_occurrences(gold: Sequence[Mapping[str, Any]], writer: Sequence[Mapping[str, Any]],
                      matcher: PredicateMatcher | None) -> list[tuple[int, int]]:
    """One-to-one pairs (gold index, writer index) per message; with `matcher` the predicate
    must also be equivalent (loose), without it names suffice (anchor)."""
    by_msg: dict[str, list[int]] = defaultdict(list)
    for j, w in enumerate(writer):
        by_msg[w["message_id"]].append(j)
    cands = []
    for i, g in enumerate(gold):
        for j in by_msg.get(g["message_id"], []):
            w = writer[j]
            if not names_match(g, w):
                continue
            if matcher is not None and not matcher.equivalent(
                    str(w["subject"]), g["predicate"], w["predicate"], g["object"], _quote(g)):
                continue
            cands.append((-_pair_score(g, w), i, j))
    cands.sort()
    used_g: set[int] = set()
    used_w: set[int] = set()
    pairs = []
    for _, i, j in cands:
        if i in used_g or j in used_w:
            continue
        used_g.add(i)
        used_w.add(j)
        pairs.append((i, j))
    return sorted(pairs)


def judge_inputs(gold: Sequence[Mapping[str, Any]], writer: Sequence[Mapping[str, Any]]
                 ) -> list[tuple[str, str, str, str, str]]:
    """The anchor-matched (subject, gold predicate, writer predicate, object, quote) items a
    judging predicate matcher may have to decide (for `PredicateMatcher.prefetch`)."""
    by_msg: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for w in writer:
        by_msg[w["message_id"]].append(w)
    out = []
    for g in gold:
        for w in by_msg.get(g["message_id"], []):
            if names_match(g, w):
                out.append((str(w["subject"]), g["predicate"], w["predicate"], g["object"],
                            _quote(g)))
    return out


def _prf(matched: int, n_writer: int, n_gold: int) -> dict[str, Any]:
    p, r = _ratio(matched, n_writer), _ratio(matched, n_gold)
    return {"matched": matched, "precision": p, "recall": r, "f1": _f1(p, r)}


def score_sequence(sequence_id: str, sequence_dir: Path, graph: WriterGraph | None,
                   updates: Sequence[Mapping[str, Any]], matcher: PredicateMatcher
                   ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Counts of one sequence and one row per gold or writer occurrence (with its match)."""
    gold, gold_end = gold_occurrences(sequence_dir)
    writer, writer_end = writer_occurrences(graph) if graph is not None else ([], [])
    anchor = match_occurrences(gold, writer, None)
    loose = match_occurrences(gold, writer, matcher)
    lg = {i: j for i, j in loose}
    lw = {j: i for i, j in loose}
    c: Counter = Counter(gold=len(gold), writer=len(writer), anchor=len(anchor),
                         loose=len(loose))
    for i, j in loose:
        g, w = gold[i], writer[j]
        for f in ("function", "polarity"):
            c[f"{f}:n"] += 1
            c[f"{f}:equal"] += g.get(f) == w.get(f)
    rows = []
    for i, g in enumerate(gold):
        rows.append({"sequence": sequence_id, "side": "gold", **g,
                     "loose": writer[lg[i]]["claim_id"] if i in lg else None})
    for j, w in enumerate(writer):
        rows.append({"sequence": sequence_id, "side": "writer", **w,
                     "loose": gold[lw[j]]["claim_id"] if j in lw else None})

    # endings
    end_pairs = []
    used = set()
    for gi, ge in enumerate(gold_end):
        for wi, we in enumerate(writer_end):
            if wi not in used and ge["message_id"] == we["message_id"] and names_match(ge, we):
                end_pairs.append((gi, wi))
                used.add(wi)
                break
    c["gold_endings"] = len(gold_end)
    c["writer_endings"] = len(writer_end)
    c["endings_matched"] = len(end_pairs)
    for ge in gold_end:
        c[f"gold_endings:{ge['kind']}"] += 1

    # dropped ending stances
    matched_gold_endings = {gi for gi, _ in end_pairs}
    lost: set[int] = set()
    for upd in updates:
        mids = set(upd.get("message_ids", []))
        for d in upd.get("dropped", []):
            if d.get("item") != "stance" or d.get("reason") not in ENDING_DROPS:
                continue
            c["drops"] += 1
            c[f"drops:{d['reason']}"] += 1
            claim = graph.claims.get(d.get("detail")) if graph is not None else None
            false = False
            if claim is not None:
                w = {"subject": graph.label(claim["subject"]), "object": graph.object_text(claim)}
                hits = [gi for gi, ge in enumerate(gold_end)
                        if ge["message_id"] in mids and names_match(ge, w)]
                false = bool(hits)
                lost |= {gi for gi in hits if gi not in matched_gold_endings}
            c["false_drops"] += false
            rows.append({"sequence": sequence_id, "side": "dropped_ending",
                         "message_ids": sorted(mids), "reason": d["reason"],
                         "claim_id": d.get("detail"), "false_drop": false})
    c["gold_endings_lost_to_drops"] = len(lost)
    return dict(c), rows


def summarise(counts: Mapping[str, Mapping[str, int]], rows: Sequence[Mapping[str, Any]]
              ) -> dict[str, Any]:
    """Totals over sequences (and per family, the sequence ID before `-rho`)."""
    def total(keys) -> Counter:
        t: Counter = Counter()
        for k in keys:
            t.update(counts[k])
        return t

    def block(t: Counter) -> dict[str, Any]:
        return {
            "gold_occurrences": t["gold"], "writer_occurrences": t["writer"],
            "anchor": _prf(t["anchor"], t["writer"], t["gold"]),
            "loose": _prf(t["loose"], t["writer"], t["gold"]),
            "fields_on_loose": {f: _ratio(t[f"{f}:equal"], t[f"{f}:n"])
                                for f in ("function", "polarity")},
            "endings": {"gold": t["gold_endings"], "writer": t["writer_endings"],
                        "matched": t["endings_matched"],
                        "recall": _ratio(t["endings_matched"], t["gold_endings"]),
                        "precision": _ratio(t["endings_matched"], t["writer_endings"]),
                        "gold_by_kind": {k.split(":", 1)[1]: v for k, v in sorted(t.items())
                                         if k.startswith("gold_endings:")}},
            "ending_drops": {"drops": t["drops"], "false_drops": t["false_drops"],
                             "false_drop_rate": _ratio(t["false_drops"], t["drops"]),
                             "gold_endings_lost_to_drops": t["gold_endings_lost_to_drops"],
                             **{k: v for k, v in sorted(t.items()) if k.startswith("drops:")}},
        }
    families: dict[str, list[str]] = defaultdict(list)
    for k in counts:
        families[k.split("-rho")[0]].append(k)
    per_pred_gold: dict[str, Counter] = defaultdict(Counter)
    per_pred_writer: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["side"] == "gold":
            per_pred_gold[r["predicate"]]["n"] += 1
            per_pred_gold[r["predicate"]]["matched"] += r["loose"] is not None
        elif r["side"] == "writer":
            per_pred_writer[r["predicate"]]["n"] += 1
            per_pred_writer[r["predicate"]]["matched"] += r["loose"] is not None
    return {
        "all": block(total(counts)),
        "per_family": {f: block(total(ks)) for f, ks in sorted(families.items())},
        "per_gold_predicate": {p: {"n": v["n"], "recall": _ratio(v["matched"], v["n"])}
                               for p, v in sorted(per_pred_gold.items())},
        "per_writer_predicate": {p: {"n": v["n"], "precision": _ratio(v["matched"], v["n"])}
                                 for p, v in sorted(per_pred_writer.items(),
                                                    key=lambda kv: -kv[1]["n"])[:40]},
        "sequences": sorted(counts),
    }


def score_run(run: WriterRun, sequence_dirs: Mapping[str, Path], matcher: PredicateMatcher,
              run_many=None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Score every sequence of `sequence_dirs` against the writer run's graph of it."""
    updates_by: dict[str, list] = defaultdict(list)
    for u in run.updates:
        updates_by[u["history_id"]].append(u)
    if matcher.method == "judge":
        items = []
        for sid, path in sequence_dirs.items():
            graph = run.graphs.get(sid)
            if graph is not None:
                items += judge_inputs(gold_occurrences(path)[0], writer_occurrences(graph)[0])
        matcher.prefetch(items, run_many)
    counts, rows = {}, []
    for sid, path in sorted(sequence_dirs.items()):
        c, r = score_sequence(sid, path, run.graphs.get(sid), updates_by.get(sid, []), matcher)
        counts[sid] = c
        rows += r
    return summarise(counts, rows), rows


# ---- answer coverage -------------------------------------------------------------------------

STOP = frozenset("a an the of in on at to for and or with by from is was are were be been it "
                 "that this as i my me you your he she his her they their them we our".split())


def _content(text: Any) -> set[str]:
    if isinstance(text, (list, tuple)):
        text = " ".join(map(str, text))
    return {t for t in norm_text(text).split() if t not in STOP}


def answer_coverage(graphs: Mapping[str, WriterGraph], gold: Sequence[Mapping[str, Any]]
                    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Upper bounds on what the graph channel can answer (plan 6.7 / memory metrics).

    Per question (`gold`: `history_id`, `task_id`, `reference`, `evidence_ids`, optional
    `stratum`): `evidence_any` / `evidence_all`: some / every gold evidence message carries at least
    one writer claim; `answer_in_evidence_claims`: every content token of the reference occurs in
    the claims (subject, predicate words, object) attributed to the evidence messages;
    `answer_partial`: at least half of them do; `answer_in_graph`: every content token occurs in
    some claim of the history's graph. Questions without evidence IDs or without content tokens in
    the reference count in the denominators of the measures they can be computed for only."""
    rows = []
    for q in gold:
        graph = graphs.get(q["history_id"])
        claims_by_msg: dict[str, list[set[str]]] = defaultdict(list)
        all_tokens: set[str] = set()
        if graph is not None:
            for a in graph.attributions:
                c = graph.claims.get(a["claim_id"])
                if c is None:
                    continue
                toks = _content(graph.label(c["subject"])) | _content(graph.object_text(c)) | \
                    set(norm_predicate(c["predicate"]).split())
                claims_by_msg[a["message_id"]].append(toks)
                all_tokens |= toks
        ev = list(q.get("evidence_ids") or [])
        ref = _content(q.get("reference"))
        ev_tokens = set().union(*(t for m in ev for t in claims_by_msg.get(m, []))) if ev else set()
        row = {"history_id": q["history_id"], "task_id": q["task_id"],
               "stratum": q.get("stratum"), "n_evidence": len(ev), "n_reference_tokens": len(ref),
               "evidence_any": any(claims_by_msg.get(m) for m in ev) if ev else None,
               "evidence_all": all(claims_by_msg.get(m) for m in ev) if ev else None,
               "answer_in_evidence_claims": (ref <= ev_tokens) if ev and ref else None,
               "answer_partial": (len(ref & ev_tokens) >= len(ref) / 2) if ev and ref else None,
               "answer_in_graph": (ref <= all_tokens) if ref else None}
        rows.append(row)

    def block(rs) -> dict[str, Any]:
        out: dict[str, Any] = {"questions": len(rs)}
        for k in ("evidence_any", "evidence_all", "answer_in_evidence_claims", "answer_partial",
                  "answer_in_graph"):
            vals = [r[k] for r in rs if r[k] is not None]
            out[k] = {"n": len(vals), "rate": _ratio(sum(vals), len(vals))}
        return out
    strata: dict[str, list] = defaultdict(list)
    for r in rows:
        strata[str(r["stratum"])].append(r)
    return {"all": block(rows),
            "per_stratum": {k: block(v) for k, v in sorted(strata.items())} if len(strata) > 1
            else {}}, rows
