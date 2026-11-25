"""Token counting with the model's own tokenizer and chat template (plan 8.1, Cost ledger).

The tokenizer and chat template are pinned per model config (`configs/models/<model>.yaml`): the
Hugging Face repository, the revision, and the SHA-256 of every tokenizer file and of the chat
template. `HFTokenCounter.from_model_config` refuses to count when a file on disk differs from its
pin, so two runs that count differently cannot both claim the same pin. No model choice is wired in
here; the model line-up is decision D006.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

Message = Mapping[str, str]


class TokenizerPinError(RuntimeError):
    """The tokenizer or chat template on disk does not match its pin, or is missing."""


class TokenCounter(Protocol):
    """What the LLM client and the context assembly need from a counter."""

    name: str

    def count_text(self, text: str) -> int:
        """Tokens of plain text, without special tokens."""

    def count_messages(self, messages: Sequence[Message]) -> int:
        """Tokens of a whole prompt: the messages rendered by the chat template, with the
        generation prompt appended, exactly as the server will see them."""


@dataclass(frozen=True)
class TokenizerPin:
    """The tokenizer part of a model config."""

    model: str
    hf_repo: str
    revision: str
    files: dict[str, str]  # file name in the snapshot -> SHA-256
    chat_template: str  # file name of the chat template in the snapshot
    template_kwargs: dict = field(default_factory=dict)  # e.g. {"enable_thinking": false}
    thinking: bool = False

    @classmethod
    def from_config(cls, config: Mapping) -> TokenizerPin:
        """Parse a model config. `thinking` (a top-level boolean) is required: a reasoning model
        such as Qwen3.5 writes its thinking into `content` unless thinking is disabled in the
        template or the server runs a reasoning parser, so the setting is never left implicit.
        `enable_thinking` in the template kwargs, when present, must agree with it."""
        try:
            tok = config["tokenizer"]
            pin = cls(model=config["model"], hf_repo=config["hf_repo"],
                      revision=config["revision"], files=dict(tok["files"]),
                      chat_template=tok["chat_template"],
                      template_kwargs=dict(tok.get("template_kwargs") or {}),
                      thinking=config["thinking"])
        except (KeyError, TypeError) as exc:
            raise TokenizerPinError(f"model config lacks tokenizer pin field: {exc}") from exc
        if not isinstance(pin.thinking, bool):
            raise TokenizerPinError(f"{pin.model}: `thinking` must be true or false")
        if pin.template_kwargs.get("enable_thinking", pin.thinking) != pin.thinking:
            raise TokenizerPinError(f"{pin.model}: template_kwargs.enable_thinking disagrees "
                                    "with `thinking`")
        if len(pin.revision) != 40:
            raise TokenizerPinError(f"{pin.model}: revision must be a full 40-character SHA")
        if pin.chat_template not in pin.files:
            raise TokenizerPinError(f"{pin.model}: chat template {pin.chat_template} is not pinned")
        for name, digest in pin.files.items():
            if not (isinstance(digest, str) and len(digest) == 64):
                raise TokenizerPinError(f"{pin.model}: {name} needs a SHA-256 hex digest")
        return pin

    @classmethod
    def from_file(cls, path: Path) -> TokenizerPin:
        return cls.from_config(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    @property
    def template_sha256(self) -> str:
        return self.files[self.chat_template]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def locate_snapshot(pin: TokenizerPin) -> Path:
    """Local snapshot directory of the pinned revision; never downloads."""
    from huggingface_hub import snapshot_download

    try:
        path = snapshot_download(pin.hf_repo, revision=pin.revision, local_files_only=True,
                                 allow_patterns=sorted(pin.files))
    except Exception as exc:  # the hub raises several types for "not in the cache"
        raise TokenizerPinError(
            f"{pin.hf_repo}@{pin.revision} is not in the local Hugging Face cache") from exc
    return Path(path)


def verify_snapshot(pin: TokenizerPin, snapshot: Path) -> None:
    """Compare every pinned file with its SHA-256; raise naming each mismatch."""
    problems = []
    for name, expected in sorted(pin.files.items()):
        path = snapshot / name
        if not path.is_file():
            problems.append(f"{name}: missing")
        elif (actual := sha256_file(path)) != expected:
            problems.append(f"{name}: sha256 {actual} != pinned {expected}")
    if problems:
        raise TokenizerPinError(f"{pin.model} at {snapshot}: " + "; ".join(problems))


class HFTokenCounter:
    """Counts with a pinned Hugging Face tokenizer and chat template (CPU only, no torch)."""

    def __init__(self, pin: TokenizerPin, snapshot: Path):
        verify_snapshot(pin, snapshot)
        from transformers import AutoTokenizer

        self.pin = pin
        self.name = f"{pin.hf_repo}@{pin.revision}"
        self._tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
        template = (snapshot / pin.chat_template).read_text(encoding="utf-8")
        self._tokenizer.chat_template = template  # the pinned file, whatever the config embeds

    @classmethod
    def from_model_config(cls, path: Path) -> HFTokenCounter:
        pin = TokenizerPin.from_file(path)
        return cls(pin, locate_snapshot(pin))

    def count_text(self, text: str) -> int:
        return len(self._tokenizer(text, add_special_tokens=False)["input_ids"])

    def render(self, messages: Sequence[Message]) -> str:
        """The prompt string the chat template produces, with the generation prompt."""
        return self._tokenizer.apply_chat_template(
            [dict(m) for m in messages], tokenize=False, add_generation_prompt=True,
            **self.pin.template_kwargs)

    def count_messages(self, messages: Sequence[Message]) -> int:
        ids = self._tokenizer.apply_chat_template(
            [dict(m) for m in messages], tokenize=True, add_generation_prompt=True,
            **self.pin.template_kwargs)
        if isinstance(ids, Mapping):  # some versions return a BatchEncoding
            ids = ids["input_ids"]
        return len(ids)
