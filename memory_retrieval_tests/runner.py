"""Run local tests for candidate-aware memory retrieval."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from memory.models import MemoryRecord, MemoryRecordType, MemorySourceRef
from memory.retrieval import CandidateMemoryRetriever, CandidateRetrievalResult
from memory.storage import InMemoryMemoryStore

USER_ID = "usr_retrieval_test"
SESSION_ID = "ses_retrieval_test"


def main() -> int:
    tests: list[Callable[[], None]] = [
        test_entity_exact_match,
        test_entity_match_expands_properties,
        test_event_match_expands_description_and_time,
        test_scope_filtering,
        test_unrelated_candidate_returns_empty,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"passed={len(tests)}/{len(tests)}")
    return 0


def test_entity_exact_match() -> None:
    store = InMemoryMemoryStore(
        [
            _record(
                "ent_tea",
                "entity",
                "茉莉花茶",
                client_id="ent_tea",
                metadata={"entity_type": "object", "aliases": ["jasmine tea"]},
            )
        ]
    )
    result = CandidateMemoryRetriever(store).retrieve_related(
        [_candidate("entity", "茉莉花茶", client_id="cand_tea")],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    related = _ids(result)
    assert "ent_tea" in related, related
    assert _has_reason(result, "ent_tea", "text_exact")


def test_entity_match_expands_properties() -> None:
    store = InMemoryMemoryStore(
        [
            _record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea"),
            _record(
                "prop_sugar",
                "property",
                "用户偏好茉莉花茶少糖",
                client_id="prop_sugar",
                metadata={
                    "entity_client_id": "ent_tea",
                    "property_type": "preference",
                },
            ),
            _link(
                "link_tea_sugar",
                from_type="entity",
                from_client_id="ent_tea",
                to_type="property",
                to_client_id="prop_sugar",
                relation_type="has_property",
            ),
        ]
    )
    result = CandidateMemoryRetriever(store).retrieve_related(
        [_candidate("entity", "茉莉花茶", client_id="cand_tea")],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    related = _ids(result)
    assert {"ent_tea", "prop_sugar", "link_tea_sugar"} <= related, related
    assert _has_reason(result, "prop_sugar", "one_hop_neighbor")


def test_event_match_expands_description_and_time() -> None:
    store = InMemoryMemoryStore(
        [
            _record(
                "evt_swim",
                "event",
                "游泳训练安排",
                client_id="evt_swim",
                metadata={"event_type": "plan", "summary": "每周三晚上游泳"},
                source_id="msg_swim",
            ),
            _record(
                "desc_swim",
                "description",
                "用户每周三晚上去虹口游泳馆练自由泳",
                client_id="desc_swim",
                source_id="msg_swim",
            ),
            _link(
                "link_swim_desc",
                from_type="event",
                from_client_id="evt_swim",
                to_type="description",
                to_client_id="desc_swim",
                relation_type="has_description",
                source_id="msg_swim",
            ),
            _record(
                "time_swim",
                "time_ref",
                "每周三晚上",
                client_id="time_swim",
                metadata={
                    "raw_text": "每周三晚上",
                    "time_kind": "recurring",
                    "timeline_kind": "real_world",
                },
                source_id="msg_swim",
            ),
            _time_link(
                "tlink_swim",
                target_type="event",
                target_client_id="evt_swim",
                time_ref_client_id="time_swim",
                time_role="recurs_at",
                source_id="msg_swim",
            ),
        ]
    )
    result = CandidateMemoryRetriever(store).retrieve_related(
        [
            _candidate(
                "event",
                "游泳训练安排",
                client_id="cand_swim",
                metadata={"event_type": "plan", "summary": "固定游泳计划"},
            )
        ],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    related = _ids(result)
    expected = {"evt_swim", "desc_swim", "link_swim_desc", "time_swim", "tlink_swim"}
    assert expected <= related, related


def test_scope_filtering() -> None:
    store = InMemoryMemoryStore(
        [
            _record("ent_user_tea", "entity", "茉莉花茶", client_id="ent_user_tea"),
            _record(
                "ent_other_tea",
                "entity",
                "茉莉花茶",
                client_id="ent_other_tea",
                metadata={"user_id": "usr_other", "session_id": SESSION_ID},
            ),
        ]
    )
    result = CandidateMemoryRetriever(store).retrieve_related(
        [_candidate("entity", "茉莉花茶", client_id="cand_tea")],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    related = _ids(result)
    assert "ent_user_tea" in related, related
    assert "ent_other_tea" not in related, related


def test_unrelated_candidate_returns_empty() -> None:
    store = InMemoryMemoryStore(
        [_record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea")]
    )
    result = CandidateMemoryRetriever(store).retrieve_related(
        [_candidate("entity", "蓝色收音机", client_id="cand_radio")],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    assert result.records == [], result.to_record()


def _record(
    record_id: str,
    memory_type: MemoryRecordType,
    text: str,
    client_id: str,
    metadata: dict[str, Any] | None = None,
    source_id: str = "msg_old",
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
        source_refs=[MemorySourceRef(source_type="message", source_id=source_id)],
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


def _link(
    record_id: str,
    from_type: str,
    from_client_id: str,
    to_type: str,
    to_client_id: str,
    relation_type: str,
    source_id: str = "msg_old",
) -> MemoryRecord:
    return _record(
        record_id,
        "link",
        f"{from_type} {from_client_id} {relation_type} {to_type} {to_client_id}",
        client_id=record_id,
        metadata={
            "from_type": from_type,
            "from_client_id": from_client_id,
            "to_type": to_type,
            "to_client_id": to_client_id,
            "relation_type": relation_type,
        },
        source_id=source_id,
    )


def _time_link(
    record_id: str,
    target_type: str,
    target_client_id: str,
    time_ref_client_id: str,
    time_role: str,
    source_id: str = "msg_old",
) -> MemoryRecord:
    return _record(
        record_id,
        "time_link",
        f"{target_type} {target_client_id} {time_role} {time_ref_client_id}",
        client_id=record_id,
        metadata={
            "target_type": target_type,
            "target_client_id": target_client_id,
            "time_ref_client_id": time_ref_client_id,
            "time_role": time_role,
        },
        source_id=source_id,
    )


def _ids(result: CandidateRetrievalResult) -> set[str]:
    return {
        related.record.id or ""
        for related in result.records
    }


def _has_reason(
    result: CandidateRetrievalResult,
    record_id: str,
    expected: str,
) -> bool:
    for related in result.records:
        if related.record.id != record_id:
            continue
        return any(reason.startswith(expected) for reason in related.reasons)
    return False


if __name__ == "__main__":
    sys.exit(main())
