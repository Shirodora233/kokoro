"""Run local tests for candidate-aware memory retrieval."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from memory.models import (
    MemoryObjectRef,
    MemoryRecord,
    MemoryRecordType,
    MemoryRetrievalRequest,
    MemorySearchHit,
    MemorySearchRequest,
    MemorySearchResult,
    MemorySourceRef,
)
from memory.persistence import (
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentLink,
    PersistentMemoryBundle,
    PersistentObjectRef,
    PersistentProperty,
    PersistentTimeLink,
    PersistentTimeRef,
)
from memory.retrieval import (
    CandidateMemoryMatcher,
    CandidateRelatedGroup,
    CandidateRetrievalResult,
    NormalizedMemoryRanker,
    NormalizedMemoryContextRetriever,
    RelatedMemory,
)
from memory.storage import InMemoryMemoryStore

USER_ID = "usr_retrieval_test"
SESSION_ID = "ses_retrieval_test"


def main() -> int:
    tests: list[Callable[[], None]] = [
        test_entity_exact_match,
        test_entity_match_expands_properties,
        test_event_match_expands_description_and_time,
        test_one_hop_expansion_does_not_chain,
        test_groups_keep_direct_and_expanded_separate,
        test_groups_include_unmatched_candidates,
        test_groups_separate_multiple_candidates,
        test_groups_preserve_shared_record_matches,
        test_scope_filtering,
        test_unrelated_candidate_returns_empty,
        test_normalized_retrieval_renders_event_view_without_raw_links,
        test_normalized_retrieval_query_matches_entity_property,
        test_normalized_search_hydrates_description_hit_without_recent_pool,
        test_normalized_ranker_prioritizes_session_high_quality_hit,
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
    result = _match(store, 
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
                "用户偏好少糖",
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
    result = _match(store, 
        [_candidate("entity", "茉莉花茶", client_id="cand_tea")],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    related = _ids(result)
    assert {"ent_tea", "prop_sugar", "link_tea_sugar"} <= related, related
    assert _has_reason(result, "prop_sugar", "one_hop_neighbor")
    assert _match_kind(result, "ent_tea") == "direct"
    assert _match_kind(result, "prop_sugar") == "expanded"


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
    result = _match(store, 
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


def test_one_hop_expansion_does_not_chain() -> None:
    store = InMemoryMemoryStore(
        [
            _record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea"),
            _record(
                "prop_sugar",
                "property",
                "用户偏好少糖",
                client_id="prop_sugar",
                metadata={"entity_client_id": "ent_tea"},
            ),
            _link(
                "link_tea_sugar",
                from_type="entity",
                from_client_id="ent_tea",
                to_type="property",
                to_client_id="prop_sugar",
                relation_type="has_property",
            ),
            _record(
                "time_sugar",
                "time_ref",
                "昨天",
                client_id="time_sugar",
                metadata={"raw_text": "昨天"},
            ),
            _time_link(
                "tlink_sugar_time",
                target_type="property",
                target_client_id="prop_sugar",
                time_ref_client_id="time_sugar",
                time_role="mentioned_at",
            ),
        ]
    )
    result = _match(store, 
        [_candidate("entity", "茉莉花茶", client_id="cand_tea")],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    related = _ids(result)
    assert {"ent_tea", "prop_sugar", "link_tea_sugar"} <= related, related
    assert "time_sugar" not in related, related
    assert "tlink_sugar_time" not in related, related


def test_groups_keep_direct_and_expanded_separate() -> None:
    store = InMemoryMemoryStore(
        [
            _record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea"),
            _record(
                "prop_sugar",
                "property",
                "用户偏好少糖",
                client_id="prop_sugar",
                metadata={"entity_client_id": "ent_tea"},
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
    result = _match(store, 
        [_candidate("entity", "茉莉花茶", client_id="cand_tea")],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    group = _group(result, "cand_tea")
    assert group is not None
    assert _related_ids(group.direct_matches) == {"ent_tea"}
    assert {"prop_sugar", "link_tea_sugar"} <= _related_ids(group.expanded_context)


def test_groups_include_unmatched_candidates() -> None:
    store = InMemoryMemoryStore(
        [_record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea")]
    )
    result = _match(store, 
        [
            _candidate("entity", "茉莉花茶", client_id="cand_tea"),
            _candidate("entity", "蓝色收音机", client_id="cand_radio"),
        ],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    assert len(result.groups) == 2
    unmatched = _group(result, "cand_radio")
    assert unmatched is not None
    assert unmatched.direct_matches == []
    assert unmatched.expanded_context == []


def test_groups_separate_multiple_candidates() -> None:
    store = InMemoryMemoryStore(
        [
            _record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea"),
            _record("ent_radio", "entity", "蓝色收音机", client_id="ent_radio"),
        ]
    )
    result = _match(store, 
        [
            _candidate("entity", "茉莉花茶", client_id="cand_tea"),
            _candidate("entity", "蓝色收音机", client_id="cand_radio"),
        ],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    tea_group = _group(result, "cand_tea")
    radio_group = _group(result, "cand_radio")
    assert tea_group is not None
    assert radio_group is not None
    assert _related_ids(tea_group.direct_matches) == {"ent_tea"}
    assert _related_ids(radio_group.direct_matches) == {"ent_radio"}


def test_groups_preserve_shared_record_matches() -> None:
    store = InMemoryMemoryStore(
        [
            _record(
                "evt_radio",
                "event",
                "蓝色收音机故事元素",
                client_id="evt_radio",
                metadata={"event_type": "story_beat"},
            ),
            _record("ent_radio", "entity", "蓝色收音机", client_id="ent_radio"),
        ]
    )
    result = _match(store, 
        [
            _candidate(
                "event",
                "蓝色收音机播报天气",
                client_id="cand_event",
                metadata={"event_type": "story_beat"},
            ),
            _candidate("entity", "蓝色收音机", client_id="cand_radio"),
        ],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    event_group = _group(result, "cand_event")
    radio_group = _group(result, "cand_radio")
    assert event_group is not None
    assert radio_group is not None
    assert "evt_radio" in _related_ids(event_group.direct_matches)
    assert "ent_radio" in _related_ids(radio_group.direct_matches)


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
    result = _match(store, 
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
    result = _match(store, 
        [_candidate("entity", "蓝色收音机", client_id="cand_radio")],
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    assert result.records == [], result.to_record()


def test_normalized_retrieval_renders_event_view_without_raw_links() -> None:
    result = NormalizedMemoryContextRetriever(_NormalizedFixtureRepository()).retrieve(
        MemoryRetrievalRequest(
            user_id=USER_ID,
            session_id=SESSION_ID,
            query="林医生",
            limit=4,
        )
    )
    assert result.memory_context
    content = result.memory_context[0].content

    assert "Event: 复诊安排" in content
    assert "Details: 用户计划明天上午十点和林医生复诊，地点在静安门诊。" in content
    assert "Time: scheduled_for 明天上午十点" in content
    assert "Entities: 林医生" in content
    assert "link_visit_doctor" not in content
    assert "tlink_visit_time" not in content
    assert all(record.metadata["normalized"] for record in result.records)


def test_normalized_retrieval_query_matches_entity_property() -> None:
    result = NormalizedMemoryContextRetriever(_NormalizedFixtureRepository()).retrieve(
        MemoryRetrievalRequest(
            user_id=USER_ID,
            session_id=SESSION_ID,
            query="复诊的医生",
            limit=4,
        )
    )
    content = result.memory_context[0].content

    assert "Entity: 林医生 (person)" in content
    assert "Properties: 林医生是用户此次复诊的医生。" in content
    assert "link_visit_doctor" not in content


def test_normalized_search_hydrates_description_hit_without_recent_pool() -> None:
    result = NormalizedMemoryContextRetriever(
        _NoRecentNormalizedFixtureRepository(),
        search=_StaticNormalizedSearch(
            [
                MemorySearchHit(
                    object_ref=MemoryObjectRef("description", "desc_visit"),
                    score=0.9,
                    reason="description_text_match",
                    matched_text="静安门诊",
                )
            ]
        ),
    ).retrieve(
        MemoryRetrievalRequest(
            user_id=USER_ID,
            session_id=SESSION_ID,
            query="静安门诊",
            limit=4,
        )
    )
    assert result.memory_context
    content = result.memory_context[0].content

    assert "Event: 复诊安排" in content
    assert "Details: 用户计划明天上午十点和林医生复诊，地点在静安门诊。" in content
    assert result.metadata["search"]["search"] == "static"


def test_normalized_ranker_prioritizes_session_high_quality_hit() -> None:
    request = MemorySearchRequest(
        user_id=USER_ID,
        session_id=SESSION_ID,
        query="林医生",
        limit=4,
    )
    ranker = NormalizedMemoryRanker(
        now=datetime(2026, 5, 27, tzinfo=timezone.utc)
    )
    ranked = ranker.rank(
        [
            MemorySearchHit(
                object_ref=MemoryObjectRef("entity", "ent_global"),
                score=1.0,
                reason="entity_text_match",
                matched_text="林医生",
                metadata={
                    "match_quality": "phrase",
                    "importance": "medium",
                    "confidence": "medium",
                },
            ),
            MemorySearchHit(
                object_ref=MemoryObjectRef("event", "evt_session"),
                score=0.95,
                reason="event_text_match",
                matched_text="林医生复诊安排",
                metadata={
                    "match_quality": "phrase",
                    "user_id": USER_ID,
                    "session_id": SESSION_ID,
                    "importance": "high",
                    "confidence": "high",
                    "updated_at": "2026-05-27T00:00:00+00:00",
                },
            ),
        ],
        request,
    )

    assert ranked[0].object_ref.object_id == "evt_session"
    ranking = ranked[0].metadata["ranking"]
    assert ranking["components"]["scope"] > 0
    assert ranking["components"]["importance"] > 0
    assert ranking["components"]["confidence"] > 0


def _match(
    store: InMemoryMemoryStore,
    candidates: list[MemoryRecord],
    user_id: str | None = USER_ID,
    session_id: str | None = SESSION_ID,
    limit: int | None = None,
) -> CandidateRetrievalResult:
    return CandidateMemoryMatcher().match(
        candidates,
        _search_result_from_store(store, user_id=user_id, session_id=session_id),
        user_id=user_id,
        session_id=session_id,
        limit=limit,
    )


def _search_result_from_store(
    store: InMemoryMemoryStore,
    user_id: str | None = USER_ID,
    session_id: str | None = SESSION_ID,
) -> MemorySearchResult:
    records = store.list_records(user_id=user_id, session_id=session_id)
    return MemorySearchResult(
        hits=[
            MemorySearchHit(
                object_ref=MemoryObjectRef(record.memory_type, record.id or ""),
                score=1.0,
                reason="test_store_fixture",
                matched_text=record.text,
                record=record,
            )
            for record in records
            if record.id
        ],
        metadata={"search": "test_store_fixture", "hit_count": len(records)},
    )


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


def _related_ids(related_records: list[RelatedMemory]) -> set[str]:
    return {
        related.record.id or ""
        for related in related_records
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


def _match_kind(result: CandidateRetrievalResult, record_id: str) -> str | None:
    for related in result.records:
        if related.record.id == record_id:
            return related.match_kind
    return None


def _group(
    result: CandidateRetrievalResult,
    candidate_id: str,
) -> CandidateRelatedGroup | None:
    for group in result.groups:
        if group.candidate_id == candidate_id:
            return group
    return None


class _NormalizedFixtureRepository:
    def __init__(self) -> None:
        self.bundle = PersistentMemoryBundle(
            events=[
                PersistentEvent(
                    id="evt_visit",
                    title="复诊安排",
                    summary="用户计划和林医生复诊",
                    event_type="appointment",
                    user_id=USER_ID,
                    session_id=SESSION_ID,
                )
            ],
            descriptions=[
                PersistentDescription(
                    id="desc_visit",
                    event_id="evt_visit",
                    content="用户计划明天上午十点和林医生复诊，地点在静安门诊。",
                    user_id=USER_ID,
                    session_id=SESSION_ID,
                )
            ],
            entities=[
                PersistentEntity(
                    id="ent_doctor",
                    name="林医生",
                    entity_type="person",
                    identity_summary="用户此次复诊的医生",
                    aliases=["林医生"],
                    user_id=USER_ID,
                    session_id=SESSION_ID,
                )
            ],
            properties=[
                PersistentProperty(
                    id="prop_doctor_role",
                    entity_id="ent_doctor",
                    content="林医生是用户此次复诊的医生。",
                    property_type="role",
                    user_id=USER_ID,
                    session_id=SESSION_ID,
                )
            ],
            links=[
                PersistentLink(
                    id="link_visit_doctor",
                    from_ref=PersistentObjectRef("event", "evt_visit"),
                    to_ref=PersistentObjectRef("entity", "ent_doctor"),
                    relation_type="involves",
                )
            ],
            time_refs=[
                PersistentTimeRef(
                    id="time_visit",
                    raw_text="明天上午十点",
                    time_kind="relative",
                    timeline_kind="real_world",
                    certainty="inferred",
                    anchor_timezone="Asia/Shanghai",
                    anchor_utc_offset="+08:00",
                    anchor_message_id="msg_visit",
                    resolved_start="2026-05-16T10:00:00+08:00",
                    granularity="minute",
                )
            ],
            time_links=[
                PersistentTimeLink(
                    id="tlink_visit_time",
                    target_ref=PersistentObjectRef("event", "evt_visit"),
                    time_ref_id="time_visit",
                    time_role="scheduled_for",
                )
            ],
        )

    def save_bundle(self, bundle: PersistentMemoryBundle) -> PersistentMemoryBundle:
        return bundle

    def get_event(self, event_id: str) -> PersistentEvent | None:
        return _first(item for item in self.bundle.events if item.id == event_id)

    def get_description(self, description_id: str) -> PersistentDescription | None:
        return _first(
            item for item in self.bundle.descriptions if item.id == description_id
        )

    def get_entity(self, entity_id: str) -> PersistentEntity | None:
        return _first(item for item in self.bundle.entities if item.id == entity_id)

    def get_property(self, property_id: str) -> PersistentProperty | None:
        return _first(item for item in self.bundle.properties if item.id == property_id)

    def get_link(self, link_id: str) -> PersistentLink | None:
        return _first(item for item in self.bundle.links if item.id == link_id)

    def get_time_ref(self, time_ref_id: str) -> PersistentTimeRef | None:
        return _first(item for item in self.bundle.time_refs if item.id == time_ref_id)

    def get_time_link(self, time_link_id: str) -> PersistentTimeLink | None:
        return _first(
            item for item in self.bundle.time_links if item.id == time_link_id
        )

    def list_events(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentEvent]:
        return self.bundle.events[:limit]

    def list_entities(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentEntity]:
        return self.bundle.entities[:limit]

    def list_descriptions(
        self,
        event_ids: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentDescription]:
        ids = set(event_ids or [])
        items = [
            item for item in self.bundle.descriptions
            if not ids or item.event_id in ids
        ]
        return items[:limit]

    def list_properties(
        self,
        entity_ids: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentProperty]:
        ids = set(entity_ids or [])
        items = [
            item for item in self.bundle.properties
            if not ids or item.entity_id in ids
        ]
        return items[:limit]

    def list_links(
        self,
        object_refs: list[PersistentObjectRef] | None = None,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentLink]:
        ref_keys = {
            (ref.object_type, ref.object_id) for ref in object_refs or []
        }
        items = [
            item for item in self.bundle.links
            if not ref_keys
            or (item.from_ref.object_type, item.from_ref.object_id) in ref_keys
            or (item.to_ref.object_type, item.to_ref.object_id) in ref_keys
        ]
        return items[:limit]

    def list_time_links(
        self,
        target_refs: list[PersistentObjectRef] | None = None,
        limit: int | None = None,
    ) -> list[PersistentTimeLink]:
        ref_keys = {
            (ref.object_type, ref.object_id) for ref in target_refs or []
        }
        items = [
            item for item in self.bundle.time_links
            if not ref_keys
            or (item.target_ref.object_type, item.target_ref.object_id) in ref_keys
        ]
        return items[:limit]

    def get_time_refs(self, time_ref_ids: list[str]) -> list[PersistentTimeRef]:
        ids = set(time_ref_ids)
        return [item for item in self.bundle.time_refs if item.id in ids]


class _NoRecentNormalizedFixtureRepository(_NormalizedFixtureRepository):
    def list_events(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentEvent]:
        return []

    def list_entities(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentEntity]:
        return []


class _StaticNormalizedSearch:
    def __init__(self, hits: list[MemorySearchHit]) -> None:
        self.hits = hits

    def search(
        self,
        request: MemorySearchRequest,
    ) -> MemorySearchResult:
        return MemorySearchResult(
            hits=self.hits[: request.limit],
            metadata={
                "search": "static",
                "hit_count": min(len(self.hits), request.limit),
            },
        )


def _first(items):
    return next(iter(items), None)


if __name__ == "__main__":
    sys.exit(main())
