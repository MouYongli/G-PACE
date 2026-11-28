"""The write path after the log append: extraction, validation, guard and commit (plan 5.1).

`Updater` holds the writer side of one history: the message log (read only here; the engine
appends), the claim store, an `Extractor` and the history-local vocabulary. The engine calls

- `write(message)` after a message arrives: the message is appended to the log (an identical retry
  is a no-op) and every complete extraction unit among the pending messages is processed;
- `flush(version, read_id)` before a read at `version` that falls inside an incomplete unit: the
  part that has arrived is extracted now (trigger `read`, still write cost W; plan 8.4);
- `finish()` at the end of the history.

Pending messages are those after the store head: every version of a processed unit is committed,
as an empty change set when nothing came of it, so the store head is the writer's head and a state
restored from the log and the store resumes correctly.

**Per unit** (see the modules for each step):

1. `candidates.py` builds what the writer may see from the graph at the head and the vocabulary;
   `extract.py` makes one call. The writer never sees views, staleness marks or fingerprints.
2. Invalid output: the unit is split in halves and each half extracted on its own
   (`split_on_invalid`), down to single messages; a single message that still fails is committed
   empty. Failed call (every attempt failed): the unit stays pending and is retried on the next
   step, up to `max_unit_failures` times; then it is committed empty. Either way the messages stay
   in the log and the text indexes: a failed patch leaves the raw-text path intact.
3. `validate.py` resolves the patch; dropped items are recorded with a reason.
4. Per message of the unit, in version order, one change set stamped with that message's version
   (knowledge versions follow the evidence message, plan 8.4): entity equivalences, then claims,
   then stances. A claim that repeats a currently accepted proposition becomes an attribution and an
   evidence link on it. A new claim goes through the attribution guard (`guard.py`); a stance that
   asks to end a known claim must first quote evidence that mentions that claim
   (`validate.ending_evidence`; dropped with reason `ended_without_quote` or
   `ended_without_evidence` and counted in the note `ending_dropped` otherwise), then goes through
   the guard's removal rule. `commit.py` commits the change set.

Entity IDs are grammar-safe names made by `validate.EntityTable`; the surface names they came
from are kept in `entity_labels` and saved in the writer state (`writer.json`). They are also
written to the graph as entity labels (contracts.md, "Claim graph", version 0.3): a label goes into
the change set of the first version whose entries name the entity (subject, entity object,
speaker or merged entity) and that the store does not reject, once per entity. A label of an
entity whose claims were all dropped stays in the writer state only, until an entry names it.

Deferred resolution (T027, append-only baseline): with `deferred` (a `deferred.ResolutionLog`)
the guard still decides against the state as resolved at the writer's head, so known claims and
repeated mentions behave as in the main configuration, but no supersession is committed; the
guard's inputs (exclusivity and correction of every new claim, kind and valid end of every ending
stance) are recorded in the log instead, and the read path resolves conflicts at query time.

Every call of a unit, including retries, invalid outputs and failed attempts, is in the cost
ledger by construction (`grace.llm.client`); `UnitResult.call_ids` lists them with their statuses.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT
from grace.context.api import HistoryInfo, Message, WriteTrace
from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.entries import (
    Attribution,
    Claim,
    Entity,
    ValidTime,
)
from grace.context.memory.graph.store import ClaimStore, GraphState
from grace.context.memory.graph.vocabulary import Vocabulary, load_vocabulary
from grace.context.memory.history.log import MessageLog
from grace.context.pipeline.update.candidates import build_candidates
from grace.context.pipeline.update.commit import ChangeSetBuilder, commit_version
from grace.context.pipeline.update.deferred import ResolutionLog, resolve_at_read
from grace.context.pipeline.update.extract import Extraction, Extractor, LLMWriter, WriterInput
from grace.context.pipeline.update.guard import Guard, Pending
from grace.context.pipeline.update.patch import ClaimPatch
from grace.context.pipeline.update.segment import Granularity, Segmenter, Unit
from grace.context.pipeline.update.validate import (
    Dropped,
    EntityTable,
    LocalVocabulary,
    Resolution,
    ResolvedAlias,
    ResolvedClaim,
    ResolvedStance,
    ending_evidence,
    resolve_patch,
    speaker_of,
)
from grace.llm.client import ChatClient
from grace.llm.prompts import PROMPTS_DIR, load_pinned
from grace.llm.structured import SCHEMAS_DIR, load_schema

CONFIG_FILE = REPO_ROOT / "configs" / "common" / "writer.yaml"
PROMPT_REGISTRY = REPO_ROOT / "configs" / "common" / "prompts.yaml"
STATE_FILE = "writer.json"


# ---------------------------------------------------------------------------------------------
# Configuration


@dataclass(frozen=True)
class WriterConfig:
    prompt: str = "extract-claims"
    schema: str = "extract-claims"
    granularity: Granularity = Granularity("segment", 8)
    context_messages: int = 2
    structured_output: str = "json_schema"
    split_on_invalid: bool = True
    max_unit_failures: int = 2
    unknown_predicates: str = "local"
    guard: bool = True
    shacl: bool = True
    max_known_claims: int = 40
    max_predicates: int = 80
    max_entities: int = 40
    recent_versions: int = 8
    message_chars: int | None = 4000
    earlier_chars: int | None = 600
    decoding: Mapping[str, Any] = field(default_factory=lambda: {"temperature": 0.0,
                                                                 "max_tokens": 4096})

    def __post_init__(self) -> None:
        if self.context_messages < 0:
            raise ValueError("context_messages must be >= 0")
        if self.max_unit_failures < 1:
            raise ValueError("max_unit_failures must be >= 1")
        if self.unknown_predicates not in ("local", "drop"):
            raise ValueError("unknown_predicates must be local or drop")
        if self.structured_output not in ("json_schema", "none"):
            raise ValueError("structured_output must be json_schema or none")

    @classmethod
    def from_record(cls, raw: Mapping[str, Any]) -> WriterConfig:
        if not isinstance(raw, Mapping) or raw.get("version") != 1:
            raise ValueError("writer config: expected a mapping with version: 1")
        known = {f for f in cls.__dataclass_fields__} | {"version"}
        if unknown := sorted(set(raw) - known):
            raise ValueError(f"writer config: unknown keys {unknown}")
        values = {k: v for k, v in raw.items() if k != "version"}
        if "granularity" in values:
            values["granularity"] = Granularity.from_record(values["granularity"])
        return cls(**values)

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> WriterConfig:
        return cls.from_record(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def llm_writer(config: WriterConfig, client: ChatClient, history: HistoryInfo | None = None, *,
               registry: Path = PROMPT_REGISTRY, prompts_root: Path = PROMPTS_DIR,
               schemas_root: Path = SCHEMAS_DIR) -> LLMWriter:
    """GRACE's LLM writer with the pinned prompt and schema of `config`.

    Message dates fall back to the session timestamps of `history` (contracts.md, "History")."""
    prompt = load_pinned(config.prompt, registry, root=prompts_root)
    schema_path = Path(schemas_root) / f"{config.schema}.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    dates = ({s.segment_id: s.timestamp for s in history.segments} if history is not None
             else {})
    return LLMWriter(client=client, prompt=prompt, validator=load_schema(config.schema,
                                                                         schemas_root),
                     schema=schema, structured_output=config.structured_output,
                     decoding=dict(config.decoding), message_chars=config.message_chars,
                     earlier_chars=config.earlier_chars, dates=dates)


# ---------------------------------------------------------------------------------------------
# Results


@dataclass
class UnitResult:
    """What one extraction unit did; `to_record` is one line of the writer's update log."""

    history_id: str
    first_version: int
    last_version: int
    message_ids: tuple[str, ...]
    partial: bool
    trigger: str
    read_id: str | None
    status: str = "ok"     # ok, invalid_output, failed (retry later), failed_final, split
    error: str | None = None
    raw_output: str | None = None
    call_ids: tuple[str, ...] = ()
    call_statuses: tuple[str, ...] = ()
    changesets: list[ChangeSet] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)
    commit_errors: list[dict] = field(default_factory=list)
    notes: Counter = field(default_factory=Counter)
    timings_ms: dict[str, float] = field(default_factory=dict)

    @property
    def committed(self) -> bool:
        return bool(self.changesets)

    def counts(self) -> dict[str, int]:
        out = Counter()
        for cs in self.changesets:
            out["claims"] += len(cs.claims)
            out["attributions"] += len(cs.attributions)
            out["evidence_links"] += len(cs.evidence_links)
            out["supersessions"] += len(cs.supersessions)
            out["entity_merges"] += len(cs.entity_merges)
            out["entity_labels"] += len(cs.entity_labels)
        return {k: out[k] for k in ("claims", "attributions", "evidence_links", "supersessions",
                                    "entity_merges", "entity_labels")}

    def trace(self) -> WriteTrace:
        """The `traces/write.jsonl` record of this unit (the engine adds staleness marks)."""
        return WriteTrace(self.history_id, self.last_version, self.message_ids, self.call_ids,
                          (), dict(self.timings_ms))

    def to_record(self) -> dict[str, Any]:
        return {
            "history_id": self.history_id, "first_version": self.first_version,
            "last_version": self.last_version, "message_ids": list(self.message_ids),
            "partial": self.partial, "trigger": self.trigger, "read_id": self.read_id,
            "status": self.status, "error": self.error, "call_ids": list(self.call_ids),
            "call_statuses": list(self.call_statuses),
            "committed_versions": [cs.version for cs in self.changesets],
            "entries": self.counts(), "dropped": [d.to_record() for d in self.dropped],
            "conflicts": self.conflicts, "blocked": self.blocked,
            "commit_errors": self.commit_errors, "notes": dict(sorted(self.notes.items())),
            "raw_output": self.raw_output, "timings_ms": dict(self.timings_ms),
        }


# ---------------------------------------------------------------------------------------------
# Matching helpers


def _rep(entity: str, reps: Mapping[str, str]) -> str:
    return reps.get(entity, entity)


def _object_key(claim_object, reps: Mapping[str, str]):
    if isinstance(claim_object, Entity):
        return ("entity", _rep(claim_object.id, reps))
    return ("value", claim_object.lexical, claim_object.datatype)


def _times_agree(old: ValidTime, new: ValidTime) -> bool:
    """A repeated mention: equal bounds, or bounds on at most one side (the phrase is ignored)."""
    old_b, new_b = (old.start, old.end), (new.start, new.end)
    return old_b == new_b or old_b == (None, None) or new_b == (None, None)


def _same_proposition(claim: Claim, rc: ResolvedClaim, reps: Mapping[str, str]) -> bool:
    return (claim.predicate == rc.predicate and claim.scope == rc.scope
            and _rep(claim.subject, reps) == _rep(rc.subject, reps)
            and _object_key(claim.object, reps) == _object_key(rc.object, reps)
            and _times_agree(claim.valid_time, rc.valid_time))


# ---------------------------------------------------------------------------------------------
# Updater


class Updater:
    """Write path of one history after the log append (module docstring)."""

    def __init__(self, history: HistoryInfo, log: MessageLog, store: ClaimStore,
                 extractor: Extractor, config: WriterConfig | None = None, *,
                 vocabulary: Vocabulary | None = None, deferred: ResolutionLog | None = None):
        if log.history_id != history.history_id or store.history_id != history.history_id:
            raise ValueError("history, log and store must belong to one history")
        self.history = history
        self.log = log
        self.store = store
        self.extractor = extractor
        self.config = config or WriterConfig()
        self.vocabulary = LocalVocabulary(vocabulary or load_vocabulary(),
                                          self.config.unknown_predicates)
        self.guard = Guard(enabled=self.config.guard)
        self.deferred = deferred  # None: supersessions are committed at write (main config)
        self._notes: list[tuple] = []  # guard inputs of the change set being built (deferred)
        self.segmenter = Segmenter(self.config.granularity, history)
        self.failures: Counter = Counter()      # first version of a unit -> failed extractions
        self.entity_labels: dict[str, str] = {}  # entity ID -> surface name it was made from

    # -- engine entry points -------------------------------------------------------------------

    @property
    def head(self) -> int:
        """The last version the writer has committed."""
        return self.store.head

    def pending(self, upto: int | None = None) -> list[Message]:
        upto = self.log.head if upto is None else min(upto, self.log.head)
        return [m for m in self.log.messages(upto) if m.version > self.store.head]

    def write(self, message: Message) -> list[UnitResult]:
        self.log.append(message)
        return self._run(self.segmenter.units(self.pending()), "write", None)

    def flush(self, version: int, read_id: str | None = None) -> list[UnitResult]:
        """Extract the pending messages up to `version` before a read (trigger `read`).

        A failed call is retried at once until it succeeds or reaches `max_unit_failures`, so
        that nothing up to `version` is pending when the read starts."""
        return self._drain(version, "read", read_id)

    def finish(self) -> list[UnitResult]:
        """Extract every pending message (end of the history), retrying failed calls as `flush`."""
        return self._drain(None, "write", None)

    def _drain(self, upto: int | None, trigger: str, read_id: str | None) -> list[UnitResult]:
        out: list[UnitResult] = []
        while pending := self.pending(upto):
            results = self._run(self.segmenter.units(pending, flush=True), trigger, read_id)
            out += results
            if not results or results[-1].status != "failed":
                break
        return out

    def _state(self) -> GraphState:
        """The graph at the writer's head; resolved at query time when deferred."""
        state = self.store.state(self.store.head)
        if self.deferred is None:
            return state
        return resolve_at_read(state, self.deferred, self.guard).state

    # -- save and restore ----------------------------------------------------------------------

    def state_record(self) -> dict[str, Any]:
        return {"history_id": self.history.history_id, "head": self.store.head,
                "vocabulary": self.vocabulary.to_record(),
                "failures": {str(k): v for k, v in sorted(self.failures.items())},
                "entity_labels": dict(sorted(self.entity_labels.items()))}

    def save(self, directory: Path) -> Path:
        path = Path(directory) / STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as f:
            f.write(json.dumps(self.state_record(), indent=2, sort_keys=True) + "\n")
        return path

    def restore_state(self, directory: Path) -> None:
        record = json.loads((Path(directory) / STATE_FILE).read_text(encoding="utf-8"))
        if record["history_id"] != self.history.history_id or record["head"] != self.store.head:
            raise ValueError(f"{directory}: writer state does not match the restored store")
        self.vocabulary = LocalVocabulary.from_record(self.vocabulary.seed, record["vocabulary"])
        self.failures = Counter({int(k): v for k, v in record["failures"].items()})
        self.entity_labels = {**self.store.state(self.store.head).entity_labels(),
                              **record.get("entity_labels", {})}

    # -- units ---------------------------------------------------------------------------------

    def _run(self, units: Sequence[Unit], trigger: str, read_id: str | None) -> list[UnitResult]:
        out: list[UnitResult] = []
        for unit in units:
            results = self._unit(unit, trigger, read_id)
            out += results
            if results and results[-1].status == "failed":
                break   # the unit stays pending; later units must wait for it
        return out

    def _participants(self) -> tuple[str, ...]:
        seen = dict.fromkeys(speaker_of(m) for m in self.log.messages())
        return tuple(seen)

    def _request(self, unit: Unit, state: GraphState, trigger: str,
                 read_id: str | None) -> WriterInput:
        text = " ".join(m.text for m in unit.messages)
        participants = self._participants()
        candidates = build_candidates(
            state, self.vocabulary.current, text, unit.first_version,
            predicate_uses=self.vocabulary.uses, speakers=participants,
            max_claims=self.config.max_known_claims, max_predicates=self.config.max_predicates,
            max_entities=self.config.max_entities, recent_versions=self.config.recent_versions)
        start = max(0, unit.first_version - 1 - self.config.context_messages)
        earlier = tuple(self.log.messages(unit.first_version - 1)[start:])
        return WriterInput(self.history.history_id, unit.messages, earlier, candidates,
                           participants, trigger, read_id if trigger == "read" else None)

    def _result(self, unit: Unit, trigger: str, read_id: str | None) -> UnitResult:
        return UnitResult(self.history.history_id, unit.first_version, unit.last_version,
                          tuple(m.message_id for m in unit.messages), unit.partial, trigger,
                          read_id)

    def _commit_empty(self, unit: Unit, result: UnitResult) -> None:
        for m in unit.messages:
            builder = ChangeSetBuilder(self.history.history_id, m.version,
                                       self.vocabulary.version)
            cs, _ = commit_version(self.store, builder, validate=False)
            result.changesets.append(cs)

    def _unit(self, unit: Unit, trigger: str, read_id: str | None) -> list[UnitResult]:
        started = time.perf_counter()
        state = self._state()
        request = self._request(unit, state, trigger, read_id)
        extraction: Extraction = self.extractor.extract(request)
        extract_ms = (time.perf_counter() - started) * 1000
        result = self._result(unit, trigger, read_id)
        result.call_ids, result.call_statuses = extraction.call_ids, extraction.statuses
        result.raw_output, result.error = extraction.raw, extraction.error
        result.timings_ms["extract"] = round(extract_ms, 3)
        if extraction.status == "failed":
            self.failures[unit.first_version] += 1
            if self.failures[unit.first_version] < self.config.max_unit_failures:
                result.status = "failed"
                return [result]
            result.status = "failed_final"
            self._commit_empty(unit, result)
            return [result]
        if extraction.status == "invalid_output":
            if self.config.split_on_invalid and len(unit) > 1:
                result.status = "split"
                first, second = unit.split()
                out = [result, *self._unit(first, trigger, read_id)]
                if out[-1].status == "failed":
                    return out
                return out + self._unit(second, trigger, read_id)
            result.status = "invalid_output"
            self._commit_empty(unit, result)
            return [result]
        self._apply(unit, extraction.patch, request, result)
        result.timings_ms["apply"] = round((time.perf_counter() - started) * 1000 - extract_ms,
                                           3)
        return [result]

    # -- applying a patch ----------------------------------------------------------------------

    def _apply(self, unit: Unit, patch: ClaimPatch, request: WriterInput,
               result: UnitResult) -> None:
        state = self._state()
        entities = EntityTable.from_state(state, request.participants,
                                          {**state.entity_labels(), **self.entity_labels})
        ordered = ClaimPatch(tuple(sorted(patch.claims, key=lambda c: c.message)),
                             patch.stances, patch.aliases)
        added_before = len(self.vocabulary.added)
        resolution = resolve_patch(ordered, unit.messages, self.vocabulary, entities,
                                   request.candidates.handles)
        result.dropped += resolution.dropped
        result.notes.update(resolution.notes)
        self.entity_labels.update(entities.new_labels)
        if entities.normalised:
            result.notes["entity_id_normalised"] += entities.normalised
        additions = self.vocabulary.added[added_before:]
        local_ids: dict[str, str] = {}
        for message in unit.messages:
            label = self._label(message.version, additions, added_before)
            self._apply_message(message, resolution, local_ids, label, result)

    def _label(self, version: int, additions: list[dict], added_before: int) -> str:
        """Vocabulary label in force at `version`: additions of earlier messages count."""
        upto = [a for a in additions if a["version"] <= version]
        if upto:
            return upto[-1]["vocabulary_version"]
        if added_before:
            return self.vocabulary.added[added_before - 1]["vocabulary_version"]
        return self.vocabulary.seed.version

    def _apply_message(self, message: Message, resolution: Resolution,
                       local_ids: dict[str, str], label: str, result: UnitResult) -> None:
        version = message.version
        state = self._state()
        builder = ChangeSetBuilder(self.history.history_id, version, label)
        self._notes = []
        claims, stances, aliases = resolution.for_message(version)
        attributed: set[tuple] = set()
        new_here: set[str] = set()

        reps = self._aliases(aliases, state, builder, result)
        pending = Pending(reps=reps)
        for rc in claims:
            existing = self._find_current(rc, state, pending, reps)
            if existing is not None:
                key = (existing.claim_id, rc.speaker, rc.stance)
                if key in attributed:
                    result.notes["duplicate_in_message"] += 1
                else:
                    attributed.add(key)
                    a = builder.attribution(existing.claim_id, rc.speaker, rc.stance,
                                            message.message_id)
                    pending.add_attribution(a)
                    builder.evidence_link(existing.claim_id, message.message_id, rc.span)
                    if existing.claim_id not in new_here:
                        result.notes["repeated_mention"] += 1
                if rc.local_id is not None:
                    local_ids[rc.local_id] = existing.claim_id
                continue
            claim = builder.claim(rc.subject, rc.predicate, rc.object, rc.scope, rc.valid_time)
            a = builder.attribution(claim.claim_id, rc.speaker, rc.stance, message.message_id)
            builder.evidence_link(claim.claim_id, message.message_id, rc.span)
            attributed.add((claim.claim_id, rc.speaker, rc.stance))
            decision = self.guard.replacement(state, claim, a, exclusive=rc.exclusive,
                                              correction=rc.correction, pending=pending)
            if self.deferred is not None:
                self._notes.append(("claim", claim.claim_id, rc.exclusive, rc.correction))
            for s in decision.supersede:
                if self.deferred is None:
                    builder.supersession(s.claim_id, s.kind, s.valid_end, s.replacing_claim_id,
                                         a.attribution_id)
                pending.superseded.add(s.claim_id)
            for c in decision.conflicts:
                result.conflicts.append({"version": version, "kept": c.kept_claim_id,
                                         "new": c.new_claim_id, "reason": c.reason})
            pending.add_claim(claim)
            pending.add_attribution(a)
            new_here.add(claim.claim_id)
            if rc.local_id is not None:
                local_ids[rc.local_id] = claim.claim_id

        for rs in stances:
            self._stance(rs, state, pending, builder, local_ids, attributed, result)

        labelled = state.entity_labels()
        for entity in sorted(builder.named_entities()):
            if entity in self.entity_labels and entity not in labelled:
                builder.label(entity, self.entity_labels[entity])
        cs, error = commit_version(self.store, builder, validate=self.config.shacl)
        result.changesets.append(cs)
        self._record_notes(cs)
        if error is not None:
            result.commit_errors.append({"version": version, "error": error})
            lost = {c.claim_id for c in builder.claims}
            for local, cid in list(local_ids.items()):
                if cid in lost:
                    del local_ids[local]

    def _record_notes(self, cs: ChangeSet | None) -> None:
        """Deferred mode: log the guard inputs of the entries the store actually committed, so
        that a rejected change set leaves no hint behind (and a retry cannot meet one)."""
        notes, self._notes = self._notes, []
        if self.deferred is None or cs is None:
            return
        claims = {c.claim_id for c in cs.claims}
        attributions = {a.attribution_id for a in cs.attributions}
        for kind, entry, x, y in notes:
            if kind == "claim" and entry in claims:
                self.deferred.note_claim(entry, exclusive=x, correction=y)
            elif kind == "ending" and entry in attributions:
                self.deferred.note_ending(entry, x, y)

    def _find_current(self, rc: ResolvedClaim, state: GraphState, pending: Pending,
                      reps: Mapping[str, str]) -> Claim | None:
        for c in pending.claims:
            if c.claim_id not in pending.superseded and _same_proposition(c, rc, reps):
                return c
        matches = [c for c in state.claims.values()
                   if c.claim_id not in pending.superseded and state.is_current(c.claim_id)
                   and _same_proposition(c, rc, reps)]
        return min(matches, key=lambda c: (c.version, c.claim_id)) if matches else None

    def _aliases(self, aliases: Sequence[ResolvedAlias], state: GraphState,
                 builder: ChangeSetBuilder, result: UnitResult) -> dict[str, str]:
        """Append equivalence entries; return the representatives including them, so that a
        mention under the alias in the same message matches the known claim."""
        merged = dict(state.representatives())

        def find(x: str) -> str:
            while merged.get(x, x) != x:
                x = merged[x]
            return x

        for alias in aliases:
            a, b = find(alias.entity_a), find(alias.entity_b)
            if a == b:
                result.notes["alias_known"] += 1
                continue
            builder.equivalence(alias.entity_a, alias.entity_b)
            merged[max(a, b)] = min(a, b)
            merged.setdefault(min(a, b), min(a, b))
        return {x: find(x) for x in merged}

    def _stance(self, rs: ResolvedStance, state: GraphState, pending: Pending,
                builder: ChangeSetBuilder, local_ids: Mapping[str, str], attributed: set,
                result: UnitResult) -> None:
        claim_id = local_ids.get(rs.claim) if rs.local else rs.claim
        if claim_id is None:
            result.dropped.append(Dropped("stance", "unresolved_local_id", rs.claim))
            return
        if claim_id not in state.claims and claim_id not in {c.claim_id for c in pending.claims}:
            result.dropped.append(Dropped("stance", "unknown_claim", claim_id))
            return
        if rs.ends is not None and not rs.local and claim_id in state.claims:
            # Ending a known claim needs a quote that mentions it (validate.ending_evidence).
            claim = state.claims[claim_id]
            quote = (rs.message.text[rs.span.start:rs.span.end] if rs.span is not None
                     else None)
            label = (self.entity_labels.get(claim.object.id)
                     if isinstance(claim.object, Entity) else None)
            reason = ending_evidence(claim.predicate, claim.object, quote, label)
            if reason is not None:
                result.dropped.append(Dropped("stance", reason, claim_id))
                result.notes["ending_dropped"] += 1
                return
        key = (claim_id, rs.speaker, rs.stance)
        if key in attributed:
            result.notes["duplicate_in_message"] += 1
            return
        attributed.add(key)
        a: Attribution = builder.attribution(claim_id, rs.speaker, rs.stance,
                                             rs.message.message_id)
        builder.evidence_link(claim_id, rs.message.message_id, rs.span)
        if rs.ends is not None and self.deferred is not None:
            self._notes.append(("ending", a.attribution_id, rs.ends, rs.valid_end))
        if rs.ends is not None:
            current = claim_id not in pending.superseded and (
                claim_id not in state.claims or state.is_current(claim_id))
            if not current:
                result.blocked.append({"version": rs.message.version, "claim": claim_id,
                                       "reason": "not_current"})
            else:
                decision = self.guard.removal(state, claim_id, a, kind=rs.ends,
                                              valid_end=rs.valid_end, pending=pending)
                if decision.blocked:
                    result.blocked.append({"version": rs.message.version, "claim": claim_id,
                                           "reason": decision.blocked})
                for s in decision.supersede:
                    if self.deferred is None:
                        builder.supersession(s.claim_id, s.kind, s.valid_end, None,
                                             a.attribution_id)
                    pending.superseded.add(s.claim_id)
        pending.add_attribution(a)
        result.notes["stances"] += 1
