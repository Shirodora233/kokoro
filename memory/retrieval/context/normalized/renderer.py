"""Render normalized event/entity memory views into prompt context."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Sequence

from ....models import MemoryContextBlock, MemoryRecord, MemorySourceRef
from ....persistence.models import (
    PersistentSourceRef,
    PersistentTimeLink,
    PersistentTimeRef,
)
from .models import (
    NormalizedEntityMemoryView,
    NormalizedEventMemoryView,
    NormalizedSelectedMemoryView,
)


class NormalizedMemoryContextRenderer:
    """Select and render normalized memory views for LLM prompt context."""

    def select_views(
        self,
        event_views: Sequence[NormalizedEventMemoryView],
        entity_views: Sequence[NormalizedEntityMemoryView],
        selected_view_refs: Sequence[tuple[str, str]],
        limit: int,
    ) -> list[NormalizedSelectedMemoryView]:
        selected: list[NormalizedSelectedMemoryView] = []
        seen: set[tuple[str, str]] = set()
        event_views_by_id = {
            view.event.id: view for view in event_views if view.event.id
        }
        entity_views_by_id = {
            view.entity.id: view for view in entity_views if view.entity.id
        }

        for view_ref in selected_view_refs:
            if view_ref in seen:
                continue
            kind, object_id = view_ref
            if kind == "event" and object_id in event_views_by_id:
                selected.append(self.render_event_view(event_views_by_id[object_id]))
                seen.add(view_ref)
            elif kind == "entity" and object_id in entity_views_by_id:
                selected.append(self.render_entity_view(entity_views_by_id[object_id]))
                seen.add(view_ref)

        if not selected_view_refs:
            for view in event_views:
                selected.append(self.render_event_view(view))
            for view in entity_views:
                selected.append(self.render_entity_view(view))
        return selected[:limit]

    def render_event_view(
        self,
        view: NormalizedEventMemoryView,
    ) -> NormalizedSelectedMemoryView:
        event = view.event
        provenance = _provenance_line(event.confidence, event.importance, None)
        lines = [f"Event: {event.title}{provenance}"]
        if event.summary and event.summary != event.title:
            lines.append(f"  Summary: {event.summary}")
        detail_lines = _unique_texts(
            description.content for description in view.descriptions
        )
        if detail_lines:
            lines.append("  Details: " + "; ".join(detail_lines[:3]))
        time_lines = _time_lines(view.time_refs)
        if time_lines:
            lines.append("  Time: " + "; ".join(time_lines[:3]))
        if view.entities:
            lines.append(
                "  Entities: "
                + ", ".join(_unique_texts(entity.name for entity in view.entities)[:5])
            )
        source_line = _source_line(event.source_refs)
        if source_line:
            lines.append(source_line)
        text = "\n".join(lines)
        return NormalizedSelectedMemoryView(
            kind="event",
            key=event.id or event.title,
            text=_searchable(
                [
                    text,
                    event.event_type,
                    *[entity.identity_summary for entity in view.entities],
                ]
            ),
            record=MemoryRecord(
                id=event.id,
                memory_type="event",
                text=event.title,
                source_refs=_source_refs(event.source_refs),
                metadata={
                    "normalized": True,
                    "summary": event.summary,
                    "event_type": event.event_type,
                    "description_ids": _ids(item.id for item in view.descriptions),
                    "entity_ids": _ids(item.id for item in view.entities),
                    "time_ref_ids": _ids(time_ref.id for _, time_ref in view.time_refs),
                    "confidence": event.confidence,
                    "importance": event.importance,
                },
            ),
            lines=lines,
        )

    def render_entity_view(
        self,
        view: NormalizedEntityMemoryView,
    ) -> NormalizedSelectedMemoryView:
        entity = view.entity
        provenance = _provenance_line(entity.confidence, entity.importance, None)
        lines = [f"Entity: {entity.name} ({entity.entity_type}){provenance}"]
        if entity.identity_summary:
            lines.append(f"  Identity: {entity.identity_summary}")
        if entity.aliases:
            lines.append("  Aliases: " + ", ".join(entity.aliases[:5]))
        property_lines = _unique_texts(item.content for item in view.properties)
        if property_lines:
            lines.append("  Properties: " + "; ".join(property_lines[:5]))
        if view.events:
            lines.append(
                "  Related events: "
                + ", ".join(_unique_texts(event.title for event in view.events)[:5])
            )
        time_lines = _time_lines(view.time_refs)
        if time_lines:
            lines.append("  Time: " + "; ".join(time_lines[:3]))
        source_line = _source_line(entity.source_refs)
        if source_line:
            lines.append(source_line)
        text = "\n".join(lines)
        return NormalizedSelectedMemoryView(
            kind="entity",
            key=entity.id or entity.name,
            text=_searchable([text, *property_lines]),
            record=MemoryRecord(
                id=entity.id,
                memory_type="entity",
                text=entity.name,
                source_refs=_source_refs(entity.source_refs),
                metadata={
                    "normalized": True,
                    "entity_type": entity.entity_type,
                    "identity_summary": entity.identity_summary,
                    "aliases": entity.aliases,
                    "property_ids": _ids(item.id for item in view.properties),
                    "event_ids": _ids(item.id for item in view.events),
                    "confidence": entity.confidence,
                    "importance": entity.importance,
                },
            ),
            lines=lines,
        )

    def render_context(
        self,
        selected: Sequence[NormalizedSelectedMemoryView],
    ) -> list[MemoryContextBlock]:
        if not selected:
            return []
        preamble = (
            "Relevant memories, may be incomplete or outdated. "
            "Use only when relevant to the user's current message; "
            "the user's latest statement overrides any conflicting memory. "
            "If a memory appears stale or contradicts what the user just said, "
            "trust the user and note the discrepancy."
        )
        lines = [preamble, ""]
        for index, view in enumerate(selected, start=1):
            if index > 1:
                lines.append("")
            lines.extend(view.lines)
        return [
            MemoryContextBlock(
                content="\n".join(lines),
                kind="long_term_memory",
                source_memory_ids=[view.key for view in selected if view.key],
                priority=20,
                metadata={
                    "retriever": "normalized",
                    "view_count": len(selected),
                    "view_kinds": [view.kind for view in selected],
                },
            )
        ]


def _time_lines(
    time_refs: Sequence[tuple[PersistentTimeLink, PersistentTimeRef]],
) -> list[str]:
    lines: list[str] = []
    for time_link, time_ref in time_refs:
        text = _time_text(time_ref)
        if text:
            lines.append(f"{time_link.time_role} {text}")
    return _unique_texts(lines)


def _time_text(time_ref: PersistentTimeRef) -> str:
    return (
        time_ref.raw_text
        or time_ref.resolved_start
        or time_ref.description
        or time_ref.duration_text
        or time_ref.recurrence_text
        or ""
    )


def _provenance_line(
    confidence: str | None,
    importance: str | None,
    created_at: str | None,
) -> str:
    """Build an inline provenance tag for a memory line.

    Example: ' [confidence=high, importance=medium]'
    """
    tags: list[str] = []
    if confidence:
        tags.append(f"confidence={confidence}")
    if importance:
        tags.append(f"importance={importance}")
    if not tags:
        return ""
    return " [" + ", ".join(tags) + "]"


def _source_line(
    source_refs: Sequence[PersistentSourceRef],
) -> str:
    """Build a short source attribution line.

    Example: '  Source: message msg_abc123 ("the exact quote...")'
    """
    if not source_refs:
        return ""
    ref = source_refs[0]
    parts = [f"  Source: {ref.source_type} {ref.source_id}"]
    if ref.quote and ref.quote.strip():
        quote = ref.quote.strip()
        if len(quote) > 120:
            quote = quote[:120] + "..."
        parts.append(f' ("{quote}")')
    return "".join(parts)


def _source_refs(
    source_refs: Sequence[PersistentSourceRef],
) -> list[MemorySourceRef]:
    return [
        MemorySourceRef(
            source_type=source_ref.source_type,
            source_id=source_ref.source_id,
            quote=source_ref.quote,
            span_start=source_ref.span_start,
            span_end=source_ref.span_end,
            metadata=dict(source_ref.metadata),
        )
        for source_ref in source_refs
    ]


def _ids(values: Iterable[str | None]) -> list[str]:
    return [value for value in values if value]


def _unique_texts(values: Iterable[str | None]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        unique.append(normalized)
        seen.add(normalized)
    return unique


def _searchable(values: Sequence[str | None]) -> str:
    return " ".join(value for value in values if value)
