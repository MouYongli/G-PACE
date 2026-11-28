"""Evidence-driven assembly (T026, plan 5.5): demand, filter, selection, expansion, layout, and
the budget guarantee `context.tokens == count(context.text) <= budget` with a matching ledger."""

from __future__ import annotations

import random
import unittest
from pathlib import Path

from grace.config.paths import REPO_ROOT
from grace.context import api
from grace.context.memory.history.log import MessageLog
from grace.context.pipeline.assembly import layout
from grace.context.pipeline.assembly.assemble import Assembler, AssemblyConfig
from grace.context.pipeline.assembly.demand import ANSWER, Support, Variable, demand_of, terms
from grace.context.pipeline.assembly.expand import Expansion, expand_summary
from grace.context.pipeline.assembly.filter import Constraints, filter_items, overlaps
from grace.context.pipeline.assembly.items import (
    Item,
    answer_items,
    history_items,
    message_item,
)
from grace.context.pipeline.assembly.select import greedy, truncate, units_of

BUDGETS = (256, 512, 1024)
CONFIGS = REPO_ROOT / "configs" / "assembly"


def words(text: str) -> int:
    return len(text.split())


def chars(text: str) -> int:
    """A counter that is not additive over lines (like a real tokenizer at joins)."""
    return (len(text) + 3) // 4


def task(version: int, read: str = "q1") -> api.ReadTask:
    return api.ReadTask("locomo", "dev", "h", f"{read}@{version}", read, version, "question",
                        "When does the accepted train arrive?", None, None, None)


def msg(version: int, text: str, speaker: str = "A") -> api.Message:
    return api.Message("locomo", "dev", "h", version, f"D1:{version}", "S1", speaker, "user",
                       text, f"2023-05-0{1 + version % 9}", None)


def item(i: str, text: str, *, rank=None, version=1, **kw) -> Item:
    return Item(i, kw.pop("kind", "message"), text, (i,), (i,), version=version, rank=rank, **kw)


DEMAND = demand_of("Which train was accepted and when does it arrive?",
                   [("?train", "the accepted train"), ("?arrival", "arrival time of the train")])


def assembler(config: AssemblyConfig | None = None, count=words, log=None) -> Assembler:
    return Assembler(config or AssemblyConfig(), count, log=log, counter_name=count.__name__)


class DemandTest(unittest.TestCase):
    def test_planner_variables_and_fallback(self):
        self.assertEqual(DEMAND.names, ("train", "arrival"))
        fallback = demand_of("Where did Caroline move from?")
        self.assertEqual(fallback.names, (ANSWER,))
        self.assertEqual(fallback.variables[0].describes, "Where did Caroline move from?")
        with self.assertRaises(ValueError):
            demand_of("x", [("?a", "one"), ("a", "two")])

    def test_support_by_program_and_lexically(self):
        support = Support(0.5)
        bound = item("c1", "TR123", covers={"train"}, kind="claim")
        self.assertEqual(support.covers(bound, DEMAND.variables), {"train"})
        text = item("m1", "We accepted the 9am train, TR123.")
        self.assertEqual(support.covers(text, DEMAND.variables), {"train"})
        none = item("m2", "I like cats.")
        self.assertEqual(support.covers(none, DEMAND.variables), frozenset())
        self.assertEqual(terms("The trains arrived!"), {"train", "arriv"})


class FilterTest(unittest.TestCase):
    def test_every_drop_reason(self):
        c = Constraints(version=5, valid=("2023-05-01", "2023-05-31"), scopes=frozenset({"s1"}),
                        attribution=frozenset({"agent"}))
        items = [
            item("ok", "kept", version=5, valid=("2023-05-10", None), scope="s1",
                 attribution=("agent", "user")),
            item("late", "after the read", version=6),
            item("old", "superseded", version=2, retired=4),
            item("when", "outside window", valid=("2023-06-01", "2023-06-30")),
            item("where", "other scope", scope="s2"),
            item("who", "user only", attribution=("user",)),
            item("ok", "duplicate", rank=9),
            item("bare", "states nothing"),
        ]
        out = filter_items(items, c)
        self.assertEqual([i.item_id for i in out.kept], ["ok", "bare"])
        self.assertEqual(dict(out.dropped), {"late": "version", "old": "retired",
                                             "when": "valid", "where": "scope",
                                             "who": "attribution", "ok": "duplicate"})
        earlier = filter_items(items, Constraints(version=5, current_only=False))
        self.assertIn("old", [i.item_id for i in earlier.kept])

    def test_a_group_with_a_dropped_member_is_dropped_whole(self):
        items = [item("a", "first hop", version=2, group="p"),
                 item("b", "second hop", version=7, group="p"), item("c", "alone")]
        out = filter_items(items, Constraints(version=5))
        self.assertEqual([i.item_id for i in out.kept], ["c"])
        self.assertEqual(dict(out.dropped), {"b": "version", "a": "group"})

    def test_valid_time_must_be_iso(self):
        for bad in (("May 2023", None), ("2023-13-01", None), (None, 20230501),
                    ("20230501", None), ("2023-W19", None), ("2023-121", None),
                    ("2023-05-01T1015", None)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                item("x", "t", valid=bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Constraints(version=1, valid=bad)
        item("x", "t", valid=("2023-05-01", "2023-05-02T10:15:00Z"))

    def test_overlaps(self):
        self.assertTrue(overlaps(("2023-05-01", "2023-05-02"), ("2023-05-02T10:00", None)))
        self.assertFalse(overlaps(("2023-05-01", "2023-05-02"), ("2023-05-03", None)))
        self.assertTrue(overlaps((None, None), ("2023-05-03", "2023-05-04")))


class SelectTest(unittest.TestCase):
    def units(self, items, covers):
        return units_of(items, lambda i: words(layout.line(i)) + 1,
                        lambda i: frozenset(covers.get(i.item_id, ())))

    def test_greedy_prefers_coverage_per_token_and_fills_by_rank(self):
        items = [item("long", "train " * 30, rank=1), item("short", "TR123 at ten", rank=2),
                 item("other", "unrelated words", rank=3)]
        units = self.units(items, {"long": {"train"}, "short": {"train", "arrival"}})
        chosen = greedy(units, ["train", "arrival"], 100, fill=False)
        self.assertEqual([u.unit_id for u in chosen], ["short"])
        filled = greedy(units, ["train", "arrival"], 100, fill=True)
        self.assertEqual([u.unit_id for u in filled], ["short", "long", "other"])

    def test_two_hop_path_is_taken_whole_or_not_at_all(self):
        items = [item("a", "x " * 10, rank=1, group="p"), item("b", "y " * 10, rank=2, group="p"),
                 item("c", "z", rank=3)]
        units = self.units(items, {"a": {"train"}, "b": {"arrival"}})
        self.assertEqual(len(units), 2)
        small = greedy(units, ["train", "arrival"], 15)
        self.assertEqual([u.unit_id for u in small], ["c"])
        big = greedy(units, ["train", "arrival"], 40)
        self.assertEqual([i.item_id for u in big for i in u.items], ["a", "b", "c"])

    def test_truncate_skips_what_does_not_fit_and_keeps_filling_in_rank_order(self):
        items = [item("r2", "two", rank=2), item("r1", "one", rank=1),
                 item("r3", "w " * 50, rank=3), item("r4", "four", rank=4),
                 Item("r5", "retrieved", "chunk of one and two", ("r1", "r2"), ("r1", "r2"),
                      rank=5)]
        units = self.units(items, {})
        # same fill rule as greedy: r3 does not fit, r5 shows nothing new
        self.assertEqual([u.unit_id for u in truncate(units, 20)], ["r1", "r2", "r4"])
        self.assertEqual([u.unit_id for u in truncate(units, 200, k=1)], ["r1"])
        fill = greedy(units, [], 20)  # no demand: greedy is the fill alone
        self.assertEqual([u.unit_id for u in fill], ["r1", "r2", "r4"])


class LayoutTest(unittest.TestCase):
    def test_sections_order_citations_and_fragments(self):
        items = [
            item("D1:5", "B: later evidence", version=5, timestamp="2023-05-05"),
            item("D1:2", "A: earlier evidence", version=2),
            Item("v1", "view", "The accepted train is TR123.", ("D1:2#char=0,5", "D1:5"),
                 version=5),
            item("D1:9", "A: hello", version=9, section="recent"),
        ]
        out = layout.serialise(items, [Variable("arrival", "arrival time of the train")])
        self.assertEqual(out.text.splitlines(), [
            "Recent messages:", "[D1:9] A: hello",
            "Verified state:", "[D1:2, D1:5] The accepted train is TR123.",
            "Evidence:", "[D1:2] A: earlier evidence", "[D1:5] (2023-05-05) B: later evidence",
            "Open items (not found in memory):", "- arrival time of the train"])
        frags = layout.fragments(out, words)
        view = next(f for f in frags if f.fragment_id == "v1")
        self.assertEqual((view.kind, view.evidence_ids, view.source_ids),
                         ("view", ("D1:2", "D1:5"), ()))
        self.assertEqual(layout.serialise([]).text, layout.EMPTY)


class AssemblerTest(unittest.TestCase):
    def pool(self, seed: int, n: int = 40) -> list[Item]:
        rng = random.Random(seed)
        vocab = ["train", "arrival", "time", "accepted", "cat", "music", "ten", "TR123", "noon"]
        out = []
        for i in range(n):
            text = " ".join(rng.choice(vocab) for _ in range(rng.randint(3, 60)))
            group = f"g{i // 2}" if rng.random() < 0.2 else None
            out.append(item(f"D2:{i}", text, rank=rng.randint(1, n), version=rng.randint(1, 9),
                            group=group))
        return out

    def test_budget_is_never_exceeded_and_tokens_match_the_ledger(self):
        for count in (words, chars):
            for name in ("default.yaml", "truncate.yaml"):
                config = AssemblyConfig.load(CONFIGS / name)
                a = assembler(config, count)
                for seed in range(15):
                    for budget in BUDGETS:
                        with self.subTest(count=count.__name__, config=name, seed=seed,
                                          budget=budget):
                            result = a.assemble(task(9), DEMAND, self.pool(seed), budget)
                            ctx = result.context
                            self.assertEqual(ctx.tokens, count(ctx.text))
                            self.assertLessEqual(ctx.tokens, budget)
                            self.assertEqual(ctx.budget_tokens, budget)
                            ledger = result.ledger
                            self.assertEqual(ledger.total, ctx.tokens)
                            self.assertEqual(sum(ledger.fragments.values()) + ledger.layout,
                                             ctx.tokens)
                            self.assertEqual(set(ledger.fragments),
                                             {f.fragment_id for f in ctx.fragments})
                            for f in ctx.fragments:
                                self.assertEqual(f.tokens, count(f.text))
                                self.assertIn(f.text, ctx.text)

    def test_budget_with_the_pinned_qwen3_tokenizer(self):
        from grace.llm.tokens import HFTokenCounter, TokenizerPinError
        try:
            counter = HFTokenCounter.from_model_config(
                REPO_ROOT / "configs" / "models" / "qwen3-8b.yaml")
        except (TokenizerPinError, ImportError) as exc:
            self.skipTest(f"Qwen3-8B tokenizer not available: {exc}")
        a = Assembler(AssemblyConfig(), counter.count_text, counter_name=counter.name)
        for seed in range(5):
            for budget in BUDGETS:
                ctx = a.assemble(task(9), DEMAND, self.pool(seed), budget).context
                self.assertEqual(ctx.tokens, counter.count_text(ctx.text))
                self.assertLessEqual(ctx.tokens, budget)

    def test_larger_budgets_show_at_least_as_much(self):
        a = assembler()
        sizes = [len(a.assemble(task(9), DEMAND, self.pool(3), b).context.fragments)
                 for b in BUDGETS]
        self.assertEqual(sizes, sorted(sizes))

    def test_full_history_shows_every_filtered_item(self):
        log = MessageLog("h")
        for v in range(1, 6):
            log.append(msg(v, f"message number {v}"))
        a = assembler(log=log)
        result = a.assemble(task(4), DEMAND, history_items(log, 5), None)
        self.assertIsNone(result.context.budget_tokens)
        self.assertEqual(result.context.context_ids, ["D1:1", "D1:2", "D1:3", "D1:4"])
        self.assertEqual(dict(result.dropped), {"D1:5": "version"})
        self.assertIsNone(result.pending)

    def test_greedy_covers_the_demand_where_truncation_does_not(self):
        noise = [item(f"n{i}", "chat " * 48, rank=i) for i in range(1, 6)]
        train = item("t", "We accepted train TR123.", rank=7, covers={"train"})
        arrival = item("r", "It arrives at 10:15, arrival time confirmed.", rank=8)
        pool = [*noise, train, arrival]
        main = assembler().assemble(task(9), DEMAND, pool, 256)
        self.assertEqual(set(main.covered), {"train", "arrival"})
        self.assertIn("t", [f.fragment_id for f in main.context.fragments])
        self.assertIsNone(main.pending)
        contrast = assembler(AssemblyConfig.load(CONFIGS / "truncate.yaml")).assemble(
            task(9), DEMAND, pool, 256)
        self.assertEqual(contrast.open, DEMAND.variables)
        self.assertIsNone(contrast.expansion)

    def test_open_variable_yields_one_query_expansion(self):
        pool = [item("t", "We accepted train TR123.", rank=1)]
        a = assembler()
        first = a.assemble(task(9), DEMAND, pool, 256)
        self.assertEqual([v.name for v in first.open], ["arrival"])
        self.assertIn("Open items (not found in memory):", first.context.text)
        self.assertEqual(first.pending, Expansion("query", (DEMAND.variable("arrival"),),
                                                  query="arrival time of the train"))
        self.assertTrue(first.retrieval_used)
        self.assertEqual(first.expansions_used, 1)
        found = answer_items(_Result(("arrival",), [_Answer(("10:15",), ("D1:7",))]),
                             prefix="q", version_of=lambda m: 7, stamp_of=STAMPS.get,
                             retired_of=lambda c: None)
        second = a.assemble(task(9), DEMAND, pool + found, 256, expansions_used=1,
                            retrieval_used=True)
        self.assertEqual(second.open, ())
        self.assertIsNone(second.expansion)
        self.assertTrue(second.retrieval_used)
        self.assertIn("[D1:7] arrival = 10:15", second.context.text)
        self.assertIn("q1", [f.fragment_id for f in second.context.fragments])

    def test_no_query_once_the_reads_retrieval_is_spent(self):
        pool = [item("t", "We accepted train TR123.", rank=1)]
        result = assembler().assemble(task(9), DEMAND, pool, 256, retrieval_used=True)
        self.assertEqual([v.name for v in result.open], ["arrival"])
        self.assertIsNone(result.expansion)
        self.assertEqual(result.expansions_used, 0)

    def test_no_query_when_a_supporting_candidate_only_did_not_fit(self):
        pool = [item("t", "We accepted train TR123.", rank=1),
                item("r", "arrival time " + "of the train " * 60, rank=2)]
        result = assembler().assemble(task(9), DEMAND, pool, 64)
        self.assertEqual([v.name for v in result.open], ["arrival"])
        self.assertIsNone(result.expansion)
        self.assertFalse(result.retrieval_used)

    def test_truncation_never_expands(self):
        pool = [item("t", "We accepted train TR123.", rank=1)]
        result = assembler(AssemblyConfig.load(CONFIGS / "truncate.yaml")).assemble(
            task(9), DEMAND, pool, 256)
        self.assertEqual([v.name for v in result.open], ["arrival"])
        self.assertIsNone(result.expansion)
        self.assertFalse(result.retrieval_used)

    def test_utilisation_and_expansions_are_recorded(self):
        result = assembler().assemble(task(9), DEMAND, self.pool(2), 512)
        record = result.to_record()
        self.assertEqual(record["utilisation"], result.context.tokens / 512)
        self.assertIn("expansions_used", record)
        self.assertIn("retrieval_used", record)
        full = assembler().assemble(task(9), DEMAND, self.pool(2), None)
        self.assertIsNone(full.utilisation)

    def test_summary_expands_into_raw_messages_from_the_log(self):
        log = MessageLog("h")
        log.append(msg(1, "We accepted train TR123."))
        log.append(msg(2, "TR123 arrival time is 10:15."))
        summary = Item("s1", "summary", "Travel plans were discussed.",
                       ("D1:1", "D1:2"), (), version=2, rank=1,
                       expands_to=("D1:1", "D1:2", "D1:1"))
        result = assembler(log=log).assemble(task(2), DEMAND, [summary], 256)
        self.assertTrue(result.expansion_done)
        self.assertEqual(result.expansion.kind, "summary")
        self.assertEqual(result.expansions_used, 1)
        self.assertFalse(result.retrieval_used)
        self.assertEqual(result.context.context_ids, ["D1:1", "D1:2"])
        self.assertNotIn("s1", [f.fragment_id for f in result.context.fragments])
        self.assertEqual(result.open, ())

    def test_rejected_summary_still_queries_unsupported_variables(self):
        """Review follow-up: a fitting summary whose expansion is not strictly better is kept,
        and the variables no candidate supports still get the one query."""
        log = MessageLog("h")
        log.append(msg(1, "short note"))
        log.append(msg(2, "the arrival time is 10:15"))
        summary = Item("s1", "summary", "summary: the accepted train is TR123", ("D1:1",),
                       version=2, rank=1, covers={"train"}, expands_to=("D1:1", "D1:2"))
        demand = demand_of("q", [("train", "accepted train"), ("arrival", "arrival time"),
                                 ("platform", "departure platform")])
        result = assembler(log=log).assemble(task(2), demand, [summary], 100)
        self.assertEqual(result.covered, ("train",))
        self.assertFalse(result.expansion_done)
        self.assertEqual(result.pending.kind, "query")
        self.assertEqual([v.name for v in result.pending.variables], ["arrival", "platform"])
        self.assertTrue(result.retrieval_used)

    def test_summary_is_kept_when_its_raw_text_does_not_fit(self):
        """Regression (review of f5fbe64): budget 100, the summary covers ?train, ?arrival is
        only in ~300 words of raw text. Expanding would lose ?train and spend the expansion."""
        log = MessageLog("h")
        log.append(msg(1, "We talked a lot. " + "blah " * 150))
        log.append(msg(2, "Arrival time of the train is 10:15. " + "more " * 150))
        summary = Item("s1", "summary", "The accepted train is TR123.", ("D1:1", "D1:2"), (),
                       version=2, rank=1, covers={"train"}, expands_to=("D1:1", "D1:2"))
        result = assembler(log=log).assemble(task(2), DEMAND, [summary], 100)
        self.assertLessEqual(result.context.tokens, 100)
        self.assertIn("s1", [f.fragment_id for f in result.context.fragments])
        self.assertEqual(result.covered, ("train",))
        self.assertFalse(result.expansion_done)
        self.assertNotEqual(getattr(result.expansion, "kind", None), "summary")

    def test_expanded_messages_do_not_inherit_the_summarys_coverage(self):
        log = MessageLog("h")
        log.append(msg(1, "ok, thanks"))
        summary = Item("s1", "summary", "Plans.", ("D1:1",), (), version=1, rank=1,
                       covers={"train"}, expands_to=("D1:1",))
        raw = expand_summary(summary, log, 1)
        self.assertEqual([i.covers for i in raw], [frozenset()])
        self.assertEqual(Support().covers(raw[0], DEMAND.variables), frozenset())

    def test_answer_items_stamp_versions_and_retirement(self):
        result = _Result(("train",), [
            _Answer(("TR1",), ("D1:2#char=0,5",), [_Witness(("c1",), ("a1",))]),
            _Answer(("TR2",), ("D1:1",), [_Witness(("c2",)), _Witness(("c3",))])])
        items = answer_items(result, prefix="q", version_of={"D1:1": 1, "D1:2": 2}.get,
                             stamp_of=STAMPS.get, retired_of={"c1": 8, "c2": 6}.get)
        self.assertEqual([(i.version, i.retired) for i in items], [(4, 8), (3, None)])
        self.assertEqual(items[0].covers, {"train"})
        with self.assertRaises(ValueError):
            answer_items(result, prefix="q", version_of={"D1:1": 1}.get, stamp_of=STAMPS.get,
                         retired_of=lambda c: None)
        with self.assertRaises(ValueError):
            answer_items(result, prefix="q", version_of={"D1:1": 1, "D1:2": 2}.get,
                         stamp_of={"c1": 1}.get, retired_of=lambda c: None)

    def test_recent_messages_come_first_and_are_not_repeated(self):
        log = MessageLog("h")
        for v in range(1, 5):
            log.append(msg(v, f"line {v} about the train"))
        a = assembler(AssemblyConfig(recent_messages=2), log=log)
        pool = [message_item(log.get(4), rank=1), message_item(log.get(1), rank=2)]
        result = a.assemble(task(4), DEMAND, pool, 256)
        lines = result.context.text.splitlines()
        self.assertEqual(lines[0], "Recent messages:")
        self.assertEqual(result.context.context_ids.count("D1:4"), 1)
        self.assertEqual(result.context.context_ids[:2], ["D1:3", "D1:4"])

    def test_messages_without_a_time_show_their_segment_time(self):
        history = api.HistoryInfo("locomo", "dev", "h", None, 1,
                                  (api.Segment("S1", 1, 1, "2023-05-08", None),))
        bare = api.Message("locomo", "dev", "h", 1, "D1:1", "S1", "A", "peer", "hi", None, None)
        self.assertEqual(layout.line(message_item(bare, history=history)),
                         "[D1:1] (2023-05-08) A: hi")
        self.assertEqual(layout.line(message_item(bare)), "[D1:1] A: hi")

    def test_tiny_budget_keeps_the_empty_marker(self):
        pool = [item("big", "word " * 100, rank=1)]
        result = assembler().assemble(task(9), DEMAND, pool, 16)
        self.assertLessEqual(result.context.tokens, 16)
        self.assertEqual(result.context.fragments, ())
        with self.assertRaises(ValueError):
            assembler().assemble(task(9), DEMAND, pool, 8)

    def test_constraints_must_match_the_read_version(self):
        with self.assertRaises(ValueError):
            assembler().assemble(task(9), DEMAND, [], 256, Constraints(version=8))

    def test_record_is_json_ready(self):
        import json
        result = assembler().assemble(task(9), DEMAND, self.pool(1), 256)
        record = json.loads(json.dumps(result.to_record()))
        self.assertEqual(record["ledger"]["total"], result.context.tokens)


STAMPS = {"c1": 2, "a1": 4, "c2": 3, "c3": 1}


class _Witness:
    def __init__(self, claims, attributions=()):
        self.claims, self.attributions = claims, attributions


class _Answer:
    def __init__(self, values, evidence, witnesses=()):
        self.values, self.evidence, self.witnesses = values, evidence, witnesses


class _Result:
    def __init__(self, variables, answers):
        self.variables, self.answers = variables, answers


class ConfigTest(unittest.TestCase):
    def test_config_files_load_and_reject_unknown_keys(self):
        for path in sorted(Path(CONFIGS).glob("*.yaml")):
            AssemblyConfig.load(path)
        with self.assertRaises(ValueError):
            AssemblyConfig.from_dict({"version": 1, "budget": 3})
        with self.assertRaises(ValueError):
            AssemblyConfig(max_expansions=2)


if __name__ == "__main__":
    unittest.main()
