"""Internal DTOs for aggregate memory extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceHint:
    source_message_ids: list[str] = field(default_factory=list)
    source_quote: str | None = None


@dataclass(frozen=True)
class TimeCandidate:
    client_id: str | None = None
    role: str | None = None
    raw_text: str | None = None
    time_kind: str | None = None
    timeline_kind: str | None = None
    certainty: str | None = None
    anchor_timezone: str | None = None
    anchor_utc_offset: str | None = None
    anchor_message_id: str | None = None
    resolved_start: str | None = None
    resolved_end: str | None = None
    granularity: str | None = None
    description: str | None = None
    duration_text: str | None = None
    recurrence_text: str | None = None
    source: SourceHint = field(default_factory=SourceHint)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DescriptionCandidate:
    client_id: str | None
    text: str
    description_type: str | None = None
    time: TimeCandidate | None = None
    source: SourceHint = field(default_factory=SourceHint)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PropertyCandidate:
    client_id: str | None
    text: str
    property_type: str | None = None
    time: TimeCandidate | None = None
    source: SourceHint = field(default_factory=SourceHint)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityCandidate:
    client_id: str | None
    name: str
    entity_type: str | None = None
    identity_summary: str | None = None
    aliases: list[str] = field(default_factory=list)
    properties: list[PropertyCandidate] = field(default_factory=list)
    source: SourceHint = field(default_factory=SourceHint)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EventCandidate:
    client_id: str | None
    title: str
    summary: str | None = None
    event_type: str | None = None
    time: TimeCandidate | None = None
    descriptions: list[DescriptionCandidate] = field(default_factory=list)
    entities: list[EntityCandidate] = field(default_factory=list)
    source: SourceHint = field(default_factory=SourceHint)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionCandidateBatch:
    event_candidates: list[EventCandidate] = field(default_factory=list)
    entity_candidates: list[EntityCandidate] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
