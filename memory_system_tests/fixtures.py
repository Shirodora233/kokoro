"""Shared helpers for memory system composition tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from memory.interfaces import MemoryExtractor
from memory.models import (
    MemoryInputMessage,
    MemoryRecord,
    MemoryRecordType,
    MemorySourceRef,
    MemoryTurnInput,
)

USER_ID = "usr_system_test"
SESSION_ID = "ses_system_test"
TIMEZONE = "Asia/Shanghai"


class SequenceMemoryExtractor(MemoryExtractor):
    """Return predefined candidate batches for successive turns."""

    def __init__(self, batches: Sequence[Sequence[MemoryRecord]]) -> None:
        self._batches = [list(batch) for batch in batches]
        self._index = 0

    def extract(self, turn: MemoryTurnInput) -> Sequence[MemoryRecord]:
        if self._index >= len(self._batches):
            return []
        batch = self._batches[self._index]
        self._index += 1
        return batch


def make_turn(
    message_id: str,
    content: str,
    context_messages: Sequence[MemoryInputMessage] | None = None,
) -> MemoryTurnInput:
    message = make_message(message_id, content)
    return MemoryTurnInput(
        user_id=USER_ID,
        session_id=SESSION_ID,
        new_message=message,
        timezone=TIMEZONE,
        conversation_context=[*(context_messages or []), message],
    )


def make_message(message_id: str, content: str) -> MemoryInputMessage:
    return MemoryInputMessage(
        id=message_id,
        role="user",
        content=content,
        user_id=USER_ID,
        session_id=SESSION_ID,
        created_at="2026-05-13T10:00:00+08:00",
    )


def candidate(
    memory_type: MemoryRecordType,
    text: str,
    client_id: str,
    metadata: dict[str, Any] | None = None,
    source_message_id: str = "msg_test",
) -> MemoryRecord:
    merged_metadata = {"candidate_client_id": client_id}
    merged_metadata.update(metadata or {})
    return MemoryRecord(
        id=None,
        memory_type=memory_type,
        text=text,
        source_refs=[
            MemorySourceRef(
                source_type="message",
                source_id=source_message_id,
            )
        ],
        metadata=merged_metadata,
    )
