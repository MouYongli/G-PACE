"""SHACL validation of the claims a change set touches (plan 5.2, "Structural validation").

The data graph is built from the RDF 1.1 serialisation (rdflib, which pyshacl uses, does not read
RDF 1.2 triple terms) of:

- every entry of the change set;
- every claim the change set touches (`ChangeSet.touched_claim_ids`), with all entries on those
  claims already in the store.

Focus nodes are the change set's entries and the touched claims, so a claim the patch does not
touch is never validated, however large the store. Shapes are in `resources/rdf/shapes.ttl`.
Domain exclusivity rules are not SHACL shapes; they belong to the attribution guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pyshacl
import rdflib

from grace.context.memory.graph import rdf
from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entries import Claim
from grace.context.memory.graph.vocabulary import RDF_DIR

SHAPES_FILE = RDF_DIR / "shapes.ttl"


@dataclass(frozen=True)
class ValidationReport:
    conforms: bool
    text: str
    focus_nodes: tuple[str, ...]


@lru_cache(maxsize=4)
def _shapes(path: Path) -> rdflib.Graph:
    if not path.is_file():
        raise FileNotFoundError(f"SHACL shapes not found: {path}")
    return rdflib.Graph().parse(path, format="turtle")


def _to_rdflib(triples) -> rdflib.Graph:
    text = rdf.to_ntriples(triples)
    return rdflib.Graph().parse(data=text, format="nt")


def validate_changeset(store, changeset: ChangeSet,
                       shapes: Path = SHAPES_FILE) -> ValidationReport:
    """Validate `changeset` against the store state at its head (the change set not yet
    committed, or already committed: its own entries are not duplicated)."""
    touched = changeset.touched_claim_ids()
    state = store.state(store.head)
    own = {e.entry_id for e in changeset.all_entries()}
    context = []
    for claim_id in sorted(touched):
        if claim_id in state.claims:
            context.append(state.claims[claim_id])
            context += state.attributions_on(claim_id)
            context += state.evidence_for(claim_id)
            context += state.supersessions_of(claim_id)
    triples = [t for e in context if e.entry_id not in own for t in rdf.entry_triples(e, "rdf11")]
    triples += rdf.changeset_triples(changeset, "rdf11")
    focus = sorted({rdf.entry_iri(type(e), e.entry_id).value for e in changeset.all_entries()}
                   | {rdf.entry_iri(Claim, c).value for c in touched})
    if not focus:
        return ValidationReport(True, "no focus nodes", ())
    conforms, _, text = pyshacl.validate(
        _to_rdflib(triples), shacl_graph=_shapes(shapes), inference="none",
        focus_nodes=[rdflib.URIRef(f) for f in focus], allow_infos=True, allow_warnings=False)
    return ValidationReport(bool(conforms), str(text), tuple(focus))
