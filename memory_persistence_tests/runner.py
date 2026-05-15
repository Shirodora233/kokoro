"""Run PostgreSQL round-trip tests for normalized memory persistence."""

from __future__ import annotations

import sys

from conversation.config import StorageConfig
from memory.persistence.models import (
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentLink,
    PersistentMemoryBundle,
    PersistentObjectRef,
    PersistentProperty,
    PersistentSourceRef,
    PersistentTimeLink,
    PersistentTimeRef,
)
from memory.persistence.postgres import PostgresPersistentMemoryRepository

USER_ID = "usr_persistence_test"
SESSION_ID = "ses_persistence_test"
MESSAGE_ID = "msg_persistence_test"

EVENT_ID = "evt_persistence_test"
DESCRIPTION_ID = "desc_persistence_test"
ENTITY_ID = "ent_persistence_test"
PROPERTY_ID = "prop_persistence_test"
LINK_ID = "link_persistence_test"
TIME_REF_ID = "time_persistence_test"
TIME_LINK_ID = "tlink_persistence_test"

ALL_IDS = [
    EVENT_ID,
    DESCRIPTION_ID,
    ENTITY_ID,
    PROPERTY_ID,
    LINK_ID,
    TIME_REF_ID,
    TIME_LINK_ID,
]


def main() -> int:
    config = StorageConfig.from_env(".env")
    repository = PostgresPersistentMemoryRepository(config.database_url)
    _cleanup(repository)
    try:
        test_save_and_load_bundle(repository)
    finally:
        _cleanup(repository)
    print("PASS test_save_and_load_bundle")
    print("passed=1/1")
    return 0


def test_save_and_load_bundle(
    repository: PostgresPersistentMemoryRepository,
) -> None:
    source = PersistentSourceRef(
        source_type="message",
        source_id=MESSAGE_ID,
        quote="明天上午十点我要和林医生复诊，地点在静安门诊。",
    )
    bundle = PersistentMemoryBundle(
        events=[
            PersistentEvent(
                id=EVENT_ID,
                title="复诊安排",
                summary="用户计划和林医生复诊",
                event_type="appointment",
                user_id=USER_ID,
                session_id=SESSION_ID,
                source_refs=[source],
                confidence="high",
                importance="medium",
            )
        ],
        descriptions=[
            PersistentDescription(
                id=DESCRIPTION_ID,
                event_id=EVENT_ID,
                content="用户计划明天上午十点和林医生复诊，地点在静安门诊。",
                description_type="appointment_detail",
                user_id=USER_ID,
                session_id=SESSION_ID,
                source_refs=[source],
                confidence="high",
            )
        ],
        entities=[
            PersistentEntity(
                id=ENTITY_ID,
                name="林医生",
                entity_type="person",
                identity_summary="用户复诊安排中的医生",
                aliases=["林医生"],
                user_id=USER_ID,
                session_id=SESSION_ID,
                scope="session",
                source_refs=[source],
                confidence="high",
            )
        ],
        properties=[
            PersistentProperty(
                id=PROPERTY_ID,
                entity_id=ENTITY_ID,
                content="林医生是用户此次复诊的医生。",
                property_type="role",
                user_id=USER_ID,
                session_id=SESSION_ID,
                source_refs=[source],
                confidence="high",
            )
        ],
        links=[
            PersistentLink(
                id=LINK_ID,
                from_ref=PersistentObjectRef("event", EVENT_ID),
                to_ref=PersistentObjectRef("entity", ENTITY_ID),
                relation_type="involves",
                reason="复诊安排涉及林医生",
                source_refs=[source],
                confidence="high",
                metadata={"user_id": USER_ID},
            )
        ],
        time_refs=[
            PersistentTimeRef(
                id=TIME_REF_ID,
                raw_text="明天上午十点",
                time_kind="relative",
                timeline_kind="real_world",
                certainty="inferred",
                anchor_timezone="Asia/Shanghai",
                anchor_utc_offset="+08:00",
                anchor_message_id=MESSAGE_ID,
                resolved_start="2026-05-16T10:00:00+08:00",
                granularity="minute",
                source_refs=[source],
            )
        ],
        time_links=[
            PersistentTimeLink(
                id=TIME_LINK_ID,
                target_ref=PersistentObjectRef("event", EVENT_ID),
                time_ref_id=TIME_REF_ID,
                time_role="scheduled_for",
                source_refs=[source],
                confidence="high",
            )
        ],
    )

    stored = repository.save_bundle(bundle)
    assert stored.events[0].id == EVENT_ID
    assert stored.descriptions[0].event_id == EVENT_ID
    assert stored.properties[0].entity_id == ENTITY_ID
    assert stored.time_links[0].time_ref_id == TIME_REF_ID

    event = repository.get_event(EVENT_ID)
    description = repository.get_description(DESCRIPTION_ID)
    entity = repository.get_entity(ENTITY_ID)
    memory_property = repository.get_property(PROPERTY_ID)
    link = repository.get_link(LINK_ID)
    time_ref = repository.get_time_ref(TIME_REF_ID)
    time_link = repository.get_time_link(TIME_LINK_ID)
    listed_events = repository.list_events(USER_ID, SESSION_ID)
    listed_entities = repository.list_entities(USER_ID, SESSION_ID)

    assert event is not None and event.title == "复诊安排"
    assert event.source_refs[0].source_id == MESSAGE_ID
    assert description is not None and description.event_id == EVENT_ID
    assert entity is not None and entity.aliases == ["林医生"]
    assert memory_property is not None and memory_property.entity_id == ENTITY_ID
    assert link is not None and link.from_ref.object_id == EVENT_ID
    assert time_ref is not None and time_ref.anchor_timezone == "Asia/Shanghai"
    assert time_link is not None and time_link.target_ref.object_id == EVENT_ID
    assert any(item.id == EVENT_ID for item in listed_events)
    assert any(item.id == ENTITY_ID for item in listed_entities)


def _cleanup(repository: PostgresPersistentMemoryRepository) -> None:
    with repository.database.connect() as connection:
        for memory_type, memory_id in [
            ("event", EVENT_ID),
            ("description", DESCRIPTION_ID),
            ("entity", ENTITY_ID),
            ("property", PROPERTY_ID),
            ("link", LINK_ID),
            ("time_ref", TIME_REF_ID),
            ("time_link", TIME_LINK_ID),
        ]:
            connection.execute(
                """
                DELETE FROM memory_sources
                WHERE memory_type = %s AND memory_id = %s
                """,
                (memory_type, memory_id),
            )
        connection.execute("DELETE FROM memory_time_links WHERE id = %s", (TIME_LINK_ID,))
        connection.execute("DELETE FROM memory_links WHERE id = %s", (LINK_ID,))
        connection.execute("DELETE FROM memory_properties WHERE id = %s", (PROPERTY_ID,))
        connection.execute(
            "DELETE FROM memory_descriptions WHERE id = %s",
            (DESCRIPTION_ID,),
        )
        connection.execute("DELETE FROM memory_time_refs WHERE id = %s", (TIME_REF_ID,))
        connection.execute("DELETE FROM memory_entities WHERE id = %s", (ENTITY_ID,))
        connection.execute("DELETE FROM memory_events WHERE id = %s", (EVENT_ID,))


if __name__ == "__main__":
    sys.exit(main())
