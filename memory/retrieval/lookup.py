"""Lookup boundary for normalized memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..persistence import PersistentMemoryRepository
from ..persistence.models import ObjectType, PersistentObjectRef


@dataclass(frozen=True)
class NormalizedMemoryLookupRequest:
    user_id: str | None = None
    session_id: str | None = None
    query: str | None = None
    limit: int = 20
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedMemoryLookupHit:
    object_ref: PersistentObjectRef
    score: float
    reason: str
    matched_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedMemoryLookupResult:
    hits: list[NormalizedMemoryLookupHit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class NormalizedMemoryLookup(Protocol):
    def lookup(
        self,
        request: NormalizedMemoryLookupRequest,
    ) -> NormalizedMemoryLookupResult:
        """Return normalized object refs that should be hydrated for prompting."""


class RepositoryNormalizedMemoryLookup:
    """Fallback lookup for repository implementations without native search.

    This keeps non-Postgres tests and stores usable. Production Postgres runtime
    should use a database-backed lookup so query filtering happens before view
    hydration.
    """

    def __init__(
        self,
        repository: PersistentMemoryRepository,
        pool_limit: int = 40,
    ) -> None:
        self.repository = repository
        self.pool_limit = pool_limit

    def lookup(
        self,
        request: NormalizedMemoryLookupRequest,
    ) -> NormalizedMemoryLookupResult:
        limit = max(0, request.limit or self.pool_limit)
        if limit == 0:
            return NormalizedMemoryLookupResult(
                metadata={"lookup": "repository", "hit_count": 0}
            )

        query = (request.query or "").casefold().strip()
        hits: list[NormalizedMemoryLookupHit] = []
        events = self.repository.list_events(
            user_id=request.user_id,
            session_id=request.session_id,
            limit=self.pool_limit,
        )
        entities = self.repository.list_entities(
            user_id=request.user_id,
            session_id=request.session_id,
            limit=self.pool_limit,
        )
        for event in events:
            text = _join_text(event.title, event.summary, event.event_type)
            if event.id and _matches_query(text, query):
                hits.append(
                    _hit(
                        object_type="event",
                        object_id=event.id,
                        score=0.8,
                        reason="repository_event_match",
                        matched_text=text,
                    )
                )

        descriptions = self.repository.list_descriptions(
            event_ids=[event.id for event in events if event.id],
        )
        for description in descriptions:
            text = _join_text(description.content, description.description_type)
            if description.id and _matches_query(text, query):
                hits.append(
                    _hit(
                        object_type="description",
                        object_id=description.id,
                        score=0.75,
                        reason="repository_description_match",
                        matched_text=text,
                    )
                )

        for entity in entities:
            text = _join_text(
                entity.name,
                entity.entity_type,
                entity.identity_summary,
                *entity.aliases,
            )
            if entity.id and _matches_query(text, query):
                hits.append(
                    _hit(
                        object_type="entity",
                        object_id=entity.id,
                        score=0.9,
                        reason="repository_entity_match",
                        matched_text=text,
                    )
                )

        properties = self.repository.list_properties(
            entity_ids=[entity.id for entity in entities if entity.id],
        )
        for memory_property in properties:
            text = _join_text(memory_property.content, memory_property.property_type)
            if memory_property.id and _matches_query(text, query):
                hits.append(
                    _hit(
                        object_type="property",
                        object_id=memory_property.id,
                        score=0.8,
                        reason="repository_property_match",
                        matched_text=text,
                    )
                )

        selected = _dedupe_hits(hits)[:limit]
        return NormalizedMemoryLookupResult(
            hits=selected,
            metadata={
                "lookup": "repository",
                "hit_count": len(selected),
                "query": request.query,
            },
        )


def _hit(
    object_type: ObjectType,
    object_id: str,
    score: float,
    reason: str,
    matched_text: str | None,
) -> NormalizedMemoryLookupHit:
    return NormalizedMemoryLookupHit(
        object_ref=PersistentObjectRef(object_type, object_id),
        score=score,
        reason=reason,
        matched_text=matched_text,
    )


def _matches_query(text: str, query: str) -> bool:
    return not query or query in text.casefold()


def _join_text(*values: str | None) -> str:
    return " ".join(value for value in values if value)


def _dedupe_hits(
    hits: list[NormalizedMemoryLookupHit],
) -> list[NormalizedMemoryLookupHit]:
    selected: dict[tuple[str, str], NormalizedMemoryLookupHit] = {}
    order: list[tuple[str, str]] = []
    for hit in sorted(hits, key=lambda item: item.score, reverse=True):
        key = (hit.object_ref.object_type, hit.object_ref.object_id)
        if key in selected:
            continue
        selected[key] = hit
        order.append(key)
    return [selected[key] for key in order]
