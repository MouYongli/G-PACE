"""Scale probe of E004: database time of push, pull and hybrid staleness decisions (plan 5.4).

E004 asks at what number of standing views, write rate and graph size claim-pattern push becomes
cheaper than read-time re-query with fingerprints, and where push filtering with read-time
confirmation sits (docs/work/experiments/E004-scale-experiment.md). The three arms are the T019
strategies of `configs/views/staleness.yaml`; no LLM is called (template rendering), so pull and
hybrid spend the same tokens by construction and only time differs.

**Synthetic graphs.** A graph is built from `blocks` development sequences of the T015 generator
(`eval/datasets/changeseq/`, development families only). Each block is one generated sequence with
its gold change sets; its entity and entry IDs get the prefix `b<NNNN>-`, so blocks share no
entity, claim or message (the attribution speakers `user` and `assistant` are kept: they are
roles, not entities). The change sets of all blocks are interleaved round robin into one history:
message t of block 0, of block 1, ..., then message t+1. Messages `1..prefix` of every block form
the prefix that is committed before measuring (the graph size); messages after `prefix` form the
measured window, in the same interleaved order.

**Standing views.** Every block admits the view bindings of the generator (about 15: V1-V6 mapped
to the T018 families as in the T019 replay); `views` of them are drawn from all blocks by a seeded
permutation (nested: the first 16 of a seed are the first 16 of its 128). The views are built at
the prefix head before measuring.

**One measurement** is one arm over one window: `reads` read periods, each of `writes_per_read`
committed change sets followed by one read. A read checks either every standing view
(`read_scope: all`) or `read_scope` views drawn per read by a seeded generator (the same draws for
every arm). Per period it records the write-side matching time (`match_ms` of the strategy log:
pattern matching on change-set records, no database), the wall time of the `write` calls, the
commit time (the same for every arm, not part of the decision cost), and per read the database time
of the strategy (`check_db_ms` of the fingerprint re-query plus `maintain_db_ms` of maintenance that
re-evaluates on its own) and the wall time of the `read` call. It also records which views were
repaired and how, so the analysis can check that pull and hybrid repaired exactly the same views.

The prefix store is built once per graph (`ClaimStore.commit` per change set) and copied for every
measurement with `fork_store`, which copies the store's state directly: the graph is append-only, so
each measurement needs its own copy, and re-committing a 100k-version prefix per measurement would
cost more than the experiment.
"""

from __future__ import annotations

import gc
import os
import random
import re
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entries import Entity
from grace.context.memory.graph.store import ClaimStore
from grace.context.views.rebuild import Compiled
from grace.context.views.staleness import load_arms, make_arm
from grace.context.views.store import ADVANCE, ViewStore
from grace.context.views.template_families import ViewConfig
from grace.context.views.view import Binding
from grace.eval.datasets.changeseq.build import (
    GENERATOR_VERSION,
    generate_sequence,
    sequence_seed,
)
from grace.eval.datasets.changeseq.template_families import CellConfig, load_split

# Generator view templates -> T018 template families (as in the T019 replay).
FAMILY = {"V1": "list", "V2": "current", "V3": "count", "V4": "constraints", "V5": "pending",
          "V6": "choice"}
# Bindings one block admits per family (generator: V1-V3 for the user and one companion, V4-V6
# for each of three tasks).
BINDINGS_PER_BLOCK = {"list": 2, "count": 2, "current": 2, "constraints": 3, "pending": 3,
                      "choice": 3}
SPEAKERS = frozenset({"user", "assistant"})
ALL = "all"


class ScaleError(ValueError):
    """A scale cell cannot be built as configured."""


# ---------------------------------------------------------------------------------------------
# Blocks


@dataclass(frozen=True)
class Block:
    """One generated development sequence, with its IDs prefixed (versions still local)."""

    index: int
    family: str
    sequence_id: str
    seed: int
    changesets: tuple[ChangeSet, ...]   # local versions 1..length
    bindings: tuple[Binding, ...]


def prefix_of(index: int) -> str:
    return f"b{index:04d}-"


def _rename_entity(prefix: str, entity_id: str) -> str:
    return prefix + entity_id


def place(cs: ChangeSet, prefix: str, history_id: str, version: int) -> ChangeSet:
    """The change set with every entity and entry ID prefixed, moved to `version` of
    `history_id`. Attribution speakers are kept; entity merges are not supported."""
    if cs.entity_merges:
        raise ScaleError(f"change set {cs.version} has entity merges; blocks must have none")

    def p(x: str | None) -> str | None:
        return None if x is None else prefix + x

    claims = tuple(replace(c, claim_id=p(c.claim_id), subject=_rename_entity(prefix, c.subject),
                           object=Entity(_rename_entity(prefix, c.object.id))
                           if isinstance(c.object, Entity) else c.object, version=version)
                   for c in cs.claims)
    atts = tuple(replace(a, attribution_id=p(a.attribution_id), claim_id=p(a.claim_id),
                         speaker=a.speaker if a.speaker in SPEAKERS else p(a.speaker),
                         message_id=p(a.message_id), version=version) for a in cs.attributions)
    links = tuple(replace(e, evidence_id=p(e.evidence_id), claim_id=p(e.claim_id),
                          message_id=p(e.message_id), version=version)
                  for e in cs.evidence_links)
    sups = tuple(replace(s, supersession_id=p(s.supersession_id), claim_id=p(s.claim_id),
                         replacing_claim_id=p(s.replacing_claim_id),
                         attribution_id=p(s.attribution_id), version=version)
                 for s in cs.supersessions)
    return ChangeSet(history_id, version, claims, atts, links, sups, cs.vocabulary_version)


def generate_block(index: int, *, master_seed: int, length: int, density: float,
                   families: Sequence[str]) -> Block:
    """Block `index`: family `families[index % len]`, seed from the master seed and its ID."""
    development = set(load_split().development)
    family = families[index % len(families)]
    if family not in development:
        raise ScaleError(f"family {family!r} is not a development family; E004 uses "
                         f"development families only")
    sequence_id = f"E004-{family}-{index:04d}"
    seed = sequence_seed(master_seed, sequence_id)
    cell = CellConfig(family=family, length=length, density=density)
    bundle = generate_sequence(family, cell, seed, sequence_id, validate=None)
    prefix = prefix_of(index)
    local = tuple(place(cs, prefix, sequence_id, cs.version)
                  for cs in bundle.store.changesets())
    bindings = tuple(Binding(FAMILY[b.template], _rename_entity(prefix, b.subject), b.predicate)
                     for b in bundle.plan.bindings())
    return Block(index, family, sequence_id, seed, local, bindings)


# ---------------------------------------------------------------------------------------------
# Scaled graph


@dataclass
class ScaledGraph:
    """The interleaved history of `len(blocks)` blocks: committed prefix and measured window."""

    history_id: str
    blocks: tuple[Block, ...]
    prefix_length: int
    prefix: list[ChangeSet]
    window: list[ChangeSet]
    store: ClaimStore
    build_s: float

    @property
    def bindings(self) -> list[Binding]:
        return [b for block in self.blocks for b in block.bindings]

    def size(self) -> dict[str, int]:
        cs = self.prefix
        return {"blocks": len(self.blocks), "versions": len(cs),
                "claims": sum(len(c.claims) for c in cs),
                "attributions": sum(len(c.attributions) for c in cs),
                "evidence_links": sum(len(c.evidence_links) for c in cs),
                "supersessions": sum(len(c.supersessions) for c in cs),
                "triples": len(self.store.graph), "window_versions": len(self.window),
                "bindings": len(self.bindings)}


def interleave(blocks: Sequence[Block], history_id: str, first: int, last: int,
               start_version: int) -> list[ChangeSet]:
    """Messages `first..last` (local versions) of every block, round robin, from
    `start_version` on."""
    out, version = [], start_version
    for t in range(first, last + 1):
        for block in blocks:
            if t > len(block.changesets):
                continue
            cs = block.changesets[t - 1]
            out.append(place(cs, "", history_id, version))
            version += 1
    return out


def build_graph(blocks: Sequence[Block], prefix_length: int, history_id: str) -> ScaledGraph:
    length = min(len(b.changesets) for b in blocks)
    if not 0 < prefix_length < length:
        raise ScaleError(f"prefix {prefix_length} must lie inside the block length {length}")
    prefix = interleave(blocks, history_id, 1, prefix_length, 1)
    window = interleave(blocks, history_id, prefix_length + 1, length, len(prefix) + 1)
    store = ClaimStore(history_id)
    start = time.perf_counter()
    for cs in prefix:
        store.commit(cs)
    return ScaledGraph(history_id, tuple(blocks), prefix_length, prefix, window, store,
                       time.perf_counter() - start)


def fork_store(store: ClaimStore) -> ClaimStore:
    """An independent copy of an append-only claim store at its head (same triples, change sets,
    entries and commit-rule state), without replaying the commits."""
    copy = ClaimStore(store.history_id, store.mode)
    copy.graph.extend(store.graph)
    copy._changesets = dict(store._changesets)
    copy._entries = dict(store._entries)
    copy._current = dict(store._current)
    copy._superseded = set(store._superseded)
    copy._head = store._head
    return copy


def admitted(bindings: Sequence[Binding], families: Iterable[str]) -> list[Binding]:
    """The bindings of the given template families (the view mix of a cell)."""
    wanted = set(families)
    if unknown := sorted(wanted - set(FAMILY.values())):
        raise ScaleError(f"unknown template families {unknown}")
    return [b for b in bindings if b.family in wanted]


def choose_views(bindings: Sequence[Binding], n: int, seed: int) -> list[Binding]:
    """The first `n` bindings of a seeded permutation (nested across `n`)."""
    if n > len(bindings):
        raise ScaleError(f"{n} standing views requested but the graph admits {len(bindings)}")
    order = list(bindings)
    random.Random(f"E004-views:{seed}").shuffle(order)
    return order[:n]


def read_sets(view_ids: Sequence[str], scope: int | str, reads: int, seed: int
              ) -> list[list[str] | None]:
    """Per read, the views it checks: None (all) or `scope` views drawn without replacement."""
    if scope == ALL:
        return [None] * reads
    if not isinstance(scope, int) or scope < 1:
        raise ScaleError(f"read_scope must be {ALL!r} or a positive integer, got {scope!r}")
    if scope > len(view_ids):
        raise ScaleError(f"read_scope {scope} exceeds the {len(view_ids)} standing views")
    rng = random.Random(f"E004-reads:{seed}:{len(view_ids)}:{scope}")
    ordered = sorted(view_ids)
    return [sorted(rng.sample(ordered, scope)) for _ in range(reads)]


# ---------------------------------------------------------------------------------------------
# Measurement


@dataclass
class Period:
    """One read period: `writes` committed change sets, then one read."""

    index: int
    writes: int
    commit_ms: float = 0.0
    match_ms: float = 0.0
    write_wall_ms: float = 0.0
    marks: int = 0
    read_db_ms: float = 0.0
    check_db_ms: float = 0.0
    maintain_db_ms: float = 0.0
    read_wall_ms: float = 0.0
    views_read: int = 0
    checks: int = 0
    maintained: int = 0
    repairs: list[list[str]] = field(default_factory=list)  # [view_id, action], action != advance
    units_rendered: int = 0

    def to_record(self) -> dict[str, Any]:
        record = {k: (round(v, 4) if isinstance(v, float) else v)
                  for k, v in self.__dict__.items()}
        record["write_ms"] = round(self.match_ms / self.writes, 5) if self.writes else 0.0
        return record


@dataclass
class Measurement:
    arm: str
    strategy: str
    periods: list[Period]
    setup_s: float
    wall_s: float
    cpu_s: float
    load_before: tuple[float, float, float]
    load_after: tuple[float, float, float]
    summary: Mapping[str, Any]


def measure(graph: ScaledGraph, views: Sequence[Binding], arm: str, *, writes_per_read: int,
            reads: int, scope_sets: Sequence[list[str] | None],
            config: ViewConfig | None = None) -> Measurement:
    """One arm over the first `reads * writes_per_read` change sets of the window."""
    needed = reads * writes_per_read
    if needed > len(graph.window):
        raise ScaleError(f"{reads} reads x {writes_per_read} writes need {needed} window change "
                         f"sets; the graph has {len(graph.window)}")
    if len(scope_sets) != reads:
        raise ScaleError("one read set per read is required")
    config = config or ViewConfig(state_speaker="user")
    setup = time.perf_counter()
    store = fork_store(graph.store)
    views_store = ViewStore(graph.history_id, config=config)
    strategy = make_arm(arm, views_store)
    strategy.prime(graph.prefix)
    for b in views:
        views_store.build(b, store, store.head)
    setup_s = time.perf_counter() - setup
    gc.collect()
    load_before = os.getloadavg()
    wall0, cpu0 = time.perf_counter(), time.process_time()
    periods = []
    window = iter(graph.window[:needed])
    for i in range(reads):
        period = Period(i, writes_per_read)
        for _ in range(writes_per_read):
            cs = next(window)
            t0 = time.perf_counter()
            store.commit(cs)
            t1 = time.perf_counter()
            record = strategy.write(cs, store)
            t2 = time.perf_counter()
            period.commit_ms += (t1 - t0) * 1000
            period.write_wall_ms += (t2 - t1) * 1000
            period.match_ms += record.match_ms
            period.marks += len(record.marks)
        t0 = time.perf_counter()
        read = strategy.read(store, store.head, read_id=f"read-{i}", view_ids=scope_sets[i])
        period.read_wall_ms = (time.perf_counter() - t0) * 1000
        period.views_read = len(read.checks)
        for c in read.checks:
            period.check_db_ms += c.check_db_ms
            period.maintain_db_ms += c.maintain_db_ms
            period.checks += c.checked
            period.units_rendered += c.units_rendered
            if c.maintained:
                period.maintained += 1
                if c.action != ADVANCE:
                    period.repairs.append([c.view_id, c.action])
        period.read_db_ms = period.check_db_ms + period.maintain_db_ms
        periods.append(period)
    wall_s, cpu_s = time.perf_counter() - wall0, time.process_time() - cpu0
    load_after = os.getloadavg()
    return Measurement(arm, strategy.name, periods, setup_s, wall_s, cpu_s, load_before,
                       load_after, strategy.log.summary())


_VALUES = re.compile(r"[ \t]*VALUES (\?_k\d+) \{ (<[^>\s]+>) \}\n")


def inline_constants(sparql: str) -> str:
    """The same SPARQL with every single-IRI `VALUES ?_kN { <iri> }` block removed and `?_kN`
    replaced by the IRI. An independent reimplementation of the compiler's inlining (since
    2026-11-26 `CompiledQuery.bind` inlines single-member constants itself); a diagnostic only."""
    values = dict((k, v) for k, v in _VALUES.findall(sparql))
    out = _VALUES.sub("", sparql)
    for var, iri in values.items():
        out = re.sub(re.escape(var) + r"\b", iri, out)
    return out


def diagnostic_bindings(graph: ScaledGraph, block0: Sequence[Binding], families: Iterable[str],
                        per_family: int, seed: int) -> list[tuple[Binding, bool]]:
    """Block 0's bindings (flag True) plus, per family, up to `per_family` bindings of the other
    blocks drawn by a seeded generator (flag False). Block 0's `choice` views are often empty;
    the sample shows the cost of views with rows on the whole graph."""
    out = [(b, True) for b in block0]
    first = {b.view_id for b in block0}
    rng = random.Random(f"E004-diagnostics:{seed}")
    for family in families:
        rest = [b for b in graph.bindings if b.family == family and b.view_id not in first]
        out += [(b, False) for b in rng.sample(rest, min(per_family, len(rest)))]
    return out


def query_diagnostics(graph: ScaledGraph, bindings: Sequence[Binding | tuple[Binding, bool]], *,
                      values_families: Iterable[str], repeats: int = 3,
                      config: ViewConfig | None = None) -> list[dict[str, Any]]:
    """Per binding, the time of its main SPARQL query at the prefix head in up to three forms,
    with the row count of each (they must agree), minimum of `repeats` timings each:

    - `compiled`: the text the engine runs (`CompiledQuery.bind`, single-member constants
      inlined since 2026-11-26);
    - `inlined`: the pre-change `VALUES` form inlined by `inline_constants` (an independent
      check; `inlined_text_equal` says whether it is the same text as `compiled`);
    - `values`: the pre-change form with every constant bound by `VALUES`
      (`bind(inline=False)`), only for block-0 bindings of `values_families` (it may take
      minutes per query on large graphs).

    `bindings` are bindings or (binding, in block 0) pairs; a plain binding counts as block 0.
    """
    config = config or ViewConfig(state_speaker="user")
    views_store = ViewStore(graph.history_id, config=config)
    values_families = set(values_families)
    store, head = graph.store, graph.store.head
    out = []
    for item in bindings:
        b, block0 = item if isinstance(item, tuple) else (item, True)
        query, _ = views_store.bind(b)
        compiled = Compiled.of(query, store.mode).main
        main, _ = compiled.bind({})
        values, _ = compiled.bind({}, inline=False)
        inlined = inline_constants(values)
        record: dict[str, Any] = {"view_id": b.view_id, "family": b.family, "block0": block0,
                                  "inlined_text_equal": inlined == main}
        variants = {"compiled": main, "inlined": inlined}
        if block0 and b.family in values_families:
            variants["values"] = values
        for name, sparql in variants.items():
            times, rows = [], None
            for _ in range(repeats):
                t = time.perf_counter()
                rows = sum(1 for _ in store.query(sparql, head))
                times.append((time.perf_counter() - t) * 1000)
            record[f"{name}_ms"] = round(min(times), 4)
            record[f"{name}_rows"] = rows
        out.append(record)
    return out


def arm_strategies(arms: Iterable[str]) -> dict[str, str]:
    """Arm name -> strategy name, from configs/views/staleness.yaml."""
    configured = load_arms()
    missing = [a for a in arms if a not in configured]
    if missing:
        raise ScaleError(f"arms {missing} are not in configs/views/staleness.yaml")
    return {a: configured[a][0] for a in arms}


def repair_signature(periods: Sequence[Period]) -> list[list[list[str]]]:
    return [sorted(p.repairs) for p in periods]


def action_counts(periods: Sequence[Period]) -> dict[str, int]:
    return dict(Counter(a for p in periods for _, a in p.repairs))


__all__ = ["ALL", "FAMILY", "GENERATOR_VERSION", "Block", "Measurement", "Period", "ScaleError",
           "ScaledGraph", "action_counts", "admitted", "arm_strategies", "build_graph",
           "choose_views", "diagnostic_bindings", "fork_store", "generate_block",
           "inline_constants", "interleave",
           "measure", "place", "query_diagnostics", "read_sets", "repair_signature"]
