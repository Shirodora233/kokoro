"""PostgreSQL search for normalized memory context retrieval.

Lexical search now computes a relevance score per row instead of ordering
by updated_at alone.  Each matched term contributes to the score, with
bonuses for phrase-level matches (the full query string appearing in the
text) and for primary-query terms vs. candidate/context hint terms.

When the pg_trgm extension is available, trigram similarity provides
fuzzy matching for entity names and short queries; the system falls back
gracefully when it is not installed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from ....models import (
    MemoryObjectRef,
    MemoryObjectType,
    SearchQuery,
    MemorySearchHit,
    MemorySearchRequest,
    MemorySearchResult,
)
from ....persistence.postgres.repository import PostgresPersistentMemoryRepository
from .ranking import NormalizedMemoryRanker

LOGGER = logging.getLogger(__name__)

# Minimum term length for lexical matching (shorter terms are too noisy)
_MIN_TERM_LENGTH = 2

# Stopwords that don't add signal for substring matching
_STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "shall",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "and", "or", "not", "but", "if", "so", "as", "it", "its",
    "this", "that", "these", "those", "i", "me", "my", "we", "our",
    "you", "your", "he", "she", "they", "them", "what", "which",
    "who", "whom", "how", "when", "where", "about", "into", "over",
    "after", "before", "between", "under", "again", "further",
    "then", "once", "here", "there", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such", "no",
    "only", "own", "same", "than", "too", "very", "just",
}


class PostgresNormalizedMemorySearch:
    """Find normalized memory object refs with database-side lexical filtering.

    Uses term-level scoring with optional trigram similarity for fuzzy
    entity-name matching.
    """

    def __init__(
        self,
        repository: PostgresPersistentMemoryRepository,
        per_table_limit: int = 20,
        ranker: NormalizedMemoryRanker | None = None,
        use_trigram: bool = True,
        require_all_terms: bool = False,
        min_term_length: int = _MIN_TERM_LENGTH,
    ) -> None:
        self.repository = repository
        self.per_table_limit = per_table_limit
        self.ranker = ranker or NormalizedMemoryRanker()
        self.use_trigram = use_trigram
        self.require_all_terms = require_all_terms
        self.min_term_length = max(1, min_term_length)
        self._trigram_available: bool | None = None

    # ------------------------------------------------------------------
    # Public search entry point
    # ------------------------------------------------------------------

    def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        limit = max(0, request.limit)
        if limit == 0:
            return MemorySearchResult(
                metadata={"search": "postgres_normalized", "hit_count": 0}
            )

        query = (request.query or "").strip()
        structured = request.structured_query
        terms = search_terms_from_query(
            query, min_length=self.min_term_length
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

        # Extract weighted term groups from the structured query
        primary_terms = _primary_terms(structured, self.min_term_length)
        hint_terms = _hint_terms(structured, self.min_term_length)
        all_terms = list(dict.fromkeys([*primary_terms, *hint_terms]))

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
            all_terms=all_terms,
            primary_terms=primary_terms,
            hint_terms=hint_terms,
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
            all_terms=all_terms,
            primary_terms=primary_terms,
            hint_terms=hint_terms,
        )
        property_hits = self._search_table(
            table="memory_properties",
            table_alias="p",
            object_type="property",
            text_expression="concat_ws(' ', p.content, p.property_type)",
            base_score=0.9,
            reason="property_text_match",
            request=request,
            all_terms=all_terms,
            primary_terms=primary_terms,
            hint_terms=hint_terms,
        )
        description_hits = self._search_table(
            table="memory_descriptions",
            table_alias="d",
            object_type="description",
            text_expression="concat_ws(' ', d.content, d.description_type)",
            base_score=0.85,
            reason="description_text_match",
            request=request,
            all_terms=all_terms,
            primary_terms=primary_terms,
            hint_terms=hint_terms,
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
                "terms": all_terms,
            },
        )

    # ------------------------------------------------------------------
    # Recent hits (no-query path)
    # ------------------------------------------------------------------

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
            row_to_search_hit(
                row,
                score=0.5,
                reason="recent_normalized_memory",
                match_quality="recent",
            )
            for row in rows[:limit]
        ]

    # ------------------------------------------------------------------
    # Core table search with score-based ordering
    # ------------------------------------------------------------------

    def _search_table(
        self,
        table: str,
        table_alias: str,
        object_type: MemoryObjectType,
        text_expression: str,
        base_score: float,
        reason: str,
        request: MemorySearchRequest,
        all_terms: Sequence[str],
        primary_terms: Sequence[str],
        hint_terms: Sequence[str],
        extra_join: str = "",
    ) -> list[MemorySearchHit]:
        conditions, params = build_scope_conditions(request)
        conditions.insert(0, "o.status = 'active'")
        conditions.insert(0, "o.object_type = %s")
        params.insert(0, _object_type_for_search(object_type))

        # Build scored term conditions
        score_parts: list[str] = []
        query_phrase = " ".join(all_terms).strip()

        # Phrase bonus: full query appears as a contiguous substring
        if query_phrase:
            conditions.append(
                f"strpos(lower({text_expression}), %s) > 0"
            )
            params.append(query_phrase)
            score_parts.append(
                f"CASE WHEN strpos(lower({text_expression}), %s) > 0 "
                f"THEN 3.0 ELSE 0.0 END"
            )
            params.append(query_phrase)

        # Per-term scoring — primary terms weighted higher than hint terms
        primary_list = list(primary_terms)
        hint_list = [t for t in hint_terms if t not in set(primary_list)]

        term_score_exprs: list[str] = []
        for term in primary_list:
            term_score_exprs.append(
                f"CASE WHEN strpos(lower({text_expression}), %s) > 0 "
                f"THEN 1.0 ELSE 0.0 END"
            )
            params.append(term)
        for term in hint_list:
            term_score_exprs.append(
                f"CASE WHEN strpos(lower({text_expression}), %s) > 0 "
                f"THEN 0.4 ELSE 0.0 END"
            )
            params.append(term)

        if term_score_exprs:
            score_parts.append("(" + " + ".join(term_score_exprs) + ")")

        # Require at least one term or phrase to match
        if self.require_all_terms:
            for term in all_terms:
                conditions.append(
                    f"strpos(lower({text_expression}), %s) > 0"
                )
                params.append(term)

        # Optional trigram similarity bonus (fuzzy matching)
        trigram_expr = ""
        if self.use_trigram and self._check_trigram():
            trigram_expr = (
                f" + COALESCE(similarity(lower({text_expression}), %s), 0.0) * 2.0"
            )
            params.append(query_phrase)

        lexical_score = (
            "(" + " + ".join(score_parts) + trigram_expr + ")"
            if score_parts
            else "0.0"
        )

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
                o.updated_at,
                {lexical_score} AS lexical_score
            FROM {table} {table_alias}
            JOIN memory_objects o ON o.id = {table_alias}.id
            LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id
            {extra_join}
            WHERE {where_sql}
            ORDER BY lexical_score DESC, o.updated_at DESC, {table_alias}.id ASC
            LIMIT %s
        """
        with self.repository.database.connect() as connection:
            rows = connection.execute(
                query,
                (object_type, *params, per_table_limit),
            ).fetchall()

        return [
            row_to_search_hit(
                row,
                score=round(
                    base_score + float(row.get("lexical_score", 0.0)) * 0.02, 4
                ),
                reason=reason,
                match_quality=match_quality_for_terms(
                    row["matched_text"], all_terms
                ),
                terms=all_terms,
            )
            for row in rows
            if float(row.get("lexical_score", 0.0)) > 0
        ]

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
        conditions, params = build_scope_conditions(request)
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

    def _check_trigram(self) -> bool:
        """Check whether pg_trgm is available (cached)."""
        if self._trigram_available is not None:
            return self._trigram_available
        try:
            with self.repository.database.connect() as connection:
                row = connection.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"
                ).fetchone()
                self._trigram_available = row is not None
        except Exception:
            self._trigram_available = False
        return self._trigram_available


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def build_scope_conditions(request: MemorySearchRequest) -> tuple[list[str], list[object]]:
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


def _primary_terms(
    structured: SearchQuery | None,
    min_length: int,
) -> list[str]:
    """Extract primary query terms (user's current message)."""
    if structured is None or not structured.primary.strip():
        return []
    return [
        term for term in structured.primary.casefold().split()
        if len(term) >= min_length and term not in _STOP_WORDS
    ]


def _hint_terms(
    structured: SearchQuery | None,
    min_length: int,
) -> list[str]:
    """Extract hint terms (candidates + active context)."""
    if structured is None:
        return []
    raw = " ".join(
        [*structured.candidate_hints, *structured.context_hints]
    )
    if not raw.strip():
        return []
    seen: set[str] = set()
    result: list[str] = []
    for term in raw.casefold().split():
        if len(term) >= min_length and term not in _STOP_WORDS:
            if term not in seen:
                seen.add(term)
                result.append(term)
    return result


def search_terms_from_query(
    query: str,
    min_length: int = _MIN_TERM_LENGTH,
) -> list[str]:
    """Split query into meaningful search terms, filtering noise."""
    return [
        term for term in query.casefold().split()
        if len(term) >= min_length and term not in _STOP_WORDS
    ]


def _object_type_for_search(object_type: MemoryObjectType) -> str:
    return "relation" if object_type == "link" else object_type


def match_quality_for_terms(text: str | None, terms: Sequence[str]) -> str:
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


def row_to_search_hit(
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
