"""PostgreSQL search for normalized memory context retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ....models import (
    MemoryObjectRef,
    MemoryObjectType,
    MemorySearchHit,
    MemorySearchRequest,
    MemorySearchResult,
)
from ....persistence.postgres.repository import PostgresPersistentMemoryRepository
from .ranking import NormalizedMemoryRanker


class PostgresNormalizedMemorySearch:
    """Find normalized memory object refs with database-side lexical filtering."""

    def __init__(
        self,
        repository: PostgresPersistentMemoryRepository,
        per_table_limit: int = 20,
        ranker: NormalizedMemoryRanker | None = None,
    ) -> None:
        self.repository = repository
        self.per_table_limit = per_table_limit
        self.ranker = ranker or NormalizedMemoryRanker()

    def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        limit = max(0, request.limit)
        if limit == 0:
            return MemorySearchResult(
                metadata={"search": "postgres_normalized", "hit_count": 0}
            )

        query = (request.query or "").strip()
        terms = _search_terms(query)
        as_of_checkpoint_id = _as_of_checkpoint_id(request)
        if as_of_checkpoint_id is not None:
            return self._search_as_of_checkpoint(
                request,
                as_of_checkpoint_id,
                terms,
                limit,
            )
        if not terms:
            recent_hits = self._recent_hits(request, limit)
            ranked_hits = self.ranker.rank(recent_hits, request)
            hits = ranked_hits[:limit]
            return MemorySearchResult(
                hits=hits,
                metadata={
                    "search": "postgres_normalized",
                    "strategy": "recent",
                    "hit_count": len(hits),
                    "raw_hit_count": len(recent_hits),
                    "ranked_hit_count": len(ranked_hits),
                },
            )

        hits: list[MemorySearchHit] = []
        entity_hits = self._search_table(
            table="memory_entities",
            table_alias="ent",
            object_type="entity",
            text_expression=(
                "concat_ws(' ', ent.name, ent.entity_type, "
                "ent.identity_summary, COALESCE(alias_text.aliases, ''))"
            ),
            base_score=1.0,
            reason="entity_text_match",
            request=request,
            terms=terms,
            extra_join=(
                "LEFT JOIN ("
                "SELECT entity_id, string_agg(alias, ' ' ORDER BY position) AS aliases "
                "FROM memory_entity_aliases GROUP BY entity_id"
                ") alias_text ON alias_text.entity_id = ent.id"
            ),
        )
        event_hits = self._search_table(
            table="memory_events",
            table_alias="e",
            object_type="event",
            text_expression="concat_ws(' ', e.title, e.summary, e.event_type)",
            base_score=0.95,
            reason="event_text_match",
            request=request,
            terms=terms,
        )
        property_hits = self._search_table(
            table="memory_properties",
            table_alias="p",
            object_type="property",
            text_expression="concat_ws(' ', p.content, p.property_type)",
            base_score=0.9,
            reason="property_text_match",
            request=request,
            terms=terms,
        )
        description_hits = self._search_table(
            table="memory_descriptions",
            table_alias="d",
            object_type="description",
            text_expression="concat_ws(' ', d.content, d.description_type)",
            base_score=0.85,
            reason="description_text_match",
            request=request,
            terms=terms,
        )
        hits.extend([*entity_hits, *event_hits, *property_hits, *description_hits])
        ranked_hits = self.ranker.rank(hits, request)
        selected = ranked_hits[:limit]
        return MemorySearchResult(
            hits=selected,
            metadata={
                "search": "postgres_normalized",
                "strategy": "lexical",
                "hit_count": len(selected),
                "raw_hit_count": len(hits),
                "ranked_hit_count": len(ranked_hits),
                "raw_hit_counts": {
                    "entity": len(entity_hits),
                    "event": len(event_hits),
                    "property": len(property_hits),
                    "description": len(description_hits),
                },
                "top_score": selected[0].score if selected else None,
                "query": request.query,
                "terms": terms,
            },
        )

    def _recent_hits(
        self,
        request: MemorySearchRequest,
        limit: int,
    ) -> list[MemorySearchHit]:
        event_rows = self._recent_table_rows(
            table="memory_events",
            table_alias="e",
            object_type="event",
            text_expression="concat_ws(' ', e.title, e.summary, e.event_type)",
            request=request,
            limit=limit,
        )
        entity_rows = self._recent_table_rows(
            table="memory_entities",
            table_alias="ent",
            object_type="entity",
            text_expression=(
                "concat_ws(' ', ent.name, ent.entity_type, "
                "ent.identity_summary, COALESCE(alias_text.aliases, ''))"
            ),
            request=request,
            limit=limit,
            extra_join=(
                "LEFT JOIN ("
                "SELECT entity_id, string_agg(alias, ' ' ORDER BY position) AS aliases "
                "FROM memory_entity_aliases GROUP BY entity_id"
                ") alias_text ON alias_text.entity_id = ent.id"
            ),
        )
        rows = sorted(
            [*event_rows, *entity_rows],
            key=lambda row: row.get("updated_at"),
            reverse=True,
        )
        return [
            _row_to_hit(
                row,
                score=0.5,
                reason="recent_normalized_memory",
                match_quality="recent",
            )
            for row in rows[:limit]
        ]

    def _search_table(
        self,
        table: str,
        table_alias: str,
        object_type: MemoryObjectType,
        text_expression: str,
        base_score: float,
        reason: str,
        request: MemorySearchRequest,
        terms: Sequence[str],
        extra_join: str = "",
    ) -> list[MemorySearchHit]:
        conditions, params = _scope_conditions(request)
        conditions.insert(0, "o.status = 'active'")
        conditions.insert(0, "o.object_type = %s")
        params.insert(0, _object_type_for_search(object_type))
        term_conditions: list[str] = []
        for term in terms:
            term_conditions.append(f"strpos(lower({text_expression}), %s) > 0")
            params.append(term)
        if term_conditions:
            conditions.append("(" + " OR ".join(term_conditions) + ")")
        where_sql = " AND ".join(conditions) if conditions else "TRUE"
        per_table_limit = max(request.limit, self.per_table_limit)
        query = f"""
            SELECT
                %s AS object_type,
                {table_alias}.id AS object_id,
                {text_expression} AS matched_text,
                o.user_id,
                o.session_id,
                o.confidence,
                o.importance,
                o.updated_at
            FROM {table} {table_alias}
            JOIN memory_objects o ON o.id = {table_alias}.id
            LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id
            {extra_join}
            WHERE {where_sql}
            ORDER BY o.updated_at DESC, {table_alias}.id ASC
            LIMIT %s
        """
        with self.repository.database.connect() as connection:
            rows = connection.execute(
                query,
                (object_type, *params, per_table_limit),
            ).fetchall()
        return [
            _row_to_hit(
                row,
                score=base_score,
                reason=reason,
                match_quality=_match_quality(row["matched_text"], terms),
                terms=terms,
            )
            for row in rows
        ]

    def _search_as_of_checkpoint(
        self,
        request: MemorySearchRequest,
        checkpoint_id: str,
        terms: Sequence[str],
        limit: int,
    ) -> MemorySearchResult:
        raw_hits: list[MemorySearchHit] = []
        raw_hits.extend(
            self._hits_from_entities(
                self.repository.list_entities(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    as_of_checkpoint_id=checkpoint_id,
                ),
                terms,
            )
        )
        raw_hits.extend(
            self._hits_from_events(
                self.repository.list_events(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    as_of_checkpoint_id=checkpoint_id,
                ),
                terms,
            )
        )
        raw_hits.extend(
            self._hits_from_properties(
                self.repository.list_properties(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    as_of_checkpoint_id=checkpoint_id,
                ),
                terms,
            )
        )
        raw_hits.extend(
            self._hits_from_descriptions(
                self.repository.list_descriptions(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    as_of_checkpoint_id=checkpoint_id,
                ),
                terms,
            )
        )
        ranked_hits = self.ranker.rank(raw_hits, request)
        hits = ranked_hits[:limit]
        return MemorySearchResult(
            hits=hits,
            metadata={
                "search": "postgres_normalized",
                "strategy": "as_of_checkpoint",
                "as_of_checkpoint_id": checkpoint_id,
                "hit_count": len(hits),
                "raw_hit_count": len(raw_hits),
                "ranked_hit_count": len(ranked_hits),
                "query": request.query,
                "terms": list(terms),
            },
        )

    def _hits_from_entities(self, entities, terms: Sequence[str]) -> list[MemorySearchHit]:
        hits: list[MemorySearchHit] = []
        for entity in entities:
            text = " ".join(
                part
                for part in [
                    entity.name,
                    entity.entity_type,
                    entity.identity_summary or "",
                    " ".join(entity.aliases),
                ]
                if part
            )
            if terms and not _text_matches_terms(text, terms):
                continue
            hits.append(
                MemorySearchHit(
                    object_ref=MemoryObjectRef("entity", entity.id or ""),
                    score=1.0,
                    reason="entity_text_match",
                    matched_text=text,
                    metadata={
                        "match_quality": _match_quality(text, terms),
                        "confidence": entity.confidence,
                        "importance": entity.importance,
                    },
                )
            )
        return hits

    def _hits_from_events(self, events, terms: Sequence[str]) -> list[MemorySearchHit]:
        hits: list[MemorySearchHit] = []
        for event in events:
            text = " ".join(
                part
                for part in [event.title, event.summary or "", event.event_type or ""]
                if part
            )
            if terms and not _text_matches_terms(text, terms):
                continue
            hits.append(
                MemorySearchHit(
                    object_ref=MemoryObjectRef("event", event.id or ""),
                    score=0.95,
                    reason="event_text_match",
                    matched_text=text,
                    metadata={
                        "match_quality": _match_quality(text, terms),
                        "confidence": event.confidence,
                        "importance": event.importance,
                    },
                )
            )
        return hits

    def _hits_from_properties(
        self,
        properties,
        terms: Sequence[str],
    ) -> list[MemorySearchHit]:
        hits: list[MemorySearchHit] = []
        for memory_property in properties:
            text = " ".join(
                part
                for part in [
                    memory_property.content,
                    memory_property.property_type or "",
                ]
                if part
            )
            if terms and not _text_matches_terms(text, terms):
                continue
            hits.append(
                MemorySearchHit(
                    object_ref=MemoryObjectRef("property", memory_property.id or ""),
                    score=0.9,
                    reason="property_text_match",
                    matched_text=text,
                    metadata={
                        "match_quality": _match_quality(text, terms),
                        "confidence": memory_property.confidence,
                        "importance": memory_property.importance,
                    },
                )
            )
        return hits

    def _hits_from_descriptions(
        self,
        descriptions,
        terms: Sequence[str],
    ) -> list[MemorySearchHit]:
        hits: list[MemorySearchHit] = []
        for description in descriptions:
            text = " ".join(
                part
                for part in [
                    description.content,
                    description.description_type or "",
                ]
                if part
            )
            if terms and not _text_matches_terms(text, terms):
                continue
            hits.append(
                MemorySearchHit(
                    object_ref=MemoryObjectRef("description", description.id or ""),
                    score=0.85,
                    reason="description_text_match",
                    matched_text=text,
                    metadata={
                        "match_quality": _match_quality(text, terms),
                        "confidence": description.confidence,
                        "importance": description.importance,
                    },
                )
            )
        return hits

    def _recent_table_rows(
        self,
        table: str,
        table_alias: str,
        object_type: MemoryObjectType,
        text_expression: str,
        request: MemorySearchRequest,
        limit: int,
        extra_join: str = "",
    ) -> list[Mapping[str, Any]]:
        conditions, params = _scope_conditions(request)
        conditions.insert(0, "o.status = 'active'")
        conditions.insert(0, "o.object_type = %s")
        params.insert(0, _object_type_for_search(object_type))
        where_sql = " AND ".join(conditions) if conditions else "TRUE"
        query = f"""
            SELECT
                %s AS object_type,
                {table_alias}.id AS object_id,
                {text_expression} AS matched_text,
                o.user_id,
                o.session_id,
                o.confidence,
                o.importance,
                o.updated_at
            FROM {table} {table_alias}
            JOIN memory_objects o ON o.id = {table_alias}.id
            LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id
            {extra_join}
            WHERE {where_sql}
            ORDER BY o.updated_at DESC, {table_alias}.id ASC
            LIMIT %s
        """
        with self.repository.database.connect() as connection:
            return connection.execute(
                query,
                (object_type, *params, limit),
            ).fetchall()


def _scope_conditions(request: MemorySearchRequest) -> tuple[list[str], list[object]]:
    conditions: list[str] = []
    params: list[object] = []
    visible_scopes = _visible_session_scopes(request)
    if request.user_id is not None or request.session_id is not None:
        conditions.append("(o.user_id IS NULL OR o.user_id = %s)")
        params.append(request.user_id)
        if visible_scopes:
            session_conditions = ["o.session_id IS NULL"]
            for scope in visible_scopes:
                scoped_session_id = scope.get("session_id")
                max_sequence = scope.get("max_checkpoint_sequence")
                if not isinstance(scoped_session_id, str):
                    continue
                if isinstance(max_sequence, int):
                    session_conditions.append(
                        """
                        (
                          o.session_id = %s
                          AND (
                            o.created_checkpoint_id IS NULL
                            OR cp.sequence <= %s
                          )
                        )
                        """
                    )
                    params.extend([scoped_session_id, max_sequence])
                else:
                    session_conditions.append("o.session_id = %s")
                    params.append(scoped_session_id)
            conditions.append("(" + " OR ".join(session_conditions) + ")")
        else:
            conditions.append("(o.session_id IS NULL OR o.session_id = %s)")
            params.append(request.session_id)
    return conditions, params


def _visible_session_scopes(
    request: MemorySearchRequest,
) -> list[Mapping[str, Any]]:
    raw = request.metadata.get("visible_session_scopes")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _as_of_checkpoint_id(request: MemorySearchRequest) -> str | None:
    value = request.metadata.get("as_of_checkpoint_id")
    if isinstance(value, str) and value:
        return value
    value = request.metadata.get("base_checkpoint_id")
    if isinstance(value, str) and value:
        return value
    for scope in reversed(_visible_session_scopes(request)):
        scope_value = scope.get("as_of_checkpoint_id")
        if isinstance(scope_value, str) and scope_value:
            return scope_value
    return None


def _search_terms(query: str) -> list[str]:
    return [term for term in query.casefold().split() if term]


def _text_matches_terms(text: str | None, terms: Sequence[str]) -> bool:
    if not terms:
        return True
    normalized = (text or "").casefold()
    return any(term in normalized for term in terms)


def _object_type_for_search(object_type: MemoryObjectType) -> str:
    return "relation" if object_type == "link" else object_type


def _match_quality(text: str | None, terms: Sequence[str]) -> str:
    if not text:
        return "term"
    normalized = text.casefold()
    phrase = " ".join(terms)
    if normalized.strip() == phrase:
        return "exact"
    if phrase and phrase in normalized:
        return "phrase"
    if terms and all(term in normalized for term in terms):
        return "all_terms"
    if terms and any(term in normalized for term in terms):
        return "term"
    return "term"


def _row_to_hit(
    row: Mapping[str, Any],
    score: float,
    reason: str,
    match_quality: str,
    terms: Sequence[str] | None = None,
) -> MemorySearchHit:
    metadata: dict[str, Any] = {"match_quality": match_quality}
    updated_at = row.get("updated_at")
    if updated_at is not None:
        metadata["updated_at"] = str(updated_at)
    for key in ("user_id", "session_id", "confidence", "importance"):
        value = row.get(key)
        if value is not None:
            metadata[key] = value
    if terms:
        metadata["terms"] = list(terms)
    return MemorySearchHit(
        object_ref=MemoryObjectRef(
            object_type=row["object_type"],
            object_id=row["object_id"],
        ),
        score=score,
        reason=reason,
        matched_text=row.get("matched_text"),
        record=None,
        metadata=metadata,
    )
