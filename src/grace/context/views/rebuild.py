"""Evaluation, full build, local rebuild and citation patching of a view (plan 5.4).

- `evaluate`: run the view's query at a cut-off (and, for a count, its member query) and build the
  rows. Content comes only from deterministic query evaluation.
- `full_build`: render every unit of the rows.
- `local_rebuild` (answer-stale): rows are compared by row ID. A sentence is kept, with its
  citations patched, when none of its rows is new, vanished or changed (an aggregate whose count
  or member set changed); every other sentence is dropped, and only the units it no longer covers
  are rendered again. For deterministic renderers the result equals `full_build` on the same rows
  (tests/integration/test_views.py).
- `repair_citations` (citation-stale): the rows have the same IDs and values; witnesses and
  evidence are replaced and each sentence's evidence is recomputed from its rows by row ID. It
  takes no renderer, so it cannot make an LLM call.
- `classify`: which of the three a fresh evaluation calls for.

Whole-history invalidation on a vocabulary change or an entity merge (plan 5.2) is a flag in the
store (`ViewStore.note_changeset`); the next maintenance of an invalidated view is a `full_build`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from grace.context.memory.graph.store import ClaimStore
from grace.context.pipeline.query.compile import CompiledQuery, compile_query
from grace.context.pipeline.query.execute import execute
from grace.context.pipeline.query.ir import Query
from grace.context.pipeline.query.result import QueryResult
from grace.context.views.render import Rendered, Renderer, RenderSpec
from grace.context.views.view import (
    Row,
    Sentence,
    View,
    ViewError,
    build_rows,
    order_sentences,
    sentence_evidence,
    units,
)

BUILD = "build"
FULL_REBUILD = "full_rebuild"
LOCAL_REBUILD = "local_rebuild"
CITATION_REPAIR = "citation_repair"
ADVANCE = "advance"  # nothing changed but the cut-off


def member_query(query: Query) -> Query:
    """For COUNT(DISTINCT ?x): the same body selecting the grouping variables and ?x."""
    if query.count is None:
        raise ViewError("only a count query has a member query")
    return replace(query, select=(*query.select, query.count.var), count=None)


@dataclass(frozen=True)
class Compiled:
    main: CompiledQuery
    members: CompiledQuery | None

    @classmethod
    def of(cls, query: Query, mode: str) -> Compiled:
        return cls(compile_query(query, mode),
                   compile_query(member_query(query), mode) if query.count else None)


@dataclass(frozen=True)
class Evaluation:
    result: QueryResult
    rows: tuple[Row, ...]


def evaluate(compiled: Compiled, graph: ClaimStore, version: int) -> Evaluation:
    result = execute(compiled.main, graph, version)
    members = execute(compiled.members, graph, version) if compiled.members else None
    return Evaluation(result, build_rows(result, members))


def _sentences(rendered: Rendered, rows: dict[str, Row]) -> list[Sentence]:
    return [Sentence(text, ids, sentence_evidence(ids, rows), source)
            for ids, text, source in rendered.sentences]


def full_build(spec: RenderSpec, rows: tuple[Row, ...], renderer: Renderer, context
               ) -> tuple[tuple[Sentence, ...], Rendered, int]:
    """Render every unit. Returns the sentences, the render output and the units rendered."""
    by_id = {r.row_id: r for r in rows}
    todo = units(rows)
    rendered = renderer.render(spec, by_id, todo, context)
    return order_sentences(_sentences(rendered, by_id), rows), rendered, len(todo)


def changed_rows(old: tuple[Row, ...], new: tuple[Row, ...]) -> set[str]:
    """Row IDs that are new, vanished, or whose values or members changed."""
    a = {r.row_id: (r.values, r.members) for r in old}
    b = {r.row_id: (r.values, r.members) for r in new}
    return {rid for rid in a.keys() | b.keys() if a.get(rid) != b.get(rid)}


def local_rebuild(view: View, spec: RenderSpec, rows: tuple[Row, ...], renderer: Renderer,
                  context) -> tuple[tuple[Sentence, ...], Rendered, int, int]:
    """Keep the sentences of unchanged rows, render the rest. Returns the sentences, the render
    output, the number of kept sentences and the number of units rendered."""
    by_id = {r.row_id: r for r in rows}
    affected = changed_rows(view.rows, rows)
    kept = [Sentence(s.text, s.rows, sentence_evidence(s.rows, by_id), s.source)
            for s in view.sentences if not set(s.rows) & affected]
    covered = {rid for s in kept for rid in s.rows}
    todo = [u for u in units(rows) if not set(u) & covered]
    rendered = renderer.render(spec, by_id, todo, context) if todo else Rendered(())
    sentences = order_sentences([*kept, *_sentences(rendered, by_id)], rows)
    return sentences, rendered, len(kept), len(todo)


def repair_citations(view: View, rows: tuple[Row, ...]) -> tuple[Sentence, ...]:
    """Patch the evidence of every sentence by row ID; no renderer, hence no LLM call."""
    if changed_rows(view.rows, rows):
        raise ViewError(f"view {view.view_id}: rows changed; citation repair does not apply")
    by_id = {r.row_id: r for r in rows}
    return tuple(Sentence(s.text, s.rows, sentence_evidence(s.rows, by_id), s.source)
                 for s in view.sentences)


def classify(view: View, evaluation: Evaluation) -> str:
    """`local_rebuild` if rows changed, `citation_repair` if only witnesses or evidence did,
    `advance` otherwise. A swap of members under an unchanged count changes the aggregate row's
    members, so its sentence is rebuilt although the answer fingerprint is unchanged."""
    if changed_rows(view.rows, evaluation.rows):
        return LOCAL_REBUILD
    if view.rows != evaluation.rows:
        return CITATION_REPAIR
    return ADVANCE

