"""Search boundary for normalized memory context retrieval."""

from __future__ import annotations

from typing import Any, Protocol

from ....models import (
    MemoryObjectRef,
    MemoryObjectType,
    MemorySearchHit,
    MemorySearchRequest,
    MemorySearchResult,
)
from ....persistence import PersistentMemoryRepository
from .ranking import NormalizedMemoryRanker


class NormalizedMemorySearch(Protocol):
    def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        """Return normalized object refs that should be hydrated for prompting."""


class FallbackNormalizedMemorySearch:
    """Fallback search for repositories without native search.

    This keeps non-Postgres tests and stores usable. Production PostgreSQL
    runtime should use `PostgresNormalizedMemorySearch` so filtering happens in
    the database before hydration.
    """

    def __init__(
        self,
        repository: PersistentMemoryRepository,
        pool_limit: int = 40,
        ranker: NormalizedMemoryRanker | None = None,
    ) -> None:
        self.repository = repository
        self.pool_limit = pool_limit
        self.ranker = ranker or NormalizedMemoryRanker()

    def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        limit = max(0, request.limit or self.pool_limit)
        if limit == 0:
            return MemorySearchResult(
                metadata={"search": "fallback_normalized", "hit_count": 0}
            )

        query = (request.query or "").casefold().strip()
        hits: list[MemorySearchHit] = []
        raw_hit_counts = {
            "event": 0,
            "description": 0,
            "entity": 0,
            "property": 0,
        }
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
                raw_hit_counts["event"] += 1
                hits.append(
                    _hit(
                        object_type="event",
                        object_id=event.id,
                        score=0.8,
                        reason="fallback_event_match",
                        matched_text=text,
                        metadata={
                            "match_quality": _match_quality(text, query),
                            "user_id": event.user_id,
                            "session_id": event.session_id,
                            "importance": event.importance,
                            "confidence": event.confidence,
                        },
                    )
                )

        descriptions = self.repository.list_descriptions(
            event_ids=[event.id for event in events if event.id],
        )
        for description in descriptions:
            text = _join_text(description.content, description.description_type)
            if description.id and _matches_query(text, query):
                raw_hit_counts["description"] += 1
                hits.append(
                    _hit(
                        object_type="description",
                        object_id=description.id,
                        score=0.75,
                        reason="fallback_description_match",
                        matched_text=text,
                        metadata={
                            "match_quality": _match_quality(text, query),
                            "user_id": description.user_id,
                            "session_id": description.session_id,
                            "importance": description.importance,
                            "confidence": description.confidence,
                        },
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
                raw_hit_counts["entity"] += 1
                hits.append(
                    _hit(
                        object_type="entity",
                        object_id=entity.id,
                        score=0.9,
                        reason="fallback_entity_match",
                        matched_text=text,
                        metadata={
                            "match_quality": _match_quality(text, query),
                            "user_id": entity.user_id,
                            "session_id": entity.session_id,
                            "importance": entity.importance,
                            "confidence": entity.confidence,
                        },
                    )
                )

        properties = self.repository.list_properties(
            entity_ids=[entity.id for entity in entities if entity.id],
        )
        for memory_property in properties:
            text = _join_text(memory_property.content, memory_property.property_type)
            if memory_property.id and _matches_query(text, query):
                raw_hit_counts["property"] += 1
                hits.append(
                    _hit(
                        object_type="property",
                        object_id=memory_property.id,
                        score=0.8,
                        reason="fallback_property_match",
                        matched_text=text,
                        metadata={
                            "match_quality": _match_quality(text, query),
                            "user_id": memory_property.user_id,
                            "session_id": memory_property.session_id,
                            "importance": memory_property.importance,
                            "confidence": memory_property.confidence,
                        },
                    )
                )

        ranked = self.ranker.rank(hits, request)
        selected = ranked[:limit]
        return MemorySearchResult(
            hits=selected,
            metadata={
                "search": "fallback_normalized",
                "hit_count": len(selected),
                "raw_hit_count": len(hits),
                "ranked_hit_count": len(ranked),
                "raw_hit_counts": raw_hit_counts,
                "query": request.query,
            },
        )


def _hit(
    object_type: MemoryObjectType,
    object_id: str,
    score: float,
    reason: str,
    matched_text: str | None,
    metadata: dict[str, Any] | None = None,
) -> MemorySearchHit:
    return MemorySearchHit(
        object_ref=MemoryObjectRef(object_type, object_id),
        score=score,
        reason=reason,
        matched_text=matched_text,
        metadata=dict(metadata or {}),
    )


def _matches_query(text: str, query: str) -> bool:
    normalized = text.casefold().strip()
    if not query:
        return True
    return bool(normalized) and (query in normalized or normalized in query)


def _match_quality(text: str, query: str) -> str:
    if not query:
        return "recent"
    normalized = text.casefold()
    if normalized.strip() == query:
        return "exact"
    if query in normalized:
        return "phrase"
    terms = [term for term in query.split() if term]
    if terms and all(term in normalized for term in terms):
        return "all_terms"
    if terms and any(term in normalized for term in terms):
        return "term"
    return "term"


def _join_text(*values: str | None) -> str:
    return " ".join(value for value in values if value)
