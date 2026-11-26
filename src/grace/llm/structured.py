"""Parse model output as JSON and validate it against `resources/schemas/llm/<name>.json`.

Failures are returned to the caller, never repaired here: the caller decides whether a failure is
an `invalid_output` attempt, a compilation repair, or an `invalid` prediction (plan 5.6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from grace.config.paths import REPO_ROOT

SCHEMAS_DIR = REPO_ROOT / "resources" / "schemas" / "llm"
_FENCE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(.*?)\n?```\s*$", re.DOTALL)
_THINK = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)


@dataclass(frozen=True)
class Parsed:
    value: Any
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


def load_schema(name: str, root: Path = SCHEMAS_DIR) -> Draft202012Validator:
    schema = json.loads((Path(root) / f"{name}.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def extract_json(text: str) -> Any:
    """The single JSON value in `text`: bare, in one code fence, or after an empty think block.

    Raises ValueError when there is none or more text than one value around it.
    """
    body = _THINK.sub("", text).strip()
    if fenced := _FENCE.match(body):
        body = fenced.group(1).strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not a single JSON value: {exc.msg} at char {exc.pos}") from exc


def parse(text: str | None, validator: Draft202012Validator) -> Parsed:
    if text is None or not text.strip():
        return Parsed(None, "empty output")
    try:
        value = extract_json(text)
    except ValueError as exc:
        return Parsed(None, str(exc))
    errors = sorted(validator.iter_errors(value), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.absolute_path) or "<root>"
        return Parsed(None, f"schema violation at {where}: {first.message}")
    return Parsed(value, None)
