"""Conversation orchestration service."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from llm.config import LLMConfig
from llm.interfaces import ChatClient, ChatMessageParam
from llm.openai_client import OpenAIChatClient
from memory import (
    ContextAction,
    ConversationContextState,
    LLMMemoryExtractor,
    MemoryContextBlock,
    MemoryExtractionPromptBuilder,
    MemoryInputMessage,
    MemoryRetriever,
    MemoryRuntimeConfig,
    MemoryStore,
    MemorySystem,
    MemoryTurnInput,
    MemoryTurnResult,
    MemoryWriteResultPersistenceSync,
    NormalizedMemoryRetriever,
    InMemoryMemorySystem,
)

from .config import ConversationRuntimeConfig, StorageConfig, default_data_dir
from .context import ModelContext, PaginatedMessages, SessionManager
from .interfaces import ConversationStore
from .models import ChatSession, Message, User, utc_now
from .storage import JsonConversationStore

LOGGER = logging.getLogger(__name__)


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        chat_client: ChatClient,
        config: LLMConfig,
        memory_system: MemorySystem | None = None,
        timezone: str = "UTC",
    ) -> None:
        self.store = store
        self.chat_client = chat_client
        self.config = config
        self.sessions = SessionManager(store)
        self.memory_system = memory_system or InMemoryMemorySystem()
        self.timezone = timezone

    @classmethod
    def default(
        cls,
        env_file: str | Path = ".env",
        data_dir: str | Path | None = None,
    ) -> "ConversationService":
        config = LLMConfig.from_env(env_file)
        storage_config = StorageConfig.from_env(env_file)
        runtime_config = ConversationRuntimeConfig.from_env(env_file)
        memory_config = MemoryRuntimeConfig.from_env(env_file)
        memory_store: MemoryStore | None = None
        memory_retriever: MemoryRetriever | None = None
        persistence_sync: MemoryWriteResultPersistenceSync | None = None
        if storage_config.backend == "postgres":
            from .storage.postgres import PostgresConversationStore
            from memory.persistence.postgres import PostgresPersistentMemoryRepository
            from memory.storage.postgres import PostgresMemoryStore

            store = PostgresConversationStore(storage_config.database_url or "")
            memory_store = PostgresMemoryStore(storage_config.database_url or "")
            persistent_repository = PostgresPersistentMemoryRepository(
                storage_config.database_url or ""
            )
            persistence_sync = MemoryWriteResultPersistenceSync(
                persistent_repository
            )
            memory_retriever = NormalizedMemoryRetriever(persistent_repository)
        else:
            store = JsonConversationStore(data_dir or default_data_dir())
        chat_client = OpenAIChatClient(config)
        memory_system = InMemoryMemorySystem(
            store=memory_store,
            retriever=memory_retriever,
            persistence_sync=persistence_sync,
        )
        if memory_config.extraction_enabled:
            memory_system = InMemoryMemorySystem(
                store=memory_store,
                retriever=memory_retriever,
                persistence_sync=persistence_sync,
                extractor=LLMMemoryExtractor(
                    chat_client=chat_client,
                    model=memory_config.extraction_model or config.model,
                    temperature=memory_config.extraction_temperature,
                    prompt_builder=MemoryExtractionPromptBuilder(
                        max_context_messages=(
                            memory_config.extraction_max_context_messages
                        ),
                    ),
                )
            )
        return cls(
            store=store,
            chat_client=chat_client,
            config=config,
            memory_system=memory_system,
            timezone=runtime_config.timezone,
        )

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

        memory_result = self._process_memory_turn(session, user_message)
        self._apply_memory_context_actions(memory_result.context_actions)

        llm_messages = self._build_llm_context(
            session,
            memory_context=memory_result.memory_context,
        )
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

    def _process_memory_turn(
        self,
        session: ChatSession,
        user_message: Message,
    ) -> MemoryTurnResult:
        turn = self._build_memory_turn_input(session, user_message)
        try:
            return self.memory_system.process_turn(turn)
        except Exception as error:
            LOGGER.warning("Memory turn processing failed: %s", error)
            return MemoryTurnResult()

    def _build_memory_turn_input(
        self,
        session: ChatSession,
        user_message: Message,
    ) -> MemoryTurnInput:
        messages = self.store.list_messages(session.id)
        context_start_index = self._clamp_context_start_index(
            session.context_start_index,
            total_messages=len(messages),
        )
        active_messages = messages[context_start_index:]
        return MemoryTurnInput(
            user_id=session.user_id,
            session_id=session.id,
            new_message=self._to_memory_input_message(user_message),
            timezone=self.timezone,
            conversation_context=[
                self._to_memory_input_message(message) for message in active_messages
            ],
            context_state=ConversationContextState(
                context_start_index=context_start_index,
                total_messages=len(messages),
                max_context_messages=session.max_context_messages,
                active_message_ids=[message.id for message in active_messages],
            ),
        )

    def _to_memory_input_message(self, message: Message) -> MemoryInputMessage:
        return MemoryInputMessage(
            id=message.id,
            role=message.role,
            content=message.content,
            session_id=message.session_id,
            user_id=message.user_id,
            created_at=message.created_at,
            metadata=message.metadata,
        )

    def _apply_memory_context_actions(self, actions: list[ContextAction]) -> None:
        # No memory context actions are executable until summary storage is introduced.
        if actions:
            LOGGER.info(
                "Memory context actions are not applied yet: %s",
                [action.action_type for action in actions],
            )
        return None

    def _build_llm_context(
        self,
        session: ChatSession,
        memory_context: list[MemoryContextBlock] | None = None,
    ) -> list[ChatMessageParam]:
        messages = self.sessions.get_model_context(session.id).messages
        memory_message = self._render_memory_context(memory_context or [])
        if not memory_message:
            return messages
        insert_at = 1 if messages and messages[0]["role"] == "system" else 0
        return [*messages[:insert_at], memory_message, *messages[insert_at:]]

    def _render_memory_context(
        self,
        memory_context: list[MemoryContextBlock],
    ) -> ChatMessageParam | None:
        blocks = [block for block in memory_context if block.content.strip()]
        if not blocks:
            return None
        ordered_blocks = sorted(blocks, key=lambda block: block.priority, reverse=True)
        content = "\n\n".join(block.content.strip() for block in ordered_blocks)
        return {"role": "system", "content": f"Memory context:\n{content}"}

    def _clamp_context_start_index(
        self,
        context_start_index: int,
        total_messages: int,
    ) -> int:
        return min(max(0, context_start_index), total_messages)

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
