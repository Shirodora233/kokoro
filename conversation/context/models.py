"""Return models for conversation context use cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil
from typing import Any

from conversation.models import Message
from llm.interfaces import ChatMessageParam


@dataclass(frozen=True)
class PaginatedMessages:
    session_id: str
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool
    messages: list[Message]

    @classmethod
    def from_messages(
        cls,
        session_id: str,
        messages: list[Message],
        page: int,
        page_size: int,
    ) -> "PaginatedMessages":
        total = len(messages)
        total_pages = max(1, ceil(total / page_size))
        start = (page - 1) * page_size
        end = start + page_size
        return cls(
            session_id=session_id,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
            messages=messages[start:end],
        )

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["messages"] = [message.to_record() for message in self.messages]
        return record


@dataclass(frozen=True)
class ModelContext:
    session_id: str
    context_start_index: int
    total_messages: int
    messages: list[ChatMessageParam]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
