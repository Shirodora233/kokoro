"""Interfaces for conversation context storage backends."""

from __future__ import annotations

from typing import Protocol

from conversation.models import ChatSession, Message


class SessionRepository(Protocol):
    def get_session(self, session_id: str) -> ChatSession | None: ...

    def update_session(self, session: ChatSession) -> ChatSession: ...

    def list_messages(self, session_id: str) -> list[Message]: ...
