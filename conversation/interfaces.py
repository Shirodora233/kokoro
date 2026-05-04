"""Custom interfaces for storage and LLM providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict

from .models import ChatSession, Message, User


class ChatMessageParam(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class ChatCompletionResult:
    content: str
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    provider_message_id: str | None = None


class ChatClient(Protocol):
    def complete(
        self,
        messages: list[ChatMessageParam],
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        """Generate one assistant message from normalized chat messages."""


class ConversationStore(Protocol):
    def create_user(self, user: User) -> User: ...

    def get_user(self, user_id: str) -> User | None: ...

    def find_user_by_username(self, username: str) -> User | None: ...

    def list_users(self) -> list[User]: ...

    def delete_user(self, user_id: str, cascade: bool = False) -> dict[str, int]: ...

    def create_session(self, session: ChatSession) -> ChatSession: ...

    def get_session(self, session_id: str) -> ChatSession | None: ...

    def update_session(self, session: ChatSession) -> ChatSession: ...

    def list_sessions(self, user_id: str | None = None) -> list[ChatSession]: ...

    def delete_session(self, session_id: str) -> dict[str, int]: ...

    def append_message(self, message: Message) -> Message: ...

    def list_messages(self, session_id: str) -> list[Message]: ...

    def delete_all(self) -> dict[str, int]: ...
