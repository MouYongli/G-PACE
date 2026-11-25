"""Query planner of the read path (plan 5.3, 5.6; T023).

`Planner.plan(ctx)` turns one read task into a `Plan`:

1. **Rule templates** (`rules.py`). If a rule covers the task, its query is compiled and no LLM is
   called.
2. **Planner LLM** (call type `plan`, prompt `plan-query`). Otherwise the LLM receives the task,
   the relevant vocabulary fragment (predicates with their exclusivity and aliases, candidate
   entities, speakers) and the reference date, and returns JSON (`resources/schemas/llm/
   plan-query.json`): the IR text, the variables the answer needs, the fallback text channels,
   an optional time window and an optional anchor.
3. **Checks.** The output is parsed (JSON and schema, then the IR grammar), the time window is
   resolved to absolute dates, `now(...)` is resolved by `compile.absolutize`, the query is
   type-checked against the fragment and against the vocabulary fragment, and compiled.
4. **One compile repair.** If any check fails, the planner makes exactly one repair call (call type
   `repair`, prompt `plan-query-repair`) with the error message (plan 5.6: at most one
   compilation repair per read). If the repaired output fails too, or the LLM declines, or the
   call itself fails, the plan falls back to text retrieval over the fallback channels.

Relative time never reaches a stored view: a window resolved from a relative phrase, or a
`now(...)` comparison, is turned into absolute dates when the read is planned, and the query is
marked temporary (plan 3.3). `Plan.view_eligible` is False for such plans.

An **anchor** handles questions about what was known or true at an earlier event ("when you
offered me X, what did you have as my home city?"). The anchor is a second query that matches
the event; `bind_anchor` runs it at the version read, takes the version at which its single
witness became matched (the later of the claim's and the attribution's stamps; with several
witnesses, the earliest such version) and fixes `AT(known=k)` and/or `AT(valid=<date of k>)` of the
main query. The date of a version comes from the message log (`version_date`).

Retrieval and fusion (T025) consume `Plan.channels`; this module names the fallback channels and
does not run them.
"""

from __future__ import annotations

import datetime as _dt
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT
from grace.context.memory.graph.entries import Entity, Value
from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.query.compile import CompiledQuery, absolutize, compile_query
from grace.context.pipeline.query.execute import QueryExecutionError, execute
from grace.context.pipeline.query.grammar import parse, to_text
from grace.context.pipeline.query.ir import (
    At,
    Bound,
    Filter,
    Latest,
    LatestKey,
    Op,
    Query,
    QueryTypeError,
    ReadTime,
    State,
    ValidBound,
    Var,
    typecheck,
)
from grace.context.pipeline.query.result import QueryResult
from grace.context.pipeline.query.rules import EntityInfo, PredicateInfo, match_rules
from grace.context.pipeline.query.timeexpr import TimeExpressionError, Window, resolve_window
from grace.llm.client import ChatClient, LLMCallFailed
from grace.llm.prompts import PROMPTS_DIR, Prompt, load_pinned
from grace.llm.records import CallContext
from grace.llm.structured import SCHEMAS_DIR, load_schema
from grace.llm.structured import parse as parse_json

CONFIG_FILE = REPO_ROOT / "configs" / "common" / "planner.yaml"
PROMPT_REGISTRY = REPO_ROOT / "configs" / "common" / "prompts.yaml"
CHANNELS = ("bm25", "dense")
GRAPH = "graph"

# Routes of a plan, and the reasons a plan falls back to text retrieval.
ROUTES = ("rule", "llm", "fallback")
FAILURES = ("parse", "type", "time", "declined", "llm_error", "no_llm", "anchor")


class PlanError(ValueError):
    """One planner output failed a check; `kind` is parse, type or time."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# ---------------------------------------------------------------------------------------------
# Configuration and inputs


@dataclass(frozen=True)
class PlannerConfig:
    rules: bool = True
    prompt: str = "plan-query"
    repair_prompt: str = "plan-query-repair"
    schema: str = "plan-query"
    max_compile_repairs: int = 1
    fallback_channels: tuple[str, ...] = CHANNELS
    mode: str = "rdf11"
    decoding: Mapping[str, Any] = field(default_factory=lambda: {"temperature": 0.0,
                                                                 "max_tokens": 768})

    def __post_init__(self) -> None:
        if self.max_compile_repairs not in (0, 1):
            raise ValueError("plan 5.6 allows at most one compilation repair per read")
        if not self.fallback_channels or set(self.fallback_channels) - set(CHANNELS):
            raise ValueError(f"fallback_channels must be a non-empty subset of {CHANNELS}")

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> PlannerConfig:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping) or raw.get("version") != 1:
            raise ValueError(f"{path}: expected a mapping with version: 1")
        known = {"version", "rules", "prompt", "repair_prompt", "schema", "max_compile_repairs",
                 "fallback_channels", "mode", "decoding"}
        if unknown := sorted(set(raw) - known):
            raise ValueError(f"{path}: unknown keys {unknown}")
        values = {k: v for k, v in raw.items() if k != "version"}
        if "fallback_channels" in values:
            values["fallback_channels"] = tuple(values["fallback_channels"])
        return cls(**values)


@dataclass(frozen=True)
class PlanningContext:
    """What the planner may see for one read: the task and the relevant vocabulary fragment.

    `reference_date` is the read's `asked_at`, else the date of the last visible message; it
    anchors relative time. Nothing here comes from gold data.
    """

    history_id: str
    read_id: str
    version: int
    request: str
    reference_date: str | None
    predicates: tuple[PredicateInfo, ...] = ()
    entities: tuple[EntityInfo, ...] = ()
    speakers: tuple[str, ...] = ()
    kind: str = "question"

    @classmethod
    def from_task(cls, task, *, predicates: Sequence[PredicateInfo] = (),
                  entities: Sequence[EntityInfo] = (), speakers: Sequence[str] = (),
                  last_message_date: str | None = None) -> PlanningContext:
        """Context of a `context.api.ReadTask` (duck-typed to keep this module free of api)."""
        request = (task.question if task.kind == "question"
                   else f"State request: report the current state for {task.state_schema}")
        reference = task.asked_at[:10] if task.asked_at else last_message_date
        return cls(task.history_id, task.read_id, task.version, request, reference,
                   tuple(predicates), tuple(entities), tuple(speakers), task.kind)


@dataclass(frozen=True)
class Anchor:
    """A query matching an earlier event; `bind` lists what the event fixes (known, valid)."""

    query: Query
    bind: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """The planner's output for one read."""

    read_id: str
    route: str
    query: Query | None = None
    compiled: CompiledQuery | None = None
    anchor: Anchor | None = None
    window: Window | None = None
    variables: tuple[tuple[str, str], ...] = ()
    fallback_channels: tuple[str, ...] = CHANNELS
    rule: str | None = None
    failure: str | None = None
    failure_detail: str | None = None
    attempt_failures: tuple[str, ...] = ()  # kind of every failed LLM output, in order
    repairs: int = 0
    call_ids: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.route not in ROUTES:
            raise ValueError(f"unknown route {self.route!r}")
        if (self.route == "fallback") != (self.query is None):
            raise ValueError("a plan has a query iff it is not a fallback")
        if self.failure is not None and self.failure not in FAILURES:
            raise ValueError(f"unknown failure {self.failure!r}")

    @property
    def temporary(self) -> bool:
        return bool(self.query is not None and self.query.temporary)

    @property
    def view_eligible(self) -> bool:
        """Only a query that does not depend on the time of reading may define a view."""
        return self.query is not None and not self.query.temporary and self.anchor is None

    @property
    def channels(self) -> tuple[str, ...]:
        """Channels for retrieval (T025): the graph first when a query compiled."""
        return ((GRAPH,) if self.query is not None else ()) + self.fallback_channels

    def to_record(self) -> dict[str, Any]:
        return {
            "read_id": self.read_id, "route": self.route, "rule": self.rule,
            "ir": to_text(self.query) if self.query is not None else None,
            "anchor": ({"ir": to_text(self.anchor.query), "bind": list(self.anchor.bind)}
                       if self.anchor else None),
            "window": ({"phrase": self.window.phrase, "start": self.window.start,
                        "end": self.window.end, "relative": self.window.relative}
                       if self.window else None),
            "temporary": self.temporary, "view_eligible": self.view_eligible,
            "variables": [{"var": v, "describes": d} for v, d in self.variables],
            "channels": list(self.channels), "failure": self.failure,
            "failure_detail": self.failure_detail,
            "attempt_failures": list(self.attempt_failures), "repairs": self.repairs,
            "call_ids": list(self.call_ids), "reason": self.reason,
        }


# ---------------------------------------------------------------------------------------------
# Checks of one planner output


def _entities_of(query: Query) -> set[str]:
    out = set()
    patterns = list(query.where) + ([query.negation.pattern] if query.negation else [])
    for p in patterns:
        for term in (p.subject, p.object, p.attribution.speaker if p.attribution else None):
            if isinstance(term, Entity):
                out.add(term.id)
    filters = list(query.filters) + (list(query.negation.filters) if query.negation else [])
    out |= {f.right.id for f in filters if isinstance(f.right, Entity)}
    return out


def _predicates_of(query: Query) -> set[str]:
    patterns = list(query.where) + ([query.negation.pattern] if query.negation else [])
    return {p.predicate for p in patterns if isinstance(p.predicate, str)}


def check_vocabulary(query: Query, ctx: PlanningContext) -> None:
    """Every predicate and entity constant must come from the context (when it lists any)."""
    errors = []
    if ctx.predicates:
        allowed = {p.name for p in ctx.predicates}
        if bad := sorted(_predicates_of(query) - allowed):
            errors.append(f"unknown predicates {bad}; use one of {sorted(allowed)}")
    if ctx.entities:
        allowed = {e.id for e in ctx.entities} | set(ctx.speakers)
        if bad := sorted(_entities_of(query) - allowed):
            errors.append(f"unknown entity IDs {bad}; use IDs from the entity list")
    if errors:
        raise PlanError("type", "; ".join(errors))


def apply_window(query: Query, window: Window, label: str) -> Query:
    """Add `start(label) >= start` and `start(label) < end`; mark relative windows temporary."""
    var = Var(label.lstrip("?"))
    if var not in {p.label for p in query.where}:
        raise PlanError("type", f"time_window label {label} names no pattern; add AS {label} to "
                                "the pattern whose valid time is restricted")
    filters = (Filter(ValidBound(var, Bound.START), Op.GE, Value(window.start, "date")),
               Filter(ValidBound(var, Bound.START), Op.LT, Value(window.end, "date")))
    # the resolved window is authoritative: start filters of the same claim written by the LLM
    # (possibly computed from the relative phrase) are replaced, not combined
    kept = tuple(f for f in query.filters
                 if not (isinstance(f.left, ValidBound) and f.left.label == var
                         and f.left.bound is Bound.START))
    out = replace(query, filters=kept + filters)
    return replace(out, temporary=True) if window.relative else out


OPEN_END = "9999-12-31"


def normalise_current(query: Query, ctx: PlanningContext) -> Query:
    """Deterministic form of a current-state read of one exclusive predicate (plan 3.2, 5.2).

    For a query with one positive pattern whose predicate the context lists as exclusive, that
    reads the current state (`state=current`, no `AT(valid=...)`, no time window, no count):
    keep only claims whose valid time is still open (`end(?c) > "9999-12-31"`; the fragment has
    no "end unset" test) and select the latest by version. A past-dated claim ("I lived in
    Bremen until 2017") is then never the current value. Other queries are returned unchanged.
    """
    exclusive = {p.name for p in ctx.predicates if p.exclusive}
    if (len(query.where) != 1 or query.count is not None or query.at.valid is not None
            or query.at.state is not State.CURRENT):
        return query
    pattern = query.where[0]
    if not isinstance(pattern.predicate, str) or pattern.predicate not in exclusive:
        return query
    if any(isinstance(f.left, ValidBound) for f in query.filters):
        return query
    label = pattern.label or Var("c")
    if pattern.label is None:
        if label in pattern.variables():
            return query
        pattern = replace(pattern, label=label)
    end = Filter(ValidBound(label, Bound.END), Op.GT, Value(OPEN_END, "date"))
    latest = query.latest or Latest(label, LatestKey.VERSION)
    return replace(query, where=(pattern,), filters=tuple(query.filters) + (end,),
                   latest=latest)


def _has_read_time(query: Query) -> bool:
    filters = list(query.filters) + (list(query.negation.filters) if query.negation else [])
    return any(isinstance(f.right, ReadTime) for f in filters)


# Hints appended to parse errors that planner LLMs make often; they go into the repair message.
_HINTS = (
    ("only one NOT EXISTS", "Use a single NOT EXISTS. To exclude every reply of a speaker, leave "
                            "the function open, e.g. NOT EXISTS { (k, p, ?o) [user, _] }."),
    ("found 'FILTER'", "FILTER(...) must stand inside the braces of WHERE { ... }."),
    ("found 'OPTIONAL'", "OPTIONAL is not available; drop the optional part."),
)


def _hint(message: str) -> str:
    extra = [h for key, h in _HINTS if key in message]
    return message + (" Hint: " + " ".join(extra) if extra else "")


def _parse_ir(text: str, what: str) -> Query:
    try:
        return parse(text, check=False)
    except QueryTypeError as exc:
        raise PlanError("parse", _hint(f"{what}: {exc}")) from None
    except (ValueError, TypeError) as exc:
        raise PlanError("parse", f"{what}: {type(exc).__name__}: {exc}") from None


def _check(query: Query, ctx: PlanningContext, mode: str, what: str) -> CompiledQuery:
    try:
        typecheck(query)
    except QueryTypeError as exc:
        raise PlanError("type", f"{what}: {exc}") from None
    check_vocabulary(query, ctx)
    try:
        return compile_query(query, mode)
    except (QueryTypeError, ValueError) as exc:
        raise PlanError("type", f"{what}: {exc}") from None


@dataclass(frozen=True)
class Interpreted:
    query: Query | None
    compiled: CompiledQuery | None
    anchor: Anchor | None
    window: Window | None
    variables: tuple[tuple[str, str], ...]
    fallback_channels: tuple[str, ...]
    reason: str | None


def interpret(value: Mapping[str, Any], ctx: PlanningContext, *, mode: str = "rdf11",
              default_channels: tuple[str, ...] = CHANNELS) -> Interpreted:
    """Turn one schema-valid planner output into a compiled query, or raise `PlanError`."""
    channels = tuple(value.get("fallback_channels") or default_channels)
    reason = value.get("reason")
    if value.get("ir") is None:
        return Interpreted(None, None, None, None, (), channels, reason or "declined")
    query = _parse_ir(value["ir"], "ir")
    window = None
    if tw := value.get("time_window"):
        try:
            window = resolve_window(tw["phrase"], ctx.reference_date)
        except TimeExpressionError as exc:
            raise PlanError("time", f"time_window: {exc}") from None
        query = apply_window(query, window, tw["label"])
    if window is None:
        query = normalise_current(query, ctx)
    if _has_read_time(query):
        if ctx.reference_date is None:
            raise PlanError("time", "now(...) needs a reference date and the read has none")
        query = absolutize(query, _dt.date.fromisoformat(ctx.reference_date))
    compiled = _check(query, ctx, mode, "ir")
    anchor = None
    if a := value.get("anchor"):
        anchor_query = _parse_ir(a["ir"], "anchor")
        _check(anchor_query, ctx, mode, "anchor")
        anchor = Anchor(anchor_query, tuple(a["bind"]))
        if "known" in anchor.bind and query.at.known is not None:
            raise PlanError("type", "anchor binds known, but the query fixes AT(known=...)")
    answer_vars = {f"?{v.name}" for v in query.select}
    if query.count is not None:
        answer_vars.add(f"?{query.count.var.name}")
    variables = tuple((v["var"], v["describes"]) for v in value.get("variables") or ())
    if bad := sorted({v for v, _ in variables} - answer_vars):
        raise PlanError("type", f"variables {bad} are not selected or counted by the query")
    return Interpreted(query, compiled, anchor, window, variables, channels, reason)


# ---------------------------------------------------------------------------------------------
# Planner


def _lines_predicates(predicates: Sequence[PredicateInfo]) -> str:
    out = []
    for p in predicates:
        parts = ["exclusive" if p.exclusive else "multi-valued"]
        if p.aliases:
            parts.append("aliases: " + ", ".join(p.aliases))
        if p.description:
            parts.append(p.description)
        out.append(f"- {p.name} ({'; '.join(parts)})")
    return "\n".join(out) or "(none)"


def _lines_entities(entities: Sequence[EntityInfo]) -> str:
    out = []
    for e in entities:
        names = ", ".join(e.names) if e.names else e.id
        out.append(f"- {e.id}: {names}" + (f" [{e.kind}]" if e.kind else ""))
    return "\n".join(out) or "(none)"


class Planner:
    """Rule templates first, then the planner LLM with one compile repair, then fallback."""

    def __init__(self, config: PlannerConfig | None = None, client: ChatClient | None = None, *,
                 registry: Path = PROMPT_REGISTRY, prompts_root: Path = PROMPTS_DIR,
                 schemas_root: Path = SCHEMAS_DIR):
        self.config = config or PlannerConfig()
        self.client = client
        self.prompt: Prompt = load_pinned(self.config.prompt, registry, root=prompts_root)
        self.repair_prompt: Prompt = load_pinned(self.config.repair_prompt, registry,
                                                 root=prompts_root)
        self.validator = load_schema(self.config.schema, schemas_root)

    def messages(self, ctx: PlanningContext) -> list[dict[str, str]]:
        return self.prompt.render(
            predicates=_lines_predicates(ctx.predicates),
            entities=_lines_entities(ctx.entities),
            speakers=", ".join(ctx.speakers) or "(none)",
            reference_date=ctx.reference_date or "unknown",
            request=ctx.request)

    def _fallback(self, ctx: PlanningContext, failure: str, detail: str | None, **kw) -> Plan:
        return Plan(ctx.read_id, "fallback", failure=failure, failure_detail=detail,
                    fallback_channels=kw.pop("channels", self.config.fallback_channels), **kw)

    def plan(self, ctx: PlanningContext) -> Plan:
        if self.config.rules and ctx.kind == "question":
            hit = match_rules(ctx.request, ctx.entities, ctx.predicates)
            if hit is not None:
                try:
                    compiled = _check(hit.query, ctx, self.config.mode, "rule")
                except PlanError:
                    compiled = None  # a rule that does not compile is left to the LLM
                if compiled is not None:
                    return Plan(ctx.read_id, "rule", hit.query, compiled, rule=hit.rule,
                                variables=hit.variables,
                                fallback_channels=self.config.fallback_channels)
        if self.client is None:
            return self._fallback(ctx, "no_llm", "no rule covers the task and no planner LLM "
                                                 "is configured")
        return self._plan_llm(ctx)

    def _call(self, messages, ctx: PlanningContext, call_type: str, prompt: Prompt):
        context = CallContext(call_type=call_type, trigger="read", history_id=ctx.history_id,
                              read_id=ctx.read_id, version=ctx.version)
        return self.client.chat(messages, context, prompt_sha256=prompt.sha256,
                                decoding=self.config.decoding,
                                validate=lambda text: parse_json(text, self.validator).error)

    def _attempt(self, text: str | None, ctx: PlanningContext) -> Interpreted:
        parsed = parse_json(text, self.validator)
        if not parsed.ok:
            raise PlanError("parse", f"output is not valid planner JSON: {parsed.error}")
        return interpret(parsed.value, ctx, mode=self.config.mode,
                         default_channels=self.config.fallback_channels)

    def _plan_llm(self, ctx: PlanningContext) -> Plan:
        messages = self.messages(ctx)
        call_ids: list[str] = []
        failures: list[str] = []
        try:
            result = self._call(messages, ctx, "plan", self.prompt)
        except LLMCallFailed as exc:
            return self._fallback(ctx, "llm_error", str(exc),
                                  call_ids=tuple(r.call_id for r in exc.records))
        call_ids.append(result.call_id)
        text = result.text
        error: PlanError | None = None
        try:
            got = self._attempt(text, ctx)
        except PlanError as exc:
            error = exc
            failures.append(exc.kind)
        repairs = 0
        if error is not None and self.config.max_compile_repairs >= 1:
            repairs = 1
            repair_messages = [*messages, {"role": "assistant", "content": text or ""},
                               *self.repair_prompt.render(error=str(error))]
            try:
                result = self._call(repair_messages, ctx, "repair", self.repair_prompt)
            except LLMCallFailed as exc:
                return self._fallback(ctx, "llm_error", str(exc), repairs=1,
                                      attempt_failures=tuple(failures),
                                      call_ids=tuple(call_ids)
                                      + tuple(r.call_id for r in exc.records))
            call_ids.append(result.call_id)
            try:
                got = self._attempt(result.text, ctx)
                error = None
            except PlanError as exc:
                error = exc
                failures.append(exc.kind)
        if error is not None:
            return self._fallback(ctx, error.kind, str(error), repairs=repairs,
                                  attempt_failures=tuple(failures), call_ids=tuple(call_ids))
        if got.query is None:
            return self._fallback(ctx, "declined", got.reason, repairs=repairs,
                                  attempt_failures=tuple(failures), call_ids=tuple(call_ids),
                                  channels=got.fallback_channels, reason=got.reason)
        return Plan(ctx.read_id, "llm", got.query, got.compiled, got.anchor, got.window,
                    got.variables, got.fallback_channels, repairs=repairs,
                    attempt_failures=tuple(failures), call_ids=tuple(call_ids),
                    reason=got.reason)


# ---------------------------------------------------------------------------------------------
# Anchors and execution


def anchor_version(result: QueryResult, store: ClaimStore, cutoff: int) -> int:
    """The version at which the anchor's event happened (see the module docstring)."""
    if not result.answers:
        raise QueryExecutionError("the anchor matches no event")
    if len(result.answers) > 1:
        raise QueryExecutionError(f"the anchor matches {len(result.answers)} events; it must "
                                  "identify one")
    state = store.state(cutoff)
    entries = {**state.claims, **state.attributions}
    versions = []
    for witness in result.answers[0].witnesses:
        ids = (*witness.claims, *witness.attributions)
        versions.append(max(entries[i].version for i in ids))
    if not versions:
        raise QueryExecutionError("the anchor has no witness")
    return min(versions)


def bind_anchor(plan: Plan, store: ClaimStore, version: int,
                version_date: Callable[[int], str | None] | None = None) -> Plan:
    """Resolve the anchor of `plan` on `store` at `version`; a failure falls back to text."""
    if plan.anchor is None or plan.query is None:
        return plan
    try:
        anchor = execute(compile_query(plan.anchor.query, store.mode), store, version)
        k = anchor_version(anchor, store, anchor.cutoff)
        at = plan.query.at
        known, valid = at.known, at.valid
        if "known" in plan.anchor.bind:
            known = k
        if "valid" in plan.anchor.bind:
            date = version_date(k) if version_date else None
            if not date:
                raise QueryExecutionError(f"no date is known for version {k}")
            valid = date[:10]
        query = replace(plan.query, at=At(known=known, valid=valid, state=at.state))
        compiled = compile_query(query, store.mode)
    except (QueryExecutionError, QueryTypeError, ValueError) as exc:
        return Plan(plan.read_id, "fallback", failure="anchor", failure_detail=str(exc),
                    fallback_channels=plan.fallback_channels, repairs=plan.repairs,
                    attempt_failures=plan.attempt_failures, call_ids=plan.call_ids)
    return replace(plan, query=query, compiled=compiled)


def run_plan(plan: Plan, store: ClaimStore, version: int,
             version_date: Callable[[int], str | None] | None = None
             ) -> tuple[Plan, QueryResult | None]:
    """Bind the anchor and execute the plan's query at `version`; a fallback runs nothing.

    An execution error turns the plan into a fallback (failure `anchor` for anchors, else the
    query is reported as a `type` failure detected at execution).
    """
    plan = bind_anchor(plan, store, version, version_date)
    if plan.query is None:
        return plan, None
    try:
        return plan, execute(plan.compiled, store, version)
    except QueryExecutionError as exc:
        return (Plan(plan.read_id, "fallback", failure="type", failure_detail=str(exc),
                     fallback_channels=plan.fallback_channels, repairs=plan.repairs,
                     attempt_failures=plan.attempt_failures, call_ids=plan.call_ids), None)


# ---------------------------------------------------------------------------------------------
# Rates


def summarize(plans: Sequence[Plan]) -> dict[str, Any]:
    """Route shares, parse-failure, type-failure, repair and fallback rates of a set of plans.

    - `parse_failure_rate`: share of LLM-planned reads whose first output failed to parse (JSON,
      schema or IR grammar); `type_failure_rate` and `time_failure_rate` likewise;
    - `repair_rate`: share of LLM-planned reads that used the one repair, and `repair_success`
      the share of those that then compiled;
    - `fallback_rate`: share of all reads planned as text retrieval, with the reasons.
    """
    n = len(plans)
    llm = [p for p in plans if p.call_ids or p.failure in ("llm_error",)]
    first = Counter(p.attempt_failures[0] for p in llm if p.attempt_failures)
    repaired = [p for p in llm if p.repairs]

    def rate(k: int, d: int) -> float | None:
        return round(k / d, 4) if d else None

    fallbacks = Counter(p.failure for p in plans if p.route == "fallback")
    return {
        "reads": n,
        "routes": dict(Counter(p.route for p in plans)),
        "rule_rate": rate(sum(p.route == "rule" for p in plans), n),
        "llm_planned_reads": len(llm),
        "llm_calls": sum(len(p.call_ids) for p in plans),
        "parse_failure_rate": rate(first["parse"], len(llm)),
        "type_failure_rate": rate(first["type"], len(llm)),
        "time_failure_rate": rate(first["time"], len(llm)),
        "repair_rate": rate(len(repaired), len(llm)),
        "repair_success": rate(sum(p.route != "fallback" for p in repaired), len(repaired)),
        "fallback_rate": rate(sum(fallbacks.values()), n),
        "fallback_reasons": dict(fallbacks),
        "temporary_rate": rate(sum(p.temporary for p in plans), n),
    }
