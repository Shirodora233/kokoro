"""PostgreSQL lookup for normalized memory retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...persistence.models import ObjectType, PersistentObjectRef
from ...retrieval.lookup import (
    NormalizedMemoryLookupHit,
    NormalizedMemoryLookupRequest,
    NormalizedMemoryLookupResult,
)
from .repository import PostgresPersistentMemoryRepository


class PostgresNormalizedMemoryLookup:
    """Find normalized memory object refs with database-side lexical filtering."""

    def __init__(
        self,
        repository: PostgresPersistentMemoryRepository,
        per_table_limit: int = 20,
    ) -> None:
        self.repository = repository
        self.per_table_limit = per_table_limit

    def lookup(
        self,
        request: NormalizedMemoryLookupRequest,
    ) -> NormalizedMemoryLookupResult:
        limit = max(0, request.limit)
        if limit == 0:
            return NormalizedMemoryLookupResult(
                metadata={"lookup": "postgres_normalized", "hit_count": 0}
            )

        query = (request.query or "").strip()
        terms = _search_terms(query)
        if not terms:
            hits = self._recent_hits(request, limit)
            return NormalizedMemoryLookupResult(
                hits=hits,
                metadata={
                    "lookup": "postgres_normalized",
                    "strategy": "recent",
                    "hit_count": len(hits),
                },
            )

        hits = []
        hits.extend(
            self._lookup_table(
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
            self._lookup_table(
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
            self._lookup_table(
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
            self._lookup_table(
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
        selected = _dedupe_hits(hits)[:limit]
        return NormalizedMemoryLookupResult(
            hits=selected,
            metadata={
                "lookup": "postgres_normalized",
                "strategy": "lexical",
                "hit_count": len(selected),
                "query": request.query,
                "terms": terms,
            },
        )

    def _recent_hits(
        self,
        request: NormalizedMemoryLookupRequest,
        limit: int,
    ) -> list[NormalizedMemoryLookupHit]:
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
            _row_to_hit(row, score=0.5, reason="recent_normalized_memory")
            for row in rows[:limit]
        ]

    def _lookup_table(
        self,
        table: str,
        object_type: ObjectType,
        text_expression: str,
        base_score: float,
        reason: str,
        request: NormalizedMemoryLookupRequest,
        terms: Sequence[str],
        status_column: str | None,
    ) -> list[NormalizedMemoryLookupHit]:
        conditions, params = _scope_conditions(request)
        if status_column is not None:
            conditions.insert(0, f"{status_column} = 'active'")
        for term in terms:
            conditions.append(f"strpos(lower({text_expression}), %s) > 0")
            params.append(term)
        where_sql = " AND ".join(conditions) if conditions else "TRUE"
        per_table_limit = max(request.limit, self.per_table_limit)
        query = f"""
            SELECT
                %s AS object_type,
                id AS object_id,
                {text_expression} AS matched_text,
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
                score=_score_match(row["matched_text"], terms, base_score),
                reason=reason,
                terms=terms,
            )
            for row in rows
        ]

    def _recent_table_rows(
        self,
        table: str,
        object_type: ObjectType,
        text_expression: str,
        request: NormalizedMemoryLookupRequest,
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


def _scope_conditions(
    request: NormalizedMemoryLookupRequest,
) -> tuple[list[str], list[object]]:
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


def _score_match(
    text: str | None,
    terms: Sequence[str],
    base_score: float,
) -> float:
    if not text:
        return base_score
    normalized = text.casefold()
    exact_bonus = 0.1 if " ".join(terms) in normalized else 0.0
    coverage_bonus = min(len(terms), 5) * 0.01
    return base_score + exact_bonus + coverage_bonus


def _row_to_hit(
    row: Mapping[str, Any],
    score: float,
    reason: str,
    terms: Sequence[str] | None = None,
) -> NormalizedMemoryLookupHit:
    metadata: dict[str, Any] = {}
    updated_at = row.get("updated_at")
    if updated_at is not None:
        metadata["updated_at"] = str(updated_at)
    if terms:
        metadata["terms"] = list(terms)
    return NormalizedMemoryLookupHit(
        object_ref=PersistentObjectRef(
            object_type=row["object_type"],
            object_id=row["object_id"],
        ),
        score=score,
        reason=reason,
        matched_text=row.get("matched_text"),
        metadata=metadata,
    )


def _dedupe_hits(
    hits: list[NormalizedMemoryLookupHit],
) -> list[NormalizedMemoryLookupHit]:
    ranked = sorted(
        hits,
        key=lambda item: (
            item.score,
            item.metadata.get("updated_at", ""),
        ),
        reverse=True,
    )
    selected: dict[tuple[str, str], NormalizedMemoryLookupHit] = {}
    for hit in ranked:
        key = (hit.object_ref.object_type, hit.object_ref.object_id)
        if key not in selected:
            selected[key] = hit
    return list(selected.values())
