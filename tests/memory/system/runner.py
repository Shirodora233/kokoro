"""Run local tests for the in-memory memory system composition."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from tempfile import TemporaryDirectory

from conversation.service import ConversationService
from conversation.storage import JsonConversationStore
from llm.config import LLMConfig
from llm.interfaces import ChatCompletionResult, ChatMessageParam
from memory.models import (
    MemoryContextBlock,
    MemoryInputMessage,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemorySearchResult,
    MemoryTurnCommitInput,
    MemoryTurnInput,
    MemoryTurnPrepareResult,
    MemoryTurnResult,
    MemoryTurnSnapshot,
)
from memory.system import InMemoryMemorySystem
from memory.writing import MemoryWriteResult

from .fixtures import (
    SESSION_ID,
    TIMEZONE,
    USER_ID,
    SequenceMemoryExtractor,
    candidate,
    make_turn,
)


def main() -> int:
    tests: list[Callable[[], None]] = [
        test_prepare_commit_writes_created_candidates,
        test_prepare_commit_reuses_entity_and_attaches_property,
        test_empty_extraction_keeps_system_operational,
        test_retrieve_context_uses_active_and_stored_records,
        test_prepare_turn_searches_without_writing,
        test_commit_turn_reuses_prepare_snapshot,
        test_commit_turn_invokes_persistence_sync,
        test_conversation_send_message_prepares_before_llm_and_commits_after,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"passed={len(tests)}/{len(tests)}")
    return 0


def test_prepare_commit_writes_created_candidates() -> None:
    system = InMemoryMemorySystem(
        extractor=SequenceMemoryExtractor(
            [[candidate("entity", "茉莉花茶", "cand_tea")]]
        )
    )

    result = _prepare_and_commit(system, make_turn("msg_1", "我喜欢茉莉花茶。"))
    records = system.store.list_records(user_id=USER_ID, session_id=SESSION_ID)

    assert len(records) == 1
    assert records[0].memory_type == "entity"
    assert records[0].text == "茉莉花茶"
    assert records[0].metadata["user_id"] == USER_ID
    assert records[0].metadata["session_id"] == SESSION_ID
    assert records[0].metadata["timezone"] == TIMEZONE
    assert result.created_memories == records
    assert result.metadata["write_result"]["metadata"]["created_count"] == 1


def test_prepare_commit_reuses_entity_and_attaches_property() -> None:
    system = InMemoryMemorySystem(
        extractor=SequenceMemoryExtractor(
            [
                [candidate("entity", "茉莉花茶", "cand_tea")],
                [
                    candidate("entity", "茉莉花茶", "cand_tea_again"),
                    candidate(
                        "property",
                        "用户偏好少糖",
                        "cand_prop",
                        metadata={
                            "entity_client_id": "cand_tea_again",
                            "property_type": "preference",
                        },
                    ),
                ],
            ]
        )
    )

    first_result = _prepare_and_commit(system, make_turn("msg_1", "我喜欢茉莉花茶。"))
    first_entity_id = first_result.created_memories[0].id
    second_result = _prepare_and_commit(
        system,
        make_turn("msg_2", "以后茉莉花茶少糖就好。"),
    )

    records = system.store.list_records(user_id=USER_ID, session_id=SESSION_ID)
    entities = [record for record in records if record.memory_type == "entity"]
    properties = [record for record in records if record.memory_type == "property"]
    plan_actions = {
        operation["candidate_id"]: operation["action"]
        for operation in second_result.metadata["write_plan"]["operations"]
    }
    record_ids = second_result.metadata["write_result"]["candidate_record_ids"]
    active_context = system.get_active_context(USER_ID, SESSION_ID)

    assert len(entities) == 1
    assert len(properties) == 1
    assert entities[0].id == first_entity_id
    assert properties[0].metadata["attached_to_record_id"] == first_entity_id
    assert plan_actions["cand_tea_again"] == "reuse"
    assert plan_actions["cand_prop"] == "attach"
    assert record_ids["cand_tea_again"] == first_entity_id
    assert record_ids["cand_prop"] == properties[0].id
    assert any(record.id == first_entity_id for record in active_context.entity_memories)
    assert any(record.id == properties[0].id for record in active_context.property_memories)


def test_empty_extraction_keeps_system_operational() -> None:
    system = InMemoryMemorySystem(extractor=SequenceMemoryExtractor([[]]))

    result = _prepare_and_commit(system, make_turn("msg_empty", "只是闲聊一下。"))

    assert system.store.list_records(user_id=USER_ID, session_id=SESSION_ID) == []
    assert result.created_memories == []
    assert result.metadata["candidate_matching"]["metadata"]["candidate_count"] == 0
    assert result.metadata["write_result"]["metadata"]["operation_count"] == 0


def test_retrieve_context_uses_active_and_stored_records() -> None:
    system = InMemoryMemorySystem(
        extractor=SequenceMemoryExtractor(
            [[candidate("entity", "静安门诊", "cand_clinic")]]
        )
    )
    _prepare_and_commit(system, make_turn("msg_1", "复诊地点在静安门诊。"))

    result = system.retrieve_context(
        MemoryRetrievalRequest(
            user_id=USER_ID,
            session_id=SESSION_ID,
            query="静安",
            timezone=TIMEZONE,
            limit=8,
        )
    )

    assert len(result.records) == 1
    assert result.records[0].text == "静安门诊"
    assert result.memory_context
    assert "静安门诊" in result.memory_context[0].content


def test_prepare_turn_searches_without_writing() -> None:
    system = InMemoryMemorySystem(
        extractor=SequenceMemoryExtractor(
            [[candidate("entity", "林医生", "cand_doctor")]]
        )
    )

    prepare = system.prepare_turn(make_turn("msg_prepare", "我明天要和林医生复诊。"))

    assert prepare.snapshot.candidates[0].text == "林医生"
    assert prepare.snapshot.search_result.metadata["search"] == "simple_store_context"
    assert system.store.list_records(user_id=USER_ID, session_id=SESSION_ID) == []


def test_commit_turn_reuses_prepare_snapshot() -> None:
    system = InMemoryMemorySystem(
        extractor=SequenceMemoryExtractor(
            [[candidate("entity", "林医生", "cand_doctor")]]
        )
    )
    prepare = system.prepare_turn(make_turn("msg_commit", "我明天要和林医生复诊。"))
    commit = system.commit_turn(
        MemoryTurnCommitInput(
            snapshot=prepare.snapshot,
            assistant_message=_assistant_message("msg_assistant"),
        )
    )

    assert len(commit.created_memories) == 1
    assert commit.metadata["snapshot"]["search_result"]["metadata"]["search"] == (
        "simple_store_context"
    )
    assert commit.metadata["candidate_matching"]["metadata"]["search"]["search"] == (
        "simple_store_context"
    )


def test_commit_turn_invokes_persistence_sync() -> None:
    persistence_sync = _CapturingPersistenceSync()
    system = InMemoryMemorySystem(
        extractor=SequenceMemoryExtractor(
            [[candidate("entity", "林医生", "cand_doctor")]]
        ),
        persistence_sync=persistence_sync,  # type: ignore[arg-type]
    )

    result = _prepare_and_commit(system, make_turn("msg_sync", "我明天要和林医生复诊。"))

    assert len(persistence_sync.calls) == 1
    assert len(persistence_sync.calls[0].created_records) == 1
    assert persistence_sync.calls[0].created_records[0].text == "林医生"
    assert result.metadata["persistent_write"]["captured_created_count"] == 1


def test_conversation_send_message_prepares_before_llm_and_commits_after() -> None:
    events: list[str] = []
    memory_system = _RecordingMemorySystem(events)
    chat_client = _RecordingChatClient(events)

    with TemporaryDirectory() as data_dir:
        store = JsonConversationStore(data_dir)
        service = ConversationService(
            store=store,
            chat_client=chat_client,  # type: ignore[arg-type]
            config=LLMConfig(
                api_key="test-key",
                base_url=None,
                model="test-model",
            ),
            memory_system=memory_system,  # type: ignore[arg-type]
            timezone=TIMEZONE,
        )
        user = service.create_user("alice")
        session = service.start_session(user.id)

        user_message, assistant_message = service.send_message(
            session.id,
            "我明天要和林医生复诊。",
        )

    assert events == ["prepare", "llm", "commit"]
    assert memory_system.prepare_turn_input is not None
    assert memory_system.prepare_turn_input.new_message.id == user_message.id
    assert memory_system.prepare_turn_input.conversation_context[-1].id == user_message.id
    assert chat_client.messages is not None
    assert any(
        message["role"] == "system"
        and "Memory context:\nprepared memory context" in message["content"]
        for message in chat_client.messages
    )
    assert memory_system.commit_input is not None
    assert memory_system.commit_input.snapshot is memory_system.snapshot
    assert memory_system.commit_input.assistant_message is not None
    assert memory_system.commit_input.assistant_message.id == assistant_message.id
    assert memory_system.commit_input.assistant_message.role == "assistant"


@dataclass
class _CapturedSyncResult:
    created_count: int

    def to_record(self) -> dict[str, int]:
        return {"captured_created_count": self.created_count}


class _CapturingPersistenceSync:
    def __init__(self) -> None:
        self.calls: list[MemoryWriteResult] = []

    def sync(self, write_result: MemoryWriteResult) -> _CapturedSyncResult:
        self.calls.append(write_result)
        return _CapturedSyncResult(len(write_result.created_records))


class _RecordingMemorySystem:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.prepare_turn_input: MemoryTurnInput | None = None
        self.commit_input: MemoryTurnCommitInput | None = None
        self.snapshot: MemoryTurnSnapshot | None = None

    def prepare_turn(self, turn: MemoryTurnInput) -> MemoryTurnPrepareResult:
        self.events.append("prepare")
        self.prepare_turn_input = turn
        block = MemoryContextBlock(
            content="prepared memory context",
            priority=10,
        )
        self.snapshot = MemoryTurnSnapshot(
            turn=turn,
            search_result=MemorySearchResult(metadata={"search": "recording"}),
            memory_context=[block],
        )
        return MemoryTurnPrepareResult(
            snapshot=self.snapshot,
            memory_context=[block],
        )

    def commit_turn(self, commit: MemoryTurnCommitInput) -> MemoryTurnResult:
        self.events.append("commit")
        self.commit_input = commit
        return MemoryTurnResult()

    def retrieve_context(
        self,
        request: MemoryRetrievalRequest,
    ) -> MemoryRetrievalResult:
        return MemoryRetrievalResult()


class _RecordingChatClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.messages: list[ChatMessageParam] | None = None

    def complete(
        self,
        messages: list[ChatMessageParam],
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        self.events.append("llm")
        self.messages = messages
        return ChatCompletionResult(
            content="好的。",
            model=model or "test-model",
            usage={"total_tokens": 1},
            provider_message_id="provider_test",
        )


def _prepare_and_commit(
    system: InMemoryMemorySystem,
    turn,
):
    prepare = system.prepare_turn(turn)
    return system.commit_turn(
        MemoryTurnCommitInput(
            snapshot=prepare.snapshot,
            assistant_message=_assistant_message("msg_assistant"),
        )
    )


def _assistant_message(message_id: str) -> MemoryInputMessage:
    return MemoryInputMessage(
        id=message_id,
        role="assistant",
        content="好的。",
        session_id=SESSION_ID,
        created_at="2026-05-13T10:00:01+08:00",
    )


if __name__ == "__main__":
    sys.exit(main())
