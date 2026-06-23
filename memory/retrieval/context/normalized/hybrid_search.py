"""Hybrid search combining lexical keyword + vector semantic search.

Uses Reciprocal Rank Fusion (RRF) by default to merge result sets
without requiring score calibration between the two search paths.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from pgvector.psycopg import register_vector

from llm.interfaces import EmbeddingClient

from ....models import (
    MemoryObjectRef,
    MemoryObjectType,
    MemorySearchHit,
    MemorySearchRequest,
    MemorySearchResult,
)
from ....persistence.postgres.repository import PostgresPersistentMemoryRepository
from .postgres_search import (
    PostgresNormalizedMemorySearch,
    build_scope_conditions,
    row_to_search_hit,
    search_terms_from_query,
)
from .ranking import NormalizedMemoryRanker

LOGGER = logging.getLogger(__name__)

# RRF constant — larger values reduce the influence of high-ranked items
_RRF_K = 60


class PostgresHybridMemorySearch:
    """Find normalized memory objects via lexical + vector hybrid search.

    Implements the NormalizedMemorySearch protocol (structural).
    """

    def __init__(
        self,
        repository: PostgresPersistentMemoryRepository,
        embedding_client: EmbeddingClient,
        lexical_search: PostgresNormalizedMemorySearch | None = None,
        embedding_model: str = "text-embedding-3-small",
        fusion_method: str = "rrf",
        vector_weight: float = 0.6,
        per_table_limit: int = 20,
        min_similarity: float = 0.7,
        ranker: NormalizedMemoryRanker | None = None,
    ) -> None:
        self.repository = repository
        self.embedding_client = embedding_client
        self.lexical_search = lexical_search or PostgresNormalizedMemorySearch(
            repository, per_table_limit=per_table_limit
        )
        self.embedding_model = embedding_model
        self.fusion_method = fusion_method
        self.vector_weight = vector_weight
        self.per_table_limit = per_table_limit
        self.min_similarity = min_similarity
        self.ranker = ranker or NormalizedMemoryRanker()

    def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        limit = max(0, request.limit)
        if limit == 0:
            return MemorySearchResult(
                metadata={"search": "hybrid", "hit_count": 0}
            )

        query = (request.query or "").strip()
        if not query:
            # No query → delegate to recent-hits path
            result = self.lexical_search.search(request)
            return MemorySearchResult(
                hits=result.hits,
                metadata={
                    **result.metadata,
                    "search": "hybrid",
                    "strategy": "recent",
                },
            )

        # Run lexical search
        lexical_result = self.lexical_search.search(
            MemorySearchRequest(
                user_id=request.user_id,
                session_id=request.session_id,
                query=request.query,
                timezone=request.timezone,
                candidates=request.candidates,
                active_memory_context=request.active_memory_context,
                limit=max(limit * 3, self.per_table_limit),
                metadata=dict(request.metadata),
            )
        )

        # Run vector search
        vector_hits: list[MemorySearchHit] = []
        strategy = "hybrid"
        try:
            vector_hits = self._vector_search(request, limit)
        except Exception:
            LOGGER.warning(
                "Vector search failed, falling back to lexical-only",
                exc_info=True,
            )
            strategy = "lexical_fallback"

        # Fuse results
        if vector_hits:
            fused = self._fuse(lexical_result.hits, vector_hits)
        else:
            fused = list(lexical_result.hits)

        # Apply ranking bonuses
        ranked = self.ranker.rank(fused, request)
        selected = ranked[:limit]

        return MemorySearchResult(
            hits=selected,
            metadata={
                "search": "hybrid",
                "strategy": strategy,
                "fusion": self.fusion_method,
                "hit_count": len(selected),
                "raw_lexical_count": len(lexical_result.hits),
                "raw_vector_count": len(vector_hits),
                "fused_count": len(fused),
                "ranked_count": len(ranked),
                "top_score": selected[0].score if selected else None,
                "query": request.query,
            },
        )

    # ------------------------------------------------------------------
    # Vector search
    # ------------------------------------------------------------------

    def _vector_search(
        self,
        request: MemorySearchRequest,
        limit: int,
    ) -> list[MemorySearchHit]:
        query = (request.query or "").strip()
        if not query:
            return []

        query_vector = self.embedding_client.embed(
            [query], model=self.embedding_model
        )[0]

        conditions, params = build_scope_conditions(request)
        conditions.insert(0, "o.status = 'active'")
        conditions.insert(0, "e.model = %s")
        params.insert(0, self.embedding_model)

        where_sql = " AND ".join(conditions) if conditions else "TRUE"
        per_table_limit = max(limit * 3, self.per_table_limit)

        sql = f"""
            SELECT
                o.object_type,
                o.id AS object_id,
                e.searchable_text AS matched_text,
                o.user_id,
                o.session_id,
                o.confidence,
                o.importance,
                o.updated_at,
                1.0 - (e.embedding <=> %s::vector) AS vector_score
            FROM memory_object_embeddings e
            JOIN memory_objects o ON o.id = e.object_id
            LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id
            WHERE {where_sql}
            ORDER BY e.embedding <=> %s::vector
            LIMIT %s
        """

        with self.repository.database.connect() as connection:
            register_vector(connection)
            rows = connection.execute(
                sql,
                (
                    query_vector,
                    *params,
                    query_vector,
                    per_table_limit,
                ),
            ).fetchall()

        terms = search_terms_from_query(query)
        hits: list[MemorySearchHit] = []
        dropped_below_threshold = 0
        for row in rows:
            similarity = float(row.get("vector_score", 0.0))
            if similarity < self.min_similarity:
                dropped_below_threshold += 1
                continue
            hit = row_to_search_hit(
                row,
                score=round(similarity, 4),
                reason="vector_similarity",
                match_quality="semantic",
                terms=terms,
            )
            hits.append(hit)
        if dropped_below_threshold:
            LOGGER.debug(
                "Vector search dropped %d hits below similarity %.2f",
                dropped_below_threshold,
                self.min_similarity,
            )
        return hits

    # ------------------------------------------------------------------
    # Score fusion
    # ------------------------------------------------------------------

    @staticmethod
    def _build_best_hits(
        lexical_hits: list[MemorySearchHit],
        vector_hits: list[MemorySearchHit],
    ) -> dict[tuple[str, str], MemorySearchHit]:
        """Build a deduplicated map from (object_type, object_id) to the
        best-scoring hit, preferring lexical hits in case of a tie."""
        best: dict[tuple[str, str], MemorySearchHit] = {}
        for hit in lexical_hits:
            key = (hit.object_ref.object_type, hit.object_ref.object_id)
            if key not in best or hit.score > best[key].score:
                best[key] = hit
        for hit in vector_hits:
            key = (hit.object_ref.object_type, hit.object_ref.object_id)
            if key not in best:
                best[key] = hit
        return best

    def _fuse(
        self,
        lexical_hits: list[MemorySearchHit],
        vector_hits: list[MemorySearchHit],
    ) -> list[MemorySearchHit]:
        if self.fusion_method == "weighted_sum":
            return self._fuse_weighted(lexical_hits, vector_hits)
        return self._fuse_rrf(lexical_hits, vector_hits)

    def _fuse_rrf(
        self,
        lexical_hits: list[MemorySearchHit],
        vector_hits: list[MemorySearchHit],
    ) -> list[MemorySearchHit]:
        """Reciprocal Rank Fusion — parameter-free merging of ranked lists."""
        # Compute ranks per list
        lex_ranks: dict[tuple[str, str], int] = {}
        for rank, hit in enumerate(lexical_hits):
            key = (hit.object_ref.object_type, hit.object_ref.object_id)
            if key not in lex_ranks:
                lex_ranks[key] = rank

        vec_ranks: dict[tuple[str, str], int] = {}
        for rank, hit in enumerate(vector_hits):
            key = (hit.object_ref.object_type, hit.object_ref.object_id)
            if key not in vec_ranks:
                vec_ranks[key] = rank

        # Collect all unique objects
        all_keys: set[tuple[str, str]] = set()
        all_keys.update(lex_ranks)
        all_keys.update(vec_ranks)

        best_hits = self._build_best_hits(lexical_hits, vector_hits)

        # Compute RRF scores
        scored: list[tuple[float, MemorySearchHit]] = []
        for key in all_keys:
            rrf = 0.0
            if key in lex_ranks:
                rrf += 1.0 / (_RRF_K + lex_ranks[key] + 1)
            if key in vec_ranks:
                rrf += 1.0 / (_RRF_K + vec_ranks[key] + 1)

            hit = best_hits[key]
            hit = replace(hit, score=round(rrf, 6))
            scored.append((rrf, hit))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [hit for _, hit in scored]

    def _fuse_weighted(
        self,
        lexical_hits: list[MemorySearchHit],
        vector_hits: list[MemorySearchHit],
    ) -> list[MemorySearchHit]:
        """Weighted sum fusion with min-max normalization per result set."""
        # Normalize lexical scores to [0, 1]
        lex_scores: dict[tuple[str, str], float] = {}
        if lexical_hits:
            lex_min = min(h.score for h in lexical_hits)
            lex_max = max(h.score for h in lexical_hits)
            lex_range = lex_max - lex_min or 1.0
            for hit in lexical_hits:
                key = (hit.object_ref.object_type, hit.object_ref.object_id)
                lex_scores[key] = (hit.score - lex_min) / lex_range

        # Normalize vector scores to [0, 1]
        vec_scores: dict[tuple[str, str], float] = {}
        if vector_hits:
            vec_min = min(h.score for h in vector_hits)
            vec_max = max(h.score for h in vector_hits)
            vec_range = vec_max - vec_min or 1.0
            for hit in vector_hits:
                key = (hit.object_ref.object_type, hit.object_ref.object_id)
                vec_scores[key] = (hit.score - vec_min) / vec_range

        # Collect all unique objects
        all_keys: set[tuple[str, str]] = set()
        all_keys.update(lex_scores)
        all_keys.update(vec_scores)

        best_hits = self._build_best_hits(lexical_hits, vector_hits)

        # Compute weighted scores
        w = self.vector_weight
        scored: list[tuple[float, MemorySearchHit]] = []
        for key in all_keys:
            lex_norm = lex_scores.get(key, 0.0)
            vec_norm = vec_scores.get(key, 0.0)
            combined = (1.0 - w) * lex_norm + w * vec_norm

            hit = best_hits[key]
            hit = replace(hit, score=round(combined, 6))
            scored.append((combined, hit))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [hit for _, hit in scored]
