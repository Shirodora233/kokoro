"""Run local tests for in-memory write plan application."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from memory.models import MemoryRecord, MemoryRecordType, MemorySourceRef
from memory.reconciliation import MemoryWriteOperation, MemoryWritePlan
from memory.storage import InMemoryMemoryStore
from memory.writing import InMemoryMemoryWritePlanApplier, MemoryWriteRequest

USER_ID = "usr_write_test"
SESSION_ID = "ses_write_test"


def main() -> int:
    tests: list[Callable[[], None]] = [
        test_reuse_maps_existing_record,
        test_create_saves_record_with_scope,
        test_attach_property_to_reused_entity,
        test_attach_property_to_created_entity,
        test_attach_link_resolves_candidate_endpoints,
        test_ignore_does_not_write,
        test_missing_attach_target_fails,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"passed={len(tests)}/{len(tests)}")
    return 0


def test_reuse_maps_existing_record() -> None:
    store = InMemoryMemoryStore(
        [_record("ent_tea", "entity", "茉莉花茶", client_id="old_ent")]
    )
    result = _apply(
        store,
        [
            _operation(
                "reuse",
                _candidate("entity", "茉莉花茶", client_id="cand_tea"),
                existing_record_id="ent_tea",
            )
        ],
    )
    assert result.candidate_record_ids["cand_tea"] == "ent_tea"
    assert [record.id for record in result.reused_records] == ["ent_tea"]
    assert len(store.list_records()) == 1


def test_create_saves_record_with_scope() -> None:
    store = InMemoryMemoryStore()
    result = _apply(
        store,
        [_operation("create", _candidate("entity", "蓝色收音机", "cand_radio"))],
    )
    created = result.created_records[0]
    assert created.id is not None
    assert result.candidate_record_ids["cand_radio"] == created.id
    assert created.metadata["user_id"] == USER_ID
    assert created.metadata["session_id"] == SESSION_ID
    assert created.metadata["write_action"] == "create"


def test_attach_property_to_reused_entity() -> None:
    store = InMemoryMemoryStore(
        [_record("ent_tea", "entity", "茉莉花茶", client_id="old_ent")]
    )
    property_candidate = _candidate(
        "property",
        "用户偏好少糖",
        "cand_prop",
        metadata={"entity_client_id": "cand_tea"},
    )
    result = _apply(
        store,
        [
            _operation(
                "reuse",
                _candidate("entity", "茉莉花茶", "cand_tea"),
                existing_record_id="ent_tea",
            ),
            _operation(
                "attach",
                property_candidate,
                target_record_id="ent_tea",
                target_candidate_id="cand_tea",
                relation_type="has_property",
            ),
        ],
    )
    attached = result.attached_records[0]
    assert attached.memory_type == "property"
    assert attached.metadata["attached_to_record_id"] == "ent_tea"
    assert attached.metadata["attached_to_candidate_id"] == "cand_tea"
    assert attached.metadata["attached_relation_type"] == "has_property"
    assert result.candidate_record_ids["cand_prop"] == attached.id


def test_attach_property_to_created_entity() -> None:
    store = InMemoryMemoryStore()
    result = _apply(
        store,
        [
            _operation("create", _candidate("entity", "蓝色收音机", "cand_radio")),
            _operation(
                "attach",
                _candidate(
                    "property",
                    "收音机是蓝色的",
                    "cand_prop",
                    metadata={"entity_client_id": "cand_radio"},
                ),
                target_candidate_id="cand_radio",
                relation_type="has_property",
            ),
        ],
    )
    parent_id = result.candidate_record_ids["cand_radio"]
    attached = result.attached_records[0]
    assert attached.metadata["attached_to_record_id"] == parent_id
    assert attached.metadata["attached_to_candidate_id"] == "cand_radio"


def test_attach_link_resolves_candidate_endpoints() -> None:
    store = InMemoryMemoryStore()
    link_candidate = _candidate(
        "link",
        "entity cand_radio has_property property cand_prop",
        "cand_link",
        metadata={
            "from_type": "entity",
            "from_client_id": "cand_radio",
            "to_type": "property",
            "to_client_id": "cand_prop",
            "relation_type": "has_property",
        },
    )
    result = _apply(
        store,
        [
            _operation("create", _candidate("entity", "蓝色收音机", "cand_radio")),
            _operation(
                "attach",
                _candidate("property", "收音机是蓝色的", "cand_prop"),
                target_candidate_id="cand_radio",
                relation_type="has_property",
            ),
            _operation("attach", link_candidate, relation_type="has_property"),
        ],
    )
    link = [
        record for record in result.attached_records
        if record.memory_type == "link"
    ][0]
    assert link.metadata["from_record_id"] == result.candidate_record_ids["cand_radio"]
    assert link.metadata["to_record_id"] == result.candidate_record_ids["cand_prop"]


def test_ignore_does_not_write() -> None:
    store = InMemoryMemoryStore()
    result = _apply(
        store,
        [_operation("ignore", _candidate("entity", "临时", "cand_ignore"))],
    )
    assert len(store.list_records()) == 0
    assert len(result.ignored_operations) == 1


def test_missing_attach_target_fails() -> None:
    store = InMemoryMemoryStore()
    result = _apply(
        store,
        [
            _operation(
                "attach",
                _candidate("property", "用户偏好少糖", "cand_prop"),
                target_candidate_id="missing_entity",
                relation_type="has_property",
            )
        ],
    )
    assert result.attached_records == []
    assert len(result.failed_operations) == 1
    assert "target" in result.failed_operations[0].reason


def _apply(
    store: InMemoryMemoryStore,
    operations: list[MemoryWriteOperation],
):
    return InMemoryMemoryWritePlanApplier(store).apply(
        MemoryWriteRequest(
            plan=MemoryWritePlan(operations=operations),
            user_id=USER_ID,
            session_id=SESSION_ID,
        )
    )


def _operation(
    action: str,
    record: MemoryRecord,
    existing_record_id: str | None = None,
    target_record_id: str | None = None,
    target_candidate_id: str | None = None,
    relation_type: str | None = None,
) -> MemoryWriteOperation:
    return MemoryWriteOperation(
        action=action,  # type: ignore[arg-type]
        candidate_id=_candidate_id(record),
        candidate_type=record.memory_type,
        candidate_text=record.text,
        record=record,
        existing_record_id=existing_record_id,
        target_record_id=target_record_id,
        target_candidate_id=target_candidate_id,
        relation_type=relation_type,
        reason=f"test {action}",
    )


def _record(
    record_id: str,
    memory_type: MemoryRecordType,
    text: str,
    client_id: str,
    metadata: dict[str, Any] | None = None,
) -> MemoryRecord:
    merged_metadata = {
        "candidate_client_id": client_id,
        "user_id": USER_ID,
        "session_id": SESSION_ID,
    }
    merged_metadata.update(metadata or {})
    return MemoryRecord(
        id=record_id,
        memory_type=memory_type,
        text=text,
        source_refs=[MemorySourceRef(source_type="message", source_id="msg_old")],
        metadata=merged_metadata,
    )


def _candidate(
    memory_type: MemoryRecordType,
    text: str,
    client_id: str,
    metadata: dict[str, Any] | None = None,
) -> MemoryRecord:
    merged_metadata = {"candidate_client_id": client_id}
    merged_metadata.update(metadata or {})
    return MemoryRecord(
        id=None,
        memory_type=memory_type,
        text=text,
        metadata=merged_metadata,
    )


def _candidate_id(record: MemoryRecord) -> str | None:
    value = record.metadata.get("candidate_client_id")
    return value if isinstance(value, str) else None


if __name__ == "__main__":
    sys.exit(main())
