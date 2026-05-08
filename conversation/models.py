"""Domain models stored as JSON records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

Role = Literal["system", "user", "assistant"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass
class User:
    id: str
    username: str
    display_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        username: str,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "User":
        now = utc_now()
        return cls(
            id=new_id("usr"),
            username=username,
            display_name=display_name,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "User":
        return cls(**record)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatSession:
    id: str
    user_id: str
    title: str
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_context_messages: int | None = None
    context_start_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    archived_at: str | None = None

    @classmethod
    def create(
        cls,
        user_id: str,
        title: str = "New chat",
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_context_messages: int | None = None,
        context_start_index: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> "ChatSession":
        now = utc_now()
        return cls(
            id=new_id("ses"),
            user_id=user_id,
            title=title,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_context_messages=max_context_messages,
            context_start_index=context_start_index,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "ChatSession":
        return cls(**record)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    def touch(self) -> None:
        self.updated_at = utc_now()


@dataclass
class Message:
    id: str
    session_id: str
    role: Role
    content: str
    user_id: str | None = None
    model: str | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        session_id: str,
        role: Role,
        content: str,
        user_id: str | None = None,
        model: str | None = None,
        token_usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Message":
        return cls(
            id=new_id("msg"),
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            model=model,
            token_usage=token_usage or {},
            metadata=metadata or {},
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Message":
        return cls(**record)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
