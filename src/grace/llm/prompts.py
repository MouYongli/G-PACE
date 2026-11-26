"""Prompt templates from `resources/prompts/` (plan 5.6, "Prompt assembly"; plan 8.1).

A prompt is one directory `resources/prompts/<name>/` holding

- `system.txt`: the fixed instructions, output contract and examples. It has no placeholders, so
  it is the same for every call of this prompt and stays in the prefix cache. An empty file means
  no system message (used only for upstream prompts reproduced verbatim).
- `user.txt`: the varying part, with `{{variable}}` placeholders. Stable inputs go first and the
  call-specific inputs last (for the answer prompt: context first, question last).

The template hash `sha256` is computed over the files of the directory like `resources_sha256`
(Experiment run section): `sha256sum`-style lines `<sha256>  <relative path>` sorted by path, then
the SHA-256 of their concatenation. It goes into `prompt_sha256` of every call record and is pinned
in `configs/common/prompts.yaml`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from grace.config.paths import REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "resources" / "prompts"
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_STRAY = re.compile(r"\{\{|\}\}")


class PromptError(ValueError):
    """A malformed template, a checksum mismatch or a wrong set of variables."""


def tree_sha256(directory: Path) -> str:
    """`sha256sum`-style checksum of every regular file under `directory` (symlinks refused)."""
    directory = Path(directory)
    lines = []
    for path in sorted(directory.rglob("*"), key=lambda p: p.relative_to(directory).as_posix()
                       .encode("utf-8")):
        if path.is_symlink():
            raise PromptError(f"symbolic link in {directory}: {path}")
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(directory).as_posix()}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Prompt:
    name: str
    system: str
    user: str
    sha256: str

    @property
    def variables(self) -> tuple[str, ...]:
        """Placeholders of the user template, in order of first appearance."""
        return tuple(dict.fromkeys(PLACEHOLDER.findall(self.user)))

    def render(self, **values: str) -> list[dict[str, str]]:
        """Chat messages with every placeholder filled; missing or extra values are errors."""
        expected = set(self.variables)
        missing, extra = expected - values.keys(), values.keys() - expected
        if missing or extra:
            raise PromptError(f"prompt {self.name}: missing {sorted(missing)}, "
                              f"unexpected {sorted(extra)}")
        for key, value in values.items():
            if not isinstance(value, str):
                raise PromptError(f"prompt {self.name}: value of {key} must be a string")
        user = PLACEHOLDER.sub(lambda m: values[m.group(1)], self.user)
        if not self.system:  # an upstream prompt that sends one user message (official judges)
            return [{"role": "user", "content": user}]
        return [{"role": "system", "content": self.system}, {"role": "user", "content": user}]


def load_prompt(name: str, *, expected_sha256: str | None = None,
                root: Path = PROMPTS_DIR) -> Prompt:
    """Load `root/<name>/`; check its structure and, if given, its pinned checksum."""
    directory = Path(root) / name
    files = {p.name for p in directory.iterdir()} if directory.is_dir() else set()
    if files != {"system.txt", "user.txt"}:
        raise PromptError(f"{directory} must hold exactly system.txt and user.txt, has "
                          f"{sorted(files)}")
    system = (directory / "system.txt").read_text(encoding="utf-8")
    user = (directory / "user.txt").read_text(encoding="utf-8")
    if PLACEHOLDER.search(system) or _STRAY.search(system):
        raise PromptError(f"{directory}/system.txt is the fixed prefix and takes no placeholders")
    if _STRAY.search(PLACEHOLDER.sub("", user)):
        raise PromptError(f"{directory}/user.txt has a malformed placeholder")
    if not PLACEHOLDER.search(user):
        raise PromptError(f"{directory}/user.txt has no placeholder")
    digest = tree_sha256(directory)
    if expected_sha256 is not None and digest != expected_sha256:
        raise PromptError(f"prompt {name}: sha256 {digest} != pinned {expected_sha256}")
    return Prompt(name=name, system=system, user=user, sha256=digest)


def load_registry(path: Path) -> dict[str, Mapping]:
    """The prompt registry `configs/common/prompts.yaml`: name -> entry with `sha256`."""
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    prompts = data.get("prompts") if isinstance(data, Mapping) else None
    if not isinstance(prompts, Mapping) or not prompts:
        raise PromptError(f"{path} has no `prompts` mapping")
    return dict(prompts)


def load_pinned(name: str, registry: Path, *, root: Path = PROMPTS_DIR) -> Prompt:
    """Load a prompt and check it against its pin in the registry."""
    entries = load_registry(registry)
    if name not in entries:
        raise PromptError(f"prompt {name} is not registered in {registry}")
    return load_prompt(name, expected_sha256=entries[name]["sha256"], root=root)
