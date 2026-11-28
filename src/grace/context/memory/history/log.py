"""Append-only message log: one version per message, idempotent retries (plan 5.1).

The log of one history holds the `Message` records of `context/api.py` in version order. Appending
message r commits version r; versions are exactly 1..N without gaps (contracts.md, "Message").
Appending a message whose version is already committed is a retry: it is a no-op when the message
is identical to the stored one and an error otherwise. Nothing is ever changed or removed, so a
read at version r sees exactly the messages with version <= r, whatever was appended later.
"""

from __future__ import annotations

import json
from pathlib import Path

from grace.context.api import Message

LOG_FILE = "messages.jsonl"


class LogError(ValueError):
    """An append violates the log rules; nothing was written."""


class LogConflict(LogError):
    """A retry at a committed version carries a different message."""


class MessageLog:
    """The raw message log of one history."""

    def __init__(self, history_id: str):
        if not isinstance(history_id, str) or not history_id:
            raise LogError("history_id must be a non-empty string")
        self.history_id = history_id
        self._messages: list[Message] = []
        self._by_id: dict[str, Message] = {}

    @property
    def head(self) -> int:
        """The last committed version (0 when empty)."""
        return len(self._messages)

    def next_version(self) -> int:
        """The version the next message must carry."""
        return self.head + 1

    def append(self, message: Message) -> int:
        """Commit `message` at its version and return the version.

        Raises LogError on another history, a gap, or a reused message ID, and LogConflict when a
        retry at a committed version differs from the stored message.
        """
        if not isinstance(message, Message):
            raise LogError(f"expected a Message, got {type(message).__name__}")
        if message.history_id != self.history_id:
            raise LogError(f"message of history {message.history_id!r} appended to log of "
                           f"{self.history_id!r}")
        if message.version <= self.head:
            stored = self._messages[message.version - 1]
            if stored == message:
                return message.version
            raise LogConflict(f"version {message.version} is committed with message "
                              f"{stored.message_id!r}; the retry differs")
        if message.version != self.next_version():
            raise LogError(f"version {message.version} would leave a gap; next is "
                           f"{self.next_version()}")
        if message.message_id in self._by_id:
            raise LogError(f"message ID {message.message_id!r} is already at version "
                           f"{self._by_id[message.message_id].version}")
        self._messages.append(message)
        self._by_id[message.message_id] = message
        return message.version

    def get(self, version: int) -> Message:
        if not 1 <= version <= self.head:
            raise KeyError(f"version {version} is not committed (head {self.head})")
        return self._messages[version - 1]

    def by_id(self, message_id: str, version: int | None = None) -> Message:
        """The message with this ID; with `version`, only if it is visible at that version."""
        message = self._by_id.get(message_id)
        if message is None or (version is not None and message.version > version):
            raise KeyError(f"message {message_id!r} is not visible at version {version}")
        return message

    def messages(self, version: int | None = None) -> list[Message]:
        """The messages with version <= `version` (all when None), in version order."""
        upto = self.head if version is None else min(version, self.head)
        return list(self._messages[:max(upto, 0)])

    def save(self, directory: Path) -> Path:
        """Write `messages.jsonl` into `directory`; refuses to overwrite."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / LOG_FILE
        with path.open("x", encoding="utf-8") as f:
            for m in self._messages:
                f.write(json.dumps(m.to_record(), ensure_ascii=False, sort_keys=True) + "\n")
        return path

    @classmethod
    def restore(cls, directory: Path, history_id: str) -> MessageLog:
        log = cls(history_id)
        path = Path(directory) / LOG_FILE
        # JSON Lines are split on "\n" only: str.splitlines() also splits on U+2028
        # and U+0085, which json.dumps(ensure_ascii=False) leaves inside strings.
        text = path.read_text(encoding="utf-8")
        for line in filter(None, text.split("\n")):
            log.append(Message.from_record(json.loads(line)))
        return log
