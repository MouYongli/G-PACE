"""Run a compiled query at a cut-off version; build answers, witnesses and evidence (plan 3.4, 5.3).

`execute(compiled, store, version)` evaluates `Q[r]` on the store, where `r` is the query's fixed
cut-off (`AT(known=r0)`, a time-travel read) or else the version being read. Because every entry
stamped after `r` is filtered out by `%r%`, the result is the same on `G_r` and on any later graph
(time-travel stability, plan 3.3).

Witness rules (plan 3.4):

- positive part: every row of the main query is one witness (the claims of the positive patterns
  and the attributions that satisfy their constraints); an answer keeps its minimal witnesses;
- negation contributes no witness (its pattern is not projected);
- distinct count: one witness, the union of the witnesses of the counted members;
- latest state: the latest claim is selected first (its key is the latest version at which it
  was confirmed, the maximum key over its rows), then every witness of that claim is kept.

Entities are evaluated on the representative of their equivalence class at the cut-off
(contracts.md, "Claim graph"): entity constants match every member of their class, and entity
answers are reported as the representative. Joins on a variable still compare node identity, so a
join across two members of one class is not made (open question in docs/research/query-ir.md).
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from urllib.parse import unquote

import pyoxigraph as ox

from grace.context.memory.graph import rdf
from grace.context.memory.graph.entities import EntityEquivalence, representatives
from grace.context.memory.graph.entries import Claim, Entity, Value
from grace.context.memory.graph.store import ClaimStore
from grace.context.memory.graph.vocabulary import ENTITY, ENTRY, MESSAGE, PREDICATE, XSD
from grace.context.pipeline.query.compile import CLAIMS, CompiledQuery, compile_query
from grace.context.pipeline.query.ir import Predicate, Query
from grace.context.pipeline.query.result import (
    Answer,
    QueryResult,
    Witness,
    minimal,
    value_key,
)

_CLAIM_PREFIX = f"{ENTRY}{rdf.KIND_PATH[Claim]}/"
_ATT_PREFIX = f"{ENTRY}attribution/"
_EQUIVALENCES = """SELECT ?a ?b WHERE {
  ?q a g:EntityEquivalence ; g:entityA ?a ; g:entityB ?b ; g:knownFrom ?v .
  FILTER(?v <= %r%)
}"""


class QueryExecutionError(ValueError):
    """The query cannot run against this store at this version."""


def _local(node, prefix: str) -> str:
    if not isinstance(node, ox.NamedNode) or not node.value.startswith(prefix):
        raise QueryExecutionError(f"expected a node under {prefix}, got {node}")
    return unquote(node.value[len(prefix):])


def _value(node, reps: dict[str, str]):
    if isinstance(node, ox.Literal):
        dt = node.datatype.value
        if not dt.startswith(XSD):
            raise QueryExecutionError(f"literal datatype outside XSD: {node}")
        return Value(node.value, dt[len(XSD):])
    if isinstance(node, ox.NamedNode) and node.value.startswith(PREDICATE):
        return Predicate(_local(node, PREDICATE))
    entity = _local(node, ENTITY)
    return Entity(reps.get(entity, entity))


def _key(node) -> tuple:
    """Ordering key of LATEST: an integer version or a valid-time start."""
    dt = node.datatype.value[len(XSD):]
    if dt == "integer":
        return (int(node.value),)
    t = _dt.datetime.fromisoformat(node.value.replace("Z", "+00:00"))
    if t.tzinfo is not None:
        t = t.astimezone(_dt.UTC).replace(tzinfo=None)
    return (t,)


def equivalence_classes(store: ClaimStore, cutoff: int) -> tuple[dict[str, str], dict[str, list]]:
    """Representatives and class members of every merged entity at the cut-off."""
    eqs = [EntityEquivalence(f"q{i}", _local(row["a"], ENTITY), _local(row["b"], ENTITY), 1)
           for i, row in enumerate(store.query(_EQUIVALENCES, cutoff))]
    reps = representatives(eqs, 1)
    classes: dict[str, list] = defaultdict(list)
    for entity, rep in reps.items():
        classes[rep].append(entity)
    return reps, {e: sorted(classes[rep]) for e, rep in reps.items()}


def execute(compiled: CompiledQuery, store: ClaimStore, version: int | None = None
            ) -> QueryResult:
    """Evaluate the compiled query at the cut-off for a read at `version` (default: head)."""
    if compiled.mode != store.mode:
        raise QueryExecutionError(f"query compiled for {compiled.mode}, store uses {store.mode}")
    read = store.head if version is None else version
    known = compiled.query.at.known
    cutoff = read if known is None else known
    if cutoff > read:
        raise QueryExecutionError(f"cut-off {cutoff} lies after the version read ({read})")
    reps, classes = equivalence_classes(store, cutoff)
    main, _ = compiled.bind(classes)
    query = compiled.query

    latest = None if query.latest is None else query.latest.label.name
    rows = []
    for sol in store.query(main, cutoff):
        values = tuple(_value(sol[v], reps) for v in compiled.answer_vars)
        claims = [_local(sol[s.label], _CLAIM_PREFIX) for s in compiled.slots]
        atts = [_local(sol[s.attribution], _ATT_PREFIX) for s in compiled.slots
                if s.attribution]
        key = _key(sol[compiled.key]) if compiled.key else None
        selected = _local(sol[latest], _CLAIM_PREFIX) if latest else None
        rows.append((values, Witness.of(claims, atts), key, selected))

    if latest is not None and rows:
        rows = _latest_rows(rows)

    if query.count is not None:
        answers = _count_answers(query, rows)
    else:
        grouped: dict[tuple, list[Witness]] = defaultdict(list)
        for values, witness, *_ in rows:
            grouped[values].append(witness)
        answers = [Answer(values, minimal(ws)) for values, ws in grouped.items()]

    evidence: dict[str, tuple[str, ...]] = {}
    if query.provenance:
        claim_ids = sorted({c for a in answers for w in a.witnesses for c in w.claims})
        evidence = fetch_evidence(compiled, store, claim_ids, cutoff)
        answers = [Answer(a.values, a.witnesses, tuple(sorted(
            {e for w in a.witnesses for c in w.claims for e in evidence.get(c, ())})))
            for a in answers]
    answers.sort(key=lambda a: tuple(value_key(v) for v in a.values))
    return QueryResult(variables=compiled.answer_vars, answers=tuple(answers), cutoff=cutoff,
                       is_count=query.count is not None, temporary=query.temporary,
                       evidence=evidence)


def _latest_rows(rows: list) -> list:
    """LATEST: select the latest claim(s) first, then keep every row (witness) of them.

    A claim's key is the maximum row key over its rows: the latest version at which it was
    confirmed (claim or constraining attribution stamp). Ties between claims keep all tied claims.
    Every row of a selected claim is kept, so an earlier witness of a restated claim survives
    (plan 3.4, change-sequences.md 6.2). Only rows visible at the cut-off exist, so the selection
    is time-travel stable.
    """
    claim_key: dict[str, tuple] = {}
    for _, _, key, claim in rows:
        if claim not in claim_key or key > claim_key[claim]:
            claim_key[claim] = key
    top = max(claim_key.values())
    chosen = {c for c, k in claim_key.items() if k == top}
    return [r for r in rows if r[3] in chosen]


def _count_answers(query: Query, rows) -> list[Answer]:
    n_groups = len(query.select)
    members: dict[tuple, dict] = defaultdict(lambda: defaultdict(list))
    for values, witness, *_ in rows:
        members[values[:n_groups]][values[n_groups]].append(witness)
    if not members and n_groups == 0:
        return [Answer((Value("0", "integer"),), ())]
    answers = []
    for group, by_member in members.items():
        union = None
        for ws in by_member.values():
            for w in minimal(ws):
                union = w if union is None else union.union(w)
        answers.append(Answer((*group, Value(str(len(by_member)), "integer")),
                              (union,) if union else ()))
    return answers


def fetch_evidence(compiled: CompiledQuery, store: ClaimStore, claim_ids: list[str],
                   cutoff: int) -> dict[str, tuple[str, ...]]:
    """Run the second (evidence) query for the witness claims; unified evidence IDs per claim."""
    if not claim_ids:
        return {}
    nodes = " ".join(rdf.entry_iri(Claim, c).value.join("<>") for c in claim_ids)
    out: dict[str, set[str]] = defaultdict(set)
    for sol in store.query(compiled.evidence.replace(CLAIMS, nodes), cutoff):
        message = _local(sol["_message"], MESSAGE)
        start, end = sol["_start"], sol["_end"]
        unified = message if start is None else f"{message}#char={start.value},{end.value}"
        out[_local(sol["_claim"], _CLAIM_PREFIX)].add(unified)
    return {c: tuple(sorted(ids)) for c, ids in sorted(out.items())}


def run(query: Query, store: ClaimStore, version: int | None = None) -> QueryResult:
    """Compile for the store's serialisation and execute (convenience for tests and callers)."""
    return execute(compile_query(query, store.mode), store, version)
