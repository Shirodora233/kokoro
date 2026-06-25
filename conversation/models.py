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
    head_checkpoint_id: str | None = None
    root_session_id: str | None = None
    parent_session_id: str | None = None
    base_checkpoint_id: str | None = None
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
        head_checkpoint_id: str | None = None,
        root_session_id: str | None = None,
        parent_session_id: str | None = None,
        base_checkpoint_id: str | None = None,
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
            head_checkpoint_id=head_checkpoint_id,
            root_session_id=root_session_id,
            parent_session_id=parent_session_id,
            base_checkpoint_id=base_checkpoint_id,
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


@dataclass
class ConversationTurn:
    id: str
    session_id: str
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    checkpoint_id: str | None = None
    status: str = "llm_running"
    idempotency_key: str | None = None
    debug_trace_id: str | None = None
    memory_status: str = "not_run"
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        session_id: str,
        user_message_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ConversationTurn":
        now = utc_now()
        return cls(
            id=new_id("turn"),
            session_id=session_id,
            user_message_id=user_message_id,
            idempotency_key=idempotency_key,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "ConversationTurn":
        return cls(**record)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConversationCheckpoint:
    id: str
    session_id: str
    turn_id: str | None
    parent_checkpoint_id: str | None
    assistant_message_id: str | None
    sequence: int
    label: str | None = None
    session_snapshot: dict[str, Any] = field(default_factory=dict)
    active_memory_snapshot: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        session_id: str,
        sequence: int,
        turn_id: str | None = None,
        parent_checkpoint_id: str | None = None,
        assistant_message_id: str | None = None,
        session_snapshot: dict[str, Any] | None = None,
        active_memory_snapshot: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ConversationCheckpoint":
        return cls(
            id=new_id("chk"),
            session_id=session_id,
            turn_id=turn_id,
            parent_checkpoint_id=parent_checkpoint_id,
            assistant_message_id=assistant_message_id,
            sequence=sequence,
            session_snapshot=session_snapshot or {},
            active_memory_snapshot=active_memory_snapshot or {},
            metadata=metadata or {},
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "ConversationCheckpoint":
        return cls(**record)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConversationMemoryDebugTrace:
    trace_id: str
    session_id: str
    turn_id: str | None
    user_message_id: str | None
    assistant_message_id: str | None
    checkpoint_id: str | None
    checkpoint_sequence: int | None
    memory_status: str = "not_run"
    summary: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "ConversationMemoryDebugTrace":
        return cls(**record)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    def to_summary_record(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "user_message_id": self.user_message_id,
            "assistant_message_id": self.assistant_message_id,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_sequence": self.checkpoint_sequence,
            "memory_status": self.memory_status,
            "created_at": self.created_at,
            **dict(self.summary),
        }


@dataclass
class SessionBranch:
    session_id: str
    root_session_id: str
    parent_session_id: str
    base_checkpoint_id: str
    base_sequence: int
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "SessionBranch":
        return cls(**record)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
