"""Run PostgreSQL checkpoint and branch tests for conversation service."""

from __future__ import annotations

import sys
from collections.abc import Callable

from conversation.config import StorageConfig
from conversation.service import ConversationService
from conversation.storage.postgres import PostgresConversationStore
from llm.config import LLMConfig
from llm.interfaces import ChatCompletionResult, ChatMessageParam
from memory.models import MemoryRecord, MemorySourceRef
from memory.reconciliation import MemoryWriteOperation, MemoryWritePlan
from memory import (
    MemoryRuntime,
    MemoryDebugRecorder,
    MemorySearchRequest,
    NormalizedMemoryContextRetriever,
    PersistentMemoryWritePlanApplier,
    PostgresNormalizedMemorySearch,
)
from memory.persistence.postgres import PostgresPersistentMemoryRepository
from tests.memory.system.fixtures import SequenceMemoryExtractor, candidate
from web_frontend.server import KokoroRequestHandler


USERNAME = "checkpoint_test_user"


def main() -> int:
    config = StorageConfig.from_env(".env")
    tests: list[Callable[[str], None]] = [
        test_atomic_turn_creates_checkpoint_and_idempotent_retry,
        test_checkpoint_failure_rolls_back_visible_state,
        test_branch_session_keeps_original_and_filters_future_memory,
        test_prepare_lazily_restores_latest_active_context,
        test_persisted_memory_debug_trace_survives_restart,
        test_checkpoint_memory_filters_future_records,
        test_checkpoint_memory_replays_update_and_invalidate_revisions,
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
        records = PostgresPersistentMemoryRepository(database_url).list_entities(
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
        assert records[0].created_checkpoint_id == checkpoints[0].id
        assert records[0].created_checkpoint_sequence == 2
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
        assert PostgresPersistentMemoryRepository(database_url).list_entities(
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


def test_prepare_lazily_restores_latest_active_context(database_url: str) -> None:
    service, _chat_client = _service(
        database_url,
        [[candidate("entity", "LazyRestoreOnly", "cand_lazy")]],
    )
    user = service.create_user(USERNAME)
    session = service.start_session(user.id)

    try:
        service.send_message(session.id, "remember LazyRestoreOnly")
        restored_extractor = _CapturingExtractor([[]])
        restarted, _ = _service(
            database_url,
            [],
            extractor=restored_extractor,
        )

        restarted.send_message(session.id, "continue")

        assert restored_extractor.active_contexts
        restored_context = restored_extractor.active_contexts[0]
        assert restored_context is not None
        assert any(
            record.text == "LazyRestoreOnly"
            for record in restored_context.entity_memories
        )
        latest_checkpoint = restarted.list_checkpoints(session.id)[-1]
        active_snapshot = latest_checkpoint.active_memory_snapshot
        assert any(
            record.get("text") == "LazyRestoreOnly"
            for record in active_snapshot.get("entity_memories", [])
        )
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
            item["name"]
            for item in first_memory["normalized_memories"]["entities"]
        ]

        assert "CheckpointBeforeOnly" in texts
        assert "CheckpointAfterOnly" not in texts
        assert first_memory["checkpoint"]["id"] == first_checkpoint.id
    finally:
        _cleanup(database_url, user.id)


def test_checkpoint_memory_replays_update_and_invalidate_revisions(
    database_url: str,
) -> None:
    entity = _fixed_record(
        "ent_user_revision",
        "entity",
        "用户",
        {"entity_type": "person", "candidate_client_id": "cand_user"},
    )
    less_sugar = _fixed_record(
        "prop_sugar_revision",
        "property",
        "用户喜欢少糖",
        {
            "property_type": "preference",
            "entity_client_id": "cand_user",
            "candidate_client_id": "cand_sugar",
        },
    )
    no_sugar = _fixed_record(
        "prop_sugar_revision",
        "property",
        "用户喜欢无糖",
        {
            "property_type": "preference",
            "attached_to_record_id": "ent_user_revision",
            "candidate_client_id": "cand_sugar_update",
        },
    )
    invalidate_candidate = _fixed_record(
        "prop_sugar_revision",
        "property",
        "用户不再记录糖偏好",
        {"candidate_client_id": "cand_sugar_invalidate"},
    )
    reconciler = _SequenceReconciler(
        [
            MemoryWritePlan(
                operations=[
                    MemoryWriteOperation(
                        action="create",
                        candidate_id="cand_user",
                        candidate_type="entity",
                        candidate_text=entity.text,
                        record=entity,
                        reason="seed entity",
                    ),
                    MemoryWriteOperation(
                        action="attach",
                        candidate_id="cand_sugar",
                        candidate_type="property",
                        candidate_text=less_sugar.text,
                        record=less_sugar,
                        target_candidate_id="cand_user",
                        relation_type="has_property",
                        reason="seed property",
                    ),
                ],
                metadata={"reconciler": "sequence"},
            ),
            MemoryWritePlan(
                operations=[
                    MemoryWriteOperation(
                        action="update",
                        candidate_id="cand_sugar_update",
                        candidate_type="property",
                        candidate_text=no_sugar.text,
                        record=no_sugar,
                        existing_record_id="prop_sugar_revision",
                        replacement=no_sugar,
                        reason="replace sugar preference",
                    )
                ],
                metadata={"reconciler": "sequence"},
            ),
            MemoryWritePlan(
                operations=[
                    MemoryWriteOperation(
                        action="invalidate",
                        candidate_id="cand_sugar_invalidate",
                        candidate_type="property",
                        candidate_text=invalidate_candidate.text,
                        record=invalidate_candidate,
                        invalidated_record_ids=["prop_sugar_revision"],
                        reason="remove sugar preference",
                    )
                ],
                metadata={"reconciler": "sequence"},
            ),
        ]
    )
    service, _chat_client = _service(
        database_url,
        [[entity, less_sugar], [no_sugar], [invalidate_candidate]],
        reconciler=reconciler,
    )
    user = service.create_user(USERNAME)
    session = service.start_session(user.id)

    try:
        service.send_message(session.id, "less sugar")
        first_checkpoint = service.list_checkpoints(session.id)[-1]
        service.send_message(session.id, "no sugar")
        second_checkpoint = service.list_checkpoints(session.id)[-1]
        service.send_message(session.id, "forget sugar")
        third_checkpoint = service.list_checkpoints(session.id)[-1]

        first_memory = service.get_checkpoint_memory(first_checkpoint.id)
        second_memory = service.get_checkpoint_memory(second_checkpoint.id)
        third_memory = service.get_checkpoint_memory(third_checkpoint.id)
        first_props = _checkpoint_property_contents(first_memory)
        second_props = _checkpoint_property_contents(second_memory)
        third_props = _checkpoint_property_contents(third_memory)
        diff = service.diff_checkpoints(first_checkpoint.id, second_checkpoint.id)

        assert "用户喜欢少糖" in first_props
        assert "用户喜欢无糖" in second_props
        assert "用户喜欢少糖" not in second_props
        assert "用户喜欢无糖" not in third_props
        assert any(item["id"] == "prop_sugar_revision" for item in diff["updated"])
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
    extractor=None,
    reconciler=None,
) -> tuple[ConversationService, "_StaticChatClient"]:
    store = PostgresConversationStore(database_url)
    store.checkpoints.fail_incomplete_turns()
    persistent = PostgresPersistentMemoryRepository(database_url)
    debug_recorder = MemoryDebugRecorder()
    memory_system = MemoryRuntime(
        extractor=extractor or SequenceMemoryExtractor(memory_batches),
        context_retriever=NormalizedMemoryContextRetriever(
            persistent,
            search=PostgresNormalizedMemorySearch(persistent),
        ),
        reconciler=reconciler,
        write_applier=PersistentMemoryWritePlanApplier(persistent),
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
        connection.execute(
            "DELETE FROM memory_objects WHERE user_id = %s",
            (user_id,),
        )
        user = store.find_user_by_username(USERNAME)
        if user is not None:
            store.delete_user(user.id, cascade=True)


class _SequenceReconciler:
    def __init__(self, plans: list[MemoryWritePlan]) -> None:
        self._plans = list(plans)
        self._index = 0

    def reconcile(self, request) -> MemoryWritePlan:
        if self._index >= len(self._plans):
            return MemoryWritePlan(metadata={"reconciler": "sequence"})
        plan = self._plans[self._index]
        self._index += 1
        return plan


def _fixed_record(
    record_id: str,
    memory_type: str,
    text: str,
    metadata: dict[str, object] | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        memory_type=memory_type,
        text=text,
        source_refs=[
            MemorySourceRef(
                source_type="message",
                source_id="msg_revision_test",
            )
        ],
        metadata=dict(metadata or {}),
    )


def _checkpoint_property_contents(snapshot: dict) -> list[str]:
    normalized = snapshot.get("normalized_memories")
    if not isinstance(normalized, dict):
        return []
    properties = normalized.get("properties")
    if not isinstance(properties, list):
        return []
    result: list[str] = []
    for item in properties:
        if isinstance(item, dict) and isinstance(item.get("content"), str):
            result.append(item["content"])
    return result


class _CapturingExtractor:
    def __init__(self, batches) -> None:
        self.extractor = SequenceMemoryExtractor(batches)
        self.active_contexts = []

    def extract(self, turn):
        self.active_contexts.append(turn.active_memory_context)
        return self.extractor.extract(turn)


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
