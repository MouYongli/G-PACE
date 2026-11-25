"""Core vocabulary, alias table, exclusivity rules and vocabulary versions (plan 5.2).

The RDF terms of the model live in `resources/rdf/`: `core.ttl` (classes and properties, mapped to
PROV-O, OWL-Time, SKOS and Web Annotation), `functions.ttl` (the SKOS scheme of communicative
functions with ISO 24617-2 correspondences), `shapes.ttl` (SHACL) and `predicates.yaml` (domain
predicates, exclusivity rules, aliases). This module holds the namespaces and the predicate table.

A `Vocabulary` is immutable. A vocabulary change (an alias, a new predicate) produces a new
`Vocabulary` with a new version label; the old one stays valid for reads at earlier versions.
Vocabulary changes fall outside the soundness proposition (plan 3.4); the change set records the
version in force so that the engine can invalidate views when it changes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import yaml

from grace.config.paths import REPO_ROOT

RDF_DIR = REPO_ROOT / "resources" / "rdf"
PREDICATES_FILE = RDF_DIR / "predicates.yaml"

# Namespaces. The `example.org` base is a placeholder until the release namespace is decided.
BASE = "https://example.org/grace/"
GRACE = BASE + "ns#"            # core classes and properties
FUNCTION = BASE + "function#"   # SKOS concepts of communicative functions
PREDICATE = BASE + "predicate/"  # domain predicates
ENTITY = BASE + "entity/"       # entities and speakers
ENTRY = BASE + "entry/"         # claims, attributions, evidence links, supersessions, merges
MESSAGE = BASE + "message/"     # message IDs of the history
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"
PROV = "http://www.w3.org/ns/prov#"
TIME = "http://www.w3.org/2006/time#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
OA = "http://www.w3.org/ns/oa#"
SH = "http://www.w3.org/ns/shacl#"

PREFIXES = {
    "g": GRACE, "gf": FUNCTION, "gp": PREDICATE, "ge": ENTITY, "gx": ENTRY, "gm": MESSAGE,
    "rdf": RDF, "rdfs": RDFS, "xsd": XSD, "prov": PROV, "time": TIME, "skos": SKOS, "oa": OA,
}
SPARQL_PREFIXES = "".join(f"PREFIX {k}: <{v}>\n" for k, v in PREFIXES.items())

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


class VocabularyError(ValueError):
    """A predicate is unknown, or a vocabulary file or change is malformed."""


@dataclass(frozen=True)
class PredicateSpec:
    """A domain predicate; `exclusive` means it has an exclusivity rule (plan 3.2)."""

    name: str
    exclusive: bool

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME.fullmatch(self.name):
            raise VocabularyError(f"predicate name {self.name!r} is not [A-Za-z][A-Za-z0-9_]*")
        if not isinstance(self.exclusive, bool):
            raise VocabularyError(f"predicate {self.name}: `exclusive` must be a boolean")


@dataclass(frozen=True)
class Vocabulary:
    """One version of the predicate table and alias table."""

    version: str
    predicates: Mapping[str, PredicateSpec]
    aliases: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version:
            raise VocabularyError("vocabulary version must be a non-empty string")
        for name, spec in self.predicates.items():
            if spec.name != name:
                raise VocabularyError(f"predicate key {name!r} != spec name {spec.name!r}")
        for alias, target in self.aliases.items():
            if target not in self.predicates:
                raise VocabularyError(f"alias {alias!r} points to unknown predicate {target!r}")
        object.__setattr__(self, "predicates", MappingProxyType(dict(self.predicates)))
        object.__setattr__(self, "aliases", MappingProxyType(
            {_normalise(a): t for a, t in self.aliases.items()}))

    def resolve(self, name: str) -> str:
        """The predicate a name or alias denotes; raises VocabularyError if there is none."""
        if name in self.predicates:
            return name
        target = self.aliases.get(_normalise(name))
        if target is None:
            raise VocabularyError(f"unknown predicate or alias {name!r} in vocabulary "
                                  f"{self.version}")
        return target

    def is_exclusive(self, predicate: str) -> bool:
        return self.predicates[self.resolve(predicate)].exclusive

    def __contains__(self, predicate: object) -> bool:
        return isinstance(predicate, str) and predicate in self.predicates

    def extend(self, version: str, predicates: Mapping[str, bool] | None = None,
               aliases: Mapping[str, str] | None = None) -> Vocabulary:
        """A new version with added predicates (name -> exclusive) and aliases.

        Existing predicates and aliases are never redefined: old definitions are kept (plan 5.2).
        """
        if version == self.version:
            raise VocabularyError(f"a new vocabulary needs a new version, got {version!r}")
        new_predicates = dict(self.predicates)
        for name, exclusive in (predicates or {}).items():
            if name in new_predicates:
                raise VocabularyError(f"predicate {name!r} already defined")
            new_predicates[name] = PredicateSpec(name, exclusive)
        new_aliases = dict(self.aliases)
        for alias, target in (aliases or {}).items():
            if _normalise(alias) in new_aliases:
                raise VocabularyError(f"alias {alias!r} already defined")
            new_aliases[alias] = target
        return Vocabulary(version, new_predicates, new_aliases)


def _normalise(alias: str) -> str:
    return " ".join(alias.casefold().split())


def load_vocabulary(path: Path = PREDICATES_FILE) -> Vocabulary:
    """Read the predicate table; fail loudly on a missing file or an unknown key."""
    if not path.is_file():
        raise VocabularyError(f"vocabulary file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"version", "predicates", "aliases"}:
        raise VocabularyError(f"{path}: expected exactly the keys version, predicates, aliases")
    predicates = {}
    for name, spec in (data["predicates"] or {}).items():
        if not isinstance(spec, dict) or set(spec) != {"exclusive"}:
            raise VocabularyError(f"{path}: predicate {name!r} must be {{exclusive: bool}}")
        predicates[name] = PredicateSpec(name, spec["exclusive"])
    return Vocabulary(str(data["version"]), predicates, dict(data["aliases"] or {}))


def predicate_iri(name: str) -> str:
    return PREDICATE + name
