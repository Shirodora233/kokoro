"""Conversation orchestration service."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from llm.config import LLMConfig
from llm.interfaces import ChatClient, ChatMessageParam
from llm.openai_client import OpenAIChatClient
from memory import (
    ActiveMemoryContext,
    ContextAction,
    ConversationContextState,
    LLMMemoryExtractor,
    MemoryContextBlock,
    MemoryDebugRecorder,
    MemoryDebugService,
    MemoryExtractionPromptBuilder,
    MemoryInputMessage,
    MemoryContextRetriever,
    MemoryRecord,
    MemoryRuntimeConfig,
    MemorySearchResult,
    MemorySourceRef,
    MemorySystem,
    MemoryTurnCommitInput,
    MemoryTurnInput,
    MemoryTurnPrepareResult,
    MemoryTurnResult,
    MemoryTurnSnapshot,
    NormalizedMemoryContextRetriever,
    PostgresNormalizedMemorySearch,
    MemoryRuntime,
    PersistentMemoryWritePlanApplier,
)

from .config import ConversationRuntimeConfig, StorageConfig
from .context import ModelContext, PaginatedMessages, SessionManager
from .models import (
    ChatSession,
    ConversationCheckpoint,
    ConversationMemoryDebugTrace,
    ConversationTurn,
    Message,
    SessionBranch,
    User,
    utc_now,
)
from .storage.postgres import PostgresConversationStore

LOGGER = logging.getLogger(__name__)


class ConversationService:
    def __init__(
        self,
        store: PostgresConversationStore,
        chat_client: ChatClient,
        config: LLMConfig,
        memory_system: MemorySystem | None = None,
        memory_debug_service: MemoryDebugService | None = None,
        timezone: str = "UTC",
    ) -> None:
        self.store = store
        self.chat_client = chat_client
        self.config = config
        self.sessions = SessionManager(store)
        self.memory_system = memory_system or MemoryRuntime()
        self.memory_debug_service = (
            memory_debug_service
            or self._default_memory_debug_service(self.memory_system)
        )
        self.timezone = timezone

    @classmethod
    def default(
        cls,
        env_file: str | Path = ".env",
    ) -> "ConversationService":
        config = LLMConfig.from_env(env_file)
        storage_config = StorageConfig.from_env(env_file)
        runtime_config = ConversationRuntimeConfig.from_env(env_file)
        memory_config = MemoryRuntimeConfig.from_env(env_file)
        from memory.persistence.postgres import PostgresPersistentMemoryRepository

        store = PostgresConversationStore(storage_config.database_url)
        store.checkpoints.fail_incomplete_turns()
        persistent_repository = PostgresPersistentMemoryRepository(
            storage_config.database_url
        )
        memory_write_applier = PersistentMemoryWritePlanApplier(persistent_repository)
        memory_context_retriever: MemoryContextRetriever = (
            NormalizedMemoryContextRetriever(
                persistent_repository,
                search=PostgresNormalizedMemorySearch(persistent_repository),
            )
        )
        chat_client = OpenAIChatClient(config)
        debug_recorder = MemoryDebugRecorder(
            enabled=memory_config.debug_enabled,
            max_traces=memory_config.debug_max_traces,
            max_raw_chars=memory_config.debug_max_raw_chars,
        )
        extractor = None
        if memory_config.extraction_enabled:
            extractor = LLMMemoryExtractor(
                chat_client=chat_client,
                model=memory_config.extraction_model or config.model,
                temperature=memory_config.extraction_temperature,
                prompt_builder=MemoryExtractionPromptBuilder(
                    max_context_messages=(
                        memory_config.extraction_max_context_messages
                    ),
                ),
                debug_recorder=debug_recorder,
            )
        memory_system = MemoryRuntime(
            context_retriever=memory_context_retriever,
            write_applier=memory_write_applier,
            extractor=extractor,
            debug_recorder=debug_recorder,
        )
        memory_debug_service = MemoryDebugService(
            recorder=debug_recorder,
            active_cache=memory_system.active_cache,
            persistent_repository=persistent_repository,
        )
        return cls(
            store=store,
            chat_client=chat_client,
            config=config,
            memory_system=memory_system,
            memory_debug_service=memory_debug_service,
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
        idempotency_key: str | None = None,
    ) -> tuple[Message, Message]:
        session = self._require_session(session_id)
        author_id = user_id or session.user_id
        if author_id != session.user_id:
            raise ValueError("Only the session owner can send messages in this store")
        return self._send_checkpointed_message(
            session=session,
            content=content,
            user_id=author_id,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

    def _send_checkpointed_message(
        self,
        session: ChatSession,
        content: str,
        user_id: str,
        metadata: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> tuple[Message, Message]:
        if idempotency_key:
            existing_turn = self.store.checkpoints.get_turn_by_idempotency_key(
                session.id,
                idempotency_key,
            )
            if existing_turn is not None:
                if existing_turn.status == "committed":
                    return self._messages_for_committed_turn(existing_turn)
                raise ValueError(
                    f"Turn with idempotency_key is {existing_turn.status}: "
                    f"{idempotency_key}"
                )

        user_message = Message.create(
            session_id=session.id,
            user_id=user_id,
            role="user",
            content=content,
            metadata=metadata,
        )
        turn = ConversationTurn.create(
            session_id=session.id,
            user_message_id=user_message.id,
            idempotency_key=idempotency_key,
        )
        self.store.checkpoints.begin_turn(turn)

        try:
            base_checkpoint = self.store.checkpoints.latest_checkpoint(session.id)
            memory_prepare = self._prepare_memory_turn(
                session,
                user_message,
                include_unpersisted_user_message=True,
            )
            self._apply_memory_context_actions(memory_prepare.context_actions)
            llm_messages = self._build_llm_context_for_pending_user(
                session,
                user_message,
                memory_prepare.memory_context,
            )
            completion = self.chat_client.complete(
                llm_messages,
                model=session.model,
                temperature=session.temperature,
            )
            assistant_message = Message.create(
                session_id=session.id,
                role="assistant",
                content=completion.content,
                model=completion.model or session.model or self.config.model,
                token_usage=completion.usage,
                metadata={"provider_message_id": completion.provider_message_id},
            )
            committed = self._commit_checkpointed_turn(
                session=session,
                base_checkpoint=base_checkpoint,
                turn=turn,
                user_message=user_message,
                assistant_message=assistant_message,
                memory_prepare=memory_prepare,
            )
            return committed
        except Exception as error:
            self.store.checkpoints.mark_turn_failed(turn.id, str(error))
            raise

    def _commit_checkpointed_turn(
        self,
        session: ChatSession,
        base_checkpoint: ConversationCheckpoint | None,
        turn: ConversationTurn,
        user_message: Message,
        assistant_message: Message,
        memory_prepare: MemoryTurnPrepareResult,
    ) -> tuple[Message, Message]:
        from memory.persistence.postgres import PostgresPersistentMemoryRepository
        from memory.writing import PersistentMemoryWritePlanApplier

        memory_status = "not_run"
        memory_commit: MemoryTurnResult | None = None
        debug_trace_id = memory_prepare.metadata.get("debug_trace_id")
        with self.store.database.connect() as connection:
            try:
                with connection.transaction():
                    locked_session = self.store.checkpoints.lock_session(
                        connection,
                        session.id,
                    )
                    latest_checkpoint = (
                        self.store.checkpoints.latest_checkpoint_in_connection(
                            connection,
                            session.id,
                        )
                    )
                    if (latest_checkpoint.id if latest_checkpoint else None) != (
                        base_checkpoint.id if base_checkpoint else None
                    ):
                        raise ValueError(
                            "Session advanced while the assistant response was running"
                        )

                    user_sequence = self.store.checkpoints.next_sequence_in_connection(
                        connection,
                        session.id,
                    )
                    assistant_sequence = user_sequence + 1
                    branch = self.store.checkpoints.get_branch_in_connection(
                        connection,
                        session.id,
                    )
                    parent_checkpoint_id = (
                        latest_checkpoint.id
                        if latest_checkpoint is not None
                        else branch.base_checkpoint_id
                        if branch is not None
                        else None
                    )
                    checkpoint = ConversationCheckpoint.create(
                        session_id=session.id,
                        turn_id=turn.id,
                        parent_checkpoint_id=parent_checkpoint_id,
                        assistant_message_id=assistant_message.id,
                        sequence=assistant_sequence,
                        session_snapshot=locked_session.to_record(),
                        metadata={"memory_status": "not_run"},
                    )

                    self._tag_message_for_checkpoint(
                        user_message,
                        turn.id,
                        checkpoint.id,
                        user_sequence,
                    )
                    self._tag_message_for_checkpoint(
                        assistant_message,
                        turn.id,
                        checkpoint.id,
                        assistant_sequence,
                    )
                    self.store.checkpoints.append_message_in_connection(
                        connection,
                        user_message,
                        turn_id=turn.id,
                        checkpoint_id=checkpoint.id,
                        sequence=user_sequence,
                    )
                    self.store.checkpoints.append_message_in_connection(
                        connection,
                        assistant_message,
                        turn_id=turn.id,
                        checkpoint_id=checkpoint.id,
                        sequence=assistant_sequence,
                    )

                    try:
                        with connection.transaction():
                            base_applier = getattr(
                                self.memory_system,
                                "write_applier",
                                None,
                            )
                            if not isinstance(
                                base_applier,
                                PersistentMemoryWritePlanApplier,
                            ) or not isinstance(
                                base_applier.repository,
                                PostgresPersistentMemoryRepository,
                            ):
                                raise TypeError(
                                    "PostgreSQL memory commit requires "
                                    "PersistentMemoryWritePlanApplier"
                                )
                            write_applier = PersistentMemoryWritePlanApplier(
                                _ConnectionPersistentMemoryRepository(
                                    base_applier.repository,
                                    connection,
                                ),
                                adapter=base_applier.adapter,
                            )
                            memory_commit = self.memory_system.commit_turn_with_writers(
                                MemoryTurnCommitInput(
                                    snapshot=memory_prepare.snapshot,
                                    assistant_message=self._to_memory_input_message(
                                        assistant_message
                                    ),
                                    metadata={
                                        "source": "conversation_service",
                                        "created_turn_id": turn.id,
                                        "created_checkpoint_id": checkpoint.id,
                                        "created_checkpoint_sequence": assistant_sequence,
                                    },
                                ),
                                write_applier=write_applier,
                            )
                            memory_status = "committed"
                    except Exception as error:
                        LOGGER.warning("Memory turn commit failed: %s", error)
                        memory_status = "failed"
                        memory_commit = MemoryTurnResult(
                            metadata={"error": str(error)}
                        )

                    checkpoint = ConversationCheckpoint(
                        **{
                            **checkpoint.to_record(),
                            "active_memory_snapshot": (
                                memory_commit.metadata.get("active_memory_context", {})
                                if memory_commit is not None
                                else {}
                            ),
                            "metadata": {
                                **dict(checkpoint.metadata),
                                "memory_status": memory_status,
                            },
                        }
                    )
                    self.store.checkpoints.create_checkpoint_in_connection(
                        connection,
                        checkpoint,
                    )
                    self._persist_memory_debug_trace_in_connection(
                        connection,
                        trace_id=(
                            debug_trace_id
                            if isinstance(debug_trace_id, str)
                            else None
                        ),
                        session_id=session.id,
                        turn=turn,
                        user_message=user_message,
                        assistant_message=assistant_message,
                        checkpoint=checkpoint,
                        memory_status=memory_status,
                    )
                    self.store.checkpoints.complete_turn_in_connection(
                        connection,
                        turn.id,
                        user_message_id=user_message.id,
                        assistant_message_id=assistant_message.id,
                        checkpoint_id=checkpoint.id,
                        debug_trace_id=(
                            debug_trace_id
                            if isinstance(debug_trace_id, str)
                            else None
                        ),
                        memory_status=memory_status,
                        metadata={"checkpoint_sequence": assistant_sequence},
                    )
                    connection.execute(
                        "UPDATE sessions SET updated_at = %s WHERE id = %s",
                        (utc_now(), session.id),
                    )
            except Exception:
                self._restore_active_context(memory_prepare.snapshot)
                raise
        self._apply_memory_context_actions(
            memory_commit.context_actions if memory_commit is not None else []
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

    def list_checkpoints(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[ConversationCheckpoint]:
        self._require_session(session_id, allow_archived=True)
        return self.store.checkpoints.list_visible_checkpoints(
            session_id,
            limit=limit,
        )

    def update_checkpoint(
        self,
        checkpoint_id: str,
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationCheckpoint:
        return self.store.checkpoints.update_checkpoint_label(
            checkpoint_id,
            label=label,
            metadata=metadata,
        )

    def create_branch_from_checkpoint(
        self,
        session_id: str,
        checkpoint_id: str,
        title: str | None = None,
    ) -> ChatSession:
        parent_session = self._require_session(session_id, allow_archived=True)
        checkpoint = self.store.checkpoints.get_checkpoint(checkpoint_id)
        if checkpoint is None:
            raise ValueError(f"Unknown checkpoint_id: {checkpoint_id}")
        visible_checkpoint_ids = {
            item.id
            for item in self.store.checkpoints.list_visible_checkpoints(
                session_id,
                limit=10_000,
            )
        }
        if checkpoint.id not in visible_checkpoint_ids:
            raise ValueError("checkpoint_id is not visible from session_id")
        parent_branch = self.store.checkpoints.get_branch(session_id)
        root_session_id = (
            parent_branch.root_session_id if parent_branch else parent_session.id
        )
        branch_session = ChatSession.create(
            user_id=parent_session.user_id,
            title=title or f"{parent_session.title} branch",
            system_prompt=parent_session.system_prompt,
            model=parent_session.model,
            temperature=parent_session.temperature,
            max_context_messages=parent_session.max_context_messages,
            context_start_index=parent_session.context_start_index,
            metadata={
                **dict(parent_session.metadata),
                "branch": {
                    "parent_session_id": parent_session.id,
                    "base_checkpoint_id": checkpoint.id,
                    "base_sequence": checkpoint.sequence,
                },
            },
        )
        branch = SessionBranch(
            session_id=branch_session.id,
            root_session_id=root_session_id,
            parent_session_id=parent_session.id,
            base_checkpoint_id=checkpoint.id,
            base_sequence=checkpoint.sequence,
        )
        return self.store.checkpoints.create_branch_session(
            branch_session,
            branch,
        )

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

    def get_memory_debug_snapshot(
        self,
        username: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        user_id = self._debug_user_id(username=username, session_id=session_id)
        return self.memory_debug_service.memory_snapshot(
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )

    def list_memory_debug_traces(
        self,
        session_id: str | None = None,
        message_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.memory_debug_service.trace_summaries(
            session_id=session_id,
            message_id=message_id,
            limit=limit,
        )

    def get_memory_debug_trace(
        self,
        trace_id: str,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        trace = self.memory_debug_service.trace(
            trace_id,
            include_raw=include_raw,
        )
        if trace is not None:
            return trace
        persisted = self.store.debug.get_trace(trace_id)
        if persisted is not None:
            return persisted.trace
        raise ValueError(f"Unknown memory debug trace: {trace_id}")

    def list_session_turn_debug(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_session(session_id, allow_archived=True)
        return [
            trace.to_summary_record()
            for trace in self.store.debug.list_visible_turn_debug(
                self._visible_session_scopes(session_id),
                limit=limit,
            )
        ]

    def get_checkpoint_memory(
        self,
        checkpoint_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        checkpoint = self.store.checkpoints.get_checkpoint(checkpoint_id)
        if checkpoint is None:
            raise ValueError(f"Unknown checkpoint_id: {checkpoint_id}")
        session = self._require_session(checkpoint.session_id, allow_archived=True)
        snapshot = self.store.debug.checkpoint_memory_snapshot(
            user_id=session.user_id,
            scopes=self._checkpoint_visible_session_scopes(checkpoint),
            limit=limit,
        )
        return {
            "checkpoint": checkpoint.to_record(),
            "active_memory_snapshot": dict(checkpoint.active_memory_snapshot),
            **snapshot,
        }

    def memory_debug_trace_for_message(
        self,
        session_id: str,
        message_id: str,
    ) -> dict[str, Any] | None:
        traces = self.list_memory_debug_traces(
            session_id=session_id,
            message_id=message_id,
            limit=1,
        )
        return traces[0] if traces else None

    def _prepare_memory_turn(
        self,
        session: ChatSession,
        user_message: Message,
        include_unpersisted_user_message: bool = False,
    ) -> MemoryTurnPrepareResult:
        turn = self._build_memory_turn_input(
            session,
            user_message,
            include_unpersisted_user_message=include_unpersisted_user_message,
        )
        try:
            return self.memory_system.prepare_turn(turn)
        except Exception as error:
            LOGGER.warning("Memory turn preparation failed: %s", error)
            snapshot = MemoryTurnSnapshot(
                turn=turn,
                search_result=MemorySearchResult(
                    metadata={"error": str(error), "source": "prepare_turn"}
                ),
                metadata={"error": str(error), "source": "prepare_turn"},
            )
            return MemoryTurnPrepareResult(
                snapshot=snapshot,
                metadata=snapshot.metadata,
            )

    def _build_memory_turn_input(
        self,
        session: ChatSession,
        user_message: Message,
        include_unpersisted_user_message: bool = False,
    ) -> MemoryTurnInput:
        messages = self.store.list_messages(session.id)
        if include_unpersisted_user_message:
            messages = [*messages, user_message]
        context_start_index = self._clamp_context_start_index(
            session.context_start_index,
            total_messages=len(messages),
        )
        active_messages = messages[context_start_index:]
        active_memory_context = self._restore_active_context_if_needed(session)
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
            active_memory_context=active_memory_context,
            metadata={
                "visible_session_scopes": self._visible_session_scopes(session.id),
            },
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

    def _build_llm_context_for_pending_user(
        self,
        session: ChatSession,
        user_message: Message,
        memory_context: list[MemoryContextBlock] | None = None,
    ) -> list[ChatMessageParam]:
        committed_messages = self.store.list_messages(session.id)
        messages = [*committed_messages, user_message]
        context_start_index = self._clamp_context_start_index(
            session.context_start_index,
            total_messages=len(messages),
        )
        llm_messages: list[ChatMessageParam] = []
        if session.system_prompt:
            llm_messages.append({"role": "system", "content": session.system_prompt})
        for message in messages[context_start_index:]:
            if message.role in {"system", "user", "assistant"}:
                llm_messages.append(
                    {"role": message.role, "content": message.content}
                )
        memory_message = self._render_memory_context(memory_context or [])
        if not memory_message:
            return llm_messages
        insert_at = 1 if llm_messages and llm_messages[0]["role"] == "system" else 0
        return [*llm_messages[:insert_at], memory_message, *llm_messages[insert_at:]]

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

    def _debug_user_id(
        self,
        username: str | None,
        session_id: str | None,
    ) -> str | None:
        user_id = None
        if username:
            user = self.store.find_user_by_username(username)
            if not user:
                raise ValueError(f"Unknown username: {username}")
            user_id = user.id
        if session_id:
            session = self._require_session(session_id, allow_archived=True)
            if user_id is not None and session.user_id != user_id:
                raise ValueError("session_id does not belong to username")
            user_id = user_id or session.user_id
        return user_id

    def _restore_active_context_if_needed(
        self,
        session: ChatSession,
    ) -> ActiveMemoryContext | None:
        current = self._current_active_context(session)
        if current is not None and _active_context_has_records(current):
            return None

        checkpoints = self.store.checkpoints.list_visible_checkpoints(
            session.id,
            limit=1,
        )
        if not checkpoints:
            return None
        checkpoint = checkpoints[0]
        restored = _active_memory_context_from_record(
            checkpoint.active_memory_snapshot,
            metadata={
                "restored_from_checkpoint_id": checkpoint.id,
                "restored_from_checkpoint_sequence": checkpoint.sequence,
            },
        )
        if not _active_context_has_records(restored):
            return None

        active_cache = getattr(self.memory_system, "active_cache", None)
        set_context = getattr(active_cache, "set", None)
        if callable(set_context):
            try:
                restored = set_context(
                    user_id=session.user_id,
                    session_id=session.id,
                    context=restored,
                )
            except Exception as error:
                LOGGER.debug("Active memory context cache restore failed: %s", error)
        return restored

    def _current_active_context(
        self,
        session: ChatSession,
    ) -> ActiveMemoryContext | None:
        get_active_context = getattr(self.memory_system, "get_active_context", None)
        if not callable(get_active_context):
            return None
        try:
            context = get_active_context(
                user_id=session.user_id,
                session_id=session.id,
            )
        except Exception as error:
            LOGGER.debug("Active memory context lookup failed: %s", error)
            return None
        return context if isinstance(context, ActiveMemoryContext) else None

    def _visible_session_scopes(self, session_id: str) -> list[dict[str, Any]]:
        return self.store.checkpoints.branch_memory_scope(session_id)

    def _checkpoint_visible_session_scopes(
        self,
        checkpoint: ConversationCheckpoint,
    ) -> list[dict[str, Any]]:
        scopes = self._visible_session_scopes(checkpoint.session_id)
        scoped: list[dict[str, Any]] = []
        found_checkpoint_session = False
        for scope in scopes:
            scope_copy = dict(scope)
            if scope_copy.get("session_id") == checkpoint.session_id:
                found_checkpoint_session = True
                max_sequence = scope_copy.get("max_checkpoint_sequence")
                if not isinstance(max_sequence, int) or max_sequence > checkpoint.sequence:
                    scope_copy["max_checkpoint_sequence"] = checkpoint.sequence
            scoped.append(scope_copy)
        if not found_checkpoint_session:
            scoped.append(
                {
                    "session_id": checkpoint.session_id,
                    "max_checkpoint_sequence": checkpoint.sequence,
                }
            )
        return scoped

    def _persist_memory_debug_trace_in_connection(
        self,
        connection: Any,
        *,
        trace_id: str | None,
        session_id: str,
        turn: ConversationTurn,
        user_message: Message,
        assistant_message: Message,
        checkpoint: ConversationCheckpoint,
        memory_status: str,
    ) -> None:
        if not trace_id:
            return
        recorder = getattr(self.memory_debug_service, "recorder", None)
        trace = recorder.get(trace_id) if recorder is not None else None
        if trace is None:
            return
        payload = _sanitized_memory_debug_trace(trace.to_record(include_raw=False))
        summary = _memory_debug_summary(payload, memory_status=memory_status)
        self.store.debug.save_trace_in_connection(
            connection,
            ConversationMemoryDebugTrace(
                trace_id=trace_id,
                session_id=session_id,
                turn_id=turn.id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                checkpoint_id=checkpoint.id,
                checkpoint_sequence=checkpoint.sequence,
                memory_status=memory_status,
                summary=summary,
                trace={
                    **payload,
                    "memory_status": memory_status,
                    "checkpoint_id": checkpoint.id,
                    "checkpoint_sequence": checkpoint.sequence,
                },
            ),
        )

    def _messages_for_committed_turn(
        self,
        turn: ConversationTurn,
    ) -> tuple[Message, Message]:
        messages = self.store.list_messages(turn.session_id)
        by_id = {message.id: message for message in messages}
        user_message = (
            by_id.get(turn.user_message_id) if turn.user_message_id else None
        )
        assistant_message = (
            by_id.get(turn.assistant_message_id)
            if turn.assistant_message_id
            else None
        )
        if user_message is None or assistant_message is None:
            raise ValueError("Committed turn messages are missing")
        return user_message, assistant_message

    def _tag_message_for_checkpoint(
        self,
        message: Message,
        turn_id: str,
        checkpoint_id: str,
        sequence: int,
    ) -> None:
        message.metadata = {
            **dict(message.metadata),
            "turn_id": turn_id,
            "checkpoint_id": checkpoint_id,
            "sequence": sequence,
            "status": "active",
        }

    def _restore_active_context(self, snapshot: MemoryTurnSnapshot) -> None:
        active_cache = getattr(self.memory_system, "active_cache", None)
        if active_cache is None:
            return
        turn = snapshot.turn
        if snapshot.active_memory_context is None:
            return
        active_cache.set(
            user_id=turn.user_id,
            session_id=turn.session_id,
            context=snapshot.active_memory_context,
        )

    def _default_memory_debug_service(
        self,
        memory_system: MemorySystem,
    ) -> MemoryDebugService:
        recorder = getattr(memory_system, "debug_recorder", None)
        if recorder is None:
            recorder = MemoryDebugRecorder(enabled=False)
        return MemoryDebugService(
            recorder=recorder,
            active_cache=getattr(memory_system, "active_cache", None),
        )


def _sanitized_memory_debug_trace(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    extraction = sanitized.get("extraction")
    if isinstance(extraction, dict):
        extraction.pop("prompt_messages", None)
        extraction.pop("raw_output", None)
    retrieval = sanitized.get("retrieval")
    if isinstance(retrieval, dict):
        request = retrieval.get("retrieval_request")
        if isinstance(request, dict):
            context = request.get("conversation_context")
            if isinstance(context, list):
                request["conversation_context_count"] = len(context)
                request["conversation_context"] = [
                    {
                        "id": message.get("id"),
                        "role": message.get("role"),
                    }
                    for message in context
                    if isinstance(message, dict)
                ]
    return sanitized


def _active_memory_context_from_record(
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> ActiveMemoryContext:
    context = _dict(payload)
    context_metadata = dict(_dict(context.get("metadata")))
    context_metadata.update(metadata or {})
    last_refreshed_at_message_id = context.get("last_refreshed_at_message_id")
    return ActiveMemoryContext(
        event_memories=_memory_records_from_record(context.get("event_memories")),
        entity_memories=_memory_records_from_record(context.get("entity_memories")),
        property_memories=_memory_records_from_record(context.get("property_memories")),
        other_memories=_memory_records_from_record(context.get("other_memories")),
        last_refreshed_at_message_id=(
            last_refreshed_at_message_id
            if isinstance(last_refreshed_at_message_id, str)
            else None
        ),
        metadata=context_metadata,
    )


def _active_context_has_records(context: ActiveMemoryContext) -> bool:
    return any(
        (
            context.event_memories,
            context.entity_memories,
            context.property_memories,
            context.other_memories,
        )
    )


def _memory_records_from_record(value: Any) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    if not isinstance(value, list):
        return records
    for item in value:
        record = _memory_record_from_record(item)
        if record is not None:
            records.append(record)
    return records


def _memory_record_from_record(value: Any) -> MemoryRecord | None:
    raw = _dict(value)
    memory_type = raw.get("memory_type")
    if memory_type not in {
        "event",
        "description",
        "entity",
        "property",
        "link",
        "time_ref",
        "time_link",
        "summary",
    }:
        return None
    record_id = raw.get("id")
    text = raw.get("text")
    return MemoryRecord(
        id=record_id if isinstance(record_id, str) else None,
        memory_type=memory_type,
        text=text if isinstance(text, str) else "",
        source_refs=_memory_source_refs_from_record(raw.get("source_refs")),
        metadata=dict(_dict(raw.get("metadata"))),
    )


def _memory_source_refs_from_record(value: Any) -> list[MemorySourceRef]:
    source_refs: list[MemorySourceRef] = []
    if not isinstance(value, list):
        return source_refs
    for item in value:
        raw = _dict(item)
        source_type = raw.get("source_type")
        source_id = raw.get("source_id")
        if not isinstance(source_type, str) or not isinstance(source_id, str):
            continue
        span_start = raw.get("span_start")
        span_end = raw.get("span_end")
        quote = raw.get("quote")
        source_refs.append(
            MemorySourceRef(
                source_type=source_type,
                source_id=source_id,
                quote=quote if isinstance(quote, str) else None,
                span_start=span_start if isinstance(span_start, int) else None,
                span_end=span_end if isinstance(span_end, int) else None,
                metadata=dict(_dict(raw.get("metadata"))),
            )
        )
    return source_refs


def _memory_debug_summary(
    payload: dict[str, Any],
    *,
    memory_status: str,
) -> dict[str, Any]:
    extraction = _dict(payload.get("extraction"))
    retrieval = _dict(payload.get("retrieval"))
    search_result = _dict(retrieval.get("search_result"))
    active_context = _dict(retrieval.get("active_memory_context"))
    normalized_records = _list(extraction.get("normalized_records"))
    hits = _list(search_result.get("hits"))
    memory_context = _list(retrieval.get("memory_context"))
    return {
        "status": payload.get("status"),
        "parse_status": extraction.get("parse_status"),
        "parse_error": extraction.get("parse_error"),
        "candidate_count": len(normalized_records),
        "parsed_candidate_counts": _dict(extraction.get("parsed_candidate_counts")),
        "validated_candidate_counts": _dict(
            extraction.get("validated_candidate_counts")
        ),
        "dropped_candidate_counts": _dict(extraction.get("dropped_candidate_counts")),
        "validation_error_count": len(_list(extraction.get("validation_errors"))),
        "search_hit_count": len(hits),
        "memory_context_count": len(memory_context),
        "active_counts": {
            "events": len(_list(active_context.get("event_memories"))),
            "entities": len(_list(active_context.get("entity_memories"))),
            "properties": len(_list(active_context.get("property_memories"))),
            "other": len(_list(active_context.get("other_memories"))),
        },
        "memory_status": memory_status,
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class _ConnectionPersistentMemoryRepository:
    def __init__(self, repository: Any, connection: Any) -> None:
        self.repository = repository
        self.connection = connection

    def save_bundle(self, bundle):
        return self.repository.save_bundle_in_connection(self.connection, bundle)

    def __getattr__(self, name: str):
        return getattr(self.repository, name)
