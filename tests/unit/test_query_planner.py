"""Query planner (T023): time phrases, rule templates, LLM planning, repair and fallback."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
    ValidTime,
    Value,
)
from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.query.grammar import to_text
from grace.context.pipeline.query.planner import (
    Planner,
    PlannerConfig,
    PlanningContext,
    run_plan,
    summarize,
)
from grace.context.pipeline.query.rules import EntityInfo, PredicateInfo, match_rules
from grace.context.pipeline.query.timeexpr import TimeExpressionError, resolve_window
from grace.llm.client import ChatClient, Endpoint
from grace.llm.records import CallLedger, read_calls
from tests.llm.fakes import WordCounter

PREDICATES = (PredicateInfo("speaksLanguage", False, ("languages", "speak")),
              PredicateInfo("livesIn", True, ("home city", "live")),
              PredicateInfo("selectedService", False, ("option",)),
              PredicateInfo("tookTrip", False, ("trip",)))
ENTITIES = (EntityInfo("user", ("I", "me", "my")), EntityInfo("assistant", ("you",)),
            EntityInfo("Bogdan", ("Bogdan",)), EntityInfo("k1", ("the car rental A",)),
            EntityInfo("kia", ("Kia Ceed",)), EntityInfo("skoda", ("Skoda Octavia",)))


def ctx(question: str, *, reference: str | None = "2026-03-10", version: int = 9):
    return PlanningContext("h1", f"q@{version}", version, question, reference, PREDICATES,
                           ENTITIES, ("user", "assistant"))


def reply(obj) -> dict:
    text = obj if isinstance(obj, str) else json.dumps(obj)
    return {"choices": [{"message": {"content": text}}], "usage": {"completion_tokens": 5}}


def out(ir, **kw) -> dict:
    return {"ir": ir, "variables": kw.pop("variables", []),
            "fallback_channels": kw.pop("channels", ["bm25"]), **kw}


class Scripted:
    """Transport returning scripted replies; keeps the payloads it received."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.payloads = []

    def __call__(self, url, payload, headers, timeout):
        self.payloads.append(payload)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def planner(transport, tmp: Path, **config) -> tuple[Planner, CallLedger]:
    ledger = CallLedger(tmp / "calls.jsonl", "run-t")
    client = ChatClient(Endpoint("http://fake/v1", "m", "m@1"), ledger, WordCounter(),
                        transport=transport, max_attempts=1, sleep=lambda s: None)
    return Planner(PlannerConfig(**config), client), ledger


def build_store() -> ClaimStore:
    """user lives in Bremen (v1), then Cologne (v3, past-dated Hamburg at v4); offer of the Kia
    at v5 and acceptance at v6; trips in May and July 2026."""
    store = ClaimStore("h1")

    def att(aid, cid, v, speaker="user", fn="inform"):
        return Attribution(aid, cid, speaker, CommunicativeFunction(fn), ReportMode.OWN,
                           Polarity.POSITIVE, Certainty.CERTAIN, False, f"m{v}", v)

    def claim(cid, s, p, o, v, start=None, end=None):
        return Claim(cid, s, p, o, None, ValidTime(start, end), v)

    def ev(cid, v):
        return EvidenceLink(f"e-{cid}-{v}", cid, f"m{v}", None, v)

    store.commit(ChangeSet("h1", 1, claims=(claim("c1", "user", "livesIn", Value("Bremen"), 1),),
                           attributions=(att("a1", "c1", 1),), evidence_links=(ev("c1", 1),)))
    store.commit(ChangeSet("h1", 3, claims=(claim("c2", "user", "livesIn", Value("Cologne"), 3),),
                           attributions=(att("a2", "c2", 3),), evidence_links=(ev("c2", 3),)))
    store.commit(ChangeSet("h1", 4, claims=(claim("c3", "user", "livesIn", Value("Hamburg"), 4,
                                                  "2010-01-01", "2012-01-01"),),
                           attributions=(att("a3", "c3", 4),), evidence_links=(ev("c3", 4),)))
    store.commit(ChangeSet("h1", 5, claims=(claim("c4", "k1", "selectedService", Entity("kia"),
                                                  5),),
                           attributions=(att("a4", "c4", 5, "assistant", "offer"),),
                           evidence_links=(ev("c4", 5),)))
    store.commit(ChangeSet("h1", 6, attributions=(att("a5", "c4", 6, "user", "accept"),),
                           evidence_links=(ev("c4", 6),)))
    store.commit(ChangeSet("h1", 7, claims=(
        claim("c5", "user", "tookTrip", Entity("t1"), 7, "2026-05-02"),
        claim("c6", "user", "tookTrip", Entity("t2"), 7, "2026-07-02")),
        attributions=(att("a6", "c5", 7), att("a7", "c6", 7)),
        evidence_links=(ev("c5", 7), ev("c6", 7))))
    return store


class TimeWindowTest(unittest.TestCase):
    def test_absolute_phrases_do_not_depend_on_the_reference(self):
        cases = {"in May 2023": ("2023-05-01", "2023-06-01"), "2023": ("2023-01-01",
                                                                       "2024-01-01"),
                 "in December, 2023": ("2023-12-01", "2024-01-01"),
                 "on 5 May 2023": ("2023-05-05", "2023-05-06"),
                 "May 5th, 2023": ("2023-05-05", "2023-05-06"),
                 "2023-02-28": ("2023-02-28", "2023-03-01")}
        for phrase, (start, end) in cases.items():
            with self.subTest(phrase=phrase):
                w = resolve_window(phrase)
                self.assertEqual((w.start, w.end, w.relative), (start, end, False))

    def test_relative_phrases_resolve_against_the_reference(self):
        ref = "2024-01-11"  # a Thursday
        cases = {"yesterday": ("2024-01-10", "2024-01-11"),
                 "last week": ("2024-01-01", "2024-01-08"),
                 "this month": ("2024-01-01", "2024-02-01"),
                 "last year": ("2023-01-01", "2024-01-01"),
                 "in the last week": ("2024-01-04", "2024-01-12"),
                 "the past 3 months": ("2023-10-11", "2024-01-12"),
                 "one year ago": ("2022-07-11", "2023-07-11"),
                 "4 years ago": ("2019-07-11", "2020-07-11"),
                 "two days ago": ("2024-01-09", "2024-01-10")}
        for phrase, (start, end) in cases.items():
            with self.subTest(phrase=phrase):
                w = resolve_window(phrase, ref)
                self.assertEqual((w.start, w.end, w.relative), (start, end, True))

    def test_vague_unknown_and_unanchored_phrases_are_refused(self):
        for phrase in ("recently", "lately", "soon after the wedding", ""):
            with self.subTest(phrase=phrase), self.assertRaises(TimeExpressionError):
                resolve_window(phrase, "2024-01-11")
        with self.assertRaises(TimeExpressionError):
            resolve_window("last week", None)


class RuleTest(unittest.TestCase):
    def test_count_list_and_current_rules(self):
        hit = match_rules("How many languages does Bogdan speak?", ENTITIES, PREDICATES)
        self.assertEqual(hit.rule, "count")
        self.assertIn("COUNT(DISTINCT ?o)", to_text(hit.query))
        hit = match_rules("Which languages do I speak?", ENTITIES, PREDICATES)
        self.assertEqual((hit.rule, hit.query.where[0].subject), ("list", Entity("user")))
        hit = match_rules("Where does Bogdan live?", ENTITIES, PREDICATES)
        self.assertEqual(hit.rule, "current")
        text = to_text(hit.query)
        self.assertIn("LATEST BY version OF ?c", text)
        self.assertIn('FILTER(end(?c) > "9999-12-31"^^date)', text)

    def test_rules_do_not_fire_on_unresolved_or_other_shapes(self):
        for q in ("How many languages does Anna speak?",          # unknown entity
                  "How many cars does Bogdan own?",               # unknown predicate
                  "How many home cities does Bogdan live in?",    # count of an exclusive one
                  "What did I ask for in the car rental A?",      # attribution: LLM
                  "When you booked Kia Ceed for the car rental A, where did I live?",
                  "How many trips did I take in May 2026?"):      # time: LLM
            with self.subTest(q=q):
                self.assertIsNone(match_rules(q, ENTITIES, PREDICATES))


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_rule_covers_task_without_llm_call(self):
        transport = Scripted()
        p, ledger = planner(transport, self.tmp)
        plan = p.plan(ctx("Which languages does Bogdan speak?"))
        self.assertEqual((plan.route, plan.rule, plan.call_ids), ("rule", "list", ()))
        self.assertEqual(transport.payloads, [])
        self.assertEqual(plan.channels, ("graph", "bm25", "dense"))
        self.assertTrue(plan.view_eligible)

    def test_llm_plan_with_attribution_and_variables(self):
        ir = "SELECT ?q ?v WHERE { (k1, ?q, ?v) [user, request] }"
        transport = Scripted(reply(out(ir, variables=[{"var": "?v", "describes": "value"}])))
        p, ledger = planner(transport, self.tmp)
        plan = p.plan(ctx("What did I ask for in the car rental A?"))
        self.assertEqual((plan.route, plan.repairs, plan.failure), ("llm", 0, None))
        self.assertEqual(plan.variables, (("?v", "value"),))
        self.assertEqual(plan.fallback_channels, ("bm25",))
        calls = read_calls(ledger.path)
        self.assertEqual([(c.call_type, c.category, c.status, c.read_id) for c in calls],
                         [("plan", "U", "ok", "q@9")])
        self.assertEqual(calls[0].prompt_sha256, p.prompt.sha256)
        system, user = transport.payloads[0]["messages"]
        self.assertNotIn("car rental A?", system["content"])  # fixed prefix
        self.assertTrue(user["content"].rstrip().endswith("car rental A?"))

    def test_relative_time_becomes_an_absolute_temporary_window(self):
        ir = "SELECT COUNT(DISTINCT ?t) WHERE { (user, tookTrip, ?t) AS ?c }"
        transport = Scripted(reply(out(ir, time_window={"phrase": "last month",
                                                        "label": "?c"})))
        p, _ = planner(transport, self.tmp)
        plan = p.plan(ctx("How many trips did I take last month?", reference="2026-06-15"))
        self.assertEqual((plan.route, plan.window.start, plan.window.end),
                         ("llm", "2026-05-01", "2026-06-01"))
        self.assertTrue(plan.temporary)
        self.assertFalse(plan.view_eligible)
        text = to_text(plan.query)
        self.assertNotIn("now(", text)
        self.assertIn('FILTER(start(?c) >= "2026-05-01"^^date)', text)
        plan, result = run_plan(plan, build_store(), 7)
        self.assertEqual(result.answers[0].values, (Value("1", "integer"),))
        self.assertTrue(result.temporary)

    def test_absolute_window_is_not_temporary_and_now_is_absolutized(self):
        ir = "SELECT ?t WHERE { (user, tookTrip, ?t) AS ?c }"
        p, _ = planner(Scripted(reply(out(ir, time_window={"phrase": "in July 2026",
                                                           "label": "?c"}))), self.tmp)
        plan = p.plan(ctx("Which trips did I take in July 2026?"))
        self.assertFalse(plan.temporary)
        self.assertTrue(plan.view_eligible)
        ir = "SELECT ?t WHERE { (user, tookTrip, ?t) AS ?c FILTER(start(?c) >= now(-30)) }"
        p, _ = planner(Scripted(reply(out(ir))), self.tmp)
        plan = p.plan(ctx("Which trips did I take in the last 30 days?", reference="2026-07-20"))
        self.assertTrue(plan.temporary)
        self.assertIn('"2026-06-20"^^date', to_text(plan.query))

    def test_one_repair_after_a_parse_failure(self):
        good = "SELECT ?o WHERE { (Bogdan, speaksLanguage, ?o) }"
        transport = Scripted(reply("not json"), reply(out(good)))
        p, ledger = planner(transport, self.tmp)
        plan = p.plan(ctx("Tell me Bogdan's languages."))
        self.assertEqual((plan.route, plan.repairs, plan.attempt_failures),
                         ("llm", 1, ("parse",)))
        calls = read_calls(ledger.path)
        self.assertEqual([(c.call_type, c.status) for c in calls],
                         [("plan", "invalid_output"), ("repair", "ok")])
        self.assertEqual(calls[1].prompt_sha256, p.repair_prompt.sha256)
        repair = transport.payloads[1]["messages"]
        self.assertEqual([m["role"] for m in repair], ["system", "user", "assistant", "user"])
        self.assertIn("not valid planner JSON", repair[-1]["content"])

    def test_type_and_vocabulary_failures_are_repaired_once_then_fall_back(self):
        bad_type = "SELECT ?x WHERE { (Bogdan, speaksLanguage, ?o) }"   # ?x unbound
        bad_vocab = "SELECT ?o WHERE { (Bogdan, speaks, ?o) }"          # unknown predicate
        transport = Scripted(reply(out(bad_type)), reply(out(bad_vocab)))
        p, ledger = planner(transport, self.tmp)
        plan = p.plan(ctx("Tell me Bogdan's languages."))
        self.assertEqual((plan.route, plan.failure, plan.repairs), ("fallback", "type", 1))
        self.assertEqual(plan.attempt_failures, ("type", "type"))
        self.assertIn("unknown predicates", plan.failure_detail)
        self.assertEqual(plan.channels, ("bm25", "dense"))
        self.assertEqual(len(read_calls(ledger.path)), 2)  # never a second repair

    def test_parse_failure_without_repair_budget_falls_back(self):
        transport = Scripted(reply(out("SELECT ?o WHERE { (a, b, ?o) OPTIONAL { } }")))
        p, _ = planner(transport, self.tmp, max_compile_repairs=0)
        plan = p.plan(ctx("Tell me Bogdan's languages."))
        self.assertEqual((plan.route, plan.failure, plan.repairs), ("fallback", "parse", 0))

    def test_unresolvable_time_phrase_is_a_time_failure(self):
        ir = "SELECT ?t WHERE { (user, tookTrip, ?t) AS ?c }"
        tw = {"phrase": "recently", "label": "?c"}
        p, _ = planner(Scripted(reply(out(ir, time_window=tw)), reply(out(ir, time_window=tw))),
                       self.tmp)
        plan = p.plan(ctx("Which trips did I take recently?"))
        self.assertEqual((plan.route, plan.failure), ("fallback", "time"))

    def test_declined_and_failed_calls_fall_back(self):
        p, _ = planner(Scripted(reply(out(None, reason="asks for a feeling"))), self.tmp)
        plan = p.plan(ctx("How did Bogdan feel?"))
        self.assertEqual((plan.route, plan.failure, plan.repairs), ("fallback", "declined", 0))
        p, ledger = planner(Scripted(OSError("down")), self.tmp)
        plan = p.plan(ctx("How did Bogdan feel?"))
        self.assertEqual((plan.route, plan.failure), ("fallback", "llm_error"))
        self.assertEqual(read_calls(ledger.path)[-1].status, "failed")
        plan = Planner(PlannerConfig()).plan(ctx("How did Bogdan feel?"))
        self.assertEqual((plan.route, plan.failure), ("fallback", "no_llm"))

    def test_anchor_binds_known_version_and_valid_date(self):
        main = ("SELECT ?o WHERE { (user, livesIn, ?o) [user, inform] AS ?c } "
                "LATEST BY version OF ?c AT(state=historical)")
        anchor = ("SELECT ?x WHERE { (k1, selectedService, ?x) [user, accept] "
                  "FILTER(?x = kia) }")
        dates = {v: f"2026-03-0{v}" for v in range(1, 8)}
        store = build_store()
        for bind, known in ((["known", "valid"], 6), (["valid"], None)):
            p, _ = planner(Scripted(reply(out(main, anchor={"ir": anchor, "bind": bind}))),
                           self.tmp)
            plan = p.plan(ctx("When you booked Kia Ceed for the car rental A, where did I "
                              "live?", version=7))
            self.assertFalse(plan.view_eligible)
            bound, result = run_plan(plan, store, 7, dates.get)
            self.assertEqual((bound.query.at.known, bound.query.at.valid), (known, "2026-03-06"))
            # Hamburg (v4) is past-dated, so the latest claim valid on 2026-03-06 is Cologne
            self.assertEqual([a.values for a in result.answers], [(Value("Cologne"),)])

    def test_anchor_that_matches_nothing_falls_back(self):
        main = "SELECT ?o WHERE { (user, livesIn, ?o) AS ?c } AT(state=historical)"
        anchor = "SELECT ?x WHERE { (k1, selectedService, ?x) [user, reject] }"
        p, _ = planner(Scripted(reply(out(main, anchor={"ir": anchor, "bind": ["valid"]}))),
                       self.tmp)
        plan, result = run_plan(p.plan(ctx("When you ...?")), build_store(), 7, lambda v: None)
        self.assertEqual((plan.route, plan.failure, result), ("fallback", "anchor", None))

    def test_summary_rates(self):
        good = "SELECT ?o WHERE { (Bogdan, speaksLanguage, ?o) }"
        transport = Scripted(reply("x"), reply(out(good)), reply("x"), reply("y"))
        p, _ = planner(transport, self.tmp)
        plans = [p.plan(ctx("Which languages does Bogdan speak?")),   # rule
                 p.plan(ctx("Tell me Bogdan's languages.")),          # parse -> repaired
                 p.plan(ctx("Tell me Bogdan's languages again."))]    # parse, parse -> fallback
        s = summarize(plans)
        self.assertEqual(s["routes"], {"rule": 1, "llm": 1, "fallback": 1})
        self.assertEqual((s["llm_planned_reads"], s["llm_calls"]), (2, 4))
        self.assertEqual((s["parse_failure_rate"], s["repair_rate"], s["repair_success"]),
                         (1.0, 1.0, 0.5))
        self.assertEqual((s["fallback_rate"], s["fallback_reasons"]), (0.3333, {"parse": 1}))

    def test_config_file_loads(self):
        config = PlannerConfig.load()
        self.assertEqual((config.max_compile_repairs, config.fallback_channels),
                         (1, ("bm25", "dense")))
        with self.assertRaises(ValueError):
            PlannerConfig(max_compile_repairs=2)


if __name__ == "__main__":
    unittest.main()


class NormalisationTest(unittest.TestCase):
    def test_current_exclusive_read_keeps_open_claims_and_latest(self):
        from grace.context.pipeline.query.grammar import parse
        from grace.context.pipeline.query.planner import normalise_current

        c = ctx("Where do I live?")
        q = normalise_current(parse("SELECT ?o WHERE { (user, livesIn, ?o) [_, inform] }"), c)
        text = to_text(q)
        self.assertIn('FILTER(end(?c) > "9999-12-31"^^date)', text)
        self.assertIn("LATEST BY version OF ?c", text)
        # the past-dated Hamburg claim (v4) is not the current value
        from grace.context.pipeline.query.execute import run
        self.assertEqual([a.values for a in run(q, build_store(), 7).answers],
                         [(Value("Cologne"),)])
        for unchanged in ("SELECT ?o WHERE { (Bogdan, speaksLanguage, ?o) }",   # multi-valued
                          "SELECT ?o WHERE { (user, livesIn, ?o) } AT(state=historical)",
                          "SELECT COUNT(DISTINCT ?o) WHERE { (user, livesIn, ?o) }"):
            with self.subTest(q=unchanged):
                self.assertEqual(normalise_current(parse(unchanged), c), parse(unchanged))

    def test_window_replaces_start_filters_written_by_the_llm(self):
        from grace.context.pipeline.query.grammar import parse
        from grace.context.pipeline.query.planner import apply_window

        q = parse('SELECT ?t WHERE { (user, tookTrip, ?t) AS ?c '
                  'FILTER(start(?c) >= "2026-04-01"^^date) }')
        out = apply_window(q, resolve_window("last month", "2026-06-15"), "?c")
        text = to_text(out)
        self.assertNotIn("2026-04-01", text)
        self.assertEqual(text.count("start(?c)"), 2)
        self.assertTrue(out.temporary)
