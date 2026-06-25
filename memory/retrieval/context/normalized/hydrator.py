"""Hydrate normalized search hits into event/entity memory views."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Sequence

from ....models import MemoryRetrievalRequest, MemorySearchHit
from ....persistence import PersistentMemoryRepository
from ....persistence.models import (
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentLink,
    PersistentObjectRef,
    PersistentProperty,
    PersistentTimeLink,
    PersistentTimeRef,
)
from .models import (
    HydratedMemoryViews,
    NormalizedEntityMemoryView,
    NormalizedEventMemoryView,
)


class NormalizedMemoryHydrator:
    """Load parent event/entity views from normalized search hits."""

    def __init__(
        self,
        repository: PersistentMemoryRepository,
        default_limit: int = 8,
        pool_limit: int = 40,
    ) -> None:
        self.repository = repository
        self.default_limit = default_limit
        self.pool_limit = pool_limit

    def load_views(
        self,
        request: MemoryRetrievalRequest,
        hits: Sequence[MemorySearchHit],
    ) -> HydratedMemoryViews:
        as_of_checkpoint_id = _as_of_checkpoint_id(request)
        pool_limit = max(self.pool_limit, (request.limit or self.default_limit) * 4)
        selected_view_refs: list[tuple[str, str]] = []
        seed_descriptions: list[PersistentDescription] = []
        seed_properties: list[PersistentProperty] = []
        events_by_id: dict[str | None, PersistentEvent] = {}
        entities_by_id: dict[str | None, PersistentEntity] = {}

        for hit in hits:
            ref = hit.object_ref
            if ref.object_type == "event":
                event = _get_event(self.repository, ref.object_id, as_of_checkpoint_id)
                if event:
                    events_by_id[event.id] = event
                    _append_view_ref(selected_view_refs, "event", event.id)
            elif ref.object_type == "description":
                description = _get_description(
                    self.repository,
                    ref.object_id,
                    as_of_checkpoint_id,
                )
                if not description:
                    continue
                seed_descriptions.append(description)
                if description.event_id:
                    event = _get_event(
                        self.repository,
                        description.event_id,
                        as_of_checkpoint_id,
                    )
                    if event:
                        events_by_id[event.id] = event
                        _append_view_ref(selected_view_refs, "event", event.id)
            elif ref.object_type == "entity":
                entity = _get_entity(self.repository, ref.object_id, as_of_checkpoint_id)
                if entity:
                    entities_by_id[entity.id] = entity
                    _append_view_ref(selected_view_refs, "entity", entity.id)
            elif ref.object_type == "property":
                memory_property = _get_property(
                    self.repository,
                    ref.object_id,
                    as_of_checkpoint_id,
                )
                if not memory_property:
                    continue
                seed_properties.append(memory_property)
                if memory_property.entity_id:
                    entity = _get_entity(
                        self.repository,
                        memory_property.entity_id,
                        as_of_checkpoint_id,
                    )
                    if entity:
                        entities_by_id[entity.id] = entity
                        _append_view_ref(selected_view_refs, "entity", entity.id)

        event_ids = _ids(events_by_id.keys())
        entity_ids = _ids(entities_by_id.keys())
        descriptions = _list_descriptions(
            self.repository,
            as_of_checkpoint_id,
            event_ids=event_ids,
        )
        properties = _list_properties(
            self.repository,
            as_of_checkpoint_id,
            entity_ids=entity_ids,
        )
        descriptions = _merge_descriptions(seed_descriptions, descriptions)
        properties = _merge_properties(seed_properties, properties)

        event_refs = [PersistentObjectRef("event", event_id) for event_id in event_ids]
        entity_refs = [
            PersistentObjectRef("entity", entity_id) for entity_id in entity_ids
        ]
        links = _list_links(
            self.repository,
            as_of_checkpoint_id,
            object_refs=[*event_refs, *entity_refs],
            user_id=request.user_id,
            limit=pool_limit * 4,
        )

        self._hydrate_linked_entities(links, entities_by_id, as_of_checkpoint_id)
        self._hydrate_linked_events(links, events_by_id, as_of_checkpoint_id)

        all_entity_ids = _ids(entities_by_id.keys())
        all_event_ids = _ids(events_by_id.keys())
        if set(all_entity_ids) != set(entity_ids):
            properties = _list_properties(
                self.repository,
                as_of_checkpoint_id,
                entity_ids=all_entity_ids,
            )
        if set(all_event_ids) != set(event_ids):
            descriptions = _list_descriptions(
                self.repository,
                as_of_checkpoint_id,
                event_ids=all_event_ids,
            )

        descriptions_by_event = _group_by_event(descriptions)
        properties_by_entity = _group_by_entity(properties)
        links_by_object = _group_links_by_object(links)

        target_refs = self._time_target_refs(
            events_by_id.values(),
            descriptions,
            entities_by_id.values(),
            properties,
        )
        time_links = _list_time_links(
            self.repository,
            as_of_checkpoint_id,
            target_refs=target_refs,
            limit=pool_limit * 6,
        )
        time_ref_ids = _ids(time_link.time_ref_id for time_link in time_links)
        time_refs = {
            time_ref.id: time_ref
            for time_ref in _get_time_refs(
                self.repository,
                time_ref_ids,
                as_of_checkpoint_id=as_of_checkpoint_id,
            )
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
        return HydratedMemoryViews(
            event_views=event_views,
            entity_views=entity_views,
            selected_view_refs=selected_view_refs,
        )

    def _hydrate_linked_entities(
        self,
        links: Sequence[PersistentLink],
        entities_by_id: dict[str | None, PersistentEntity],
        as_of_checkpoint_id: str | None,
    ) -> None:
        for link in links:
            for ref in (link.from_ref, link.to_ref):
                if ref.object_type != "entity" or ref.object_id in entities_by_id:
                    continue
                entity = _get_entity(
                    self.repository,
                    ref.object_id,
                    as_of_checkpoint_id,
                )
                if entity:
                    entities_by_id[entity.id] = entity

    def _hydrate_linked_events(
        self,
        links: Sequence[PersistentLink],
        events_by_id: dict[str | None, PersistentEvent],
        as_of_checkpoint_id: str | None,
    ) -> None:
        for link in links:
            for ref in (link.from_ref, link.to_ref):
                if ref.object_type != "event" or ref.object_id in events_by_id:
                    continue
                event = _get_event(
                    self.repository,
                    ref.object_id,
                    as_of_checkpoint_id,
                )
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


def _group_by_event(
    descriptions: Sequence[PersistentDescription],
) -> dict[str, list[PersistentDescription]]:
    grouped: dict[str, list[PersistentDescription]] = {}
    for description in descriptions:
        if description.event_id:
            grouped.setdefault(description.event_id, []).append(description)
    return grouped


def _get_event(repository, object_id: str, as_of_checkpoint_id: str | None):
    if as_of_checkpoint_id is None:
        return repository.get_event(object_id)
    try:
        return repository.get_event(object_id, as_of_checkpoint_id)
    except TypeError:
        return repository.get_event(object_id)


def _get_description(repository, object_id: str, as_of_checkpoint_id: str | None):
    if as_of_checkpoint_id is None:
        return repository.get_description(object_id)
    try:
        return repository.get_description(object_id, as_of_checkpoint_id)
    except TypeError:
        return repository.get_description(object_id)


def _get_entity(repository, object_id: str, as_of_checkpoint_id: str | None):
    if as_of_checkpoint_id is None:
        return repository.get_entity(object_id)
    try:
        return repository.get_entity(object_id, as_of_checkpoint_id)
    except TypeError:
        return repository.get_entity(object_id)


def _get_property(repository, object_id: str, as_of_checkpoint_id: str | None):
    if as_of_checkpoint_id is None:
        return repository.get_property(object_id)
    try:
        return repository.get_property(object_id, as_of_checkpoint_id)
    except TypeError:
        return repository.get_property(object_id)


def _list_descriptions(repository, as_of_checkpoint_id: str | None, **kwargs):
    if as_of_checkpoint_id is not None:
        try:
            return repository.list_descriptions(
                **kwargs,
                as_of_checkpoint_id=as_of_checkpoint_id,
            )
        except TypeError:
            pass
    return repository.list_descriptions(**kwargs)


def _list_properties(repository, as_of_checkpoint_id: str | None, **kwargs):
    if as_of_checkpoint_id is not None:
        try:
            return repository.list_properties(
                **kwargs,
                as_of_checkpoint_id=as_of_checkpoint_id,
            )
        except TypeError:
            pass
    return repository.list_properties(**kwargs)


def _list_links(repository, as_of_checkpoint_id: str | None, **kwargs):
    if as_of_checkpoint_id is not None:
        try:
            return repository.list_links(
                **kwargs,
                as_of_checkpoint_id=as_of_checkpoint_id,
            )
        except TypeError:
            pass
    return repository.list_links(**kwargs)


def _list_time_links(repository, as_of_checkpoint_id: str | None, **kwargs):
    if as_of_checkpoint_id is not None:
        try:
            return repository.list_time_links(
                **kwargs,
                as_of_checkpoint_id=as_of_checkpoint_id,
            )
        except TypeError:
            pass
    return repository.list_time_links(**kwargs)


def _get_time_refs(
    repository,
    time_ref_ids: Sequence[str],
    *,
    as_of_checkpoint_id: str | None,
):
    if as_of_checkpoint_id is not None:
        try:
            return repository.get_time_refs(
                time_ref_ids,
                as_of_checkpoint_id=as_of_checkpoint_id,
            )
        except TypeError:
            pass
    return repository.get_time_refs(time_ref_ids)


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


def _append_view_ref(
    refs: list[tuple[str, str]],
    kind: str,
    object_id: str | None,
) -> None:
    if object_id:
        refs.append((kind, object_id))


def _merge_descriptions(
    first: Sequence[PersistentDescription],
    second: Sequence[PersistentDescription],
) -> list[PersistentDescription]:
    merged: list[PersistentDescription] = []
    seen: set[str] = set()
    for description in [*first, *second]:
        key = description.id or description.content
        if key in seen:
            continue
        merged.append(description)
        seen.add(key)
    return merged


def _merge_properties(
    first: Sequence[PersistentProperty],
    second: Sequence[PersistentProperty],
) -> list[PersistentProperty]:
    merged: list[PersistentProperty] = []
    seen: set[str] = set()
    for memory_property in [*first, *second]:
        key = memory_property.id or memory_property.content
        if key in seen:
            continue
        merged.append(memory_property)
        seen.add(key)
    return merged


def _ids(values: Iterable[str | None]) -> list[str]:
    return [value for value in values if value]


def _as_of_checkpoint_id(request: MemoryRetrievalRequest) -> str | None:
    value = request.metadata.get("as_of_checkpoint_id")
    if isinstance(value, str) and value:
        return value
    value = request.metadata.get("base_checkpoint_id")
    if isinstance(value, str) and value:
        return value
    raw_scopes = request.metadata.get("visible_session_scopes")
    if isinstance(raw_scopes, list):
        for scope in reversed(raw_scopes):
            if not isinstance(scope, dict):
                continue
            scope_value = scope.get("as_of_checkpoint_id")
            if isinstance(scope_value, str) and scope_value:
                return scope_value
    return None
