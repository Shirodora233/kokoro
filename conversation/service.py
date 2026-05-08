"""Conversation orchestration service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from session_management import ModelContext, PaginatedMessages, SessionManager

from .config import LLMConfig, StorageConfig, default_data_dir
from .interfaces import ChatClient, ChatMessageParam, ConversationStore
from .models import ChatSession, Message, User, utc_now
from .openai_client import OpenAIChatClient
from .storage import JsonConversationStore


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        chat_client: ChatClient,
        config: LLMConfig,
    ) -> None:
        self.store = store
        self.chat_client = chat_client
        self.config = config
        self.sessions = SessionManager(store)

    @classmethod
    def default(
        cls,
        env_file: str | Path = ".env",
        data_dir: str | Path | None = None,
    ) -> "ConversationService":
        config = LLMConfig.from_env(env_file)
        storage_config = StorageConfig.from_env(env_file)
        if storage_config.backend == "postgres":
            from database import PostgresConversationStore

            store = PostgresConversationStore(storage_config.database_url or "")
        else:
            store = JsonConversationStore(data_dir or default_data_dir())
        return cls(store=store, chat_client=OpenAIChatClient(config), config=config)

    def create_user(
        self,
        username: str,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> User:
        existing = self.store.find_user_by_username(username)
        if existing:
            return existing
        return self.store.create_user(
            User.create(username=username, display_name=display_name, metadata=metadata)
        )

    def start_session(
        self,
        user_id: str,
        title: str = "New chat",
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_context_messages: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatSession:
        session = ChatSession.create(
            user_id=user_id,
            title=title,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_context_messages=max_context_messages,
            metadata=metadata,
        )
        return self.store.create_session(session)

    def rename_session(self, session_id: str, title: str) -> ChatSession:
        session = self._require_session(session_id)
        session.title = title
        session.touch()
        return self.store.update_session(session)

    def archive_session(self, session_id: str) -> ChatSession:
        session = self._require_session(session_id)
        session.archived_at = utc_now()
        session.touch()
        return self.store.update_session(session)

    def delete_session(self, session_id: str) -> dict[str, int]:
        self._require_session(session_id, allow_archived=True)
        return self.store.delete_session(session_id)

    def delete_user(self, user_id: str, cascade: bool = False) -> dict[str, int]:
        user = self.store.get_user(user_id)
        if not user:
            raise ValueError(f"Unknown user_id: {user_id}")
        return self.store.delete_user(user_id=user_id, cascade=cascade)

    def delete_user_by_username(
        self,
        username: str,
        cascade: bool = False,
    ) -> dict[str, int]:
        user = self.store.find_user_by_username(username)
        if not user:
            raise ValueError(f"Unknown username: {username}")
        return self.delete_user(user.id, cascade=cascade)

    def delete_all(self) -> dict[str, int]:
        return self.store.delete_all()

    def send_message(
        self,
        session_id: str,
        content: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Message, Message]:
        session = self._require_session(session_id)
        author_id = user_id or session.user_id
        if author_id != session.user_id:
            raise ValueError("Only the session owner can send messages in this store")

        user_message = self.store.append_message(
            Message.create(
                session_id=session.id,
                user_id=author_id,
                role="user",
                content=content,
                metadata=metadata,
            )
        )

        llm_messages = self._build_llm_context(session)
        completion = self.chat_client.complete(
            llm_messages,
            model=session.model,
            temperature=session.temperature,
        )
        assistant_message = self.store.append_message(
            Message.create(
                session_id=session.id,
                role="assistant",
                content=completion.content,
                model=completion.model or session.model or self.config.model,
                token_usage=completion.usage,
                metadata={"provider_message_id": completion.provider_message_id},
            )
        )
        return user_message, assistant_message

    def list_users(self) -> list[User]:
        return self.store.list_users()

    def list_sessions(self, user_id: str | None = None) -> list[ChatSession]:
        return self.store.list_sessions(user_id=user_id)

    def get_transcript(self, session_id: str) -> list[Message]:
        self._require_session(session_id, allow_archived=True)
        return self.store.list_messages(session_id)

    def get_session_history(
        self,
        session_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedMessages:
        return self.sessions.get_full_history(
            session_id=session_id,
            page=page,
            page_size=page_size,
        )

    def get_model_context(self, session_id: str) -> ModelContext:
        return self.sessions.get_model_context(session_id)

    def set_context_start_index(
        self,
        session_id: str,
        context_start_index: int,
    ) -> ChatSession:
        return self.sessions.set_context_start_index(
            session_id=session_id,
            context_start_index=context_start_index,
        )

    def query_session_messages(
        self,
        session_id: str,
        query: str,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedMessages:
        return self.sessions.query_messages(
            session_id=session_id,
            query=query,
            page=page,
            page_size=page_size,
        )

    def _build_llm_context(self, session: ChatSession) -> list[ChatMessageParam]:
        return self.sessions.get_model_context(session.id).messages

    def _require_session(
        self,
        session_id: str,
        allow_archived: bool = False,
    ) -> ChatSession:
        session = self.store.get_session(session_id)
        if not session:
            raise ValueError(f"Unknown session_id: {session_id}")
        if session.archived_at and not allow_archived:
            raise ValueError(f"Session is archived: {session_id}")
        return session
