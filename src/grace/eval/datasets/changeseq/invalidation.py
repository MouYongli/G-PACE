"""Gold staleness from the event log (design docs/research/change-sequences.md, sections 4 and 6).

Everything here is a pure function of the event log, the view semantics of the family (`World`) and
the binding list. It imports nothing from `context/pipeline/query/`, no IR and no SPARQL engine
(design section 6.4; D013 import rule): the reference functions are one small function per view
template, written against the derived state of section 6.1.

- `DerivedState`: C_k, A_k(c), Ev_k(c), Cur_k(c), NC_k(c), End_k(c), Att_k(c, u, f) at any k.
- `REFERENCE`: V1 List, V2 Current, V3 Count, V4 Requested constraints, V5 Pending,
  V6 Current choice (section 6.2), each returning (ans, wit, ev).
- `hist`: the historical state with the two readings of undated starts (section 6.2).
- `gold_staleness`: the procedure of section 6.3: canonical values and fingerprints per version,
  per-message answer and citation staleness, and the change type of section 4.1.
- `check_invariants`: the type / outcome cross-table of section 4.2 and its converse.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from grace.eval.datasets.changeseq.events import LogRecord, NewClaim, Stance, Supersede

TEMPLATES = ("V1", "V2", "V3", "V4", "V5", "V6")
NEG_INF = ""          # sorts before every ISO date: the reading of an undated start as -infinity


@dataclass(frozen=True)
class World:
    """The view semantics a family fixes: authority speakers and the task predicates."""

    authority: Mapping[str, str]
    constraint_predicates: frozenset[str]
    choice_predicate: str
    catalogue_predicate: str


@dataclass(frozen=True)
class Binding:
    """A view template with its parameters bound: (x, p) for V1-V3, task k for V4-V6."""

    template: str
    subject: str
    predicate: str | None = None

    @property
    def binding_id(self) -> str:
        return ":".join(x for x in (self.template, self.subject, self.predicate) if x)

    def to_record(self) -> dict[str, Any]:
        return {"binding_id": self.binding_id, "template": self.template,
                "subject": self.subject, "predicate": self.predicate}


# ---------------------------------------------------------------------------------------------
# Derived state (section 6.1)


@dataclass(frozen=True)
class ClaimRow:
    claim_id: str
    subject: str
    predicate: str
    object: str
    start: str | None
    end: str | None
    version: int


@dataclass(frozen=True)
class AttRow:
    attribution_id: str
    claim_id: str
    speaker: str
    function: str
    report_mode: str
    polarity: str
    derived: bool
    version: int


class DerivedState:
    """Tables of the whole log; every accessor takes the knowledge version k explicitly."""

    def __init__(self, log: Sequence[LogRecord], world: World):
        self.world = world
        self.claims: dict[str, ClaimRow] = {}
        self.atts: dict[str, list[AttRow]] = defaultdict(list)
        self.evidence: dict[str, list[tuple[int, str]]] = defaultdict(list)
        self.sups: dict[str, list[tuple[int, str]]] = defaultdict(list)
        self.by_sp: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.by_p: dict[str, list[str]] = defaultdict(list)
        self.dates: dict[int, str] = {}
        for r in log:
            self.dates[r.version] = r.timestamp
            linked = set()
            for e in r.events:
                if isinstance(e, NewClaim):
                    self.claims[e.claim_id] = ClaimRow(e.claim_id, e.subject, e.predicate,
                                                       e.object, e.start, e.end, r.version)
                    self.by_sp[(e.subject, e.predicate)].append(e.claim_id)
                    self.by_p[e.predicate].append(e.claim_id)
                    linked.add(e.claim_id)
                    self.evidence[e.claim_id].append((r.version, r.message_id))
            for e in r.events:
                if isinstance(e, Stance):
                    self.atts[e.claim_id].append(AttRow(
                        e.attribution_id, e.claim_id, r.speaker, e.function, e.report_mode,
                        e.polarity, e.derived, r.version))
                    if e.claim_id not in linked:
                        linked.add(e.claim_id)
                        self.evidence[e.claim_id].append((r.version, r.message_id))
                elif isinstance(e, Supersede):
                    self.sups[e.claim_id].append((r.version, e.kind))

    # -- accessors at k ----------------------------------------------------------------------

    def known(self, cid: str, k: int) -> bool:
        return self.claims[cid].version <= k

    def claims_sp(self, s: str, p: str, k: int) -> list[ClaimRow]:
        return [self.claims[c] for c in self.by_sp.get((s, p), ()) if self.known(c, k)]

    def cur(self, cid: str, k: int) -> bool:
        return not any(v <= k for v, _ in self.sups.get(cid, ()))

    def nc(self, cid: str, k: int) -> bool:
        return not any(v <= k and kind == "correction" for v, kind in self.sups.get(cid, ()))

    def attributions(self, cid: str, k: int) -> list[AttRow]:
        return [a for a in self.atts.get(cid, ()) if a.version <= k]

    def endorsing(self, cid: str, k: int) -> list[AttRow]:
        auth = self.world.authority.get(self.claims[cid].predicate)
        return [a for a in self.attributions(cid, k) if a.speaker == auth
                and a.function == "inform" and a.report_mode == "own"
                and a.polarity == "positive" and not a.derived]

    def att(self, cid: str, speaker: str, function: str, k: int) -> list[AttRow]:
        return [a for a in self.attributions(cid, k) if a.speaker == speaker
                and a.function == function and a.report_mode == "own"
                and a.polarity == "positive"]

    def ev(self, cid: str, k: int) -> set[str]:
        return {m for v, m in self.evidence.get(cid, ()) if v <= k}


# ---------------------------------------------------------------------------------------------
# Reference functions (section 6.2)


@dataclass(frozen=True)
class ViewValue:
    """(ans, wit, ev): ans a frozenset; wit maps each answer to a frozenset of witness sets."""

    ans: frozenset
    wit: Mapping[Any, frozenset]
    ev: frozenset

    def canonical(self) -> dict[str, Any]:
        return {"ans": sorted(_jsonable(a) for a in self.ans),
                "wit": sorted([_jsonable(a), sorted(sorted(w) for w in ws)]
                              for a, ws in self.wit.items()),
                "ev": sorted(self.ev)}


def _jsonable(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


def _value(wit: dict[Any, set[frozenset]], claims_of: Iterable[str],
           S: DerivedState, k: int) -> ViewValue:
    ev = set()
    for cid in claims_of:
        ev |= S.ev(cid, k)
    return ViewValue(frozenset(wit), {a: frozenset(w) for a, w in wit.items()}, frozenset(ev))


def _witness_claims(wit: Mapping[Any, Iterable[frozenset]], S: DerivedState) -> set[str]:
    return {e for ws in wit.values() for w in ws for e in w if e in S.claims}


def _v1_k(S: DerivedState, b: Binding, k: int) -> list[ClaimRow]:
    return [c for c in S.claims_sp(b.subject, b.predicate, k)
            if S.cur(c.claim_id, k) and S.endorsing(c.claim_id, k)]


def ref_v1(S: DerivedState, b: Binding, k: int) -> ViewValue:
    wit: dict[Any, set[frozenset]] = defaultdict(set)
    for c in _v1_k(S, b, k):
        for a in S.endorsing(c.claim_id, k):
            wit[c.object].add(frozenset({c.claim_id, a.attribution_id}))
    return _value(wit, _witness_claims(wit, S), S, k)


def v2_candidates(S: DerivedState, b: Binding, k: int) -> list[ClaimRow]:
    return [c for c in _v1_k(S, b, k) if c.end is None]


def ref_v2(S: DerivedState, b: Binding, k: int) -> ViewValue:
    K = v2_candidates(S, b, k)
    wit: dict[Any, set[frozenset]] = defaultdict(set)
    if K:
        best = max(K, key=lambda c: (c.version, c.claim_id))
        for a in S.endorsing(best.claim_id, k):
            wit[best.object].add(frozenset({best.claim_id, a.attribution_id}))
    return _value(wit, _witness_claims(wit, S), S, k)


def ref_v3(S: DerivedState, b: Binding, k: int) -> ViewValue:
    """Count: one witness, the union of the witnesses of the counted members (plan 3.4; user
    decision of 2026-11-25), none when nothing is counted."""
    members = ref_v1(S, b, k)
    union = frozenset(e for ws in members.wit.values() for w in ws for e in w)
    wit = {len(members.ans): {union} if union else set()}
    return _value(wit, _witness_claims(wit, S), S, k)


def ref_v4(S: DerivedState, b: Binding, k: int) -> ViewValue:
    wit: dict[Any, set[frozenset]] = defaultdict(set)
    for q in sorted(S.world.constraint_predicates):
        for c in S.claims_sp(b.subject, q, k):
            if not S.cur(c.claim_id, k):
                continue
            for a in S.att(c.claim_id, "user", "request", k):
                wit[(q, c.object)].add(frozenset({c.claim_id, a.attribution_id}))
    return _value(wit, _witness_claims(wit, S), S, k)


def ref_v5(S: DerivedState, b: Binding, k: int) -> ViewValue:
    wit: dict[Any, set[frozenset]] = defaultdict(set)
    for c in S.claims_sp(b.subject, S.world.choice_predicate, k):
        cid = c.claim_id
        if (not S.cur(cid, k) or S.att(cid, "user", "accept", k)
                or S.att(cid, "user", "reject", k)):
            continue
        for a in S.att(cid, "assistant", "offer", k):
            wit[c.object].add(frozenset({cid, a.attribution_id}))
    return _value(wit, _witness_claims(wit, S), S, k)


def v6_candidates(S: DerivedState, b: Binding, k: int) -> list[tuple[ClaimRow, AttRow]]:
    out = []
    for c in S.claims_sp(b.subject, S.world.choice_predicate, k):
        if S.cur(c.claim_id, k) and not S.att(c.claim_id, "user", "reject", k):
            out += [(c, a) for a in S.att(c.claim_id, "user", "accept", k)]
    return out


def ref_v6(S: DerivedState, b: Binding, k: int) -> ViewValue:
    A = v6_candidates(S, b, k)
    wit: dict[Any, set[frozenset]] = defaultdict(set)
    if A:
        best, _ = max(A, key=lambda ca: (ca[1].version, ca[0].claim_id))
        accepts = [a for c, a in A if c.claim_id == best.claim_id]
        for d in S.claims_sp(best.object, S.world.catalogue_predicate, k):
            if not S.cur(d.claim_id, k):
                continue
            for ad in S.att(d.claim_id, "assistant", "inform", k):
                for a in accepts:
                    wit[(best.object, d.object)].add(frozenset(
                        {best.claim_id, a.attribution_id, d.claim_id, ad.attribution_id}))
    return _value(wit, _witness_claims(wit, S), S, k)


REFERENCE = {"V1": ref_v1, "V2": ref_v2, "V3": ref_v3, "V4": ref_v4, "V5": ref_v5, "V6": ref_v6}


def evaluate(S: DerivedState, b: Binding, k: int) -> ViewValue:
    return REFERENCE[b.template](S, b, k)


# ---------------------------------------------------------------------------------------------
# Historical state (section 6.2)


def hist(S: DerivedState, subject: str, predicate: str, tau: str, k: int,
         undated: str = "neg-inf") -> tuple[str | None, list[ClaimRow]]:
    """Hist(x, p, tau, k) under one reading of undated starts: `neg-inf` or `message-date`.

    Returns the object of the selected claim (None when no claim qualifies) and the qualifying
    candidates. Corrected claims are excluded; a claim superseded by a change stays visible.
    """
    best = hist_claim(S, subject, predicate, tau, k, undated)
    return (best[0].object if best[0] else None), best[1]


def hist_claim(S: DerivedState, subject: str, predicate: str, tau: str, k: int,
               undated: str = "neg-inf") -> tuple[ClaimRow | None, list[ClaimRow]]:
    """The claim Hist selects (or None) and the qualifying candidates."""
    candidates = []
    for c in S.claims_sp(subject, predicate, k):
        if not S.endorsing(c.claim_id, k) or not S.nc(c.claim_id, k):
            continue
        start = c.start if c.start is not None else (
            NEG_INF if undated == "neg-inf" else S.dates[c.version])
        if start <= tau and (c.end is None or tau < c.end):
            candidates.append((start, c))
    if not candidates:
        return None, []
    _, best = max(candidates, key=lambda sc: (sc[0], sc[1].version, sc[1].claim_id))
    return best, [c for _, c in candidates]


def hist_witness(S: DerivedState, subject: str, predicate: str, tau: str,
                 k: int) -> tuple[list[list[str]], list[str]]:
    """Witnesses ({c*, a} per endorsing attribution) and evidence of the Hist answer at k."""
    best, _ = hist_claim(S, subject, predicate, tau, k)
    if best is None:
        return [], []
    wit = sorted(sorted([best.claim_id, a.attribution_id])
                 for a in S.endorsing(best.claim_id, k))
    return wit, sorted(S.ev(best.claim_id, k))


def hist_determinate(S: DerivedState, subject: str, predicate: str, tau: str,
                     k: int) -> str | None:
    """The historical answer if the three rules of section 6.2 allow the question, else raise
    `Indeterminate`. Rule 1: both readings agree. Rule 2: no competing undated candidates with
    different objects under the -infinity reading. Rule 3 follows from rule 1."""
    a, cands = hist(S, subject, predicate, tau, k, "neg-inf")
    b, _ = hist(S, subject, predicate, tau, k, "message-date")
    if a != b:
        raise Indeterminate(f"readings differ: {a!r} vs {b!r}")
    undated = {c.object for c in cands if c.start is None}
    if len(undated) > 1:
        raise Indeterminate(f"competing undated candidates {sorted(undated)}")
    return a


class Indeterminate(ValueError):
    """A historical question whose gold would depend on a date the dialogue never states."""


# ---------------------------------------------------------------------------------------------
# Patterns of the view templates and the decision list (section 4.1)


@dataclass(frozen=True)
class Pattern:
    subject: str | None          # None: a variable (the join pattern of V6)
    predicates: frozenset[str]
    speaker: str
    function: str
    positive: bool = True
    in_join: bool = False
    no_valid_end: bool = False
    endorsing: bool = False      # V1-V3: End_k (not derived)


def patterns(b: Binding, world: World) -> list[Pattern]:
    sel, arr = world.choice_predicate, world.catalogue_predicate
    if b.template in ("V1", "V2", "V3"):
        auth = world.authority[b.predicate]
        return [Pattern(b.subject, frozenset({b.predicate}), auth, "inform",
                        no_valid_end=b.template == "V2", endorsing=True)]
    if b.template == "V4":
        return [Pattern(b.subject, world.constraint_predicates, "user", "request")]
    if b.template == "V5":
        return [Pattern(b.subject, frozenset({sel}), "assistant", "offer"),
                Pattern(b.subject, frozenset({sel}), "user", "accept", positive=False),
                Pattern(b.subject, frozenset({sel}), "user", "reject", positive=False)]
    return [Pattern(b.subject, frozenset({sel}), "user", "accept", in_join=True),
            Pattern(b.subject, frozenset({sel}), "user", "reject", positive=False),
            Pattern(None, frozenset({arr}), "assistant", "inform", in_join=True)]


def _matches_pattern(S: DerivedState, c: ClaimRow, pat: Pattern, k: int) -> bool:
    """c satisfies the positive pattern at k: subject/predicate, currently accepted, attribution
    constraint (own, positive) and local filters. Join partners are checked separately."""
    if not S.known(c.claim_id, k) or c.predicate not in pat.predicates:
        return False
    if pat.subject is not None and c.subject != pat.subject:
        return False
    if not S.cur(c.claim_id, k) or (pat.no_valid_end and c.end is not None):
        return False
    if pat.endorsing:
        return bool(S.endorsing(c.claim_id, k))
    return bool(S.att(c.claim_id, pat.speaker, pat.function, k))


def _has_partner(S: DerivedState, c: ClaimRow, pat: Pattern, pats: list[Pattern],
                 k: int) -> bool:
    if not pat.in_join:
        return True
    other = next(p for p in pats if p.in_join and p is not pat)
    if pat.subject is None:         # c is a catalogue claim (?o, arr, ?t): partner sel claim
        return any(_matches_pattern(S, s, other, k)
                   for s in S.claims_sp(other.subject, S.world.choice_predicate, k)
                   if s.object == c.subject)
    return any(_matches_pattern(S, d, other, k)
               for d in S.claims_sp(c.object, S.world.catalogue_predicate, k))


def relevant(S: DerivedState, c: ClaimRow, b: Binding) -> bool:
    """c in R_b: subject and predicate match a claim pattern of the binding's template."""
    return any(c.predicate in p.predicates and (p.subject is None or p.subject == c.subject)
               for p in patterns(b, S.world))


def predicates_of(b: Binding, world: World) -> set[str]:
    return {q for p in patterns(b, world) for q in p.predicates}


def newly_matches(S: DerivedState, c: ClaimRow, b: Binding, t: int) -> bool:
    pats = patterns(b, S.world)
    for pat in pats:
        if not pat.positive:
            continue
        if (_matches_pattern(S, c, pat, t) and not _matches_pattern(S, c, pat, t - 1)
                and _has_partner(S, c, pat, pats, t)):
            return True
    return False


def candidate_set_nonempty(S: DerivedState, b: Binding, k: int) -> bool:
    if b.template == "V2":
        return bool(v2_candidates(S, b, k))
    if b.template == "V6":
        return bool(v6_candidates(S, b, k))
    return False


def classify(S: DerivedState, record: LogRecord, b: Binding,
             witness_claims_before: set[str]) -> tuple[str, list[str]]:
    """The change type of message `record` with respect to binding `b` (decision list of 4.1);
    returns (type, C7 sub-kinds). `witness_claims_before` is W_b at t-1."""
    t, E = record.version, record.events
    pats = patterns(b, S.world)
    touched = []                       # claims named by the entries of E_t
    for e in E:
        touched.append(S.claims[e.claim_id])
    rel = [c for c in touched if relevant(S, c, b)]
    for e in E:                                                       # 1: C5
        if isinstance(e, Supersede) and e.kind == "correction" and relevant(
                S, S.claims[e.claim_id], b):
            return "C5", []
    for e in E:                                                       # 2: C1
        if isinstance(e, Supersede) and e.kind == "change" and e.claim_id in witness_claims_before:
            return "C1", []
    negated = {(p.speaker, p.function) for p in pats if not p.positive}
    for e in E:                                                       # 3: C3
        if (isinstance(e, Stance) and relevant(S, S.claims[e.claim_id], b)
                and (record.speaker, e.function) in negated and e.report_mode == "own"
                and e.polarity == "positive"):
            return "C3", []
    new = [c for c in dict.fromkeys(rel) if newly_matches(S, c, b, t)]
    if new:                                                           # 4 and 5: C4, C2
        if b.template == "V3" or (b.template in ("V2", "V6")
                                  and candidate_set_nonempty(S, b, t - 1)):
            return "C4", []
        return "C2", []
    for e in E:                                                       # 6: C6
        if isinstance(e, Stance) and e.claim_id in witness_claims_before:
            return "C6", []
    preds = predicates_of(b, S.world)
    subs = set()
    for c in touched:                                                 # 7: C7
        if c.predicate not in preds:
            continue
        if not relevant(S, c, b):
            subs.add("b")
            continue
        join = [p for p in pats if p.positive and p.in_join and c.predicate in p.predicates
                and (p.subject is None or p.subject == c.subject)]
        if join and any(_matches_pattern(S, c, p, t) and not _has_partner(S, c, p, pats, t)
                        for p in join):
            subs.add("c")
        else:
            subs.add("a")
    if subs:
        return "C7", sorted(subs)
    return "untouched", []


# ---------------------------------------------------------------------------------------------
# The procedure (section 6.3)


def fingerprint(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class GoldStaleness:
    """Output of `gold_staleness` for one sequence."""

    bindings: list[Binding]
    values: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # binding -> per t
    labels: list[dict[str, Any]] = field(default_factory=list)

    def value(self, binding_id: str, t: int) -> dict[str, Any]:
        return self.values[binding_id][t]

    def stale(self, binding_id: str, r0: int, r: int) -> str | None:
        """`answer`, `citation` or None for a view with cut-off r0 read at r (any pair)."""
        a, b = self.value(binding_id, r0), self.value(binding_id, r)
        if a["ans"] != b["ans"]:
            return "answer"
        if (a["wit"], a["ev"]) != (b["wit"], b["ev"]):
            return "citation"
        return None

    def reference_records(self) -> list[dict[str, Any]]:
        """Canonical (ans, wit, ev) and fingerprints at each version where they change."""
        out = []
        for b in self.bindings:
            previous = None
            for t, v in enumerate(self.values[b.binding_id]):
                if v != previous:
                    out.append({"binding_id": b.binding_id, "version": t, **v,
                                "fa": fingerprint(v["ans"]), "fw": fingerprint(v["wit"]),
                                "fe": fingerprint(v["ev"])})
                previous = v
        return out


def gold_staleness(log: Sequence[LogRecord], world: World,
                   bindings: Sequence[Binding]) -> GoldStaleness:
    S = DerivedState(log, world)
    out = GoldStaleness(list(bindings))
    values: dict[str, list[ViewValue]] = {}
    for b in bindings:
        values[b.binding_id] = [evaluate(S, b, t) for t in range(len(log) + 1)]
        out.values[b.binding_id] = [v.canonical() for v in values[b.binding_id]]
    for record in log:
        t = record.version
        for b in bindings:
            before, after = out.values[b.binding_id][t - 1], out.values[b.binding_id][t]
            answer = before["ans"] != after["ans"]
            citation = not answer and (before["wit"], before["ev"]) != (after["wit"],
                                                                        after["ev"])
            w_before = _witness_claims(values[b.binding_id][t - 1].wit, S)
            kind, subs = classify(S, record, b, w_before)
            out.labels.append({"version": t, "message_id": record.message_id,
                               "binding_id": b.binding_id, "answer_stale": answer,
                               "citation_stale": citation, "change_type": kind,
                               "sub_kinds": subs})
    return out


ALLOWED = {"C1": {"answer"}, "C2": {"answer"}, "C3": {"answer", "neither"}, "C4": {"answer"},
           "C5": {"answer", "citation"}, "C6": {"citation"}, "C7": {"neither"},
           "untouched": {"neither"}}


def outcome(label: Mapping[str, Any]) -> str:
    if label["answer_stale"]:
        return "answer"
    return "citation" if label["citation_stale"] else "neither"


def check_invariants(gold: GoldStaleness) -> list[str]:
    """Violations of the cross-table of section 4.2 (and its converse: every staleness has a
    type in C1-C6). A violation is a generator or reference-function bug."""
    return [f"t={x['version']} {x['binding_id']}: {x['change_type']} with outcome {outcome(x)}"
            for x in gold.labels if outcome(x) not in ALLOWED[x["change_type"]]]
