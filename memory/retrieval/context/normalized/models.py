"""View models used by normalized memory context retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field

from ....models import MemoryRecord
from ....persistence.models import (
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentLink,
    PersistentProperty,
    PersistentTimeLink,
    PersistentTimeRef,
)


@dataclass(frozen=True)
class NormalizedEventMemoryView:
    event: PersistentEvent
    descriptions: list[PersistentDescription] = field(default_factory=list)
    entities: list[PersistentEntity] = field(default_factory=list)
    time_refs: list[tuple[PersistentTimeLink, PersistentTimeRef]] = field(
        default_factory=list
    )
    links: list[PersistentLink] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizedEntityMemoryView:
    entity: PersistentEntity
    properties: list[PersistentProperty] = field(default_factory=list)
    events: list[PersistentEvent] = field(default_factory=list)
    time_refs: list[tuple[PersistentTimeLink, PersistentTimeRef]] = field(
        default_factory=list
    )
    links: list[PersistentLink] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizedSelectedMemoryView:
    kind: str
    key: str
    text: str
    record: MemoryRecord
    lines: list[str]


@dataclass(frozen=True)
class HydratedMemoryViews:
    event_views: list[NormalizedEventMemoryView]
    entity_views: list[NormalizedEntityMemoryView]
    selected_view_refs: list[tuple[str, str]]
