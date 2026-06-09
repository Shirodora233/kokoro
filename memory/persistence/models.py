"""Provider-neutral DTOs for durable memory persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ObjectType = Literal[
    "event",
    "description",
    "entity",
    "property",
    "relation",
    "link",
    "time_ref",
    "time_link",
    "message",
    "message_section",
    "summary",
]
Confidence = Literal["low", "medium", "high"]
Importance = Literal["low", "medium", "high"]
TimelineKind = Literal["real_world", "fictional"]
TimeKind = Literal["exact", "relative", "vague", "duration", "recurring"]
TimeCertainty = Literal["resolved", "inferred", "vague", "unknown"]


@dataclass(frozen=True)
class PersistentSourceRef:
    source_type: str
    source_id: str
    quote: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentObjectRef:
    object_type: ObjectType
    object_id: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentEvent:
    id: str | None
    title: str
    summary: str | None = None
    event_type: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    status: str = "active"
    source_refs: list[PersistentSourceRef] = field(default_factory=list)
    confidence: Confidence = "medium"
    importance: Importance = "medium"
    created_turn_id: str | None = None
    created_checkpoint_id: str | None = None
    created_checkpoint_sequence: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentDescription:
    id: str | None
    event_id: str | None
    content: str
    description_type: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    source_refs: list[PersistentSourceRef] = field(default_factory=list)
    confidence: Confidence = "medium"
    importance: Importance = "low"
    created_turn_id: str | None = None
    created_checkpoint_id: str | None = None
    created_checkpoint_sequence: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentEntity:
    id: str | None
    name: str
    entity_type: str
    identity_summary: str | None = None
    aliases: list[str] = field(default_factory=list)
    user_id: str | None = None
    session_id: str | None = None
    scope: str = "session"
    source_refs: list[PersistentSourceRef] = field(default_factory=list)
    confidence: Confidence = "medium"
    importance: Importance = "medium"
    created_turn_id: str | None = None
    created_checkpoint_id: str | None = None
    created_checkpoint_sequence: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentProperty:
    id: str | None
    entity_id: str | None
    content: str
    property_type: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    source_refs: list[PersistentSourceRef] = field(default_factory=list)
    confidence: Confidence = "medium"
    importance: Importance = "medium"
    created_turn_id: str | None = None
    created_checkpoint_id: str | None = None
    created_checkpoint_sequence: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentLink:
    id: str | None
    from_ref: PersistentObjectRef
    to_ref: PersistentObjectRef
    relation_type: str
    reason: str | None = None
    source_refs: list[PersistentSourceRef] = field(default_factory=list)
    confidence: Confidence = "medium"
    created_turn_id: str | None = None
    created_checkpoint_id: str | None = None
    created_checkpoint_sequence: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentTimeRef:
    id: str | None
    raw_text: str
    time_kind: TimeKind
    timeline_kind: TimelineKind
    certainty: TimeCertainty
    anchor_timezone: str
    anchor_utc_offset: str
    anchor_message_id: str | None = None
    resolved_start: str | None = None
    resolved_end: str | None = None
    granularity: str | None = None
    description: str | None = None
    duration_text: str | None = None
    recurrence_text: str | None = None
    source_refs: list[PersistentSourceRef] = field(default_factory=list)
    created_turn_id: str | None = None
    created_checkpoint_id: str | None = None
    created_checkpoint_sequence: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentTimeLink:
    id: str | None
    target_ref: PersistentObjectRef
    time_ref_id: str
    time_role: str
    source_refs: list[PersistentSourceRef] = field(default_factory=list)
    confidence: Confidence = "medium"
    created_turn_id: str | None = None
    created_checkpoint_id: str | None = None
    created_checkpoint_sequence: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentMemoryBundle:
    events: list[PersistentEvent] = field(default_factory=list)
    descriptions: list[PersistentDescription] = field(default_factory=list)
    entities: list[PersistentEntity] = field(default_factory=list)
    properties: list[PersistentProperty] = field(default_factory=list)
    links: list[PersistentLink] = field(default_factory=list)
    time_refs: list[PersistentTimeRef] = field(default_factory=list)
    time_links: list[PersistentTimeLink] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
