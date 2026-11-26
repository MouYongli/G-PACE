"""Tokenisation and chunking shared by BM25, dense retrieval and the retrieval baselines.

Minimal first version written by T003 for the retrieval baselines; the package belongs to T025
(docs/work/plan/structure.md), which may extend it. Retrieval terms are lexical tokens for BM25,
not the answering model's tokens: budgets are always counted with the model's tokenizer.

A chunk is one message, so every chunk maps to exactly one evidence ID (`message_id`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from grace.context.api import Message

_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lower-cased word tokens (Unicode letters, digits and underscore)."""
    return [token.lower() for token in _TOKEN.findall(text)]


@dataclass(frozen=True)
class Chunk:
    """A retrievable unit: its ID, the evidence IDs whose text it holds, and its text."""

    chunk_id: str
    evidence_ids: tuple[str, ...]
    version: int
    text: str


def render_message(message: Message) -> str:
    """The text of a message as it is indexed: speaker and text."""
    return f"{message.speaker}: {message.text}" if message.speaker else message.text


def chunk_message(message: Message) -> list[Chunk]:
    """One chunk per message, identified by its `message_id`."""
    return [Chunk(message.message_id, (message.message_id,), message.version,
                  render_message(message))]
