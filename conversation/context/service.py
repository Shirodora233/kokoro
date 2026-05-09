"""Session history, context-window, and query management."""

from __future__ import annotations

from conversation.models import ChatSession, Message
from llm.interfaces import ChatMessageParam

from .interfaces import SessionRepository
from .models import ModelContext, PaginatedMessages


class SessionManager:
    """Owns session-level chat history and model-context behavior."""

    def __init__(self, repository: SessionRepository, max_page_size: int = 200) -> None:
        self.repository = repository
        self.max_page_size = max_page_size

    def get_full_history(
        self,
        session_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedMessages:
        self._require_session(session_id, allow_archived=True)
        page = self._normalize_page(page)
        page_size = self._normalize_page_size(page_size)
        messages = self.repository.list_messages(session_id)
        return PaginatedMessages.from_messages(
            session_id=session_id,
            messages=messages,
            page=page,
            page_size=page_size,
        )

    def get_model_context(
        self,
        session_id: str,
        include_system_prompt: bool = True,
    ) -> ModelContext:
        session = self._require_session(session_id)
        messages = self.repository.list_messages(session_id)
        context_start_index = self._clamp_context_start_index(
            session.context_start_index,
            total_messages=len(messages),
        )
        if context_start_index != session.context_start_index:
            session.context_start_index = context_start_index
            self.repository.update_session(session)

        context_messages: list[ChatMessageParam] = []
        if include_system_prompt and session.system_prompt:
            context_messages.append({"role": "system", "content": session.system_prompt})

        for message in messages[context_start_index:]:
            if message.role in {"system", "user", "assistant"}:
                context_messages.append({"role": message.role, "content": message.content})

        return ModelContext(
            session_id=session_id,
            context_start_index=context_start_index,
            total_messages=len(messages),
            messages=context_messages,
        )

    def set_context_start_index(
        self,
        session_id: str,
        context_start_index: int,
    ) -> ChatSession:
        session = self._require_session(session_id, allow_archived=True)
        messages = self.repository.list_messages(session_id)
        if context_start_index < 0 or context_start_index > len(messages):
            raise ValueError(
                "context_start_index must be between 0 and the total message count"
            )
        session.context_start_index = context_start_index
        session.touch()
        return self.repository.update_session(session)

    def query_messages(
        self,
        session_id: str,
        query: str,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedMessages:
        self._require_session(session_id, allow_archived=True)
        raise NotImplementedError(
            "Session message query is reserved for the database-backed implementation"
        )

    def _require_session(
        self,
        session_id: str,
        allow_archived: bool = False,
    ) -> ChatSession:
        session = self.repository.get_session(session_id)
        if not session:
            raise ValueError(f"Unknown session_id: {session_id}")
        if session.archived_at and not allow_archived:
            raise ValueError(f"Session is archived: {session_id}")
        return session

    def _normalize_page(self, page: int) -> int:
        return max(1, page)

    def _normalize_page_size(self, page_size: int) -> int:
        page_size = max(1, page_size)
        return min(page_size, self.max_page_size)

    def _clamp_context_start_index(
        self,
        context_start_index: int,
        total_messages: int,
    ) -> int:
        return min(max(0, context_start_index), total_messages)
