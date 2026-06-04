"""Coalesce duplicate candidates within one extraction batch."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .schema import (
    EntityCandidate,
    EventCandidate,
    ExtractionCandidateBatch,
    PropertyCandidate,
    SourceHint,
)


class MemoryCandidateCoalescer:
    """Deterministically clean duplicate structure from one LLM output batch."""

    def coalesce(self, batch: ExtractionCandidateBatch) -> ExtractionCandidateBatch:
        state = _CoalesceState()
        top_level_keys: set[_EntityKey] = set()
        event_entity_count = 0

        for event in batch.event_candidates:
            for entity in event.entities:
                event_entity_count += 1
                key = state.add_entity(entity)

        for entity in batch.entity_candidates:
            key = state.add_entity(entity)
            top_level_keys.add(key)

        coalesced_events = [
            self._event_with_entity_refs(event, state) for event in batch.event_candidates
        ]
        entity_candidate_keys = {
            key
            for key, entity in state.entities.items()
            if key in top_level_keys or entity.properties
        }
        coalesced_entities = [
            state.entities[key]
            for key in state.entity_order
            if key in entity_candidate_keys
        ]
        metadata = dict(batch.metadata)
        metadata.setdefault(
            "coalescer",
            {
                "entity_count_before": event_entity_count + len(batch.entity_candidates),
                "entity_count_after": len(state.entities),
                "top_level_entity_count_after": len(coalesced_entities),
            },
        )
        return ExtractionCandidateBatch(
            event_candidates=coalesced_events,
            entity_candidates=coalesced_entities,
            metadata=metadata,
        )

    def _event_with_entity_refs(
        self,
        event: EventCandidate,
        state: "_CoalesceState",
    ) -> EventCandidate:
        refs: list[EntityCandidate] = []
        seen_keys: set[_EntityKey] = set()
        for entity in event.entities:
            key = state.key_for_entity(entity)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            refs.append(_entity_ref(state.entities[key], fallback_source=entity.source))
        return replace(event, entities=refs)


_EntityKey = tuple[str, str]
_PropertyKey = tuple[str, str]


class _CoalesceState:
    def __init__(self) -> None:
        self.entities: dict[_EntityKey, EntityCandidate] = {}
        self.entity_order: list[_EntityKey] = []
        self.entity_keys_by_client_id: dict[str, _EntityKey] = {}
        self.entity_keys_by_identity: dict[tuple[str, str], _EntityKey] = {}

    def add_entity(self, entity: EntityCandidate) -> _EntityKey:
        key = self.key_for_entity(entity)
        if key not in self.entities:
            self.entities[key] = entity
            self.entity_order.append(key)
        else:
            self.entities[key] = _merge_entity(self.entities[key], entity)
        if entity.client_id:
            self.entity_keys_by_client_id[entity.client_id] = key
        self._index_entity(self.entities[key], key)
        return key

    def key_for_entity(self, entity: EntityCandidate) -> _EntityKey:
        if entity.client_id and entity.client_id in self.entity_keys_by_client_id:
            return self.entity_keys_by_client_id[entity.client_id]

        identity = _entity_identity(entity)
        if identity in self.entity_keys_by_identity:
            return self.entity_keys_by_identity[identity]

        if entity.client_id:
            return ("client_id", entity.client_id)
        return ("identity", "\x1f".join(identity))

    def _index_entity(self, entity: EntityCandidate, key: _EntityKey) -> None:
        if entity.client_id:
            self.entity_keys_by_client_id[entity.client_id] = key
        self.entity_keys_by_identity[_entity_identity(entity)] = key


def _merge_entity(left: EntityCandidate, right: EntityCandidate) -> EntityCandidate:
    return EntityCandidate(
        client_id=left.client_id or right.client_id,
        name=left.name or right.name,
        entity_type=left.entity_type or right.entity_type,
        identity_summary=_prefer_text(left.identity_summary, right.identity_summary),
        aliases=_merge_strings(left.aliases, right.aliases),
        properties=_merge_properties(left.properties, right.properties),
        source=_merge_source(left.source, right.source),
        metadata=_merge_metadata(left.metadata, right.metadata),
    )


def _merge_properties(
    left: list[PropertyCandidate],
    right: list[PropertyCandidate],
) -> list[PropertyCandidate]:
    properties: dict[_PropertyKey, PropertyCandidate] = {}
    order: list[_PropertyKey] = []
    keys_by_client_id: dict[str, _PropertyKey] = {}
    keys_by_identity: dict[tuple[str, str], _PropertyKey] = {}
    for prop in [*left, *right]:
        key = _property_key(prop, keys_by_client_id, keys_by_identity)
        if key not in properties:
            properties[key] = prop
            order.append(key)
        else:
            properties[key] = _merge_property(properties[key], prop)
        if prop.client_id:
            keys_by_client_id[prop.client_id] = key
        if properties[key].client_id:
            keys_by_client_id[properties[key].client_id] = key
        keys_by_identity[_property_identity(properties[key])] = key
    return [properties[key] for key in order]


def _merge_property(
    left: PropertyCandidate,
    right: PropertyCandidate,
) -> PropertyCandidate:
    return PropertyCandidate(
        client_id=left.client_id or right.client_id,
        text=left.text or right.text,
        property_type=left.property_type or right.property_type,
        time=left.time or right.time,
        source=_merge_source(left.source, right.source),
        metadata=_merge_metadata(left.metadata, right.metadata),
    )


def _entity_ref(
    entity: EntityCandidate,
    *,
    fallback_source: SourceHint,
) -> EntityCandidate:
    return EntityCandidate(
        client_id=entity.client_id,
        name=entity.name,
        entity_type=entity.entity_type,
        identity_summary=entity.identity_summary,
        aliases=list(entity.aliases),
        properties=[],
        source=_merge_source(fallback_source, entity.source),
        metadata=dict(entity.metadata),
    )


def _property_key(
    prop: PropertyCandidate,
    keys_by_client_id: dict[str, _PropertyKey],
    keys_by_identity: dict[tuple[str, str], _PropertyKey],
) -> _PropertyKey:
    if prop.client_id and prop.client_id in keys_by_client_id:
        return keys_by_client_id[prop.client_id]
    identity = _property_identity(prop)
    if identity in keys_by_identity:
        return keys_by_identity[identity]
    if prop.client_id:
        return ("client_id", prop.client_id)
    return ("identity", "\x1f".join(identity))


def _entity_identity(entity: EntityCandidate) -> tuple[str, str]:
    return (_normalize_text(entity.name), _normalize_text(entity.entity_type or ""))


def _property_identity(prop: PropertyCandidate) -> tuple[str, str]:
    return (_normalize_text(prop.text), _normalize_text(prop.property_type or ""))


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def _merge_source(left: SourceHint, right: SourceHint) -> SourceHint:
    return SourceHint(
        source_message_ids=_merge_strings(
            left.source_message_ids,
            right.source_message_ids,
        ),
        source_quote=left.source_quote or right.source_quote,
    )


def _merge_metadata(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(right)
    metadata.update(left)
    return metadata


def _merge_strings(left: list[str], right: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*left, *right]:
        key = _normalize_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _prefer_text(left: str | None, right: str | None) -> str | None:
    if not left:
        return right
    if not right:
        return left
    return left if len(left) >= len(right) else right
