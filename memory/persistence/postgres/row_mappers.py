"""Row mappers for normalized PostgreSQL memory persistence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ..models import (
    Confidence,
    Importance,
    ObjectType,
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentLink,
    PersistentObjectRef,
    PersistentProperty,
    PersistentSourceRef,
    PersistentTimeLink,
    PersistentTimeRef,
    TimeCertainty,
    TimeKind,
    TimelineKind,
)


def event_from_row(
    row: Mapping[str, Any],
    source_refs: list[PersistentSourceRef],
) -> PersistentEvent:
    return PersistentEvent(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        event_type=row["event_type"],
        user_id=row["user_id"],
        session_id=row["session_id"],
        status=row["status"],
        source_refs=source_refs,
        confidence=cast(Confidence, row["confidence"]),
        importance=cast(Importance, row["importance"]),
        created_turn_id=row.get("created_turn_id"),
        created_checkpoint_id=row.get("created_checkpoint_id"),
        created_checkpoint_sequence=row.get("created_checkpoint_sequence"),
        metadata=_metadata_dict(row["metadata"]),
    )


def description_from_row(
    row: Mapping[str, Any],
    source_refs: list[PersistentSourceRef],
) -> PersistentDescription:
    return PersistentDescription(
        id=row["id"],
        event_id=row["event_id"],
        content=row["content"],
        description_type=row["description_type"],
        user_id=row["user_id"],
        session_id=row["session_id"],
        source_refs=source_refs,
        confidence=cast(Confidence, row["confidence"]),
        importance=cast(Importance, row["importance"]),
        created_turn_id=row.get("created_turn_id"),
        created_checkpoint_id=row.get("created_checkpoint_id"),
        created_checkpoint_sequence=row.get("created_checkpoint_sequence"),
        metadata=_metadata_dict(row["metadata"]),
    )


def entity_from_row(
    row: Mapping[str, Any],
    source_refs: list[PersistentSourceRef],
) -> PersistentEntity:
    return PersistentEntity(
        id=row["id"],
        name=row["name"],
        entity_type=row["entity_type"],
        identity_summary=row["identity_summary"],
        aliases=_string_list(row["aliases"]),
        user_id=row["user_id"],
        session_id=row["session_id"],
        scope=row["scope"],
        source_refs=source_refs,
        confidence=cast(Confidence, row["confidence"]),
        importance=cast(Importance, row["importance"]),
        created_turn_id=row.get("created_turn_id"),
        created_checkpoint_id=row.get("created_checkpoint_id"),
        created_checkpoint_sequence=row.get("created_checkpoint_sequence"),
        metadata=_metadata_dict(row["metadata"]),
    )


def property_from_row(
    row: Mapping[str, Any],
    source_refs: list[PersistentSourceRef],
) -> PersistentProperty:
    return PersistentProperty(
        id=row["id"],
        entity_id=row["entity_id"],
        content=row["content"],
        property_type=row["property_type"],
        user_id=row["user_id"],
        session_id=row["session_id"],
        source_refs=source_refs,
        confidence=cast(Confidence, row["confidence"]),
        importance=cast(Importance, row["importance"]),
        created_turn_id=row.get("created_turn_id"),
        created_checkpoint_id=row.get("created_checkpoint_id"),
        created_checkpoint_sequence=row.get("created_checkpoint_sequence"),
        metadata=_metadata_dict(row["metadata"]),
    )


def link_from_row(
    row: Mapping[str, Any],
    source_refs: list[PersistentSourceRef],
) -> PersistentLink:
    return PersistentLink(
        id=row["id"],
        from_ref=PersistentObjectRef(
            object_type=cast(ObjectType, row["from_type"]),
            object_id=row["from_id"],
        ),
        to_ref=PersistentObjectRef(
            object_type=cast(ObjectType, row["to_type"]),
            object_id=row["to_id"],
        ),
        relation_type=row["relation_type"],
        reason=row["reason"],
        source_refs=source_refs,
        confidence=cast(Confidence, row["confidence"]),
        created_turn_id=row.get("created_turn_id"),
        created_checkpoint_id=row.get("created_checkpoint_id"),
        created_checkpoint_sequence=row.get("created_checkpoint_sequence"),
        metadata=_metadata_dict(row["metadata"]),
    )


def time_ref_from_row(
    row: Mapping[str, Any],
    source_refs: list[PersistentSourceRef],
) -> PersistentTimeRef:
    return PersistentTimeRef(
        id=row["id"],
        raw_text=row["raw_text"],
        time_kind=cast(TimeKind, row["time_kind"]),
        timeline_kind=cast(TimelineKind, row["timeline_kind"]),
        certainty=cast(TimeCertainty, row["certainty"]),
        anchor_timezone=row["anchor_timezone"],
        anchor_utc_offset=row["anchor_utc_offset"],
        anchor_message_id=row["anchor_message_id"],
        resolved_start=row["resolved_start"],
        resolved_end=row["resolved_end"],
        granularity=row["granularity"],
        description=row["description"],
        duration_text=row["duration_text"],
        recurrence_text=row["recurrence_text"],
        source_refs=source_refs,
        created_turn_id=row.get("created_turn_id"),
        created_checkpoint_id=row.get("created_checkpoint_id"),
        created_checkpoint_sequence=row.get("created_checkpoint_sequence"),
        metadata=_metadata_dict(row["metadata"]),
    )


def time_link_from_row(
    row: Mapping[str, Any],
    source_refs: list[PersistentSourceRef],
) -> PersistentTimeLink:
    return PersistentTimeLink(
        id=row["id"],
        target_ref=PersistentObjectRef(
            object_type=cast(ObjectType, row["target_type"]),
            object_id=row["target_id"],
        ),
        time_ref_id=row["time_ref_id"],
        time_role=row["time_role"],
        source_refs=source_refs,
        confidence=cast(Confidence, row["confidence"]),
        created_turn_id=row.get("created_turn_id"),
        created_checkpoint_id=row.get("created_checkpoint_id"),
        created_checkpoint_sequence=row.get("created_checkpoint_sequence"),
        metadata=_metadata_dict(row["metadata"]),
    )


def _metadata_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
