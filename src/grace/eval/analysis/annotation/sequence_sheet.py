"""Audit sample and annotation sheet of the controlled change sequences (task T016).

Protocol: docs/research/change-sequences.md section 8; guideline: docs/research/sequence-audit.md.
Reads only the files of a generated dataset in a run directory (`<RUN_DIR>/dataset`, written by
the T015 generator), as every module under `eval/analysis/` does. It imports no generator code.

The sample is a pure function of the dataset and the seed string `SAMPLE_SEED`:

- per development scenario family, `PER_FAMILY` sequences, stratified over revision density
  (one per density level in seeded order, then the rest in seeded order);
- per sequence one audit window of `WINDOW` consecutive messages after the setup episode, with a
  seeded start, and the `CONTEXT` preceding messages as read-only context;
- per window at most `MAX_QUESTIONS` questions of the sequence's primary schedule whose read
  version lies inside the window, always both members of a pair;
- `PILOT_WINDOWS` calibration windows (not counted) in sequences of different families, disjoint
  from the audit window and its context.

Every seeded choice orders candidates by the SHA-256 of `SAMPLE_SEED:<purpose>:<key>`, so it does
not depend on Python's random module or on file order. Held-out families are refused.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SAMPLE_SEED = "T016-audit-v1"
PER_FAMILY = 5
WINDOW = 30
CONTEXT = 10
MAX_QUESTIONS = 5
PILOT_WINDOWS = 2
DEVELOPMENT = "development"

SHEET_COLUMNS = (
    "item_id", "kind", "part", "window", "family", "sequence_id", "density", "version",
    "episode", "date", "speaker", "text", "events", "cue", "skeleton", "gold",
    "annotator", "label", "subclass", "note",
)
ANNOTATOR_COLUMNS = ("annotator", "label", "subclass", "note")
PARTS = ("context", "pilot", "audit")


class SampleError(ValueError):
    """The dataset cannot be sampled as the protocol requires."""


def rank(purpose: str, key: str, seed: str = SAMPLE_SEED) -> str:
    """Seeded sort key: hex SHA-256 of `seed:purpose:key`."""
    return hashlib.sha256(f"{seed}:{purpose}:{key}".encode()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


@dataclass
class SequenceData:
    sequence_id: str
    meta: dict
    messages: list[dict]
    events: list[dict]
    questions: list[dict]

    @property
    def family(self) -> str:
        return self.meta["family"]

    @property
    def density(self) -> int:
        return int(self.meta["cell"]["density"])

    @property
    def setup_length(self) -> int:
        return int(self.meta["world"]["setup_length"])

    @property
    def n_messages(self) -> int:
        return len(self.messages)


@dataclass
class Dataset:
    root: Path
    manifest_sha256: str
    dataset_meta: dict
    sequences: dict[str, SequenceData] = field(default_factory=dict)


def verify_manifest(root: Path) -> str:
    """Check every file listed in `MANIFEST.sha256`; return the manifest's own SHA-256."""
    manifest = Path(root) / "MANIFEST.sha256"
    if not manifest.is_file():
        raise SampleError(f"{root}: no MANIFEST.sha256")
    bad = []
    listed = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, name = line.split(None, 1)
        listed.add(name.strip())
        target = Path(root) / name.strip()
        if not target.is_file() or sha256_file(target) != expected:
            bad.append(name.strip())
    if bad:
        raise SampleError(f"{root}: {len(bad)} files do not match the manifest, e.g. {bad[:3]}")
    present = {p.relative_to(root).as_posix() for p in Path(root).rglob("*")
               if p.is_file() and p.name != "MANIFEST.sha256"}
    unlisted = sorted(present - listed)
    if unlisted:
        raise SampleError(f"{root}: {len(unlisted)} files are not in the manifest, "
                          f"e.g. {unlisted[:3]}")
    return sha256_file(manifest)


def load_dataset(root: Path, verify: bool = True) -> Dataset:
    """Read every sequence of a generated dataset directory (manifest checked first)."""
    root = Path(root)
    if not (root / "sequences").is_dir():
        raise SampleError(f"{root}: not a generated dataset (no sequences/)")
    manifest_sha = verify_manifest(root) if verify else ""
    dataset_meta = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    data = Dataset(root, manifest_sha, dataset_meta)
    for directory in sorted(p for p in (root / "sequences").iterdir() if p.is_dir()):
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        schedule = directory / "schedules" / f"{meta['primary_schedule']}.jsonl"
        data.sequences[meta["sequence_id"]] = SequenceData(
            meta["sequence_id"], meta, _jsonl(directory / "messages.jsonl"),
            _jsonl(directory / "events.jsonl"), _jsonl(schedule))
    return data


def select_sequences(sequences: Mapping[str, SequenceData],
                     per_family: int = PER_FAMILY) -> dict[str, list[str]]:
    """family -> sampled sequence IDs, stratified over revision density. Refuses held-out data."""
    held_out = sorted(s for s, d in sequences.items() if d.meta.get("split") != DEVELOPMENT)
    if held_out:
        raise SampleError(f"held-out or unsplit sequences in the pool: {held_out[:5]}")
    by_family: dict[str, list[SequenceData]] = {}
    for seq in sequences.values():
        by_family.setdefault(seq.family, []).append(seq)
    chosen: dict[str, list[str]] = {}
    for family, pool in sorted(by_family.items()):
        if len(pool) < per_family:
            raise SampleError(f"family {family}: {len(pool)} sequences, the audit needs "
                              f"{per_family}")
        ordered = sorted(pool, key=lambda s: rank("sequence", s.sequence_id))
        picked: list[str] = []
        levels = sorted({s.density for s in pool})
        # Round-robin over density levels in seeded order until `per_family` are taken.
        while len(picked) < per_family:
            for level in levels:
                rest = [s for s in ordered if s.density == level and s.sequence_id not in picked]
                if rest and len(picked) < per_family:
                    picked.append(rest[0].sequence_id)
        chosen[family] = sorted(picked)
    return chosen


def window_start(seq: SequenceData, purpose: str = "window") -> int:
    """Seeded first version of the audit window: after the setup episode, fully inside."""
    first = seq.setup_length + 1
    last = seq.n_messages - WINDOW + 1
    if last < first:
        raise SampleError(f"{seq.sequence_id}: too short for a {WINDOW}-message window")
    return first + int(rank(purpose, seq.sequence_id), 16) % (last - first + 1)


def _span(start: int) -> tuple[int, int]:
    """Versions shown for a window starting at `start`: context and window."""
    return max(1, start - CONTEXT), start + WINDOW - 1


def pilot_windows(sequences: Mapping[str, SequenceData], audit_starts: Mapping[str, int],
                  n: int = PILOT_WINDOWS) -> dict[str, int]:
    """sequence ID -> pilot window start, in sequences of distinct families, disjoint (with
    context) from that sequence's audit window and its context."""
    pilots: dict[str, int] = {}
    families: set[str] = set()
    for sid in sorted(audit_starts, key=lambda s: rank("pilot", s)):
        seq = sequences[sid]
        if seq.family in families:
            continue
        a_lo, a_hi = _span(audit_starts[sid])
        candidates = [s for s in range(seq.setup_length + 1, seq.n_messages - WINDOW + 2)
                      if _span(s)[1] < a_lo or _span(s)[0] > a_hi]
        if not candidates:
            continue
        candidates.sort(key=lambda s: rank("pilot-start", f"{sid}:{s}"))
        pilots[sid] = candidates[0]
        families.add(seq.family)
        if len(pilots) == n:
            break
    if len(pilots) < n:
        raise SampleError(f"only {len(pilots)} pilot windows fit; {n} needed")
    return pilots


def select_questions(seq: SequenceData, start: int,
                     limit: int = MAX_QUESTIONS) -> list[dict]:
    """At most `limit` primary-schedule questions read inside the window; pairs stay whole."""
    end = start + WINDOW - 1
    inside = [q for q in seq.questions if start <= int(q["read_version"]) <= end]
    units: dict[str, list[dict]] = {}
    for q in inside:
        units.setdefault(q.get("pair_id") or q["question_id"], []).append(q)
    picked: list[dict] = []
    for key in sorted(units, key=lambda k: rank("question", f"{seq.sequence_id}:{k}")):
        if len(picked) + len(units[key]) <= limit:
            picked.extend(units[key])
    return sorted(picked, key=lambda q: (int(q["read_version"]), q["question_id"]))


# ---------------------------------------------------------------- readable rendering


def _proposition(claim: Mapping[str, Any]) -> str:
    text = f"({claim['subject']}, {claim['predicate']}, {claim['object']})"
    start, end = claim.get("start"), claim.get("end")
    if start and end:
        text += f" valid {start} to {end}"
    elif start:
        text += f" valid from {start}"
    elif end:
        text += f" valid until {end}"
    return text


def _stance(stance: Mapping[str, Any], speaker: str) -> str:
    text = (f"{speaker}: {stance['function']}, {stance['report_mode']}, "
            f"{stance['polarity']}")
    if stance.get("derived"):
        text += ", restatement"
    return text


def render_events(events: Sequence[Mapping[str, Any]], speaker: str,
                  claims: dict[str, dict]) -> str:
    """Readable form of one message's events; `claims` is updated with new claims."""
    parts: list[str] = []
    new_ids: set[str] = set()
    for event in events:
        kind = event["type"]
        if kind == "NewClaim":
            claims[event["claim_id"]] = dict(event)
            new_ids.add(event["claim_id"])
        elif kind == "Stance":
            claim = claims.get(event["claim_id"])
            if claim is None:
                raise SampleError(f"stance on unknown claim {event['claim_id']}")
            tag = "NEW" if event["claim_id"] in new_ids else "ON"
            parts.append(f"{tag} {event['claim_id']} {_proposition(claim)} "
                         f"[{_stance(event, speaker)}]")
        elif kind == "Supersede":
            claim = claims.get(event["claim_id"])
            if claim is None:
                raise SampleError(f"supersession of unknown claim {event['claim_id']}")
            replaced = event.get("replacing_claim_id")
            parts.append(f"SUPERSEDE {event['claim_id']} {_proposition(claim)} as "
                         f"{event['kind']}" + (f", replaced by {replaced}" if replaced
                                                else ", no replacement"))
        else:
            raise SampleError(f"unknown event type {kind!r}")
    return " || ".join(parts) if parts else "(none)"


_DISCOURSE = {"change": "must signal that the state changed",
              "correction": "must signal that an earlier statement was wrong"}


def render_cue(record: Mapping[str, Any]) -> str:
    cue, macro = record["cue"], record.get("macro")
    if cue["skeleton"] == "filler":
        return "filler: must express no state of the family"
    parts = []
    if macro:
        parts.append(f"macro {macro['name']} ({macro['intended_type']}, focus {macro['focus']})")
    if cue.get("required"):
        parts.append("must mention: " + ", ".join(cue["required"]))
    if cue.get("allowed"):
        parts.append("may mention: " + ", ".join(cue["allowed"]))
    if cue.get("discourse"):
        parts.append(_DISCOURSE.get(cue["discourse"], cue["discourse"]))
    return "; ".join(parts)


def _quote(message: Mapping[str, Any]) -> str:
    return f"[{message['message_id']} | {message['speaker']}] {message['text']}"


def _value(value: Any) -> str:
    """An answer value: a string, or a tuple such as (constraint predicate, value)."""
    if isinstance(value, list | tuple):
        return " = ".join(_value(v) for v in value)
    return str(value)


def render_gold(question: Mapping[str, Any], messages: Mapping[int, Mapping[str, Any]],
                ids: Mapping[str, int]) -> str:
    q = question
    answer = ", ".join(_value(v) for v in q["answer_text"])
    parts = [f"type {q['type']}; template {q['template']} ({q['binding_id']})",
             "answer: " + (answer or "(empty)")]
    if q.get("expected_abstention"):
        parts.append("expected abstention: yes")
    if q.get("outdated_text"):
        parts.append("outdated: " + ", ".join(_value(v) for v in q["outdated_text"]))
    if q.get("premise_outdated"):
        parts.append("premise outdated: yes")
    if q.get("pair_id"):
        parts.append(f"pair {q['pair_id']} ({q['pair_kind']}, {q['pair_role']})")
    if q.get("tau"):
        parts.append(f"world time {q['tau']}")
    if q.get("kappa") is not None:
        # The anchor event identifies the knowledge version of a known-then question; for a
        # seen-from-now question the knowledge version is the read version itself.
        anchor = messages.get(int(q["kappa"]))
        if q.get("pair_role") == "known-then" and anchor:
            parts.append(f"knowledge version {q['kappa']}, anchor {_quote(anchor)}")
        else:
            parts.append(f"knowledge version {q['kappa']} (the read version)"
                         if int(q["kappa"]) == int(q["read_version"])
                         else f"knowledge version {q['kappa']}")
    evidence = [messages[ids[m]] for m in q.get("evidence", []) if m in ids]
    if evidence:
        parts.append("evidence: " + " || ".join(_quote(m) for m in evidence))
    return "; ".join(parts)


# ---------------------------------------------------------------- sheet


def _window_rows(seq: SequenceData, start: int, part: str, window_id: str) -> list[dict]:
    lo, hi = _span(start)
    by_version = {int(m["version"]): m for m in seq.messages}
    ids = {m["message_id"]: int(m["version"]) for m in seq.messages}
    claims: dict[str, dict] = {}
    rendered: dict[int, str] = {}
    for record in seq.events:  # claims must be known from version 1 on
        rendered[int(record["version"])] = render_events(record["events"], record["speaker"],
                                                         claims)
    base = {"window": window_id, "family": seq.family, "sequence_id": seq.sequence_id,
            "density": str(seq.density)}
    events = {int(r["version"]): r for r in seq.events}
    rows: list[dict] = []
    for version in range(lo, hi + 1):
        message, record = by_version[version], events[version]
        if message["message_id"] != record["message_id"]:
            raise SampleError(f"{seq.sequence_id}: messages and events disagree at {version}")
        rows.append(base | {
            "item_id": f"{seq.sequence_id}:{message['message_id']}", "kind": "message",
            "part": "context" if version < start else part, "version": str(version),
            "episode": message["episode"], "date": message["timestamp"],
            "speaker": message["speaker"], "text": message["text"],
            "events": rendered[version], "cue": render_cue(record),
            "skeleton": record["cue"]["skeleton"], "gold": ""})
    order = {r["version"]: i for i, r in enumerate(rows)}
    for q in select_questions(seq, start):
        rows.append(base | {
            "item_id": f"{seq.sequence_id}:{q['question_id']}", "kind": "question",
            "part": part, "version": str(q["read_version"]), "episode": "",
            "date": q["asked_at"], "speaker": "user", "text": q["text"], "events": "",
            "cue": "", "skeleton": q["type"], "gold": render_gold(q, by_version, ids)})
    # questions follow the message at their read version
    rows.sort(key=lambda r: (order[r["version"]], r["kind"] == "question", r["item_id"]))
    return [{c: r.get(c, "") for c in SHEET_COLUMNS} for r in rows]


def build_sheet(data: Dataset) -> tuple[list[dict], dict]:
    """Sheet rows (pilot windows first, then audit windows by family) and the sample record."""
    chosen = select_sequences(data.sequences)
    starts = {sid: window_start(data.sequences[sid]) for ids in chosen.values() for sid in ids}
    pilots = pilot_windows(data.sequences, starts)
    rows: list[dict] = []
    windows: list[dict] = []
    for i, (sid, start) in enumerate(sorted(pilots.items(), key=lambda kv: rank("pilot", kv[0]))):
        wid = f"pilot-{i + 1}"
        part_rows = _window_rows(data.sequences[sid], start, "pilot", wid)
        rows += part_rows
        windows.append(_window_record(wid, "pilot", data.sequences[sid], start, part_rows))
    for _family, ids in sorted(chosen.items()):
        for sid in ids:
            wid = f"{sid}:w{starts[sid]:03d}"
            part_rows = _window_rows(data.sequences[sid], starts[sid], "audit", wid)
            rows += part_rows
            windows.append(_window_record(wid, "audit", data.sequences[sid], starts[sid],
                                          part_rows))
    generator = data.dataset_meta.get("generator", {})
    renderer = data.dataset_meta.get("renderer", {})
    record = {
        "task": "T016", "seed": SAMPLE_SEED, "dataset": data.dataset_meta.get("dataset"),
        "generator_version": generator.get("version"), "generator_code_sha":
        generator.get("code_sha"), "renderer": renderer.get("name"),
        "manifest_sha256": data.manifest_sha256,
        "parameters": {"per_family": PER_FAMILY, "window": WINDOW, "context": CONTEXT,
                       "max_questions": MAX_QUESTIONS, "pilot_windows": PILOT_WINDOWS},
        "families": sorted(chosen), "sequences": chosen, "windows": windows,
        "counts": _counts(rows),
    }
    return rows, record


def _window_record(wid: str, part: str, seq: SequenceData, start: int,
                   rows: Iterable[dict]) -> dict:
    rows = list(rows)
    return {"window": wid, "part": part, "family": seq.family, "sequence_id": seq.sequence_id,
            "density": seq.density, "primary_schedule": seq.meta["primary_schedule"],
            "start": start, "end": start + WINDOW - 1, "context_from": _span(start)[0],
            "questions": [r["item_id"].split(":", 1)[1] for r in rows if r["kind"] == "question"]}


def _counts(rows: Iterable[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        key = f"{r['part']}_{r['kind']}s"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def write_sheet(rows: Iterable[Mapping[str, str]], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in SHEET_COLUMNS})


def write_record(record: Mapping[str, Any], path: Path) -> None:
    Path(path).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
