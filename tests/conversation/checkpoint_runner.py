"""Run PostgreSQL checkpoint and branch tests for conversation service."""

from __future__ import annotations

import sys
from collections.abc import Callable

from conversation.config import StorageConfig
from conversation.service import ConversationService
from conversation.storage.postgres import PostgresConversationStore
from llm.config import LLMConfig
from llm.interfaces import ChatCompletionResult, ChatMessageParam
from memory import (
    InMemoryMemorySystem,
    MemoryDebugRecorder,
    MemorySearchRequest,
    MemoryWriteResultPersistenceSync,
    NormalizedMemoryContextRetriever,
    PostgresNormalizedMemorySearch,
)
from memory.persistence.postgres import PostgresPersistentMemoryRepository
from memory.storage.postgres import PostgresMemoryStore
from tests.memory.system.fixtures import SequenceMemoryExtractor, candidate
from web_frontend.server import KokoroRequestHandler


USERNAME = "checkpoint_test_user"


def main() -> int:
    config = StorageConfig.from_env(".env")
    tests: list[Callable[[str], None]] = [
        test_atomic_turn_creates_checkpoint_and_idempotent_retry,
        test_checkpoint_failure_rolls_back_visible_state,
        test_branch_session_keeps_original_and_filters_future_memory,
        test_persisted_memory_debug_trace_survives_restart,
        test_checkpoint_memory_filters_future_records,
        test_http_checkpoint_and_branch_routes,
    ]
    for test in tests:
        test(config.database_url or "")
        print(f"PASS {test.__name__}")
    print(f"passed={len(tests)}/{len(tests)}")
    return 0


def test_atomic_turn_creates_checkpoint_and_idempotent_retry(database_url: str) -> None:
    service, chat_client = _service(
        database_url,
        [[candidate("entity", "AtomicBeforeOnly", "cand_atomic")]],
    )
    user = service.create_user(USERNAME)
    session = service.start_session(user.id)

    try:
        user_message, assistant_message = service.send_message(
            session.id,
            "remember AtomicBeforeOnly",
            idempotency_key="idem-atomic",
        )
        retry_user, retry_assistant = service.send_message(
            session.id,
            "remember AtomicBeforeOnly again",
            idempotency_key="idem-atomic",
        )
        messages = service.get_transcript(session.id)
        checkpoints = service.list_checkpoints(session.id)
        records = service.memory_system.store.list_records(
            user_id=user.id,
            session_id=session.id,
        )

        assert chat_client.call_count == 1
        assert retry_user.id == user_message.id
        assert retry_assistant.id == assistant_message.id
        assert [message.role for message in messages] == ["user", "assistant"]
        assert len(checkpoints) == 1
        assert checkpoints[0].assistant_message_id == assistant_message.id
        assert checkpoints[0].sequence == 2
        assert records
        assert records[0].metadata["created_checkpoint_id"] == checkpoints[0].id
        assert records[0].metadata["created_checkpoint_sequence"] == 2
    finally:
        _cleanup(database_url, user.id)


def test_checkpoint_failure_rolls_back_visible_state(database_url: str) -> None:
    service, _chat_client = _service(
        database_url,
        [[candidate("entity", "RollbackOnly", "cand_rollback")]],
    )
    user = service.create_user(USERNAME)
    session = service.start_session(user.id)
    postgres_store = service.store
    original = postgres_store.checkpoints.create_checkpoint_in_connection

    def fail_checkpoint(*args, **kwargs):
        raise RuntimeError("injected checkpoint failure")

    postgres_store.checkpoints.create_checkpoint_in_connection = fail_checkpoint
    try:
        try:
            service.send_message(session.id, "rollback please")
        except RuntimeError as error:
            assert "injected checkpoint failure" in str(error)
        else:
            raise AssertionError("send_message should fail")
        assert service.get_transcript(session.id) == []
        assert service.list_checkpoints(session.id) == []
        assert service.memory_system.store.list_records(
            user_id=user.id,
            session_id=session.id,
        ) == []
    finally:
        postgres_store.checkpoints.create_checkpoint_in_connection = original
        _cleanup(database_url, user.id)


def test_branch_session_keeps_original_and_filters_future_memory(
    database_url: str,
) -> None:
    service, _chat_client = _service(
        database_url,
        [
            [candidate("entity", "BranchBeforeOnly", "cand_before")],
            [candidate("entity", "BranchAfterOnly", "cand_after")],
            [candidate("entity", "BranchChildOnly", "cand_child")],
        ],
    )
    user = service.create_user(USERNAME)
    session = service.start_session(user.id)

    try:
        service.send_message(session.id, "before")
        first_checkpoint = service.list_checkpoints(session.id)[0]
        service.send_message(session.id, "after")
        branch = service.create_branch_from_checkpoint(
            session.id,
            first_checkpoint.id,
            title="checkpoint branch",
        )
        service.send_message(branch.id, "child")

        original_messages = service.get_transcript(session.id)
        branch_messages = service.get_transcript(branch.id)
        branch_scopes = service._visible_session_scopes(branch.id)
        persistent = PostgresPersistentMemoryRepository(database_url)
        search = PostgresNormalizedMemorySearch(persistent)
        after_result = search.search(
            MemorySearchRequest(
                user_id=user.id,
                session_id=branch.id,
                query="BranchAfterOnly",
                metadata={"visible_session_scopes": branch_scopes},
            )
        )
        before_result = search.search(
            MemorySearchRequest(
                user_id=user.id,
                session_id=branch.id,
                query="BranchBeforeOnly",
                metadata={"visible_session_scopes": branch_scopes},
            )
        )

        assert len(original_messages) == 4
        assert len(branch_messages) == 4
        assert [message.content for message in branch_messages[:2]] == [
            "before",
            "assistant response 1",
        ]
        assert branch_messages[-2].content == "child"
        assert after_result.hits == []
        assert before_result.hits
    finally:
        _cleanup(database_url, user.id)


def test_persisted_memory_debug_trace_survives_restart(database_url: str) -> None:
    service, _chat_client = _service(
        database_url,
        [[candidate("entity", "PersistedDebugOnly", "cand_debug")]],
    )
    user = service.create_user(USERNAME)
    session = service.start_session(user.id)

    try:
        service.send_message(session.id, "remember PersistedDebugOnly")
        summaries = service.list_session_turn_debug(session.id)
        assert len(summaries) == 1
        assert summaries[0]["candidate_count"] == 1
        assert summaries[0]["memory_status"] == "committed"
        trace_id = summaries[0]["trace_id"]

        restarted, _ = _service(database_url, [])
        restarted_summaries = restarted.list_session_turn_debug(session.id)
        persisted_trace = restarted.get_memory_debug_trace(
            trace_id,
            include_raw=True,
        )

        assert restarted_summaries[0]["trace_id"] == trace_id
        assert persisted_trace["trace_id"] == trace_id
        assert persisted_trace["extraction"]["parse_status"] == "external"
        assert "raw_output" not in persisted_trace["extraction"]
        assert "prompt_messages" not in persisted_trace["extraction"]
    finally:
        _cleanup(database_url, user.id)


def test_checkpoint_memory_filters_future_records(database_url: str) -> None:
    service, _chat_client = _service(
        database_url,
        [
            [candidate("entity", "CheckpointBeforeOnly", "cand_before")],
            [candidate("entity", "CheckpointAfterOnly", "cand_after")],
        ],
    )
    user = service.create_user(USERNAME)
    session = service.start_session(user.id)

    try:
        service.send_message(session.id, "before memory")
        first_checkpoint = service.list_checkpoints(session.id)[0]
        service.send_message(session.id, "after memory")

        first_memory = service.get_checkpoint_memory(first_checkpoint.id)
        texts = [
            item["text"]
            for item in first_memory["generic_memories"]
        ]

        assert "CheckpointBeforeOnly" in texts
        assert "CheckpointAfterOnly" not in texts
        assert first_memory["checkpoint"]["id"] == first_checkpoint.id
    finally:
        _cleanup(database_url, user.id)


def test_http_checkpoint_and_branch_routes(database_url: str) -> None:
    service, _chat_client = _service(
        database_url,
        [[candidate("entity", "HttpCheckpointOnly", "cand_http")]],
    )
    user = service.create_user(USERNAME)
    session = service.start_session(user.id)
    handler = object.__new__(KokoroRequestHandler)
    handler.service = service

    try:
        handler._route_api(
            "POST",
            f"/api/sessions/{session.id}/messages",
            {},
            {"content": "http checkpoint"},
        )
        checkpoints_response = handler._route_api(
            "GET",
            f"/api/sessions/{session.id}/checkpoints",
            {},
            {},
        )
        checkpoint_id = checkpoints_response["checkpoints"][0]["id"]
        turn_debug_response = handler._route_api(
            "GET",
            f"/api/sessions/{session.id}/turn-debug",
            {},
            {},
        )
        checkpoint_memory_response = handler._route_api(
            "GET",
            f"/api/checkpoints/{checkpoint_id}/memory",
            {},
            {},
        )
        updated_response = handler._route_api(
            "PATCH",
            f"/api/checkpoints/{checkpoint_id}",
            {},
            {"label": "saved point", "metadata": {"pinned": True}},
        )
        branch_response = handler._route_api(
            "POST",
            f"/api/sessions/{session.id}/branches",
            {},
            {"checkpoint_id": checkpoint_id, "title": "http branch"},
        )

        assert updated_response["checkpoint"]["label"] == "saved point"
        assert updated_response["checkpoint"]["metadata"]["pinned"] is True
        assert branch_response["session"]["title"] == "http branch"
        assert turn_debug_response["turn_debug"][0]["checkpoint_id"] == checkpoint_id
        assert checkpoint_memory_response["memory"]["checkpoint"]["id"] == checkpoint_id
    finally:
        _cleanup(database_url, user.id)


def _service(
    database_url: str,
    memory_batches,
) -> tuple[ConversationService, "_StaticChatClient"]:
    store = PostgresConversationStore(database_url)
    store.checkpoints.fail_incomplete_turns()
    memory_store = PostgresMemoryStore(database_url)
    persistent = PostgresPersistentMemoryRepository(database_url)
    debug_recorder = MemoryDebugRecorder()
    memory_system = InMemoryMemorySystem(
        store=memory_store,
        extractor=SequenceMemoryExtractor(memory_batches),
        context_retriever=NormalizedMemoryContextRetriever(
            persistent,
            search=PostgresNormalizedMemorySearch(persistent),
        ),
        persistence_sync=MemoryWriteResultPersistenceSync(persistent),
        debug_recorder=debug_recorder,
    )
    chat_client = _StaticChatClient()
    return (
        ConversationService(
            store=store,
            chat_client=chat_client,
            config=LLMConfig(api_key="test", base_url=None, model="test-model"),
            memory_system=memory_system,
            timezone="Asia/Shanghai",
        ),
        chat_client,
    )


def _cleanup(database_url: str, user_id: str) -> None:
    store = PostgresConversationStore(database_url)
    with store.database.connect() as connection:
        entity_ids = [
            row["id"]
            for row in connection.execute(
                "SELECT id FROM memory_entities WHERE user_id = %s",
                (user_id,),
            ).fetchall()
        ]
        record_ids = [
            row["id"]
            for row in connection.execute(
                "SELECT id FROM memory_records WHERE user_id = %s",
                (user_id,),
            ).fetchall()
        ]
        for memory_type, ids in (
            ("entity", entity_ids),
            ("record", record_ids),
        ):
            if not ids:
                continue
            if memory_type == "entity":
                connection.execute(
                    "DELETE FROM memory_sources WHERE memory_type = 'entity' AND memory_id = ANY(%s)",
                    (ids,),
                )
                connection.execute(
                    "DELETE FROM memory_entities WHERE id = ANY(%s)",
                    (ids,),
                )
            else:
                connection.execute(
                    "DELETE FROM memory_source_refs WHERE memory_record_id = ANY(%s)",
                    (ids,),
                )
                connection.execute(
                    "DELETE FROM memory_records WHERE id = ANY(%s)",
                    (ids,),
                )
        user = store.find_user_by_username(USERNAME)
        if user is not None:
            store.delete_user(user.id, cascade=True)


class _StaticChatClient:
    def __init__(self) -> None:
        self.call_count = 0

    def complete(
        self,
        messages: list[ChatMessageParam],
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        self.call_count += 1
        return ChatCompletionResult(
            content=f"assistant response {self.call_count}",
            model=model or "test-model",
            usage={"total_tokens": self.call_count},
            provider_message_id=f"provider_{self.call_count}",
        )


if __name__ == "__main__":
    sys.exit(main())
