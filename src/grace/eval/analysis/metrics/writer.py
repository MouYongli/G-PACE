"""Writer statistics from the files of a writer run (T022 follow-up smoke run).

Reads only run-directory files: `updates.jsonl` (one record per extraction unit, the updater's
`UnitResult.to_record()`), `calls.jsonl` (the cost ledger) and the saved change sets of each
history (`graphs/<history_id>/store/changesets.jsonl`). Nothing here imports engine code.

- `unit_stats`: units by status (`ok`, `split`, `invalid_output`, `failed`, `failed_final`),
  how many messages ended in an empty change set because extraction gave up, entries committed,
  dropped items by reason, conflicts, blocked removals and commit errors; empty patches (`ok`
  units whose patch is empty, E007) and the repair of invalid outputs by splitting.
- `call_stats`: calls by status and attempt, the rates of invalid outputs and failed attempts, and
  token totals (input, output, cached input) overall and per status.
- `graph_stats`: the shape of the committed graph (predicates, catch-all share, long string
  objects, valid times, supersessions and removals, grammar-unsafe entity IDs).
- `sample_units`: a seeded sample of units with their messages, the writer's raw output and the
  entries committed for them, for a qualitative look (there are no gold labels for LoCoMo's
  claims, so nothing here is an accuracy).
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

UNIT_STATUSES = ("ok", "split", "invalid_output", "failed", "failed_final")
ENTRY_KINDS = ("claims", "attributions", "evidence_links", "supersessions", "entity_merges")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def unit_stats(updates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts over the update records of one or more histories."""
    status = Counter(u["status"] for u in updates)
    entries: Counter = Counter()
    dropped: Counter = Counter()
    notes: Counter = Counter()
    for u in updates:
        entries.update(u["entries"])
        dropped.update(f"{d['item'].split('[')[0]}:{d['reason']}" for d in u["dropped"])
        notes.update(u["notes"])
    # Top-level units: a split unit's halves are records of their own, so count the messages of
    # final records (every status except `split` and the retried `failed`).
    final = [u for u in updates if u["status"] not in ("split", "failed")]
    messages = sum(len(u["message_ids"]) for u in final)
    given_up = sum(len(u["message_ids"]) for u in final
                   if u["status"] in ("invalid_output", "failed_final"))
    split_roots = sum(1 for u in updates if u["status"] == "split")
    ok_final = [u for u in final if u["status"] == "ok"]
    empty = sum(1 for u in ok_final if _empty_patch(u["raw_output"]))
    # T022 counted units with nothing committed (an all-dropped patch included): 45 of 136 there
    nothing = sum(1 for u in ok_final
                  if not (u["entries"]["claims"] or u["entries"]["attributions"]))
    return {
        "records": len(updates),
        "by_status": {s: status.get(s, 0) for s in UNIT_STATUSES},
        "final_units": len(final),
        "messages": messages,
        "messages_given_up": given_up,
        "messages_given_up_rate": _rate(given_up, messages),
        "split_events": split_roots,
        "partial_units": sum(1 for u in updates if u["partial"]),
        "empty_patches": empty,
        "empty_patch_rate": _rate(empty, len(ok_final)),
        "empty_commits": nothing,
        "empty_commit_rate": _rate(nothing, len(ok_final)),
        "repair": repair_stats(updates),
        "entries": {k: entries.get(k, 0) for k in ENTRY_KINDS},
        "dropped": dict(sorted(dropped.items())),
        "dropped_total": sum(dropped.values()),
        "notes": dict(sorted(notes.items())),
        "conflicts": sum(len(u["conflicts"]) for u in updates),
        "blocked": sum(len(u["blocked"]) for u in updates),
        "commit_errors": sum(len(u["commit_errors"]) for u in updates),
    }


def _empty_patch(raw: str | None) -> bool:
    """An `ok` unit whose patch holds no claim, stance or same_as entry (E007: empty patch)."""
    patch = json.loads(raw or "{}")
    return not any(patch.get(k) for k in ("claims", "stances", "same_as"))


def repair_stats(updates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Recovery of invalid outputs by splitting (the writer's only repair).

    A root is a `split` record not inside another split record of its history; it is repaired
    when no message in its range ends in a final `invalid_output` or `failed_final` record. Units
    that returned invalid output at a single message are given up without a split."""
    splits = [u for u in updates if u["status"] == "split"]

    def inside(u, v):
        return (u is not v and u["history_id"] == v["history_id"]
                and v["first_version"] <= u["first_version"]
                and u["last_version"] <= v["last_version"])

    roots = [u for u in splits if not any(inside(u, v) for v in splits)]
    lost = [u for u in updates if u["status"] in ("invalid_output", "failed_final")]
    repaired = sum(1 for r in roots if not any(inside(u, r) for u in lost))
    single = sum(1 for u in lost if u["status"] == "invalid_output"
                 and not any(inside(u, r) for r in roots))
    return {"split_roots": len(roots), "repaired": repaired,
            "repair_rate": _rate(repaired, len(roots)),
            "invalid_single_units": single}


def call_stats(calls: Sequence[Mapping[str, Any]], call_type: str = "extract") -> dict[str, Any]:
    """Statuses, attempts and tokens of the calls of one type."""
    rows = [c for c in calls if c["call_type"] == call_type]
    status = Counter(c["status"] for c in rows)
    tokens: dict[str, Counter] = defaultdict(Counter)
    for c in rows:
        for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
            tokens[c["status"]][key] += int(c[key] or 0)
            tokens["all"][key] += int(c[key] or 0)
    latency = sorted(float(c["latency_ms"]) for c in rows if c["status"] != "failed")
    answered = status.get("ok", 0) + status.get("invalid_output", 0)
    return {
        "call_type": call_type,
        "calls": len(rows),
        "by_status": dict(sorted(status.items())),
        "by_attempt": dict(sorted(Counter(str(c["attempt"]) for c in rows).items())),
        "retried_attempts": sum(1 for c in rows if int(c["attempt"]) > 1),
        "invalid_output_rate": _rate(status.get("invalid_output", 0), answered),
        "failed_attempt_rate": _rate(status.get("failed", 0), len(rows)),
        "tokens": {k: dict(v) for k, v in sorted(tokens.items())},
        "mean_input_tokens": _rate(tokens["all"]["input_tokens"], len(rows)),
        "mean_output_tokens": _rate(tokens["all"]["output_tokens"], len(rows)),
        "latency_ms_median": latency[len(latency) // 2] if latency else None,
        "models": sorted({c["model"] for c in rows}),
    }


def _label(claim: Mapping[str, Any]) -> str:
    obj = claim["object"]
    text = obj["entity"] if "entity" in obj else f'"{obj["value"]}" ({obj["datatype"]})'
    parts = [claim["subject"], claim["predicate"], text]
    if claim.get("scope"):
        parts.append(f"scope {claim['scope']}")
    vt = claim["valid_time"]
    if vt["start"] or vt["end"]:
        parts.append(f"valid {vt['start'] or '?'}..{vt['end'] or 'open'}")
    elif vt["expression"]:
        parts.append(f"time {vt['expression']}")
    return " | ".join(parts)


def unit_entries(changesets: Iterable[Mapping[str, Any]], versions: Iterable[int]
                 ) -> list[dict[str, Any]]:
    """Readable entries of the change sets at `versions`."""
    want = set(versions)
    out = []
    for cs in changesets:
        if cs["version"] not in want:
            continue
        e = cs["entries"]
        claims = {c["claim_id"]: _label(c) for c in e["claims"]}
        out.append({
            "version": cs["version"],
            "claims": [claims[c] for c in sorted(claims)],
            "attributions": [
                f"{a['claim_id']}: {a['speaker']} "
                + ("not " if a["polarity"] == "negative" else "") + a["function"]
                + (f" ({a['report_mode']})" if a["report_mode"] != "own" else "")
                for a in e["attributions"]],
            "supersessions": [f"{s['claim_id']} {s['kind']}"
                              + (f" by {s['replacing_claim_id']}" if s["replacing_claim_id"]
                                 else "") for s in e["supersessions"]],
            "entity_merges": [f"{m['entity_a']} = {m['entity_b']}"
                              for m in cs.get("entity_merges", [])],
        })
    return out


def sample_units(updates: Sequence[Mapping[str, Any]],
                 changesets: Mapping[str, Sequence[Mapping[str, Any]]],
                 messages: Mapping[tuple[str, str], Mapping[str, Any]], n: int, seed: int
                 ) -> list[dict[str, Any]]:
    """A seeded sample of `n` final units (not `split` or retried records), every status.

    `messages` maps (history_id, message_id) to the message record; message IDs are unique
    within a history only."""
    final = [u for u in updates if u["status"] not in ("split", "failed")]
    rng = random.Random(seed)
    chosen = sorted(rng.sample(range(len(final)), min(n, len(final))))
    out = []
    for i in chosen:
        u = final[i]
        versions = range(u["first_version"], u["last_version"] + 1)
        out.append({
            "history_id": u["history_id"], "versions": [u["first_version"], u["last_version"]],
            "status": u["status"],
            "messages": [f"[{msg['version']}] {msg['speaker']}: {msg['text']}"
                         for msg in (messages[(u["history_id"], m)] for m in u["message_ids"])],
            "raw_output": u["raw_output"],
            "committed": unit_entries(changesets[u["history_id"]], versions),
            "dropped": u["dropped"], "conflicts": u["conflicts"], "blocked": u["blocked"],
            "commit_errors": u["commit_errors"],
        })
    return out


# Catch-all predicates of the first smoke run (T022-20261126T184442Z-2a64): about half its claims.
CATCH_ALL = ("experienced", "hasExperience", "hasMemory", "hasPlan", "hasIntention", "hasFeeling",
             "feels", "said", "mentioned", "talkedAbout")
# Predicates that record the conversation itself rather than a fact (fixed before the comparison
# runs, from the same smoke run).
DIALOGUE_ACTS = ("asks", "askedAbout", "commentsOn", "appreciates", "expresses",
                 "expressedInterest", "expressedPraise", "expressedHappiness", "encourages",
                 "greeted", "thanks", "compliments")
_SAFE_ID = re.compile(r"[A-Za-z0-9_]+")


def graph_stats(changesets: Sequence[Mapping[str, Any]], top: int = 15) -> dict[str, Any]:
    """Shape of the committed graph of one or more histories, from change sets only.

    Descriptive, not accuracy: claims per predicate (top `top`), the share of catch-all
    predicates (`CATCH_ALL`), claims with a dialogue-act predicate (`DIALOGUE_ACTS`), string
    objects of six or more words, claims with a valid-time start or a kept time phrase,
    supersessions by kind and whether they replace a claim (a new value) or only end one (a
    removal), the largest number of removals by one message, and entity IDs
    that are not bare names of the query IR grammar (`[A-Za-z0-9_]+`)."""
    claims = [c for cs in changesets for c in cs["entries"]["claims"]]
    sups = [s for cs in changesets for s in cs["entries"]["supersessions"]]
    # message IDs are unique within a history only
    atts = {(cs["history_id"], a["attribution_id"]): (cs["history_id"], a["message_id"])
            for cs in changesets for a in cs["entries"]["attributions"]}
    sup_keys = [(cs["history_id"], s["attribution_id"]) for cs in changesets
                for s in cs["entries"]["supersessions"] if s["replacing_claim_id"] is None]
    preds = Counter(c["predicate"] for c in claims)
    long_strings = sum(1 for c in claims if "value" in c["object"]
                       and c["object"]["datatype"] == "string"
                       and len(c["object"]["value"].split()) >= 6)
    entities = set()
    for c in claims:
        entities.add(c["subject"])
        if "entity" in c["object"]:
            entities.add(c["object"]["entity"])
    removals = [s for s in sups if s["replacing_claim_id"] is None]
    per_message = Counter(atts[k] for k in sup_keys if k in atts)
    catch_all = sum(preds[p] for p in CATCH_ALL)
    return {
        "claims": len(claims),
        "predicates_used": len(preds),
        "top_predicates": dict(preds.most_common(top)),
        "catch_all_claims": catch_all,
        "catch_all_share": _rate(catch_all, len(claims)),
        "dialogue_act_claims": sum(preds[p] for p in DIALOGUE_ACTS),
        "long_string_objects": long_strings,
        "valid_from_filled": sum(1 for c in claims if c["valid_time"]["start"]),
        "time_expression_kept": sum(1 for c in claims if c["valid_time"]["expression"]),
        "supersessions": dict(sorted(Counter(s["kind"] for s in sups).items())),
        "replacements": len(sups) - len(removals),
        "removals": len(removals),
        "max_removals_per_message": max(per_message.values(), default=0),
        "entities": len(entities),
        "unsafe_entity_ids": sum(1 for e in entities if not _SAFE_ID.fullmatch(e)),
    }
