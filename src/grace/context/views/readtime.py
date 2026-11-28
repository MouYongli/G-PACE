"""Read-time view content sources for ablation C on extracted graphs (plan 5.4, 7.3; E010).

The engine's view slot (`components.views: {factory: read-time-views, source: ...}`). Nothing is
stored at write time, so the component is read-side only (stages.py: a view source that reads the
graph at read time) and one ingest run serves every arm. At a read, the query answers of the
plan (`GraceEngine._state_items`) are presented by one content source:

- `template`: template serialisation of the result rows (the family's sentence pattern for a
  resident-equivalent view, `name = value` otherwise). No model call.
- `llm`: LLM rendering of the same rows (`render.LLMRenderer`: frozen `render-view` prompt,
  rendering check, template fallback).
- `rewrite`: LLM rewriting from raw text. The model sees the view's title and the raw text of
  the messages the rows cite (`rewrite-view` prompt), never the rows, and writes sentences
  labelled with the messages they are based on. A source outside the given messages is dropped
  and counted as a wrong citation; a sentence left without a source is dropped. A chunk whose call
  fails or keeps no sentence falls back to the template (counted).

Rows are cut into the same chunks for `llm` and `rewrite` (`max_rows_per_call` of the view
config), and both are booked like a temporary view's rendering at read time (call type `render`,
trigger `read`, ledger W).

Resident-equivalent views (view hits). A resident view is a binding of a template family whose
query reaches the instantiation threshold (`ViewStore.materialise`); its query is a function of
the binding and the graph only. The plan's query is a hit when it equals the bound query
of such a binding at the read version modulo variable renaming (`hitrule`), which is the hit
rule of the resident store (`engine.Views.hit`) evaluated at read time, as
`serialise.SerialisedViews` does. A hit is presented with the family's title and sentence pattern
(filled with the plan's rows, their columns named as in the bound query) and named in
`Presentation.view_id` (the engine reports it in the read trace's `view_hits`); every other
query result is a temporary view (plan 5.4), titled by the plan's variable descriptions.

Every presentation is also handed to `EVENT_SINK` when it is set (the E010 driver collects them
into `views/presentations.jsonl` of the run): the source, the hit, the nearest bindings when there
is no hit (a binding whose subject and predicate occur in the plan's query), row and unit counts,
rendering-check counts, rewrite citations and the model calls.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from grace.context import api
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import Vocabulary
from grace.context.pipeline.query.compile import compile_query
from grace.context.pipeline.query.execute import execute
from grace.context.pipeline.query.grammar import to_text
from grace.context.views import hitrule
from grace.context.views.rebuild import member_query
from grace.context.views.render import (
    LLMRenderer,
    RenderContext,
    Rendered,
    RenderSpec,
    TemplateRenderer,
    _chunks,
    display,
    humanise,
    normalise,
    template_sentence,
)
from grace.context.views.store import ViewStore
from grace.context.views.template_families import (
    TemplateFamily,
    ViewConfig,
    candidate_bindings,
    load_families,
)
from grace.context.views.view import Binding, Row, build_rows, row_id, units
from grace.llm.client import LLMCallFailed
from grace.llm.prompts import Prompt, load_pinned
from grace.llm.structured import load_schema, parse

SOURCES = ("template", "llm", "rewrite")
REWRITE_PROMPT = "rewrite-view"
REWRITE_SCHEMA = "rewrite-view"
MAX_NEAR = 5
_VAR = re.compile(r"\?[A-Za-z_][A-Za-z0-9_]*")
_ATTRIBUTION = re.compile(r"\[[^\]]*\]")
# Why a near binding's bound query is not the plan's query, from the closest difference down.
NEAR_CLASSES = ("variable_names", "attribution", "other")

# Set by a driver to receive one record per presentation (thread-safe callable).
EVENT_SINK: Callable[[dict[str, Any]], None] | None = None
_SINK_LOCK = threading.Lock()


def _emit(record: dict[str, Any]) -> None:
    sink = EVENT_SINK
    if sink is not None:
        with _SINK_LOCK:
            sink(record)


@dataclass(frozen=True)
class Presentation:
    """Sentences as (text, indices of the answers they state, evidence IDs); `view_id` names
    the resident-equivalent view the query matched (a view hit), else None."""

    view_id: str | None
    sentences: tuple[tuple[str, tuple[int, ...], tuple[str, ...]], ...]
    call_ids: tuple[str, ...] = ()


# ---------------------------------------------------------------------------------------------
# LLM rewriting from raw text


@dataclass(frozen=True)
class Rewritten:
    sentences: tuple[tuple[str, tuple[str, ...]], ...]   # (text, message IDs)
    call_ids: tuple[str, ...]
    ok: bool
    sources_given: int = 0      # sources named in the kept output, before the check
    wrong_citations: int = 0    # sources outside the messages given (dropped)
    dropped: int = 0            # sentences left without a valid source


@dataclass
class Rewriter:
    """One `rewrite-view` call per chunk: title and messages in, sentences with sources out."""

    client: Any
    prompt: Prompt
    decoding: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._schema = load_schema(REWRITE_SCHEMA)

    def _validate(self, text: str) -> str | None:
        return parse(text, self._schema).error

    def rewrite(self, title: str, messages: Sequence[api.Message],
                context: RenderContext) -> Rewritten:
        lines = []
        for m in messages:
            stamp = f" ({m.timestamp})" if m.timestamp else ""
            lines.append(f"[{m.message_id}]{stamp} {m.speaker or m.role}: {m.text}")
        prompt = self.prompt.render(title=title, messages="\n".join(lines))
        try:
            result = self.client.chat(prompt, context.call_context(),
                                      prompt_sha256=self.prompt.sha256, decoding=self.decoding,
                                      validate=self._validate)
        except LLMCallFailed as exc:
            return Rewritten((), tuple(r.call_id for r in exc.records), False)
        ids = tuple(r.call_id for r in result.records)
        if result.status != "ok":
            return Rewritten((), ids, False)
        given = {m.message_id for m in messages}
        out, named, wrong, dropped = [], 0, 0, 0
        for item in parse(result.text, self._schema).value["sentences"]:
            text = item["text"].strip()
            sources = list(dict.fromkeys(item["sources"]))
            named += len(sources)
            valid = tuple(s for s in sources if s in given)
            wrong += len(sources) - len(valid)
            if not text or not valid:
                dropped += 1
                continue
            out.append((text, valid))
        return Rewritten(tuple(out), ids, True, named, wrong, dropped)


# ---------------------------------------------------------------------------------------------
# The component


def canonical(query_text: str, attribution: bool = True) -> str:
    """The query text with variables renamed in order of first use (`?v1`, `?v2`, ...) and, with
    `attribution` False, every attribution constraint replaced by `[*]`."""
    names: dict[str, str] = {}

    def rename(m: re.Match) -> str:
        return names.setdefault(m.group(0), f"?v{len(names) + 1}")
    text = _VAR.sub(rename, query_text)
    return text if attribution else _ATTRIBUTION.sub("[*]", text)


def near_class(plan_text: str, bound_text: str) -> str:
    """How the plan's query differs from a binding's bound query: only in variable names, also
    in attribution constraints, or otherwise (patterns, projection, aggregation, time). A
    diagnostic on query text; the hit rule itself is `hitrule.match` on the IR, under which a
    near binding of class `variable_names` is a hit unless the plan is not view-eligible or the
    binding misses its instantiation threshold."""
    if canonical(plan_text) == canonical(bound_text):
        return "variable_names"
    if canonical(plan_text, False) == canonical(bound_text, False):
        return "attribution"
    return "other"


def _title(plan, query_text: str) -> str:
    """Title of a temporary view: the plan's variable descriptions, else its patterns."""
    described = [d for _, d in getattr(plan, "variables", ()) if d]
    if described:
        return "; ".join(described)
    body = query_text.split("{", 1)[-1].rsplit("}", 1)[0]
    patterns = [line.split("[")[0].strip() for line in body.splitlines() if line.strip()]
    return "query result: " + "; ".join(p for p in patterns if p)


class ReadTimeViews:
    """The view component of the read-time content sources (module docstring)."""

    def __init__(self, history_id: str, config: ViewConfig, vocabulary: Vocabulary | None,
                 source: str, client: Any = None,
                 families: Mapping[str, TemplateFamily] | None = None):
        if source not in SOURCES:
            raise ValueError(f"read-time-views: source must be one of {SOURCES}, got {source!r}")
        if source != "template" and client is None:
            raise ValueError(f"read-time-views: source {source!r} needs the run's chat client")
        self.history_id, self.config, self.vocabulary = history_id, config, vocabulary
        self.source = source
        self.families = dict(families) if families is not None else load_families(
            config.families)
        decoding = dict(config.rendering.decoding)
        self.template = TemplateRenderer()
        self.renderer = (LLMRenderer(client, load_pinned(config.rendering.prompt,
                                                         _registry()),
                                     decoding, max_rows_per_call=config.rendering.max_rows_per_call)
                         if source == "llm" else None)
        self.rewriter = (Rewriter(client, load_pinned(REWRITE_PROMPT, _registry()), decoding)
                         if source == "rewrite" else None)

    # -- the view-slot interface ---------------------------------------------------------------

    def on_commit(self, changeset, graph: ClaimStore):
        return [], []

    def on_read(self, graph: ClaimStore, version: int, read_id: str):
        return [], []

    def hit(self, plan):
        return None  # hits are found in `present`, where the query answers are at hand

    def save(self, directory):
        return []

    def restore(self, directory, graph: ClaimStore) -> None:
        pass

    def present(self, plan, result, graph: ClaimStore, version: int, read_id: str,
                message: Callable[[str], api.Message]) -> Presentation | None:
        if plan.query is None or result is None:
            return None
        query_text = to_text(plan.query)
        event: dict[str, Any] = {"read_id": read_id, "history_id": self.history_id,
                                 "version": version, "source": self.source,
                                 "plan_route": getattr(plan, "route", None),
                                 "view_eligible": bool(plan.view_eligible),
                                 "plan_query": query_text}
        binding, mapping, near, n_candidates, near_info = self._match(plan, query_text, graph,
                                                                      version)
        rows = self._rows(plan, result, graph, version)
        if rows is None:
            _emit({**event, "status": "skipped", "reason": "count without member rows",
                   "view_id": None, "near": near, "candidates": n_candidates, **near_info})
            return None
        if binding is not None:
            claims = {c for r in rows for w in r.witnesses for c in w.claims}
            if len(claims) < self.config.threshold(binding.family):
                near = [binding.view_id, *near][:MAX_NEAR]
                binding = None  # a resident store would not hold this view
        spec = self._spec(binding, plan, query_text, result, mapping)
        answer_of = self._answer_index(result)
        by_id = {r.row_id: r for r in rows}
        todo = units(rows)
        context = RenderContext("read", self.history_id, version, read_id)
        counts = {"rows": len(rows), "units": len(todo), "llm_sentences": 0,
                  "failed_sentences": 0, "fallback_units": 0}
        if not todo:
            sentences: list[tuple[str, tuple[int, ...], tuple[str, ...]]] = []
            calls: tuple[str, ...] = ()
        elif self.source == "rewrite":
            sentences, calls, extra = self._rewrite(spec, by_id, todo, answer_of, context,
                                                    message)
            counts.update(extra)
        else:
            renderer = self.renderer if self.source == "llm" else self.template
            rendered: Rendered = renderer.render(spec, by_id, todo, context)
            calls = rendered.call_ids
            counts.update(llm_sentences=rendered.llm_sentences,
                          failed_sentences=rendered.failed_sentences,
                          fallback_units=rendered.fallback_units)
            sentences = [(text, _answers(ids, answer_of), _evidence(ids, by_id))
                         for ids, text, _ in rendered.sentences]
        view_id = binding.view_id if binding is not None else None
        _emit({**event, "status": "presented", "view_id": view_id,
               "family": binding.family if binding is not None else None,
               "near": [] if binding is not None else near, "candidates": n_candidates,
               **({} if binding is not None else near_info),
               "title": spec.title, **counts, "sentences": len(sentences),
               "call_ids": list(calls)})
        return Presentation(view_id, tuple(sentences), tuple(calls))

    # -- helpers -------------------------------------------------------------------------------

    def _match(self, plan, query_text: str, graph: ClaimStore, version: int
               ) -> tuple[Binding | None, dict[str, str] | None, list[str], int, dict[str, Any]]:
        """The binding whose bound query is the plan's query modulo variable renaming (eligible
        plans only; `hitrule.match`) with the mapping from the plan's variable names to the
        bound query's, the nearest bindings otherwise (subject and predicate occur in the query
        text), the number of candidate bindings at the read version, and the closest near
        binding with its bound query and difference class (`near_class`; `NEAR_CLASSES`
        order)."""
        bindings = candidate_bindings(graph.state(version), self.families, self.config,
                                      self.vocabulary)
        store = ViewStore(self.history_id, self.template, config=self.config,
                          families=self.families, vocabulary=self.vocabulary)
        near: list[str] = []
        best: tuple[int, str, str] | None = None
        tokens = set(_tokens(query_text))
        consts = hitrule.constants(plan.query) if plan.view_eligible else frozenset()
        for b in bindings:
            in_text = b.subject in tokens and (b.predicate is None or b.predicate in tokens)
            in_query = b.subject in consts and (b.predicate is None or b.predicate in consts)
            if not (in_text or in_query):
                continue
            bound_query = store.bind(b)[0]
            if in_query:
                mapping = hitrule.match(plan.query, bound_query)
                if mapping is not None:
                    return b, mapping, [], len(bindings), {}
            if not in_text:
                continue
            bound = to_text(bound_query)
            if len(near) < MAX_NEAR:
                near.append(b.view_id)
            kind = near_class(query_text, bound)
            if best is None or NEAR_CLASSES.index(kind) < best[0]:
                best = (NEAR_CLASSES.index(kind), b.view_id, bound)
        info = ({"near_class": NEAR_CLASSES[best[0]], "near_binding": best[1],
                 "near_query": best[2]} if best is not None
                else {"near_class": None, "near_binding": None, "near_query": None})
        return None, None, near, len(bindings), info

    def _spec(self, binding: Binding | None, plan, query_text: str, result,
              mapping: dict[str, str] | None = None) -> RenderSpec:
        if binding is not None:
            # The family's sentence pattern names the bound query's variables: the plan's
            # columns are renamed to them (the rows are the plan's, in the same column order).
            family = self.families[binding.family]
            title = family.title.format(subject=binding.subject,
                                        predicate=humanise(binding.predicate or ""))
            columns = tuple((mapping or {}).get(v, v) for v in result.variables)
            return RenderSpec(title, columns, bool(result.is_count),
                              binding.subject, binding.predicate, family.sentence)
        return RenderSpec(_title(plan, query_text), tuple(result.variables),
                          bool(result.is_count))

    @staticmethod
    def _rows(plan, result, graph: ClaimStore, version: int) -> tuple[Row, ...] | None:
        if not result.is_count:
            return build_rows(result)
        compiled = getattr(plan, "compiled", None)
        if compiled is None:
            return None
        try:
            members = execute(compile_query(member_query(compiled.query), graph.mode), graph,
                              version)
        except Exception:  # noqa: BLE001 - reported as a skipped presentation
            return None
        return build_rows(result, members)

    @staticmethod
    def _answer_index(result) -> dict[str, list[int]]:
        groups = len(result.variables) - 1
        out: dict[str, list[int]] = {}
        for i, a in enumerate(result.answers):
            rid = (row_id(a.values[:groups], aggregate=True) if result.is_count
                   else row_id(a.values))
            out.setdefault(rid, []).append(i)
        return out

    def _rewrite(self, spec: RenderSpec, by_id: Mapping[str, Row], todo, answer_of, context,
                 message: Callable[[str], api.Message]):
        sentences: list[tuple[str, tuple[int, ...], tuple[str, ...]]] = []
        calls: list[str] = []
        extra = {"rewrite_sentences": 0, "rewrite_sources": 0, "wrong_citations": 0,
                 "dropped_sentences": 0, "rows_stated": 0, "rewrite_calls_failed": 0}
        for chunk in _chunks(todo, self.config.rendering.max_rows_per_call):
            ids = [rid for unit in chunk for rid in unit]
            mids = list(dict.fromkeys(_message_id(e) for rid in ids
                                      for e in by_id[rid].evidence))
            out = self.rewriter.rewrite(spec.title, [message(m) for m in mids], context)
            calls += out.call_ids
            extra["rewrite_sources"] += out.sources_given
            extra["wrong_citations"] += out.wrong_citations
            extra["dropped_sentences"] += out.dropped
            if not out.ok:
                extra["rewrite_calls_failed"] += 1
            if not out.sentences:
                extra["fallback_units"] = extra.get("fallback_units", 0) + len(chunk)
                sentences += [(template_sentence(spec, by_id, u), _answers(u, answer_of),
                               _evidence(u, by_id)) for u in chunk]
                continue
            extra["rewrite_sentences"] += len(out.sentences)
            text = normalise(" ".join(t for t, _ in out.sentences))
            for unit in chunk:  # descriptive check: every value of the unit's head row stated
                values = [display(v) for v in by_id[unit[0]].values]
                if all(normalise(v) in text for v in values if normalise(v)):
                    extra["rows_stated"] += 1
            sentences += [(t, (), src) for t, src in out.sentences]
        return sentences, tuple(calls), extra


def _tokens(text: str) -> list[str]:
    out, word = [], []
    for ch in text:
        if ch.isalnum() or ch == "_":
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def _message_id(evidence: str) -> str:
    return evidence.split("#", 1)[0]


def _answers(row_ids: Sequence[str], answer_of: Mapping[str, list[int]]) -> tuple[int, ...]:
    return tuple(i for rid in row_ids for i in answer_of.get(rid, ()))


def _evidence(row_ids: Sequence[str], by_id: Mapping[str, Row]) -> tuple[str, ...]:
    return tuple(sorted({e for rid in row_ids for e in by_id[rid].evidence}))


def _registry():
    from grace.config.paths import REPO_ROOT
    return REPO_ROOT / "configs" / "common" / "prompts.yaml"


def read_time_views(*, writer=None, client=None, view_config: ViewConfig | None = None,
                    source: str = "template", **options):
    """Component factory (`config/registry.py`, name `read-time-views`) for the engine's `views`
    slot: `make(history, vocabulary)` gives one `ReadTimeViews` per history."""
    if options:
        raise TypeError(f"read-time-views takes only `source`, got {sorted(options)}")
    config = view_config or ViewConfig()
    if source not in SOURCES:
        raise ValueError(f"read-time-views: source must be one of {SOURCES}, got {source!r}")

    def make(history, vocabulary) -> ReadTimeViews:
        return ReadTimeViews(history.history_id, config, vocabulary, source, client)
    return make


__all__ = ["EVENT_SINK", "Presentation", "ReadTimeViews", "Rewriter", "SOURCES",
           "read_time_views"]
