"""Runtime adapters from generic write results to durable memory persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, Sequence, cast

from ..models import MemoryRecord, MemorySourceRef
from ..writing import MemoryWriteResult
from .models import (
    Confidence,
    Importance,
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
    ObjectType,
    TimeCertainty,
    TimeKind,
    TimelineKind,
)

_CONFIDENCE_VALUES = {"low", "medium", "high"}
_IMPORTANCE_VALUES = {"low", "medium", "high"}
_TIME_KIND_VALUES = {"exact", "relative", "vague", "duration", "recurring"}
_TIMELINE_KIND_VALUES = {"real_world", "fictional"}
_TIME_CERTAINTY_VALUES = {"resolved", "inferred", "vague", "unknown"}
_OBJECT_TYPE_VALUES = {
    "event",
    "description",
    "entity",
    "property",
    "link",
    "time_ref",
    "time_link",
    "message",
    "message_section",
    "summary",
}


class PersistentMemoryBundleRepository(Protocol):
    """Minimal repository surface needed by runtime persistence sync."""

    def save_bundle(self, bundle: PersistentMemoryBundle) -> PersistentMemoryBundle:
        """Persist normalized memory objects."""


@dataclass(frozen=True)
class PersistentMemorySkippedRecord:
    record_id: str | None
    memory_type: str
    text: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentMemoryBuildResult:
    bundle: PersistentMemoryBundle
    skipped_records: list[PersistentMemorySkippedRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentMemorySyncResult:
    build_result: PersistentMemoryBuildResult
    stored_bundle: PersistentMemoryBundle
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class MemoryRecordPersistenceAdapter:
    """Build normalized persistence DTOs from generic memory records."""

    def build_bundle(
        self,
        records: Sequence[MemoryRecord],
    ) -> PersistentMemoryBuildResult:
        deduped_records = self._dedupe_records(records)
        skipped: list[PersistentMemorySkippedRecord] = []
        bundle = PersistentMemoryBundle()

        for record in deduped_records:
            try:
                self._append_record(bundle, record)
            except ValueError as error:
                skipped.append(
                    PersistentMemorySkippedRecord(
                        record_id=record.id,
                        memory_type=record.memory_type,
                        text=record.text,
                        reason=str(error),
                    )
                )

        return PersistentMemoryBuildResult(
            bundle=bundle,
            skipped_records=skipped,
            metadata={
                "adapter": self.__class__.__name__,
                "input_record_count": len(records),
                "deduped_record_count": len(deduped_records),
                "persistable_record_count": _bundle_object_count(bundle),
                "skipped_count": len(skipped),
            },
        )

    def _append_record(
        self,
        bundle: PersistentMemoryBundle,
        record: MemoryRecord,
    ) -> None:
        if record.memory_type == "event":
            bundle.events.append(self._event(record))
        elif record.memory_type == "description":
            bundle.descriptions.append(self._description(record))
        elif record.memory_type == "entity":
            bundle.entities.append(self._entity(record))
        elif record.memory_type == "property":
            bundle.properties.append(self._property(record))
        elif record.memory_type == "link":
            bundle.links.append(self._link(record))
        elif record.memory_type == "time_ref":
            bundle.time_refs.append(self._time_ref(record))
        elif record.memory_type == "time_link":
            bundle.time_links.append(self._time_link(record))
        else:
            raise ValueError(f"{record.memory_type} is not persisted by this adapter")

    def _event(self, record: MemoryRecord) -> PersistentEvent:
        metadata = record.metadata
        return PersistentEvent(
            id=self._required_record_id(record),
            title=record.text,
            summary=_optional_string(metadata, "summary"),
            event_type=_optional_string(metadata, "event_type"),
            user_id=_optional_string(metadata, "user_id"),
            session_id=_optional_string(metadata, "session_id"),
            status=_optional_string(metadata, "status") or "active",
            source_refs=_source_refs(record.source_refs),
            confidence=_confidence(metadata),
            importance=_importance(metadata, "medium"),
            created_turn_id=_optional_string(metadata, "created_turn_id"),
            created_checkpoint_id=_optional_string(metadata, "created_checkpoint_id"),
            created_checkpoint_sequence=_optional_int(
                metadata,
                "created_checkpoint_sequence",
            ),
            metadata=dict(metadata),
        )

    def _description(self, record: MemoryRecord) -> PersistentDescription:
        metadata = record.metadata
        return PersistentDescription(
            id=self._required_record_id(record),
            event_id=self._required_metadata_string(metadata, "attached_to_record_id"),
            content=record.text,
            description_type=_optional_string(metadata, "description_type"),
            user_id=_optional_string(metadata, "user_id"),
            session_id=_optional_string(metadata, "session_id"),
            source_refs=_source_refs(record.source_refs),
            confidence=_confidence(metadata),
            importance=_importance(metadata, "low"),
            created_turn_id=_optional_string(metadata, "created_turn_id"),
            created_checkpoint_id=_optional_string(metadata, "created_checkpoint_id"),
            created_checkpoint_sequence=_optional_int(
                metadata,
                "created_checkpoint_sequence",
            ),
            metadata=dict(metadata),
        )

    def _entity(self, record: MemoryRecord) -> PersistentEntity:
        metadata = record.metadata
        return PersistentEntity(
            id=self._required_record_id(record),
            name=record.text,
            entity_type=_optional_string(metadata, "entity_type") or "unknown",
            identity_summary=_optional_string(metadata, "identity_summary"),
            aliases=_string_list(metadata.get("aliases")),
            user_id=_optional_string(metadata, "user_id"),
            session_id=_optional_string(metadata, "session_id"),
            scope=self._entity_scope(metadata),
            source_refs=_source_refs(record.source_refs),
            confidence=_confidence(metadata),
            importance=_importance(metadata, "medium"),
            created_turn_id=_optional_string(metadata, "created_turn_id"),
            created_checkpoint_id=_optional_string(metadata, "created_checkpoint_id"),
            created_checkpoint_sequence=_optional_int(
                metadata,
                "created_checkpoint_sequence",
            ),
            metadata=dict(metadata),
        )

    def _property(self, record: MemoryRecord) -> PersistentProperty:
        metadata = record.metadata
        return PersistentProperty(
            id=self._required_record_id(record),
            entity_id=self._required_metadata_string(metadata, "attached_to_record_id"),
            content=record.text,
            property_type=_optional_string(metadata, "property_type"),
            user_id=_optional_string(metadata, "user_id"),
            session_id=_optional_string(metadata, "session_id"),
            source_refs=_source_refs(record.source_refs),
            confidence=_confidence(metadata),
            importance=_importance(metadata, "medium"),
            created_turn_id=_optional_string(metadata, "created_turn_id"),
            created_checkpoint_id=_optional_string(metadata, "created_checkpoint_id"),
            created_checkpoint_sequence=_optional_int(
                metadata,
                "created_checkpoint_sequence",
            ),
            metadata=dict(metadata),
        )

    def _link(self, record: MemoryRecord) -> PersistentLink:
        metadata = record.metadata
        from_type = self._object_type(metadata, "from_type")
        to_type = self._object_type(metadata, "to_type")
        return PersistentLink(
            id=self._required_record_id(record),
            from_ref=PersistentObjectRef(
                object_type=from_type,
                object_id=self._required_metadata_string(metadata, "from_record_id"),
            ),
            to_ref=PersistentObjectRef(
                object_type=to_type,
                object_id=self._required_metadata_string(metadata, "to_record_id"),
            ),
            relation_type=self._required_metadata_string(metadata, "relation_type"),
            reason=_optional_string(metadata, "write_reason"),
            source_refs=_source_refs(record.source_refs),
            confidence=_confidence(metadata),
            created_turn_id=_optional_string(metadata, "created_turn_id"),
            created_checkpoint_id=_optional_string(metadata, "created_checkpoint_id"),
            created_checkpoint_sequence=_optional_int(
                metadata,
                "created_checkpoint_sequence",
            ),
            metadata=dict(metadata),
        )

    def _time_ref(self, record: MemoryRecord) -> PersistentTimeRef:
        metadata = record.metadata
        return PersistentTimeRef(
            id=self._required_record_id(record),
            raw_text=self._required_metadata_string(metadata, "raw_text"),
            time_kind=self._time_kind(metadata),
            timeline_kind=self._timeline_kind(metadata),
            certainty=self._time_certainty(metadata),
            anchor_timezone=self._required_metadata_string(
                metadata,
                "anchor_timezone",
            ),
            anchor_utc_offset=self._required_metadata_string(
                metadata,
                "anchor_utc_offset",
            ),
            anchor_message_id=_optional_string(metadata, "anchor_message_id"),
            resolved_start=_optional_string(metadata, "resolved_start"),
            resolved_end=_optional_string(metadata, "resolved_end"),
            granularity=_optional_string(metadata, "granularity"),
            description=_optional_string(metadata, "description"),
            duration_text=_optional_string(metadata, "duration_text"),
            recurrence_text=_optional_string(metadata, "recurrence_text"),
            source_refs=_source_refs(record.source_refs),
            created_turn_id=_optional_string(metadata, "created_turn_id"),
            created_checkpoint_id=_optional_string(metadata, "created_checkpoint_id"),
            created_checkpoint_sequence=_optional_int(
                metadata,
                "created_checkpoint_sequence",
            ),
            metadata=dict(metadata),
        )

    def _time_link(self, record: MemoryRecord) -> PersistentTimeLink:
        metadata = record.metadata
        return PersistentTimeLink(
            id=self._required_record_id(record),
            target_ref=PersistentObjectRef(
                object_type=self._object_type(metadata, "target_type"),
                object_id=self._required_metadata_string(metadata, "target_record_id"),
            ),
            time_ref_id=self._required_metadata_string(metadata, "time_ref_record_id"),
            time_role=self._required_metadata_string(metadata, "time_role"),
            source_refs=_source_refs(record.source_refs),
            confidence=_confidence(metadata),
            created_turn_id=_optional_string(metadata, "created_turn_id"),
            created_checkpoint_id=_optional_string(metadata, "created_checkpoint_id"),
            created_checkpoint_sequence=_optional_int(
                metadata,
                "created_checkpoint_sequence",
            ),
            metadata=dict(metadata),
        )

    def _dedupe_records(
        self,
        records: Sequence[MemoryRecord],
    ) -> list[MemoryRecord]:
        deduped: list[MemoryRecord] = []
        seen: set[str] = set()
        for record in records:
            key = record.id or f"{record.memory_type}:{record.text}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(record)
        return deduped

    def _required_record_id(self, record: MemoryRecord) -> str:
        if not record.id:
            raise ValueError(f"{record.memory_type} has no persisted record id")
        return record.id

    def _required_metadata_string(
        self,
        metadata: dict[str, Any],
        key: str,
    ) -> str:
        value = _optional_string(metadata, key)
        if not value:
            raise ValueError(f"metadata.{key} is required")
        return value

    def _entity_scope(self, metadata: dict[str, Any]) -> str:
        configured = _optional_string(metadata, "scope")
        if configured in {"global", "user", "session"}:
            return configured
        if _optional_string(metadata, "session_id"):
            return "session"
        if _optional_string(metadata, "user_id"):
            return "user"
        return "global"

    def _object_type(self, metadata: dict[str, Any], key: str) -> ObjectType:
        value = _optional_string(metadata, key)
        if value not in _OBJECT_TYPE_VALUES:
            raise ValueError(f"metadata.{key} has unsupported object type")
        return cast(ObjectType, value)

    def _time_kind(self, metadata: dict[str, Any]) -> TimeKind:
        value = self._required_metadata_string(metadata, "time_kind")
        if value not in _TIME_KIND_VALUES:
            raise ValueError("metadata.time_kind has unsupported value")
        return cast(TimeKind, value)

    def _timeline_kind(self, metadata: dict[str, Any]) -> TimelineKind:
        value = self._required_metadata_string(metadata, "timeline_kind")
        if value not in _TIMELINE_KIND_VALUES:
            raise ValueError("metadata.timeline_kind has unsupported value")
        return cast(TimelineKind, value)

    def _time_certainty(self, metadata: dict[str, Any]) -> TimeCertainty:
        value = self._required_metadata_string(metadata, "certainty")
        if value not in _TIME_CERTAINTY_VALUES:
            raise ValueError("metadata.certainty has unsupported value")
        return cast(TimeCertainty, value)


class MemoryWriteResultPersistenceSync:
    """Persist generic runtime write results into normalized memory tables."""

    def __init__(
        self,
        repository: PersistentMemoryBundleRepository,
        adapter: MemoryRecordPersistenceAdapter | None = None,
    ) -> None:
        self.repository = repository
        self.adapter = adapter or MemoryRecordPersistenceAdapter()

    def sync(self, write_result: MemoryWriteResult) -> PersistentMemorySyncResult:
        build_result = self.adapter.build_bundle(
            [
                *write_result.reused_records,
                *write_result.created_records,
                *write_result.attached_records,
            ]
        )
        if _bundle_object_count(build_result.bundle) == 0:
            stored_bundle = PersistentMemoryBundle()
        else:
            stored_bundle = self.repository.save_bundle(build_result.bundle)
        return PersistentMemorySyncResult(
            build_result=build_result,
            stored_bundle=stored_bundle,
            metadata={
                "sync": self.__class__.__name__,
                "repository": self.repository.__class__.__name__,
                "stored_count": _bundle_object_count(stored_bundle),
                "skipped_count": len(build_result.skipped_records),
            },
        )


def _source_refs(source_refs: Sequence[MemorySourceRef]) -> list[PersistentSourceRef]:
    return [
        PersistentSourceRef(
            source_type=source_ref.source_type,
            source_id=source_ref.source_id,
            quote=source_ref.quote,
            span_start=source_ref.span_start,
            span_end=source_ref.span_end,
            metadata=dict(source_ref.metadata),
        )
        for source_ref in source_refs
    ]


def _optional_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(metadata: dict[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, int):
        return value
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _confidence(metadata: dict[str, Any]) -> Confidence:
    value = _optional_string(metadata, "confidence")
    if value in _CONFIDENCE_VALUES:
        return cast(Confidence, value)
    return "medium"


def _importance(metadata: dict[str, Any], default: Importance) -> Importance:
    value = _optional_string(metadata, "importance")
    if value in _IMPORTANCE_VALUES:
        return cast(Importance, value)
    return default


def _bundle_object_count(bundle: PersistentMemoryBundle) -> int:
    return (
        len(bundle.events)
        + len(bundle.descriptions)
        + len(bundle.entities)
        + len(bundle.properties)
        + len(bundle.links)
        + len(bundle.time_refs)
        + len(bundle.time_links)
    )
