"""Component registry: engine kinds that live in `context/`, by import path (structure.md).

The harness (`eval/runner/harness/`) may import only `context/api.py`, so it cannot import
`context/engine.py`. An engine config names its kind (`engine: grace`); kinds not served by the
baselines package are looked up here and imported lazily, which keeps the import rules intact
(structure.md: "The component registry in `config/` stores only a mapping from names to import
paths and loads lazily"). A registered class builds itself from the harness's model port and the
config's params with `from_port(model, **params)`.
"""

from __future__ import annotations

import importlib
from typing import Any

ENGINES: dict[str, str] = {
    "grace": "grace.context.engine:GraceEngine",
}


def load_engine(kind: str) -> Any:
    """The class registered for `kind`; KeyError for an unknown kind."""
    module, _, name = ENGINES[kind].partition(":")
    return getattr(importlib.import_module(module), name)
