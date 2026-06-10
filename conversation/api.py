"""Public application interface for embedding the dialogue system."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import Message
from .service import ConversationService


class DialogueAPI:
    """Small facade that callers can use without depending on storage details."""

    def __init__(self, service: ConversationService) -> None:
        self.service = service

    def register_user(
        self,
        username: str,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.service.create_user(username, display_name, metadata).to_record()

    def open_session(
        self,
        username: str,
        title: str = "New chat",
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user = self.service.create_user(username)
        session = self.service.start_session(
            user_id=user.id,
            title=title,
            system_prompt=system_prompt,
            metadata=metadata,
        )
        return session.to_record()

    def ask(
        self,
        session_id: str,
        content: str,
        username: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user_id = None
        if username:
            user = self.service.create_user(username)
            user_id = user.id
        user_message, assistant_message = self.service.send_message(
            session_id=session_id,
            content=content,
            user_id=user_id,
            metadata=metadata,
        )
        return {
            "user_message": user_message.to_record(),
            "assistant_message": assistant_message.to_record(),
        }

    def transcript(self, session_id: str) -> list[dict[str, Any]]:
        return [message.to_record() for message in self.service.get_transcript(session_id)]

    def session_history(
        self,
        session_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        return self.service.get_session_history(
            session_id=session_id,
            page=page,
            page_size=page_size,
        ).to_record()

    def model_context(self, session_id: str) -> dict[str, Any]:
        return self.service.get_model_context(session_id).to_record()

    def set_context_start_index(
        self,
        session_id: str,
        context_start_index: int,
    ) -> dict[str, Any]:
        return self.service.set_context_start_index(
            session_id=session_id,
            context_start_index=context_start_index,
        ).to_record()

    def query_session_messages(
        self,
        session_id: str,
        query: str,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        return self.service.query_session_messages(
            session_id=session_id,
            query=query,
            page=page,
            page_size=page_size,
        ).to_record()

    def users(self) -> list[dict[str, Any]]:
        return [user.to_record() for user in self.service.list_users()]

    def sessions(self, username: str | None = None) -> list[dict[str, Any]]:
        user_id = None
        if username:
            user = self.service.create_user(username)
            user_id = user.id
        return [session.to_record() for session in self.service.list_sessions(user_id)]

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        return self.service.rename_session(session_id, title).to_record()

    def archive_session(self, session_id: str) -> dict[str, Any]:
        return self.service.archive_session(session_id).to_record()

    def delete_session(self, session_id: str) -> dict[str, int]:
        return self.service.delete_session(session_id)

    def delete_user(self, username: str, cascade: bool = False) -> dict[str, int]:
        return self.service.delete_user_by_username(username, cascade=cascade)

    def delete_all(self) -> dict[str, int]:
        return self.service.delete_all()


def create_default_api(
    env_file: str | Path = ".env",
) -> DialogueAPI:
    return DialogueAPI(ConversationService.default(env_file=env_file))


def format_transcript(messages: list[Message]) -> str:
    lines: list[str] = []
    for message in messages:
        lines.append(f"[{message.created_at}] {message.role}: {message.content}")
    return "\n".join(lines)
