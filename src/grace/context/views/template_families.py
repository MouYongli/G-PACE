"""The six template families of resident views, their bindings and the instantiation threshold.

Plan 5.4, "View selection": questions are invisible during ingestion, so resident views are
materialised from a template list. Each family is one file `resources/views/<family>.yaml` with a
query template in the text grammar of docs/research/query-ir.md and a sentence pattern:

| Family | Binding | Reference (change-sequences.md 6.2) |
| --- | --- | --- |
| `list` | (entity, predicate without an exclusivity rule) | V1 |
| `current` | (entity, predicate with an exclusivity rule) | V2 |
| `count` | (entity, predicate without an exclusivity rule) | V3 |
| `constraints` | task | V4 |
| `pending` | task | V5 |
| `choice` | task | V6 |

Query placeholders: `$subject`, `$predicate` (the binding), `$user`, `$assistant`,
`$state_speaker` (speaker IDs; `_` when `state_speaker` is null) and `$choice` (the choice
predicate) from `configs/views/default.yaml`.

Encodings the query fragment forces (shared with the reference encodings of
src/grace/cli/data/changeseq_crosscheck.py): `[u, f]` cannot require report mode own, positive
polarity or not derived (query-ir.md, open question 2; awaiting a decision); `constraints` leaves
the constraint predicate open; `pending` has one NOT EXISTS over `[user, _]`; `current` writes "no
valid end" as `end(?c) > 9999-12-31`. One choice of T018: `choice` joins every fact the assistant
informed about the chosen item (predicate variable `?attribute`) instead of one catalogue
predicate fixed per domain. A predicate the vocabulary
does not know has no exclusivity rule (plan 5.2: without one, values coexist).

Instantiation (`candidate_bindings`, `ViewStore.materialise`): a view is instantiated for a
binding once the number of distinct claims in the witnesses of its query at the version written
reaches the threshold of the config. Once instantiated, a resident view stays resident.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import quote

import yaml

from grace.config.paths import REPO_ROOT
from grace.context.memory.graph.entries import CommunicativeFunction
from grace.context.memory.graph.store import GraphState
from grace.context.memory.graph.vocabulary import Vocabulary, VocabularyError
from grace.context.pipeline.query.grammar import parse
from grace.context.pipeline.query.ir import Query
from grace.context.views.view import Binding, ViewError

VIEWS_DIR = REPO_ROOT / "resources" / "views"
VIEW_CONFIG = REPO_ROOT / "configs" / "views" / "default.yaml"
FAMILIES = ("list", "current", "count", "constraints", "pending", "choice")
BINDING_KINDS = ("entity_predicate", "task")
PREDICATE_KINDS = ("multi_valued", "exclusive")
RENDER_MODES = ("template", "llm")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_FAMILY_KEYS = {"family", "reference", "binding", "title", "query", "sentence"}
_CONFIG_KEYS = {"families", "instantiation_threshold", "thresholds", "speakers",
                "choice_predicate", "state_speaker", "rendering"}


def _yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ViewError(f"file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ViewError(f"{path}: expected a mapping")
    return data


def _entity(entity_id: str) -> str:
    return f"<{quote(entity_id, safe='')}>"


def _name(name: str, what: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ViewError(f"{what} {name!r} is not a predicate name [A-Za-z][A-Za-z0-9_]*")
    return name


# ---------------------------------------------------------------------------------------------
# Config


@dataclass(frozen=True)
class RenderingConfig:
    mode: str = "template"
    prompt: str = "render-view"
    max_rows_per_call: int = 16
    decoding: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in RENDER_MODES:
            raise ViewError(f"rendering mode {self.mode!r} not in {RENDER_MODES}")
        if not isinstance(self.max_rows_per_call, int) or self.max_rows_per_call < 1:
            raise ViewError("max_rows_per_call must be an integer >= 1")
        object.__setattr__(self, "decoding", MappingProxyType(dict(self.decoding)))


@dataclass(frozen=True)
class ViewConfig:
    families: tuple[str, ...] = FAMILIES
    instantiation_threshold: int = 1
    thresholds: Mapping[str, int] = field(default_factory=dict)
    speakers: Mapping[str, str] = field(
        default_factory=lambda: {"user": "user", "assistant": "assistant"})
    choice_predicate: str = "selectedService"
    state_speaker: str | None = None
    rendering: RenderingConfig = field(default_factory=RenderingConfig)

    def __post_init__(self) -> None:
        object.__setattr__(self, "families", tuple(self.families))
        if unknown := sorted(set(self.families) - set(FAMILIES)):
            raise ViewError(f"unknown template families {unknown}")
        for name, value in (("instantiation_threshold", self.instantiation_threshold),
                            *self.thresholds.items()):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ViewError(f"threshold {name} must be an integer >= 1, got {value!r}")
        if unknown := sorted(set(self.thresholds) - set(FAMILIES)):
            raise ViewError(f"thresholds for unknown families {unknown}")
        if set(self.speakers) != {"user", "assistant"}:
            raise ViewError("speakers must name exactly `user` and `assistant`")
        _name(self.choice_predicate, "choice_predicate")
        object.__setattr__(self, "thresholds", MappingProxyType(dict(self.thresholds)))
        object.__setattr__(self, "speakers", MappingProxyType(dict(self.speakers)))

    def threshold(self, family: str) -> int:
        return self.thresholds.get(family, self.instantiation_threshold)


def load_view_config(path: Path = VIEW_CONFIG) -> ViewConfig:
    data = _yaml(path)
    if set(data) != _CONFIG_KEYS:
        raise ViewError(f"{path}: expected exactly the keys {sorted(_CONFIG_KEYS)}")
    rendering = data["rendering"] or {}
    if not isinstance(rendering, dict) or not set(rendering) <= {
            "mode", "prompt", "max_rows_per_call", "decoding"}:
        raise ViewError(f"{path}: rendering takes mode, prompt, max_rows_per_call, decoding")
    return ViewConfig(tuple(data["families"]), data["instantiation_threshold"],
                      dict(data["thresholds"] or {}), dict(data["speakers"]),
                      data["choice_predicate"], data["state_speaker"],
                      RenderingConfig(**rendering))


# ---------------------------------------------------------------------------------------------
# Families


@dataclass(frozen=True)
class TemplateFamily:
    name: str
    reference: str
    binding_kind: str
    predicates: str | None
    title: str
    query_template: str
    sentence: str

    def __post_init__(self) -> None:
        if self.binding_kind not in BINDING_KINDS:
            raise ViewError(f"family {self.name}: binding {self.binding_kind!r} not in "
                            f"{BINDING_KINDS}")
        if (self.binding_kind == "entity_predicate") != (self.predicates is not None):
            raise ViewError(f"family {self.name}: `predicates` is required exactly for "
                            "entity_predicate bindings")
        if self.predicates is not None and self.predicates not in PREDICATE_KINDS:
            raise ViewError(f"family {self.name}: predicates {self.predicates!r} not in "
                            f"{PREDICATE_KINDS}")

    def bind(self, binding: Binding, config: ViewConfig) -> Query:
        """The family's query with the binding's parameters; type-checked."""
        if binding.family != self.name:
            raise ViewError(f"binding of family {binding.family} given to family {self.name}")
        if (binding.predicate is None) != (self.binding_kind == "task"):
            raise ViewError(f"family {self.name}: binding {binding.view_id} has the wrong shape")
        values = {"$subject": _entity(binding.subject),
                  "$user": _entity(config.speakers["user"]),
                  "$assistant": _entity(config.speakers["assistant"]),
                  "$state_speaker": (_entity(config.state_speaker)
                                     if config.state_speaker else "_"),
                  "$choice": config.choice_predicate}
        if binding.predicate is not None:
            values["$predicate"] = _name(binding.predicate, "predicate")
        text = self.query_template
        for key in sorted(values, key=len, reverse=True):
            text = text.replace(key, values[key])
        if "$" in text:
            raise ViewError(f"family {self.name}: unresolved placeholder in {text!r}")
        return parse(text)


def load_family(name: str, root: Path = VIEWS_DIR) -> TemplateFamily:
    path = Path(root) / f"{name}.yaml"
    data = _yaml(path)
    if not _FAMILY_KEYS <= set(data) <= _FAMILY_KEYS | {"predicates"}:
        raise ViewError(f"{path}: expected the keys {sorted(_FAMILY_KEYS)} (and `predicates`)")
    if data["family"] != name:
        raise ViewError(f"{path}: family {data['family']!r} != file name {name!r}")
    family = TemplateFamily(name, str(data["reference"]), data["binding"],
                            data.get("predicates"), data["title"], data["query"],
                            data["sentence"])
    # The template must parse once bound with dummy parameters.
    dummy = Binding(name, "x", "p" if family.binding_kind == "entity_predicate" else None)
    family.bind(dummy, ViewConfig())
    return family


def load_families(names: Iterable[str] = FAMILIES, root: Path = VIEWS_DIR
                  ) -> dict[str, TemplateFamily]:
    return {name: load_family(name, root) for name in names}


# ---------------------------------------------------------------------------------------------
# Bindings


def _exclusive(predicate: str, vocabulary: Vocabulary | None) -> bool:
    if vocabulary is None:
        return False
    try:
        return vocabulary.is_exclusive(predicate)
    except VocabularyError:
        return False  # no exclusivity rule known: values coexist (plan 5.2)


def candidate_bindings(state: GraphState, families: Mapping[str, TemplateFamily],
                       config: ViewConfig, vocabulary: Vocabulary | None = None
                       ) -> list[Binding]:
    """Bindings the claims visible in `state` could instantiate, before the threshold.

    (entity, predicate) pairs come from currently accepted claims (subjects as the representative
    of their entity class), except the choice predicate, which only the task families read. A
    task is the subject of a claim carrying a request by the user or an offer by the assistant.
    """
    reps = state.representatives()
    user, assistant = config.speakers["user"], config.speakers["assistant"]
    pairs: set[tuple[str, str]] = set()
    tasks: set[str] = set()
    for claim in state.claims.values():
        subject = reps.get(claim.subject, claim.subject)
        if state.is_current(claim.claim_id) and claim.predicate != config.choice_predicate:
            pairs.add((subject, claim.predicate))
    for a in state.attributions.values():
        if (a.speaker, a.function) in ((user, CommunicativeFunction.REQUEST),
                                       (assistant, CommunicativeFunction.OFFER)):
            claim = state.claims[a.claim_id]
            tasks.add(reps.get(claim.subject, claim.subject))
    out = []
    for name in config.families:
        family = families[name]
        if family.binding_kind == "task":
            out += [Binding(name, t) for t in sorted(tasks)]
            continue
        want = family.predicates == "exclusive"
        out += [Binding(name, s, p) for s, p in sorted(pairs)
                if _NAME.fullmatch(p) and _exclusive(p, vocabulary) == want]
    return out
