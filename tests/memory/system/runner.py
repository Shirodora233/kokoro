"""Run local tests for the in-memory memory system composition."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from memory.models import MemoryRetrievalRequest
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
        test_process_turn_writes_created_candidates,
        test_process_turn_reuses_entity_and_attaches_property,
        test_empty_extraction_keeps_system_operational,
        test_retrieve_context_uses_active_and_stored_records,
        test_process_turn_invokes_persistence_sync,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"passed={len(tests)}/{len(tests)}")
    return 0


def test_process_turn_writes_created_candidates() -> None:
    system = InMemoryMemorySystem(
        extractor=SequenceMemoryExtractor(
            [[candidate("entity", "茉莉花茶", "cand_tea")]]
        )
    )

    result = system.process_turn(make_turn("msg_1", "我喜欢茉莉花茶。"))
    records = system.store.list_records(user_id=USER_ID, session_id=SESSION_ID)

    assert len(records) == 1
    assert records[0].memory_type == "entity"
    assert records[0].text == "茉莉花茶"
    assert records[0].metadata["user_id"] == USER_ID
    assert records[0].metadata["session_id"] == SESSION_ID
    assert records[0].metadata["timezone"] == TIMEZONE
    assert result.created_memories == records
    assert result.metadata["write_result"]["metadata"]["created_count"] == 1


def test_process_turn_reuses_entity_and_attaches_property() -> None:
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

    first_result = system.process_turn(make_turn("msg_1", "我喜欢茉莉花茶。"))
    first_entity_id = first_result.created_memories[0].id
    second_result = system.process_turn(
        make_turn("msg_2", "以后茉莉花茶少糖就好。")
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

    result = system.process_turn(make_turn("msg_empty", "只是闲聊一下。"))

    assert system.store.list_records(user_id=USER_ID, session_id=SESSION_ID) == []
    assert result.created_memories == []
    assert result.metadata["candidate_retrieval"]["metadata"]["candidate_count"] == 0
    assert result.metadata["write_result"]["metadata"]["operation_count"] == 0


def test_retrieve_context_uses_active_and_stored_records() -> None:
    system = InMemoryMemorySystem(
        extractor=SequenceMemoryExtractor(
            [[candidate("entity", "静安门诊", "cand_clinic")]]
        )
    )
    system.process_turn(make_turn("msg_1", "复诊地点在静安门诊。"))

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


def test_process_turn_invokes_persistence_sync() -> None:
    persistence_sync = _CapturingPersistenceSync()
    system = InMemoryMemorySystem(
        extractor=SequenceMemoryExtractor(
            [[candidate("entity", "林医生", "cand_doctor")]]
        ),
        persistence_sync=persistence_sync,  # type: ignore[arg-type]
    )

    result = system.process_turn(make_turn("msg_sync", "我明天要和林医生复诊。"))

    assert len(persistence_sync.calls) == 1
    assert len(persistence_sync.calls[0].created_records) == 1
    assert persistence_sync.calls[0].created_records[0].text == "林医生"
    assert result.metadata["persistent_write"]["captured_created_count"] == 1


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


if __name__ == "__main__":
    sys.exit(main())
