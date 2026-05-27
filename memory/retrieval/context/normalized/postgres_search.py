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
        if not terms:
            hits = self.ranker.rank(self._recent_hits(request, limit), request)[:limit]
            return MemorySearchResult(
                hits=hits,
                metadata={
                    "search": "postgres_normalized",
                    "strategy": "recent",
                    "hit_count": len(hits),
                },
            )

        hits: list[MemorySearchHit] = []
        hits.extend(
            self._search_table(
                table="memory_entities",
                object_type="entity",
                text_expression=(
                    "concat_ws(' ', name, entity_type, identity_summary, aliases::text)"
                ),
                base_score=1.0,
                reason="entity_text_match",
                request=request,
                terms=terms,
                status_column=None,
            )
        )
        hits.extend(
            self._search_table(
                table="memory_events",
                object_type="event",
                text_expression="concat_ws(' ', title, summary, event_type)",
                base_score=0.95,
                reason="event_text_match",
                request=request,
                terms=terms,
                status_column="status",
            )
        )
        hits.extend(
            self._search_table(
                table="memory_properties",
                object_type="property",
                text_expression="concat_ws(' ', content, property_type)",
                base_score=0.9,
                reason="property_text_match",
                request=request,
                terms=terms,
                status_column="status",
            )
        )
        hits.extend(
            self._search_table(
                table="memory_descriptions",
                object_type="description",
                text_expression="concat_ws(' ', content, description_type)",
                base_score=0.85,
                reason="description_text_match",
                request=request,
                terms=terms,
                status_column="status",
            )
        )
        selected = self.ranker.rank(hits, request)[:limit]
        return MemorySearchResult(
            hits=selected,
            metadata={
                "search": "postgres_normalized",
                "strategy": "lexical",
                "hit_count": len(selected),
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
            object_type="event",
            text_expression="concat_ws(' ', title, summary, event_type)",
            request=request,
            status_column="status",
            limit=limit,
        )
        entity_rows = self._recent_table_rows(
            table="memory_entities",
            object_type="entity",
            text_expression=(
                "concat_ws(' ', name, entity_type, identity_summary, aliases::text)"
            ),
            request=request,
            status_column=None,
            limit=limit,
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
        object_type: MemoryObjectType,
        text_expression: str,
        base_score: float,
        reason: str,
        request: MemorySearchRequest,
        terms: Sequence[str],
        status_column: str | None,
    ) -> list[MemorySearchHit]:
        conditions, params = _scope_conditions(request)
        if status_column is not None:
            conditions.insert(0, f"{status_column} = 'active'")
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
                id AS object_id,
                {text_expression} AS matched_text,
                user_id,
                session_id,
                confidence,
                importance,
                updated_at
            FROM {table}
            WHERE {where_sql}
            ORDER BY updated_at DESC, id ASC
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

    def _recent_table_rows(
        self,
        table: str,
        object_type: MemoryObjectType,
        text_expression: str,
        request: MemorySearchRequest,
        status_column: str | None,
        limit: int,
    ) -> list[Mapping[str, Any]]:
        conditions, params = _scope_conditions(request)
        if status_column is not None:
            conditions.insert(0, f"{status_column} = 'active'")
        where_sql = " AND ".join(conditions) if conditions else "TRUE"
        query = f"""
            SELECT
                %s AS object_type,
                id AS object_id,
                {text_expression} AS matched_text,
                user_id,
                session_id,
                confidence,
                importance,
                updated_at
            FROM {table}
            WHERE {where_sql}
            ORDER BY updated_at DESC, id ASC
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
    if request.user_id is not None or request.session_id is not None:
        conditions.append("(user_id IS NULL OR user_id = %s)")
        params.append(request.user_id)
        conditions.append("(session_id IS NULL OR session_id = %s)")
        params.append(request.session_id)
    return conditions, params


def _search_terms(query: str) -> list[str]:
    return [term for term in query.casefold().split() if term]


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
