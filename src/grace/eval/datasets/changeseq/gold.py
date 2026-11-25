"""Event log -> gold claim graph (design docs/research/change-sequences.md, section 3.1).

Each primitive event maps deterministically to entries of the four kinds, all stamped with the
message's version t (contracts.md, "Claim graph"):

- `NewClaim(c, s, p, o, tau)`: claim c; evidence link (c, h_t);
- `Stance(c, f, rho, pi, derived)`: attribution of the message speaker; evidence link (c, h_t)
  unless one was added at t;
- `Supersede(c, eta)`: supersession (c, t, eta) with its replacing claim and licensing
  attribution.

Every version gets a change set (empty for fillers), so the store holds versions 1..N and G_t is
the set of entries stamped <= t. The entry types come from `context/memory/graph/`; nothing here
queries the graph. A supersession of kind change carries no `valid_end`: the design's historical
semantics (section 6.2) reads the valid end from the claim itself.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path

import pyshacl
import rdflib

from grace.context.memory.graph import rdf
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
from grace.context.memory.graph.shacl import SHAPES_FILE
from grace.context.memory.graph.store import ClaimStore
from grace.eval.datasets.changeseq.events import LogRecord, NewClaim, Stance, Supersede


class GoldGraphError(ValueError):
    """The gold graph of a sequence does not commit or does not conform to the shapes."""


def evidence_id(claim_id: str, version: int) -> str:
    return f"ev-{claim_id}-{version}"


def changeset(record: LogRecord, history_id: str,
              vocabulary_version: str | None = None) -> ChangeSet:
    t, m = record.version, record.message_id
    claims, atts, links, sups = [], [], [], []
    linked: set[str] = set()
    for e in record.events:
        if isinstance(e, NewClaim):
            obj = Entity(e.object) if e.object_type == "entity" else Value(e.object,
                                                                         e.object_type)
            claims.append(Claim(e.claim_id, e.subject, e.predicate, obj, None,
                                ValidTime(e.start, e.end), t))
            links.append(EvidenceLink(evidence_id(e.claim_id, t), e.claim_id, m, None, t))
            linked.add(e.claim_id)
    for e in record.events:
        if isinstance(e, Stance):
            atts.append(Attribution(
                e.attribution_id, e.claim_id, record.speaker, CommunicativeFunction(e.function),
                ReportMode(e.report_mode), Polarity(e.polarity), Certainty.CERTAIN, e.derived,
                m, t))
            if e.claim_id not in linked:
                links.append(EvidenceLink(evidence_id(e.claim_id, t), e.claim_id, m, None, t))
                linked.add(e.claim_id)
        elif isinstance(e, Supersede):
            sups.append(Supersession(e.supersession_id, e.claim_id, SupersessionKind(e.kind),
                                     None, e.replacing_claim_id, e.attribution_id, t))
    return ChangeSet(history_id, t, tuple(claims), tuple(atts), tuple(links), tuple(sups),
                     vocabulary_version)


def build_store(log: Sequence[LogRecord], history_id: str, *, validate: str | None = "graph",
                vocabulary_version: str | None = None) -> ClaimStore:
    """Commit the change set of every version to a fresh store.

    `validate`: `commit` validates the touched claims of every change set (T014's commit-time
    check); `graph` validates the whole final graph once against the same shapes; None skips.
    """
    store = ClaimStore(history_id)
    for record in log:
        cs = changeset(record, history_id, vocabulary_version)
        try:
            store.commit(cs, validate=validate == "commit")
        except Exception as exc:  # CommitError and SHACL failures carry the version
            raise GoldGraphError(f"{history_id} version {record.version}: {exc}") from exc
    if validate == "graph":
        conforms, text = validate_graph(store)
        if not conforms:
            raise GoldGraphError(f"{history_id}: gold graph does not conform:\n{text}")
    return store


# pyshacl and rdflib keep process-wide state (SPARQL query preparation): concurrent validations
# from the parallel sequence builds of `build_dataset` reported spurious violations, so validation
# runs one at a time.
_VALIDATION = threading.Lock()


def validate_graph(store: ClaimStore, shapes: Path = SHAPES_FILE) -> tuple[bool, str]:
    """SHACL validation of every entry of the store (RDF 1.1 serialisation), T014 shapes."""
    with _VALIDATION:
        data = rdflib.Graph().parse(data=rdf.to_ntriples(store.triples()) or "\n", format="nt")
        shape_graph = rdflib.Graph().parse(shapes, format="turtle")
        conforms, _, text = pyshacl.validate(data, shacl_graph=shape_graph, inference="none",
                                             allow_infos=True, allow_warnings=False)
    return bool(conforms), str(text)
