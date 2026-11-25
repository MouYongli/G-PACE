"""Development subset of the query planner (T023): build it, load it, check plans against it.

Not a test module (no `test_` prefix); `test_planner_devset.py` imports it, and the development
check of the planner LLM runs it as a script:

    uv run python -m tests.integration.planner_dev build-subset          # rewrite subset.yaml
    uv run python -m tests.integration.planner_dev check --base-url http://127.0.0.1:8104/v1
    uv run python -m tests.integration.planner_dev check --rules-only

The subset (`docs/research/annotations/planner-dev/`) has two parts, both development data only:

- change-seq: questions of the development smoke set (`configs/changeseq/dev-smoke.yaml`,
  development families), regenerated here with the T015 generator, with the generator's gold
  graph and gold answers; the annotated IR, attribution and time expectations are the agent's.
- LoCoMo conv-26 and conv-49 (the development histories): questions inside the fragment, a
  hand-built partial claim graph (`locomo-graphs.yaml`) and the agent's annotation.

The annotator is the manager agent session m01-T023, not a human annotator.

The check plans every case, binds anchors, executes the query on the case's gold graph and
compares (a) the attribution constraints, (b) the time parameters and (c) the execution result
with the annotation. The planner sees only the question, the reference date and the vocabulary
fragment (predicates, entity names, speakers); gold answers stay on the checking side.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT
from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entries import (
    Attribution,
    Certainty,
    Claim,
    CommunicativeFunction,
    Entity,
    EvidenceLink,
    Polarity,
    ReportMode,
    Supersession,
    SupersessionKind,
    ValidTime,
    Value,
)
from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.query.grammar import parse
from grace.context.pipeline.query.ir import Bound, Op, Predicate, Query, ValidBound
from grace.context.pipeline.query.planner import (
    Anchor,
    Plan,
    Planner,
    PlannerConfig,
    PlanningContext,
    run_plan,
    summarize,
)
from grace.context.pipeline.query.result import QueryResult
from grace.context.pipeline.query.rules import EntityInfo, PredicateInfo

SUBSET_DIR = REPO_ROOT / "docs" / "research" / "annotations" / "planner-dev"
SUBSET_FILE = SUBSET_DIR / "subset.yaml"
LOCOMO_FILE = SUBSET_DIR / "locomo-graphs.yaml"
DEV_SMOKE = REPO_ROOT / "configs" / "changeseq" / "dev-smoke.yaml"
ANNOTATOR = "agent-m01-T023"
SELECTION_SALT = "T023-planner-dev-v1"
CS_SEQUENCES = ("train-travel-rho10-L200-000", "flight-travel-rho10-L200-000",
                "car-rental-rho10-L200-000", "hotel-stay-rho10-L200-000",
                "apartment-search-rho10-L200-000")
CS_SCHEDULES = ("A20d1", "A20d5")
SPEAKERS = ("user", "assistant")
OPEN_END = "9999-12-31"  # end(?c) > OPEN_END holds only for an open valid end


# ---------------------------------------------------------------------------------------------
# Change-seq: regenerate the sequences, vocabulary fragment, gold IR


@dataclass
class CsSequence:
    sequence_id: str
    family: Any
    world: Any
    tasks: dict[str, str]
    store: ClaimStore
    dates: dict[int, str]
    questions: list[dict[str, Any]]
    companion: str


def generate_changeseq(sequence_ids: Sequence[str] = CS_SEQUENCES) -> dict[str, CsSequence]:
    """Regenerate the named sequences of the development smoke set (deterministic)."""
    from grace.eval.datasets.changeseq.build import DatasetConfig, generate_sequence, sequence_seed

    config = DatasetConfig.from_dict(yaml.safe_load(DEV_SMOKE.read_text(encoding="utf-8")))
    cells = dict(config.sequence_ids())
    out = {}
    for sid in sequence_ids:
        bundle = generate_sequence(cells[sid].family, cells[sid], sequence_seed(config.seed, sid),
                                   sid)
        plan = bundle.plan
        questions = [q for s in bundle.schedules if s.name in CS_SCHEDULES for q in s.questions]
        dates = {r.version: r.timestamp for r in plan.log}
        out[sid] = CsSequence(sid, plan.family, plan.world, dict(plan.tasks), bundle.store,
                              dates, questions, plan.companion)
    return out


def _verb(ask: str) -> str | None:
    m = re.match(r"^(?:which|what|where)(?: [\w ]+?)? do I (.+?)\?$", ask, re.IGNORECASE)
    return m.group(1) if m else None


def changeseq_vocabulary(seq: CsSequence) -> tuple[tuple[PredicateInfo, ...],
                                                   tuple[EntityInfo, ...]]:
    """The vocabulary fragment and entity table a GRACE read of this history would show.

    Built from the family's predicate names, nouns and the verbs of its question forms, and from
    the entity names the dialogue uses (people, task names, item labels). No answer is in it.
    """
    from grace.eval.datasets.changeseq.template_families import grammar

    fam = seq.family
    preds = []
    for sp in (fam.multi, fam.exclusive):
        aliases = tuple(x for x in (sp.noun, _verb(sp.forms.get("ask_first", ""))) if x)
        preds.append(PredicateInfo(sp.predicate, sp.exclusive, aliases))
    for c in fam.task.constraints:
        preds.append(PredicateInfo(c.predicate, fam.is_exclusive(c.predicate),
                                   description=f"a requirement of the {fam.task.noun}"))
    cat = fam.task.catalogue
    preds.append(PredicateInfo(cat.predicate, True, (cat.noun,),
                               description="property of an option, stated by the assistant"))
    choice = grammar().choice_predicate
    preds.append(PredicateInfo(choice, False, ("option", "selected option"),
                               description=f"an option for a {fam.task.noun}; offered, "
                                           "accepted or rejected"))
    ents = [EntityInfo("user", ("I", "me", "my"), "speaker"),
            EntityInfo("assistant", ("you",), "speaker"),
            EntityInfo(seq.companion, (seq.companion,), "person")]
    for k, name in sorted(seq.tasks.items()):
        ents.append(EntityInfo(k, (name, name.removeprefix("the ")), fam.task.noun))
    for item_id, label in fam.task.items:
        ents.append(EntityInfo(item_id, (label,), "option"))
    return tuple(preds), tuple(ents)


def _item_id(seq: CsSequence, label: str) -> str:
    return next(i for i, lab in seq.family.task.items if lab == label)


def changeseq_gold(seq: CsSequence, q: dict[str, Any]) -> dict[str, Any]:
    """The agent's annotation of one generated question (design section 6.2 semantics)."""
    from grace.eval.datasets.changeseq.template_families import grammar

    template, binding = q["template"], q["binding_id"].split(":")
    choice = grammar().choice_predicate
    cat = seq.world.catalogue_predicate
    att: list[list[str]]
    anchor = None
    time = {"state": "current", "known": "r", "valid": None, "window": None,
            "temporary": False, "latest_valid": False, "open_end": False}
    if template in ("V1", "V2", "V3"):
        x, p = binding[1], binding[2]
        auth = seq.world.authority[p]
        pat = f"({x}, {p}, ?o) [{auth}, inform]"
        att = [[f"+{auth}/inform"], ["+_/inform"], []]
        if template == "V1":
            ir = f"SELECT ?o WHERE {{ {pat} }}"
        elif template == "V3":
            ir = f"SELECT COUNT(DISTINCT ?o) WHERE {{ {pat} }}"
        elif q["type"] not in ("known_then", "seen_from_now"):
            # current state: only claims whose valid time has not ended (design 6.2, V2)
            ir = (f"SELECT ?o WHERE {{ {pat} AS ?c FILTER(end(?c) > \"{OPEN_END}\"^^date) }} "
                  "LATEST BY version OF ?c")
            time["open_end"] = True
        else:
            ir = f"SELECT ?o WHERE {{ {pat} AS ?c }} LATEST BY version OF ?c"
            if q["type"] in ("known_then", "seen_from_now"):
                m = re.search(r"(booked|offered me) (.+?) for (the .+?)(?:,|\?|$)", q["text"])
                verb, label, task_name = m.groups()
                k = next(t for t, n in seq.tasks.items() if n == task_name)
                item = _item_id(seq, label)
                sf = "[user, accept]" if verb == "booked" else "[assistant, offer]"
                anchor = {"ir": f"SELECT ?x WHERE {{ ({k}, {choice}, ?x) {sf} "
                                f"FILTER(?x = {item}) }}",
                          "bind": ["known", "valid"] if q["type"] == "known_then"
                          else ["valid"]}
                ir += " AT(state=historical)"
                att = [a + [f"a{sf[1:-1].replace(', ', '/')}"] for a in att]
                time.update(state="historical", valid=q["tau"],
                            known=q["kappa"] if q["type"] == "known_then" else "r")
    elif template == "V4":
        k = binding[1]
        ir = f"SELECT ?q ?v WHERE {{ ({k}, ?q, ?v) [user, request] }}"
        att = [["+user/request"]]
    elif template == "V5":
        k = binding[1]
        ir = (f"SELECT ?o WHERE {{ ({k}, {choice}, ?o) [assistant, offer] "
              f"NOT EXISTS {{ ({k}, {choice}, ?o) [user, _] }} }}")
        att = [["+assistant/offer", "-user/_"]]
    elif template == "V6":
        k = binding[1]
        ir = (f"SELECT ?o ?t WHERE {{ ({k}, {choice}, ?o) [user, accept] AS ?c . "
              f"(?o, {cat}, ?t) [assistant, inform] "
              f"NOT EXISTS {{ ({k}, {choice}, ?o) [user, reject] }} }} LATEST BY version OF ?c")
        att = [["+user/accept", "+assistant/inform", "-user/reject"],
               ["+user/accept", "-user/reject"]]
    else:
        raise ValueError(f"unknown template {template}")
    return {"gold_ir": ir, "gold_anchor": anchor, "attribution": att, "time": time}


def _canonical(answer: Any) -> list[str]:
    return [str(x) for x in answer] if isinstance(answer, list) else [str(answer)]


def build_changeseq_cases(sequences: dict[str, CsSequence]) -> list[dict[str, Any]]:
    """One question per (family, template, type) stratum, the first by SHA-256 order."""
    cases = []
    for sid in CS_SEQUENCES:
        seq = sequences[sid]
        strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for q in seq.questions:
            strata[(q["template"], q["type"])].append(q)
        for (template, qtype), qs in sorted(strata.items()):
            def key(q, sid=sid):
                text = f"{SELECTION_SALT}:{sid}:{q['schedule']}:{q['question_id']}"
                return hashlib.sha256(text.encode()).hexdigest()
            q = min(qs, key=key)
            gold = changeseq_gold(seq, q)
            cases.append({
                "case_id": f"cs:{sid}:{q['schedule']}:{q['question_id']}",
                "source": "change-seq", "history_id": sid, "schedule": q["schedule"],
                "question_id": q["question_id"], "template": template, "type": qtype,
                "read_version": q["read_version"], "reference_date": q["asked_at"],
                "question": q["text"],
                "gold_answer": sorted("|".join(_canonical(a)) for a in q["answer"]),
                **gold})
    return cases


# ---------------------------------------------------------------------------------------------
# LoCoMo: the hand-built partial graphs


@dataclass
class LocomoHistory:
    history_id: str
    store: ClaimStore
    dates: dict[int, str]
    reference_date: str
    read_version: int
    predicates: tuple[PredicateInfo, ...]
    entities: tuple[EntityInfo, ...]
    speakers: tuple[str, ...]


def _term(raw: Any):
    if isinstance(raw, dict) and "entity" in raw:
        return Entity(raw["entity"])
    if isinstance(raw, dict):
        return Value(str(raw["value"]), raw.get("datatype", "string"))
    return Value(str(raw))


def load_locomo(path: Path = LOCOMO_FILE) -> dict[str, LocomoHistory]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out = {}
    for hid, h in raw["histories"].items():
        messages = {m: (int(v), str(d)) for m, (v, d) in h["messages"].items()}
        per_version: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        atts: dict[tuple[str, int], str] = {}
        n = 0
        for c in h["claims"]:
            first = min(messages[a[2]][0] for a in c["attributions"])
            vt = ValidTime(c.get("start"), c.get("end"), c.get("expression"))
            claim = Claim(c["id"], c["s"], c["p"], _term(c["o"]), c.get("scope"), vt, first)
            per_version[first]["claims"].append(claim)
            for i, (speaker, function, msg) in enumerate(c["attributions"]):
                v = messages[msg][0]
                aid = f"{c['id']}-a{i}"
                atts[(c["id"], i)] = aid
                per_version[v]["attributions"].append(Attribution(
                    aid, c["id"], speaker, CommunicativeFunction(function), ReportMode.OWN,
                    Polarity.POSITIVE, Certainty.CERTAIN, False, msg, v))
            for msg in c.get("evidence") or sorted({a[2] for a in c["attributions"]}):
                v = messages[msg][0]
                n += 1
                per_version[v]["evidence_links"].append(
                    EvidenceLink(f"ev{n}-{c['id']}", c["id"], msg, None, v))
        for i, s in enumerate(h.get("supersessions") or ()):
            v = messages[s["message"]][0]
            per_version[v]["supersessions"].append(Supersession(
                f"s{i}-{s['claim']}", s["claim"], SupersessionKind(s["kind"]),
                s.get("valid_end"), s.get("replacing"), atts[(s["licence"][0], s["licence"][1])],
                v))
        store = ClaimStore(hid)
        for v in sorted(per_version):
            parts = per_version[v]
            store.commit(ChangeSet(hid, v, claims=tuple(parts["claims"]),
                                   attributions=tuple(parts["attributions"]),
                                   evidence_links=tuple(parts["evidence_links"]),
                                   supersessions=tuple(parts["supersessions"])))
        preds = tuple(PredicateInfo(p["name"], p["exclusive"], tuple(p.get("aliases") or ()),
                                    p.get("description")) for p in h["predicates"])
        ents = tuple(EntityInfo(e["id"], tuple(e.get("names") or ()), e.get("kind"))
                     for e in h["entities"])
        out[hid] = LocomoHistory(hid, store, {v: d for v, d in messages.values()},
                                 str(h["reference_date"]), int(h["read_version"]), preds, ents,
                                 tuple(h["speakers"]))
    return out


# ---------------------------------------------------------------------------------------------
# Subset file


def load_subset(path: Path = SUBSET_FILE) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def write_subset(cases: list[dict[str, Any]], locomo_cases: list[dict[str, Any]],
                 path: Path = SUBSET_FILE) -> None:
    header = {
        "subset": "T023 planner development subset", "version": 1,
        "annotator": ANNOTATOR,
        "annotator_kind": "agent session (manager m01-T023); not a human annotator",
        "data": {
            "change-seq": "development smoke set, configs/changeseq/dev-smoke.yaml (development "
                          "families), regenerated with the T015 generator; gold answers are the "
                          "generator's; gold IR, attribution and time expectations are the "
                          "agent's annotation of the semantics in docs/research/"
                          "change-sequences.md section 6.2",
            "locomo": "snap-research/locomo @ 3eb6f2c, development histories conv-26 and conv-49 "
                      "only; questions, gold answers, hand-built partial graph "
                      "(locomo-graphs.yaml) and expectations annotated by the agent",
        },
        "selection": {"change-seq": f"sequences {list(CS_SEQUENCES)}, schedules "
                                    f"{list(CS_SCHEDULES)}; per sequence one question per "
                                    "(template, type) stratum, the smallest SHA-256 of "
                                    f"'{SELECTION_SALT}:<sequence>:<schedule>:<question_id>'",
                      "locomo": "hand-picked inside-fragment questions with attribution or time "
                                "content; see locomo-graphs.yaml"},
        "fields": {
            "attribution": "alternatives; each a list of constraints: +speaker/function on a "
                           "positive pattern, -speaker/function on the negated pattern, "
                           "aspeaker/function on the anchor; _ is an open position; +_/inform "
                           "is neutral and ignored on both sides",
            "time": "state, known (r or the bound version), valid (bound world time), window "
                    "([start, end) of the start(?c) filters), temporary, latest_valid",
            "gold_answer": "sorted answers; columns of one answer joined by |",
        },
    }
    body = {**header, "cases": [*cases, *locomo_cases]}
    text = ("# T023 planner development subset. Generated by "
            "`uv run python -m tests.integration.planner_dev build-subset` from the change-seq "
            "generator and\n# locomo-graphs.yaml; annotator: agent session m01-T023 (not a human "
            "annotator). Development data only.\n")
    path.write_text(text + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100),
                    encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# Checks


def attribution_signature(query: Query | None, anchor: Anchor | None) -> list[str]:
    out = []

    def sig(prefix, p):
        if p.attribution is not None:
            a = p.attribution
            speaker = "_" if a.speaker is None else getattr(a.speaker, "id", str(a.speaker))
            function = "_" if a.function is None else a.function.value
            out.append(f"{prefix}{speaker}/{function}")

    if query is not None:
        for p in query.where:
            sig("+", p)
        if query.negation is not None:
            sig("-", query.negation.pattern)
    if anchor is not None:
        for p in anchor.query.where:
            sig("a", p)
    return sorted(out)


def _neutral(signature: Sequence[str]) -> list[str]:
    """Drop `+_/inform` ("someone stated it"): it names no speaker, so it is never an
    attribution error to add or omit it on a positive pattern."""
    return sorted(x for x in signature if x != "+_/inform")


def time_signature(query: Query | None) -> dict[str, Any] | None:
    if query is None:
        return None
    lo = hi = None
    for f in query.filters:
        if isinstance(f.left, ValidBound) and f.left.bound is Bound.START:
            if f.op is Op.GE:
                lo = f.right.lexical
            elif f.op is Op.LT:
                hi = f.right.lexical
    window = [lo, hi] if lo or hi else None
    open_end = any(isinstance(f.left, ValidBound) and f.left.bound is Bound.END
                   and f.op in (Op.GT, Op.GE) and f.right.lexical == OPEN_END
                   for f in query.filters)
    return {"state": query.at.state.value,
            "known": "r" if query.at.known is None else query.at.known,
            "valid": query.at.valid, "window": window, "temporary": query.temporary,
            "latest_valid": bool(query.latest and query.latest.key.value == "valid"),
            "open_end": open_end}


def answers_of(result: QueryResult | None) -> list[str] | None:
    if result is None:
        return None
    rows = []
    for a in result.answers:
        cols = []
        for v in a.values:
            if isinstance(v, Entity):
                cols.append(v.id)
            elif isinstance(v, Predicate):
                cols.append(v.name)
            else:
                cols.append(v.lexical)
        rows.append("|".join(cols))
    return sorted(rows)


@dataclass
class Graph:
    store: ClaimStore
    dates: dict[int, str]
    predicates: tuple[PredicateInfo, ...]
    entities: tuple[EntityInfo, ...]
    speakers: tuple[str, ...]
    endorsed: ClaimStore | None = None  # F1 diagnostic store, see `endorsed_store`


def endorsed_store(store: ClaimStore) -> ClaimStore:
    """The same graph without attributions that are not own, positive and non-derived.

    Diagnostic for gap F1 (query-ir.md 7.2): an attribution constraint [u, f] cannot yet require
    report mode own, positive polarity or not derived, which the change-seq semantics (design
    section 6.1, "endorsed") do. Evaluating the same query on this store shows which execution
    mismatches that gap alone explains. Licensing attributions of supersessions are kept.
    """
    licences = {s.attribution_id for cs in store.changesets() for s in cs.supersessions}
    out = ClaimStore(store.history_id, store.mode)
    for cs in store.changesets():
        atts = tuple(a for a in cs.attributions if a.attribution_id in licences or (
            a.report_mode is ReportMode.OWN and a.polarity is Polarity.POSITIVE
            and not a.derived))
        out.commit(ChangeSet(cs.history_id, cs.version, cs.claims, atts, cs.evidence_links,
                             cs.supersessions, cs.vocabulary_version, cs.entity_merges))
    return out


def graphs(cases: Sequence[dict[str, Any]]) -> dict[str, Graph]:
    need_cs = sorted({c["history_id"] for c in cases if c["source"] == "change-seq"})
    out = {}
    if need_cs:
        for sid, seq in generate_changeseq(need_cs).items():
            preds, ents = changeseq_vocabulary(seq)
            out[sid] = Graph(seq.store, seq.dates, preds, ents, SPEAKERS,
                             endorsed_store(seq.store))
    if any(c["source"] == "locomo" for c in cases):
        for hid, h in load_locomo().items():
            out[hid] = Graph(h.store, h.dates, h.predicates, h.entities, h.speakers)
    return out


def context_of(case: dict[str, Any], graph: Graph) -> PlanningContext:
    return PlanningContext(case["history_id"], case["case_id"], case["read_version"],
                           case["question"], str(case["reference_date"]), graph.predicates,
                           graph.entities, graph.speakers)


def gold_plan(case: dict[str, Any]) -> Plan:
    """The annotated IR as a plan (for checking the annotation itself)."""
    from grace.context.pipeline.query.planner import apply_window
    from grace.context.pipeline.query.timeexpr import resolve_window

    query = parse(case["gold_ir"], check=False)
    window = None
    if tw := case.get("gold_window"):
        window = resolve_window(tw["phrase"], str(case["reference_date"]))
        query = apply_window(query, window, tw["label"])
    anchor = None
    if a := case.get("gold_anchor"):
        anchor = Anchor(parse(a["ir"]), tuple(a["bind"]))
    from grace.context.pipeline.query.compile import compile_query

    return Plan(case["case_id"], "llm", query, compile_query(query), anchor, window)


def check_case(case: dict[str, Any], plan: Plan, graph: Graph) -> dict[str, Any]:
    """Run the plan and compare attribution, time and result with the annotation."""
    planned = plan
    plan, result = run_plan(plan, graph.store, case["read_version"], graph.dates.get)
    att = attribution_signature(plan.query, planned.anchor)
    tsig = time_signature(plan.query)
    expected_time = {k: v for k, v in case["time"].items()}
    got = answers_of(result)
    record = {
        "case_id": case["case_id"], "source": case["source"], "template": case.get("template"),
        "type": case.get("type"), "question": case["question"], "route": plan.route,
        "rule": plan.rule, "failure": plan.failure, "failure_detail": plan.failure_detail,
        "repairs": plan.repairs, "attempt_failures": list(plan.attempt_failures),
        "attribution": att, "attribution_ok": any(_neutral(alt) == _neutral(att)
                                                  for alt in case["attribution"]),
        "time": tsig, "time_ok": tsig == expected_time,
        "answer": got, "gold_answer": case["gold_answer"],
        "execution_ok": got == case["gold_answer"],
        "plan": plan.to_record(),
    }
    # F1 diagnostic: the same plan on the endorsement-filtered graph (change-seq only).
    if graph.endorsed is not None:
        _, result_f1 = run_plan(planned, graph.endorsed, case["read_version"], graph.dates.get)
        record["answer_endorsed"] = answers_of(result_f1)
        record["execution_ok_endorsed"] = record["answer_endorsed"] == case["gold_answer"]
        record["f1_explained"] = (not record["execution_ok"]
                                  and record["execution_ok_endorsed"])
    else:
        record["answer_endorsed"] = got
        record["execution_ok_endorsed"] = record["execution_ok"]
        record["f1_explained"] = False
    if plan.query is None:
        record["attribution_ok"] = record["time_ok"] = record["execution_ok"] = False
        record["execution_ok_endorsed"] = record["f1_explained"] = False
    return record


def score(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def share(key, rows):
        return round(sum(r[key] for r in rows) / len(rows), 4) if rows else None

    by = defaultdict(list)
    for r in records:
        by[r["source"]].append(r)
        by[f"route:{r['route']}"].append(r)
    out = {"cases": len(records)}
    for name, rows in [("all", list(records)), *sorted(by.items())]:
        out[name] = {"n": len(rows), "attribution_ok": share("attribution_ok", rows),
                     "time_ok": share("time_ok", rows),
                     "execution_ok": share("execution_ok", rows),
                     "execution_ok_endorsed": share("execution_ok_endorsed", rows),
                     "f1_explained": sum(r["f1_explained"] for r in rows),
                     "all_ok": round(sum(r["attribution_ok"] and r["time_ok"]
                                         and r["execution_ok"] for r in rows) / len(rows), 4)}
    return out


# ---------------------------------------------------------------------------------------------
# Command line


def _client(base_url: str, model_config: Path, ledger_path: Path, run_id: str):
    from grace.llm.client import ChatClient, Endpoint
    from grace.llm.records import CallLedger
    from grace.llm.tokens import HFTokenCounter, TokenizerPin, locate_snapshot

    raw = yaml.safe_load(model_config.read_text(encoding="utf-8"))
    pin = TokenizerPin.from_config(raw)
    counter = HFTokenCounter(pin, locate_snapshot(pin))
    endpoint = Endpoint.for_model(pin, base_url, raw["served_name"], timeout_s=120.0)
    return ChatClient(endpoint, CallLedger(ledger_path, run_id), counter), raw


def cmd_build(_args) -> int:
    from grace.context.pipeline.query.grammar import parse as _parse

    sequences = generate_changeseq()
    cases = build_changeseq_cases(sequences)
    locomo = yaml.safe_load(LOCOMO_FILE.read_text(encoding="utf-8"))["cases"]
    for c in locomo:
        _parse(c["gold_ir"], check=False)
    write_subset(cases, locomo)
    print(f"wrote {SUBSET_FILE.relative_to(REPO_ROOT)}: {len(cases)} change-seq, "
          f"{len(locomo)} locomo cases")
    return 0


def cmd_check(args) -> int:
    from grace.config.paths import project_root
    from grace.eval.runner.harness import rundir

    subset = load_subset()
    cases = subset["cases"]
    if args.limit:
        cases = cases[:args.limit]
    graph_by_history = graphs(cases)
    experiment = "T023"
    run_dir = rundir.create(project_root() / "runs", experiment,
                            args.run_id) if not args.out else Path(args.out)
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_dir.name
    config_path = REPO_ROOT / "configs" / "common" / "planner.yaml"
    config = PlannerConfig.load(config_path)
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump({"planner": {k: (list(v) if isinstance(v, tuple) else
                                        dict(v) if isinstance(v, dict) else v)
                                    for k, v in config.__dict__.items()},
                        "rules_only": args.rules_only, "base_url": args.base_url,
                        "model_config": args.model_config, "subset": "docs/research/annotations/"
                        "planner-dev/subset.yaml", "limit": args.limit}, sort_keys=True),
        encoding="utf-8")
    code = rundir.code_state()
    subset_sha = rundir.file_sha256(SUBSET_FILE)
    locomo_sha = rundir.file_sha256(LOCOMO_FILE)
    run = rundir.RunJson(run_dir, {
        "run_id": run_id, "experiment": experiment, "stage": "planner-dev-check",
        "upstream": [], "code_sha": code.sha, "code_dirty": code.dirty,
        "config_path": "configs/common/planner.yaml",
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(),
        "data": [{"benchmark": "planner-dev-subset", "split": "development",
                  "path": SUBSET_FILE.as_posix(), "sha256": subset_sha},
                 {"benchmark": "locomo-hand-graphs", "split": "development",
                  "path": LOCOMO_FILE.as_posix(), "sha256": locomo_sha},
                 {"benchmark": "change-seq", "split": "development",
                  "path": DEV_SMOKE.as_posix(), "sha256": rundir.file_sha256(DEV_SMOKE),
                  "note": "sequences regenerated in memory with the generator at code_sha"}],
        "project_root": project_root().as_posix(), "seed": None,
        "command": " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment("cpu"), "model_calls": 0,
        "held_out_access": "none"})
    client = None
    try:
        if not args.rules_only:
            client, raw = _client(args.base_url, Path(args.model_config),
                                  run_dir / "calls.jsonl", run_id)
            run.data["model"] = {"hf_repo": raw["hf_repo"], "revision": raw["revision"],
                                 "base_url": args.base_url,
                                 "compute": args.compute or "none"}
        planner = Planner(config, client)
        records, plans = [], []
        with (run_dir / "plans.jsonl").open("w", encoding="utf-8") as out:
            for case in cases:
                graph = graph_by_history[case["history_id"]]
                plan = planner.plan(context_of(case, graph))
                plans.append(plan)
                rec = check_case(case, plan, graph)
                records.append(rec)
                out.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
                print(f"{case['case_id']}: route={rec['route']} att={rec['attribution_ok']} "
                      f"time={rec['time_ok']} exec={rec['execution_ok']}"
                      + (f" failure={rec['failure']}" if rec["failure"] else ""), flush=True)
        summary = {"planner": summarize(plans), "checks": score(records),
                   "by_template": {
                       k: score([r for r in records if (r["template"] or r["source"]) == k])["all"]
                       for k in sorted({r["template"] or r["source"] for r in records})},
                   "failures": dict(Counter(r["failure"] for r in records if r["failure"]))}
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True)
                                              + "\n", encoding="utf-8")
        run.data["model_calls"] = summary["planner"]["llm_calls"]
        run.finish(len(records))
        print(json.dumps(summary, indent=2, sort_keys=True))
        print(f"run directory: {run_dir}")
    except Exception as exc:  # noqa: BLE001 - recorded in run.json, then re-raised
        run.finish(0, f"{type(exc).__name__}: {exc}")
        raise
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planner_dev")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build-subset")
    check = sub.add_parser("check")
    check.add_argument("--base-url", default="http://127.0.0.1:8104/v1")
    check.add_argument("--model-config", default=str(REPO_ROOT / "configs" / "models"
                                                     / "qwen3-8b.yaml"))
    check.add_argument("--rules-only", action="store_true")
    check.add_argument("--run-id", default=None)
    check.add_argument("--out", default=None, help="explicit run directory (tests)")
    check.add_argument("--compute", default=None, help="the compute.yaml reservation used")
    check.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    return cmd_build(args) if args.cmd == "build-subset" else cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())

