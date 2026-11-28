"""Manual correction of a writer's extraction (E009 preparation: "LoCoMo development histories
with manually corrected extraction").

An ingest run (`changesets.jsonl`, `snapshot/<history>/log/messages.jsonl`,
`snapshot/<history>/engine.json`) is split into review *items*, one per entry a human can judge:

- `claim`: a claim with the attributions and evidence links written with it (same version);
- `attribution`: a later mention of an earlier claim (attribution plus its evidence links);
- `supersession`: an ending (`replacing_claim_id: null`), a change or a correction.

Item IDs are the entry IDs of the ingest (`c205.1`, `a205.3`, `s205.1`). A correction file
(JSON Lines, written by the review page `web/human-reviewer/locomo/correction/`) holds one record
per decision:

    {"history_id", "item_id" | null, "add_id" | null, "message_id", "decision", "fields",
     "reason", "annotator", "basis"}

with `decision` one of `accept`, `reject`, `edit` (items), `add_claim`, `add_ending`,
`add_supersession` (additions, keyed by `add_id`) and `dismiss` (an addition proposed by the
agent pre-review that the human turned down). `apply_corrections` replays the ingest change sets
with these decisions and returns corrected change sets in the format of the ingest (contract
"Claim graph", one change set per version), every one committed through `ClaimStore`.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grace.context.memory.graph.changeset import ChangeSet
from grace.context.memory.graph.store import ClaimStore

ITEM_DECISIONS = ("accept", "reject", "edit")
ADD_DECISIONS = ("add_claim", "add_ending", "add_supersession")
DECISIONS = ITEM_DECISIONS + ADD_DECISIONS + ("dismiss",)
CLAIM_EDIT_FIELDS = ("subject", "predicate", "object", "scope", "valid_time")
SUPERSESSION_EDIT_FIELDS = ("kind", "valid_end", "replacing_claim_id")
ATTRIBUTION_DEFAULTS = {"function": "inform", "report_mode": "own", "polarity": "positive",
                        "certainty": "certain", "derived": False}
ADD_ID = re.compile(r"[hp][0-9]+\.[0-9]+")


class CorrectionError(ValueError):
    """A correction record that cannot be applied; the message names the record."""


# ---------------------------------------------------------------------------------------------
# Reading an ingest run


@dataclass
class History:
    history_id: str
    messages: list[dict[str, Any]]
    segments: list[dict[str, Any]]
    changesets: dict[int, dict[str, Any]]

    @property
    def by_message(self) -> dict[str, dict[str, Any]]:
        return {m["message_id"]: m for m in self.messages}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def load_ingest(run_dir: Path) -> dict[str, History]:
    """The histories of an ingest run, in the order of `snapshot/manifest.json`."""
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if run.get("status") != "completed":
        raise CorrectionError(f"{run_dir}: the ingest run is not completed")
    records: dict[str, dict[int, dict]] = defaultdict(dict)
    for record in read_jsonl(run_dir / "changesets.jsonl"):
        records[record["history_id"]][record["version"]] = record
    manifest = json.loads((run_dir / "snapshot" / "manifest.json").read_text(encoding="utf-8"))
    out: dict[str, History] = {}
    for entry in manifest["histories"]:
        hid = entry["history_id"]
        base = run_dir / "snapshot" / hid
        messages = sorted(read_jsonl(base / "log" / "messages.jsonl"), key=lambda m: m["version"])
        engine = base / "engine.json"
        segments = []
        if engine.exists():
            segments = json.loads(engine.read_text(encoding="utf-8")).get("history", {}).get(
                "segments", [])
        out[hid] = History(hid, messages, segments, dict(sorted(records.get(hid, {}).items())))
    return out


# ---------------------------------------------------------------------------------------------
# Review items


def history_items(history: History) -> list[dict[str, Any]]:
    """The review items of one history, in message order (claims, then later mentions, then
    supersessions within a message)."""
    msg_of_version = {m["version"]: m["message_id"] for m in history.messages}
    claims: dict[str, dict] = {}
    replacing = set()
    for record in history.changesets.values():
        for s in record["entries"]["supersessions"]:
            if s["replacing_claim_id"]:
                replacing.add(s["replacing_claim_id"])
    items = []
    for version, record in history.changesets.items():
        entries = record["entries"]
        new = {c["claim_id"]: c for c in entries["claims"]}
        claims.update(new)
        evidence = defaultdict(list)
        for e in entries["evidence_links"]:
            evidence[e["claim_id"]].append(e)
        attributions = defaultdict(list)
        for a in entries["attributions"]:
            attributions[a["claim_id"]].append(a)
        for cid, claim in new.items():
            change = ["replacing"] if cid in replacing else []
            if any(a["polarity"] == "negative" for a in attributions[cid]):
                change.append("negative")
            items.append({
                "item_id": cid, "kind": "claim", "version": version,
                "message_id": _message_of(attributions[cid], evidence[cid], msg_of_version,
                                          version),
                "claim": claim, "attributions": attributions[cid], "evidence": evidence[cid],
                "change": change})
        for cid, atts in attributions.items():
            if cid in new:
                continue
            for a in atts:
                items.append({
                    "item_id": a["attribution_id"], "kind": "attribution", "version": version,
                    "message_id": a["message_id"], "claim_id": cid, "claim": claims.get(cid),
                    "attributions": [a], "evidence": evidence[cid],
                    "change": ["negative"] if a["polarity"] == "negative" else []})
        for s in entries["supersessions"]:
            kind = "ending" if s["replacing_claim_id"] is None else (
                "correction" if s["kind"] == "correction" else "supersession")
            if kind == "ending" and s["kind"] == "correction":
                kind = "correction"
            items.append({
                "item_id": s["supersession_id"], "kind": "supersession", "version": version,
                "message_id": msg_of_version.get(version), "supersession": s,
                "claim": claims.get(s["claim_id"]),
                "replacing": claims.get(s["replacing_claim_id"]) if s["replacing_claim_id"]
                else None,
                "change": [kind]})
    return items


def _message_of(attributions, evidence, msg_of_version, version):
    for entry in list(attributions) + list(evidence):
        if entry.get("message_id"):
            return entry["message_id"]
    return msg_of_version.get(version)


def entity_labels(history: History) -> dict[str, str]:
    labels = {}
    for record in history.changesets.values():
        for x in record.get("entity_labels", []):
            labels[x["entity"]] = x["label"]
    return labels


def build_bundle(run_dir: Path, proposals: Sequence[Mapping[str, Any]] = (),
                 source_name: str | None = None) -> dict[str, Any]:
    """The data file of the review page: messages, items and the agent proposals."""
    histories = load_ingest(run_dir)
    run = json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))
    by_history = defaultdict(list)
    for p in proposals:
        by_history[p["history_id"]].append(dict(p))
    out = []
    for hid, h in histories.items():
        items = history_items(h)
        flagged = {p["item_id"] for p in by_history[hid] if p.get("item_id")
                   and p.get("change_event")}
        for item in items:
            if item["item_id"] in flagged and "agent" not in item["change"]:
                item["change"].append("agent")
        out.append({
            "history_id": hid,
            "segments": h.segments,
            "messages": [{k: m.get(k) for k in ("message_id", "version", "speaker", "segment_id",
                                                 "text")} for m in h.messages],
            "entity_labels": entity_labels(h),
            "items": items,
        })
    known = {h["history_id"] for h in out}
    stray = sorted({p["history_id"] for p in proposals} - known)
    if stray:
        raise CorrectionError(f"proposals name histories not in the ingest: {stray}")
    return {
        "kind": "locomo-correction-bundle", "version": 1,
        "source": {"run_id": run.get("run_id"), "name": source_name or run.get("run_id")},
        "histories": out,
        "proposals": [dict(p) for p in proposals],
    }


# ---------------------------------------------------------------------------------------------
# Correction records


def check_record(record: Mapping[str, Any], where: str) -> None:
    decision = record.get("decision")
    if decision not in DECISIONS:
        raise CorrectionError(f"{where}: unknown decision {decision!r}")
    if not record.get("history_id"):
        raise CorrectionError(f"{where}: history_id is missing")
    if decision in ITEM_DECISIONS:
        if not record.get("item_id"):
            raise CorrectionError(f"{where}: decision {decision} needs item_id")
        if decision == "edit" and not isinstance(record.get("fields"), Mapping):
            raise CorrectionError(f"{where}: an edit needs fields")
    else:
        add_id = record.get("add_id")
        if not isinstance(add_id, str) or not ADD_ID.fullmatch(add_id):
            raise CorrectionError(f"{where}: decision {decision} needs add_id like h12.1 or "
                                  f"p12.1, got {add_id!r}")
        if decision != "dismiss":
            if not record.get("message_id"):
                raise CorrectionError(f"{where}: decision {decision} needs message_id")
            if not isinstance(record.get("fields"), Mapping):
                raise CorrectionError(f"{where}: decision {decision} needs fields")


def read_records(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        for n, record in enumerate(read_jsonl(path), start=1):
            check_record(record, f"{Path(path).name}:{n}")
            records.append(record)
    return records


def key_of(record: Mapping[str, Any]) -> tuple[str, str]:
    return record["history_id"], record.get("item_id") or record["add_id"]


def merge_decisions(human: Sequence[Mapping[str, Any]],
                    fallback: Sequence[Mapping[str, Any]] = ()) -> dict[tuple, dict[str, Any]]:
    """One decision per (history, item or addition): the last human record wins; a fallback
    record (agent proposal) fills only keys the human did not decide."""
    out: dict[tuple, dict] = {}
    for record in fallback:
        out[key_of(record)] = {**record, "_source": "fallback"}
    for record in human:
        out[key_of(record)] = {**record, "_source": "human"}
    return out


# ---------------------------------------------------------------------------------------------
# Applying corrections


@dataclass
class Report:
    counts: Counter = field(default_factory=Counter)
    events: list[dict[str, Any]] = field(default_factory=list)

    def note(self, kind: str, **detail: Any) -> None:
        self.counts[kind] += 1
        self.events.append({"event": kind, **detail})

    def to_record(self) -> dict[str, Any]:
        return {"counts": dict(sorted(self.counts.items())), "events": self.events}


def _canonical_object(obj: Any) -> dict[str, Any]:
    if isinstance(obj, Mapping) and "entity" in obj:
        return {"entity": obj["entity"]}
    if isinstance(obj, Mapping) and "value" in obj:
        return {"value": str(obj["value"]), "datatype": obj.get("datatype") or "string"}
    raise CorrectionError(f"object must be {{'entity': id}} or {{'value', 'datatype'}}, "
                          f"got {obj!r}")


def _valid_time(value: Any) -> dict[str, Any]:
    value = value or {}
    return {"start": value.get("start") or None, "end": value.get("end") or None,
            "expression": value.get("expression") or None}


def _edited_claim(claim: Mapping[str, Any], fields: Mapping[str, Any], where: str) -> dict:
    unknown = sorted(set(fields) - set(CLAIM_EDIT_FIELDS))
    if unknown:
        raise CorrectionError(f"{where}: claim fields cannot be edited: {unknown}")
    out = dict(claim)
    for name, value in fields.items():
        if name == "object":
            out["object"] = _canonical_object(value)
        elif name == "valid_time":
            out["valid_time"] = _valid_time(value)
        elif name == "scope":
            out["scope"] = value or None
        else:
            if not isinstance(value, str) or not value.strip():
                raise CorrectionError(f"{where}: {name} must be a non-empty string")
            out[name] = value.strip()
    return out


def _proposition(claim: Mapping[str, Any]) -> str:
    return json.dumps([claim["subject"], claim["predicate"], claim["object"], claim["scope"],
                       claim["valid_time"]], sort_keys=True)


def _span(text: str, quote: str | None) -> dict[str, int] | None:
    if not quote:
        return None
    start = text.find(quote)
    return None if start < 0 else {"start": start, "end": start + len(quote)}


def apply_corrections(history: History, decisions: Mapping[tuple, Mapping[str, Any]],
                      report: Report | None = None, *, validate: bool = True
                      ) -> tuple[list[ChangeSet], ClaimStore]:
    """Corrected change sets of one history (every version of the ingest, in order), committed
    through a fresh `ClaimStore`. `decisions` comes from `merge_decisions`."""
    report = report if report is not None else Report()
    hid = history.history_id
    messages = history.by_message
    version_of = {m["message_id"]: m["version"] for m in history.messages}
    message_at = {m["version"]: m["message_id"] for m in history.messages}
    mine = {k[1]: d for k, d in decisions.items() if k[0] == hid}
    items = {i["item_id"]: i for i in history_items(history)}
    for key, d in mine.items():
        if d["decision"] in ITEM_DECISIONS and key not in items:
            raise CorrectionError(f"{hid}: decision on unknown item {key!r}")
        if d["decision"] == "edit" and items[key]["kind"] == "attribution":
            raise CorrectionError(f"{hid}: item {key} is a mention; accept or reject it")
    additions: dict[int, list[dict]] = defaultdict(list)
    for key, d in sorted(mine.items(), key=lambda kv: kv[0]):
        if d["decision"] in ADD_DECISIONS:
            mid = d["message_id"]
            if mid not in version_of:
                raise CorrectionError(f"{hid}: addition {key} names unknown message {mid!r}")
            additions[version_of[mid]].append(d)
        elif d["decision"] == "dismiss":
            report.note("dismissed", history_id=hid, add_id=key)

    def decision(entry_id: str) -> str:
        d = mine.get(entry_id)
        return d["decision"] if d else "accept"

    store = ClaimStore(hid)
    alias: dict[str, str] = {}          # folded claim -> claim it repeats
    dropped: set[str] = set()           # claims removed (rejected or cascaded)
    kept_entries: dict[str, dict] = {}  # entry ID -> committed record (claims and attributions)
    current: dict[str, str] = {}        # proposition -> current claim ID
    superseded: set[str] = set()
    out: list[ChangeSet] = []

    def resolve(cid: str | None) -> str | None:
        while cid in alias:
            cid = alias[cid]
        return cid

    for version, record in history.changesets.items():
        entries = record["entries"]
        mid = message_at.get(version)
        msg = messages.get(mid, {})
        claims: list[dict] = []
        atts: list[dict] = []
        evid: list[dict] = []
        sups: list[dict] = []
        for c in entries["claims"]:
            d = decision(c["claim_id"])
            if d == "reject":
                dropped.add(c["claim_id"])
                report.note("claim_rejected", history_id=hid, item_id=c["claim_id"])
                continue
            if d == "edit":
                c = _edited_claim(c, mine[c["claim_id"]]["fields"], f"{hid}:{c['claim_id']}")
                report.note("claim_edited", history_id=hid, item_id=c["claim_id"])
            claims.append(dict(c))
        new_ids = {c["claim_id"] for c in entries["claims"]}
        for a in entries["attributions"]:
            cid = a["claim_id"]
            if cid not in new_ids and decision(a["attribution_id"]) == "reject":
                report.note("mention_rejected", history_id=hid, item_id=a["attribution_id"])
                continue
            if cid in dropped or resolve(cid) in dropped:
                if cid not in new_ids:
                    report.note("mention_cascaded", history_id=hid, item_id=a["attribution_id"],
                                claim_id=cid)
                continue
            atts.append(dict(a))
        kept_att_claims = {a["claim_id"] for a in atts}
        for e in entries["evidence_links"]:
            if e["claim_id"] in kept_att_claims or (e["claim_id"] in new_ids
                                                     and e["claim_id"] not in dropped):
                evid.append(dict(e))
        for s in entries["supersessions"]:
            sid = s["supersession_id"]
            d = decision(sid)
            if d == "reject":
                report.note("supersession_rejected", history_id=hid, item_id=sid)
                continue
            s = dict(s)
            if d == "edit":
                fields = mine[sid]["fields"]
                unknown = sorted(set(fields) - set(SUPERSESSION_EDIT_FIELDS))
                if unknown:
                    raise CorrectionError(f"{hid}:{sid}: fields cannot be edited: {unknown}")
                s.update({k: (v or None) for k, v in fields.items()})
                report.note("supersession_edited", history_id=hid, item_id=sid)
            sups.append(s)
        # Additions at this message.
        for add in additions.get(version, []):
            aid = add["add_id"]
            f = add["fields"]
            speaker = f.get("speaker") or msg.get("speaker")
            text = msg.get("text", "")
            if add["decision"] == "add_claim":
                claim = {"claim_id": aid, "subject": f.get("subject"),
                         "predicate": f.get("predicate"),
                         "object": _canonical_object(f.get("object")),
                         "scope": f.get("scope") or None,
                         "valid_time": _valid_time(f.get("valid_time")), "version": version}
                for name in ("subject", "predicate"):
                    if not isinstance(claim[name], str) or not claim[name].strip():
                        raise CorrectionError(f"{hid}:{aid}: {name} is missing")
                claims.append(claim)
                atts.append({"attribution_id": f"{aid}.a", "claim_id": aid, "speaker": speaker,
                             **{k: f.get(k, v) for k, v in ATTRIBUTION_DEFAULTS.items()},
                             "message_id": mid, "version": version})
                evid.append({"evidence_id": f"{aid}.e", "claim_id": aid, "message_id": mid,
                             "span": _span(text, f.get("quote")), "version": version})
                report.note("claim_added", history_id=hid, add_id=aid, message_id=mid)
                continue
            target = resolve(f.get("claim_id"))
            replacing = resolve(f.get("replacing_claim_id")) if add["decision"] == \
                "add_supersession" else None
            if target in dropped or target is None:
                raise CorrectionError(f"{hid}:{aid}: target claim {f.get('claim_id')!r} is "
                                      f"missing or rejected")
            if add["decision"] == "add_supersession" and (replacing is None
                                                          or replacing in dropped):
                raise CorrectionError(f"{hid}:{aid}: replacing claim "
                                      f"{f.get('replacing_claim_id')!r} is missing or rejected")
            kind = f.get("kind") or "change"
            if replacing is None:
                # An ending is licensed by a negative own stance of the speaker on the claim.
                earlier = [a for a in kept_entries.values() if a.get("claim_id") == target
                           and "attribution_id" in a and a["speaker"] == speaker]
                function = earlier[0]["function"] if earlier else "inform"
                licence = f"{aid}.a"
                atts.append({"attribution_id": licence, "claim_id": target, "speaker": speaker,
                             "function": function, "report_mode": "own",
                             "polarity": "negative", "certainty": "certain", "derived": False,
                             "message_id": mid, "version": version})
                evid.append({"evidence_id": f"{aid}.e", "claim_id": target, "message_id": mid,
                             "span": _span(text, f.get("quote")), "version": version})
            else:
                pool = [a for a in list(kept_entries.values()) + atts
                        if "attribution_id" in a and resolve(a["claim_id"]) == replacing]
                if not pool:
                    raise CorrectionError(f"{hid}:{aid}: replacing claim {replacing} has no "
                                          f"attribution at or before {mid}")
                licence = pool[-1]["attribution_id"]
            sups.append({"supersession_id": aid, "claim_id": target, "kind": kind,
                         "valid_end": None if kind == "correction" else (f.get("valid_end")
                                                                         or None),
                         "replacing_claim_id": replacing, "attribution_id": licence,
                         "version": version})
            report.note("ending_added" if replacing is None else "supersession_added",
                        history_id=hid, add_id=aid, message_id=mid, claim_id=target)
        # Fold claims that repeat a current proposition into the earlier claim.
        ending_now = {resolve(s["claim_id"]) for s in sups}
        live = {p: c for p, c in current.items() if c not in superseded | ending_now}
        kept_claims = []
        for c in claims:
            p = _proposition(c)
            if p in live and live[p] != c["claim_id"]:
                alias[c["claim_id"]] = live[p]
                report.note("claim_folded", history_id=hid, item_id=c["claim_id"],
                            into=live[p])
                continue
            live[p] = c["claim_id"]
            kept_claims.append(c)
        for a in atts:
            a["claim_id"] = resolve(a["claim_id"])
        for e in evid:
            e["claim_id"] = resolve(e["claim_id"])
        final_sups = []
        for s in sups:
            s["claim_id"] = resolve(s["claim_id"])
            if s["replacing_claim_id"]:
                s["replacing_claim_id"] = resolve(s["replacing_claim_id"])
            names = [s["claim_id"], s["replacing_claim_id"]]
            if any(n in dropped for n in names if n) or s["claim_id"] == s["replacing_claim_id"]:
                report.note("supersession_cascaded", history_id=hid,
                            item_id=s["supersession_id"])
                continue
            att_ids = {a["attribution_id"] for a in atts} | set(kept_entries)
            if s["attribution_id"] not in att_ids:
                report.note("supersession_cascaded", history_id=hid,
                            item_id=s["supersession_id"], reason="licence dropped")
                continue
            final_sups.append(s)
        cs_record = {**record, "entries": {"claims": kept_claims, "attributions": atts,
                                           "evidence_links": evid,
                                           "supersessions": final_sups}}
        cs = store.commit(ChangeSet.from_record(cs_record), validate=validate)
        out.append(cs)
        for c in kept_claims:
            current[_proposition(c)] = c["claim_id"]
            kept_entries[c["claim_id"]] = c
        for a in atts:
            kept_entries[a["attribution_id"]] = a
        superseded.update(s["claim_id"] for s in final_sups)
    return out, store
