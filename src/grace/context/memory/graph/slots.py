"""Fixed-schema slot table: the representation arm of ablation B (plan 7.3, B; plan 7.2; T027).

Replaces the open-predicate claim graph (`store.py`) inside the GRACE assembly, so that ablation B
can cross representation (slot table, claim graph) with the attribution guard (on, off) and time
(single, bitemporal). Decision D013 puts it next to the component it replaces; the standalone
pilot slot table of T003 (`eval/engines/baselines/slots.py`) is a separate implementation with no
guard and no bitemporality, and the two share only the frozen slot inventory and function list in
`configs/engines/slot-table.yaml` (T003 and T027 Logs, 2026-11-25 and 2026-11-28).

**Rows.** The table is append-only: one `SlotRow` per stated value, stamped with the knowledge
version of its message. A row carries the slot, the subject it is about, the value, the speaker,
the communicative function (from the inventory), the report mode, the polarity, the writer's
correction flag and, for the bitemporal arm, the valid interval. Rows are never changed; what is
current at version v is derived from the rows of versions <= v (`SlotTable.state`), so the table
reads at any cut-off version like the claim store.

**Resolution** mirrors the guard of `pipeline/update/guard.py` (plan 3.2) on slot rows:

- A value is the pair (key, normalised value), key = (normalised subject, slot). A row that
  repeats a current value adds an attribution to it.
- A new positive value of an exclusive slot supersedes a current open-ended value of the same key
  only if, with the guard on, some attribution of the old value has the same speaker and the same
  function as the new row, and the new row is an own statement; otherwise both are kept and the
  pair is listed as a conflict. With the guard off, the new value always supersedes (plan 7.3:
  "a new value always supersedes the old one"); attributions are still recorded.
- A negative own row on a current value ends it under the same speaker-and-function condition
  (guard off: any negative row ends it).
- The function `correct` of the pilot list counts as `inform` when functions are compared, and
  marks the supersession as a correction, like the writer's `correction` flag.
- Time `single`: valid times are not stored; every value competes. Time `bitemporal`: a row with
  a stated valid end describes a closed past interval and competes with nothing (guard condition
  5); a change gives the old value the valid end = start of the new value when stated; the
  state can be read as of a world time.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT

INVENTORY_FILE = REPO_ROOT / "configs" / "engines" / "slot-table.yaml"
TIMES = ("single", "bitemporal")
REPORT_MODES = ("own", "quote", "hypothetical")
POLARITIES = ("positive", "negative")
# Exclusive slots: one current value per subject. A DEVELOPMENT PLACEHOLDER for the pilot
# inventory, like the inventory itself; frozen with it before the configuration lock (D012).
DEFAULT_EXCLUSIVE = ("person.location", "person.occupation", "event.time", "event.place",
                     "item.choice")
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


def _date(value: str) -> _dt.date:
    return _dt.date.fromisoformat(value[:10])


@dataclass(frozen=True)
class SlotInventory:
    """The frozen slot inventory: slot -> description, the function list, the exclusive slots."""

    slots: Mapping[str, str]
    functions: tuple[str, ...]
    exclusive: frozenset[str]

    def __post_init__(self) -> None:
        if not self.slots or not self.functions:
            raise ValueError("slot inventory needs slots and functions")
        unknown = set(self.exclusive) - set(self.slots)
        if unknown:
            raise ValueError(f"exclusive slots outside the inventory: {sorted(unknown)}")

    def match_function(self, function: str) -> str:
        """The function as compared by the guard: `correct` counts as `inform`."""
        return "inform" if function == "correct" else function


def load_inventory(path: Path = INVENTORY_FILE,
                   exclusive: Collection[str] = DEFAULT_EXCLUSIVE) -> SlotInventory:
    """The inventory of the pilot slot table's config (shared with T003's baseline)."""
    params = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["params"]
    return SlotInventory(dict(params["slots"]), tuple(params["functions"]),
                         frozenset(exclusive))


@dataclass(frozen=True)
class SlotRow:
    """One value stated in message `message_id` (version `version`)."""

    row_id: str
    slot: str
    subject: str
    value: str
    speaker: str
    function: str
    report_mode: str
    polarity: str
    correction: bool
    valid_from: str | None
    valid_until: str | None
    message_id: str
    version: int

    def __post_init__(self) -> None:
        for name in ("row_id", "slot", "subject", "value", "speaker", "function", "message_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"SlotRow.{name}: non-empty string required, got {value!r}")
        if self.report_mode not in REPORT_MODES or self.polarity not in POLARITIES:
            raise ValueError(f"SlotRow: bad report mode or polarity in {self!r}")
        for name in ("valid_from", "valid_until"):
            value = getattr(self, name)
            if value is not None:
                _date(value)  # raises on a malformed date
        if self.valid_from and self.valid_until and \
                not _date(self.valid_from) < _date(self.valid_until):
            raise ValueError(f"SlotRow: valid_from {self.valid_from} not before {self.valid_until}")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError(f"SlotRow.version: positive integer required, got {self.version!r}")

    @property
    def key(self) -> tuple[str, str]:
        return (normalise(self.subject), self.slot)


@dataclass
class SlotValue:
    """A distinct value of one key, with every row that stated it and its supersession."""

    key: tuple[str, str]
    value: str
    rows: list[SlotRow]
    valid_from: str | None = None
    valid_until: str | None = None          # stated, or set by a change (bitemporal only)
    superseded_at: int | None = None        # version of the superseding row
    superseded_by: str | None = None        # row ID of the superseding row
    kind: str | None = None                 # change | correction

    @property
    def current(self) -> bool:
        return self.superseded_at is None

    @property
    def first(self) -> SlotRow:
        return self.rows[0]

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r.message_id for r in self.rows))


@dataclass
class SlotState:
    version: int
    values: list[SlotValue]
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def current(self, as_of: str | None = None) -> list[SlotValue]:
        """Currently accepted values; with `as_of` (bitemporal), the values holding at that day:
        corrections excluded, changed values included while their valid interval covers it."""
        if as_of is None:
            return [v for v in self.values if v.current]
        day = _date(as_of)
        out = []
        for v in self.values:
            if v.kind == "correction":
                continue
            if v.valid_from is not None and _date(v.valid_from) > day:
                continue
            if v.valid_until is not None and _date(v.valid_until) <= day:
                continue
            if not v.current and v.valid_until is None:
                continue  # ended at an unknown time: not asserted for any day
            out.append(v)
        return out


class SlotTable:
    """Append-only slot rows of one history; `guard` and `time` are the ablation-B factors."""

    def __init__(self, history_id: str, inventory: SlotInventory, *, guard: bool = True,
                 time: str = "bitemporal"):
        if time not in TIMES:
            raise ValueError(f"time must be one of {TIMES}")
        self.history_id, self.inventory = history_id, inventory
        self.guard, self.time = guard, time
        self.rows: list[SlotRow] = []

    @property
    def head(self) -> int:
        return self.rows[-1].version if self.rows else 0

    def append(self, rows: Iterable[SlotRow]) -> None:
        """Append the rows of one version (all with the same version, after the head)."""
        rows = list(rows)
        versions = {r.version for r in rows}
        if len(versions) > 1 or (versions and min(versions) <= self.head):
            raise ValueError(f"rows must share one version after the head {self.head}")
        ids = {r.row_id for r in self.rows}
        for row in rows:
            if row.slot not in self.inventory.slots:
                raise ValueError(f"slot {row.slot!r} outside the inventory")
            if row.function not in self.inventory.functions:
                raise ValueError(f"function {row.function!r} outside the inventory")
            if row.row_id in ids:
                raise ValueError(f"duplicate row ID {row.row_id}")
            ids.add(row.row_id)
        self.rows.extend(rows)

    # resolution -------------------------------------------------------------------------------
    def _licensed(self, row: SlotRow, old: SlotValue) -> str | None:
        """None when `row` may end `old`; else the failed guard condition."""
        if not self.guard:
            return None
        fn = self.inventory.match_function(row.function)
        if not any(r.speaker == row.speaker and self.inventory.match_function(r.function) == fn
                   for r in old.rows):
            return "speaker_or_function"
        if row.report_mode != "own":
            return "report_mode"
        return None

    def _end(self, old: SlotValue, row: SlotRow, valid_end: str | None) -> None:
        old.superseded_at, old.superseded_by = row.version, row.row_id
        old.kind = "correction" if row.correction or row.function == "correct" else "change"
        if old.kind == "change" and self.time == "bitemporal" and valid_end is not None \
                and old.valid_until is None:
            if old.valid_from is None or _date(old.valid_from) < _date(valid_end):
                old.valid_until = valid_end

    def state(self, version: int | None = None) -> SlotState:
        """The values and their status at cut-off `version` (default: the head)."""
        version = self.head if version is None else version
        bitemporal = self.time == "bitemporal"
        values: list[SlotValue] = []
        conflicts: list[dict[str, Any]] = []
        for row in self.rows:
            if row.version > version:
                break
            start = row.valid_from if bitemporal else None
            until = row.valid_until if bitemporal else None
            same = [v for v in values if v.key == row.key and v.current
                    and normalise(v.value) == normalise(row.value)
                    and (not bitemporal or (v.valid_from, v.first.valid_until) == (start, until))]
            if row.polarity == "negative":
                for old in same:
                    reason = self._licensed(row, old)
                    if reason is None:
                        self._end(old, row, until)
                    else:
                        conflicts.append({"version": row.version, "kept": old.first.row_id,
                                          "new": row.row_id, "reason": reason})
                continue
            if same:
                same[0].rows.append(row)
                continue
            new = SlotValue(row.key, row.value, [row], start, until)
            if row.slot in self.inventory.exclusive and until is None:
                for old in values:
                    if old.key != row.key or not old.current or old.valid_until is not None:
                        continue
                    reason = self._licensed(row, old)
                    if reason is None:
                        self._end(old, row, start)
                    else:
                        conflicts.append({"version": row.version, "kept": old.first.row_id,
                                          "new": row.row_id, "reason": reason})
            values.append(new)
        return SlotState(version, values, conflicts)

    # persistence ------------------------------------------------------------------------------
    def save(self, directory: Path) -> list[Path]:
        path = Path(directory) / "slots.json"
        path.write_text(json.dumps({"history_id": self.history_id, "guard": self.guard,
                                    "time": self.time, "rows": [asdict(r) for r in self.rows]},
                                   ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return [path]

    @classmethod
    def restore(cls, directory: Path, inventory: SlotInventory, *, guard: bool | None = None,
                time: str | None = None) -> SlotTable:
        """Replay a snapshot; `guard` and `time`, when given, must equal the snapshot's arm."""
        data = json.loads((Path(directory) / "slots.json").read_text(encoding="utf-8"))
        for name, expected in (("guard", guard), ("time", time)):
            if expected is not None and data[name] != expected:
                raise ValueError(f"{directory}: snapshot has {name}={data[name]!r}, the config "
                                 f"{expected!r}")
        table = cls(data["history_id"], inventory, guard=data["guard"], time=data["time"])
        by_version: dict[int, list[SlotRow]] = {}
        for record in data["rows"]:
            row = SlotRow(**record)
            by_version.setdefault(row.version, []).append(row)
        for version in sorted(by_version):
            table.append(by_version[version])
        return table
