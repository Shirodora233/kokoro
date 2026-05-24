"""Normalized memory retrieval and prompt rendering."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Sequence

from ..models import (
    MemoryContextBlock,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemorySourceRef,
)
from ..persistence import PersistentMemoryRepository
from ..persistence.models import (
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentLink,
    PersistentObjectRef,
    PersistentProperty,
    PersistentSourceRef,
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
class _SelectedView:
    kind: str
    key: str
    text: str
    record: MemoryRecord
    lines: list[str]


class NormalizedMemoryRetriever:
    """Retrieve prompt-ready memory context from normalized persistence tables.

    This retriever deliberately hides low-level relation objects such as raw
    links and time-links from the prompt. It uses them to assemble event/entity
    views, then renders only useful semantic context.
    """

    def __init__(
        self,
        repository: PersistentMemoryRepository,
        default_limit: int = 8,
        pool_limit: int = 40,
    ) -> None:
        self.repository = repository
        self.default_limit = default_limit
        self.pool_limit = pool_limit

    def retrieve(self, request: MemoryRetrievalRequest) -> MemoryRetrievalResult:
        limit = self.default_limit if request.limit is None else max(0, request.limit)
        if limit == 0:
            return MemoryRetrievalResult(
                metadata={"retriever": "normalized", "record_count": 0}
            )

        event_views, entity_views = self.假如数据库很大的话，会不会很多数据直接被_load_views过滤掉了进不来(request)
        selected = self._select_views(
            event_views=event_views,
            entity_views=entity_views,
            query=request.query,
            limit=limit,
        )
        context_blocks = self._render_context(selected)
        return MemoryRetrievalResult(
            memory_context=context_blocks,
            records=[view.record for view in selected],
            metadata={
                "retriever": "normalized",
                "repository": self.repository.__class__.__name__,
                "record_count": len(selected),
                "event_view_count": len(event_views),
                "entity_view_count": len(entity_views),
                "query": request.query,
            },
        )

    def _load_views(
        self,
        request: MemoryRetrievalRequest,
    ) -> tuple[list[NormalizedEventMemoryView], list[NormalizedEntityMemoryView]]:
        pool_limit = max(self.pool_limit, (request.limit or self.default_limit) * 4)
        events = self.repository.list_events(
            user_id=request.user_id,
            session_id=request.session_id,
            limit=pool_limit,
        )
        entities = self.repository.list_entities(
            user_id=request.user_id,
            session_id=request.session_id,
            limit=pool_limit,
        )

        event_ids = _ids(event.id for event in events)
        entity_ids = _ids(entity.id for entity in entities)
        descriptions = self.repository.list_descriptions(event_ids=event_ids)
        properties = self.repository.list_properties(entity_ids=entity_ids)

        event_refs = [PersistentObjectRef("event", event_id) for event_id in event_ids]
        entity_refs = [
            PersistentObjectRef("entity", entity_id) for entity_id in entity_ids
        ]
        links = self.repository.list_links(
            object_refs=[*event_refs, *entity_refs],
            user_id=request.user_id,
            limit=pool_limit * 4,
        )

        entities_by_id = {entity.id: entity for entity in entities if entity.id}
        events_by_id = {event.id: event for event in events if event.id}
        self._hydrate_linked_entities(links, entities_by_id)
        self._hydrate_linked_events(links, events_by_id)

        all_entity_ids = _ids(entities_by_id.keys())
        all_event_ids = _ids(events_by_id.keys())
        if set(all_entity_ids) != set(entity_ids):
            properties = self.repository.list_properties(entity_ids=all_entity_ids)
        if set(all_event_ids) != set(event_ids):
            descriptions = self.repository.list_descriptions(event_ids=all_event_ids)

        descriptions_by_event = _group_by_event(descriptions)
        properties_by_entity = _group_by_entity(properties)
        links_by_object = _group_links_by_object(links)

        target_refs = self._time_target_refs(
            events_by_id.values(),
            descriptions,
            entities_by_id.values(),
            properties,
        )
        time_links = self.repository.list_time_links(
            target_refs=target_refs,
            limit=pool_limit * 6,
        )
        time_ref_ids = _ids(time_link.time_ref_id for time_link in time_links)
        time_refs = {
            time_ref.id: time_ref
            for time_ref in self.repository.get_time_refs(time_ref_ids)
            if time_ref.id
        }
        time_links_by_target = _group_time_links_by_target(time_links, time_refs)

        event_views = [
            NormalizedEventMemoryView(
                event=event,
                descriptions=descriptions_by_event.get(event.id or "", []),
                entities=self._linked_entities(event, links_by_object, entities_by_id),
                time_refs=time_links_by_target.get(("event", event.id or ""), []),
                links=links_by_object.get(("event", event.id or ""), []),
            )
            for event in events_by_id.values()
        ]
        entity_views = [
            NormalizedEntityMemoryView(
                entity=entity,
                properties=properties_by_entity.get(entity.id or "", []),
                events=self._linked_events(entity, links_by_object, events_by_id),
                time_refs=time_links_by_target.get(("entity", entity.id or ""), []),
                links=links_by_object.get(("entity", entity.id or ""), []),
            )
            for entity in entities_by_id.values()
        ]
        return event_views, entity_views

    def _hydrate_linked_entities(
        self,
        links: Sequence[PersistentLink],
        entities_by_id: dict[str | None, PersistentEntity],
    ) -> None:
        for link in links:
            for ref in (link.from_ref, link.to_ref):
                if ref.object_type != "entity" or ref.object_id in entities_by_id:
                    continue
                entity = self.repository.get_entity(ref.object_id)
                if entity:
                    entities_by_id[entity.id] = entity

    def _hydrate_linked_events(
        self,
        links: Sequence[PersistentLink],
        events_by_id: dict[str | None, PersistentEvent],
    ) -> None:
        for link in links:
            for ref in (link.from_ref, link.to_ref):
                if ref.object_type != "event" or ref.object_id in events_by_id:
                    continue
                event = self.repository.get_event(ref.object_id)
                if event:
                    events_by_id[event.id] = event

    def _linked_entities(
        self,
        event: PersistentEvent,
        links_by_object: dict[tuple[str, str], list[PersistentLink]],
        entities_by_id: dict[str | None, PersistentEntity],
    ) -> list[PersistentEntity]:
        linked: list[PersistentEntity] = []
        seen: set[str] = set()
        for link in links_by_object.get(("event", event.id or ""), []):
            entity_ref = _opposite_ref(link, "event", event.id or "", "entity")
            if not entity_ref or entity_ref.object_id in seen:
                continue
            entity = entities_by_id.get(entity_ref.object_id)
            if entity:
                linked.append(entity)
                seen.add(entity_ref.object_id)
        return linked

    def _linked_events(
        self,
        entity: PersistentEntity,
        links_by_object: dict[tuple[str, str], list[PersistentLink]],
        events_by_id: dict[str | None, PersistentEvent],
    ) -> list[PersistentEvent]:
        linked: list[PersistentEvent] = []
        seen: set[str] = set()
        for link in links_by_object.get(("entity", entity.id or ""), []):
            event_ref = _opposite_ref(link, "entity", entity.id or "", "event")
            if not event_ref or event_ref.object_id in seen:
                continue
            event = events_by_id.get(event_ref.object_id)
            if event:
                linked.append(event)
                seen.add(event_ref.object_id)
        return linked

    def _time_target_refs(
        self,
        events: Sequence[PersistentEvent],
        descriptions: Sequence[PersistentDescription],
        entities: Sequence[PersistentEntity],
        properties: Sequence[PersistentProperty],
    ) -> list[PersistentObjectRef]:
        refs: list[PersistentObjectRef] = []
        refs.extend(PersistentObjectRef("event", item.id) for item in events if item.id)
        refs.extend(
            PersistentObjectRef("description", item.id)
            for item in descriptions
            if item.id
        )
        refs.extend(
            PersistentObjectRef("entity", item.id) for item in entities if item.id
        )
        refs.extend(
            PersistentObjectRef("property", item.id) for item in properties if item.id
        )
        return refs

    def _select_views(
        self,
        event_views: Sequence[NormalizedEventMemoryView],
        entity_views: Sequence[NormalizedEntityMemoryView],
        query: str | None,
        limit: int,
    ) -> list[_SelectedView]:
        selected: list[_SelectedView] = []
        for view in event_views:
            rendered = self._render_event_view(view)
            if self._matches_query(rendered.text, query):
                selected.append(rendered)
        for view in entity_views:
            rendered = self._render_entity_view(view)
            if self._matches_query(rendered.text, query):
                selected.append(rendered)
        return selected[:limit]

    def _render_event_view(self, view: NormalizedEventMemoryView) -> _SelectedView:
        event = view.event
        lines = [f"Event: {event.title}"]
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
        text = "\n".join(lines)
        return _SelectedView(
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
                },
            ),
            lines=lines,
        )

    def _render_entity_view(self, view: NormalizedEntityMemoryView) -> _SelectedView:
        entity = view.entity
        lines = [f"Entity: {entity.name} ({entity.entity_type})"]
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
        text = "\n".join(lines)
        return _SelectedView(
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
                },
            ),
            lines=lines,
        )

    def _matches_query(self, text: str, query: str | None) -> bool:
        normalized_query = (query or "").casefold().strip()
        if not normalized_query:
            return True
        return normalized_query in text.casefold()

    def _render_context(
        self,
        selected: Sequence[_SelectedView],
    ) -> list[MemoryContextBlock]:
        if not selected:
            return []
        lines = ["Relevant memories:"]
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


def _group_by_event(
    descriptions: Sequence[PersistentDescription],
) -> dict[str, list[PersistentDescription]]:
    grouped: dict[str, list[PersistentDescription]] = {}
    for description in descriptions:
        if description.event_id:
            grouped.setdefault(description.event_id, []).append(description)
    return grouped


def _group_by_entity(
    properties: Sequence[PersistentProperty],
) -> dict[str, list[PersistentProperty]]:
    grouped: dict[str, list[PersistentProperty]] = {}
    for memory_property in properties:
        if memory_property.entity_id:
            grouped.setdefault(memory_property.entity_id, []).append(memory_property)
    return grouped


def _group_links_by_object(
    links: Sequence[PersistentLink],
) -> dict[tuple[str, str], list[PersistentLink]]:
    grouped: dict[tuple[str, str], list[PersistentLink]] = {}
    for link in links:
        grouped.setdefault(
            (link.from_ref.object_type, link.from_ref.object_id),
            [],
        ).append(link)
        grouped.setdefault(
            (link.to_ref.object_type, link.to_ref.object_id),
            [],
        ).append(link)
    return grouped


def _group_time_links_by_target(
    time_links: Sequence[PersistentTimeLink],
    time_refs: dict[str | None, PersistentTimeRef],
) -> dict[tuple[str, str], list[tuple[PersistentTimeLink, PersistentTimeRef]]]:
    grouped: dict[tuple[str, str], list[tuple[PersistentTimeLink, PersistentTimeRef]]] = {}
    for time_link in time_links:
        time_ref = time_refs.get(time_link.time_ref_id)
        if not time_ref:
            continue
        grouped.setdefault(
            (time_link.target_ref.object_type, time_link.target_ref.object_id),
            [],
        ).append((time_link, time_ref))
    return grouped


def _opposite_ref(
    link: PersistentLink,
    object_type: str,
    object_id: str,
    target_type: str,
) -> PersistentObjectRef | None:
    if (
        link.from_ref.object_type == object_type
        and link.from_ref.object_id == object_id
        and link.to_ref.object_type == target_type
    ):
        return link.to_ref
    if (
        link.to_ref.object_type == object_type
        and link.to_ref.object_id == object_id
        and link.from_ref.object_type == target_type
    ):
        return link.from_ref
    return None


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
