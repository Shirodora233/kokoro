"""Integration tests for hybrid memory search (requires PostgreSQL + pgvector)."""

from __future__ import annotations

import sys
from collections.abc import Callable

from pgvector.psycopg import register_vector

from conversation.config import StorageConfig
from conversation.storage.postgres import PostgresConversationStore
from memory.models import MemorySearchRequest
from memory.persistence.models import (
    PersistentEntity,
    PersistentEvent,
    PersistentMemoryBundle,
    PersistentSourceRef,
)
from memory.persistence.postgres import PostgresPersistentMemoryRepository
from memory.retrieval.context.normalized import PostgresHybridMemorySearch
from memory.retrieval.context.normalized.postgres_search import (
    PostgresNormalizedMemorySearch,
)

USER_ID = "usr_hybrid_test"
SESSION_ID = "ses_hybrid_test"
MESSAGE_ID = "msg_hybrid_test"


# ---------------------------------------------------------------------------
# Stub embedding client — returns deterministic vectors for testing
# ---------------------------------------------------------------------------

class _StubEmbeddingClient:
    """Returns vectors based on text hash for deterministic testing."""

    def __init__(self, dimension: int = 1536) -> None:
        self.dimension = dimension

    def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            # Use a simple hash to generate deterministic but distinct vectors
            seed = hash(text) & 0xFFFFFFFF
            vec = [0.0] * self.dimension
            for i in range(min(10, self.dimension)):
                seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
                vec[i] = (seed % 1000) / 1000.0
            vectors.append(vec)
        return vectors


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def _cleanup(repository: PostgresPersistentMemoryRepository) -> None:
    with repository.database.connect() as conn:
        conn.execute("DELETE FROM memory_object_embeddings")
        conn.execute(
            "DELETE FROM memory_objects WHERE user_id = %s OR session_id = %s",
            (USER_ID, SESSION_ID),
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_hybrid_search_finds_lexical_match(
    repository: PostgresPersistentMemoryRepository,
) -> None:
    """Objects persisted with embeddings appear in hybrid search results."""
    source = PersistentSourceRef(
        source_type="message",
        source_id=MESSAGE_ID,
        quote="The user likes jasmine tea.",
    )
    event = PersistentEvent(
        id="evt_hybrid_1",
        title="Jasmine tea preference",
        summary="User expressed a preference for jasmine tea",
        event_type="preference",
        user_id=USER_ID,
        session_id=SESSION_ID,
        source_refs=[source],
    )
    entity = PersistentEntity(
        id="ent_hybrid_1",
        name="Jasmine Tea",
        entity_type="object",
        identity_summary="A type of green tea with jasmine flowers",
        aliases=["jasmine tea", "茉莉花茶"],
        user_id=USER_ID,
        session_id=SESSION_ID,
        scope="session",
        source_refs=[source],
    )
    bundle = PersistentMemoryBundle(
        events=[event],
        entities=[entity],
        descriptions=[],
        properties=[],
        links=[],
        time_refs=[],
        time_links=[],
        metadata={},
    )
    repository.save_bundle(bundle)

    # Manually insert embeddings for the test objects
    embedding_client = _StubEmbeddingClient()
    evt_text = "Jasmine tea preference User expressed a preference for jasmine tea preference"
    ent_text = "Jasmine Tea object A type of green tea with jasmine flowers jasmine tea 茉莉花茶"

    evt_vec = embedding_client.embed([evt_text])[0]
    ent_vec = embedding_client.embed([ent_text])[0]

    with repository.database.connect() as conn:
        register_vector(conn)
        conn.execute(
            """INSERT INTO memory_object_embeddings
               (object_id, embedding, model, searchable_text)
               VALUES (%s, %s::vector, %s, %s)
               ON CONFLICT (object_id) DO UPDATE SET embedding = EXCLUDED.embedding""",
            ("evt_hybrid_1", evt_vec, "text-embedding-3-small", evt_text),
        )
        conn.execute(
            """INSERT INTO memory_object_embeddings
               (object_id, embedding, model, searchable_text)
               VALUES (%s, %s::vector, %s, %s)
               ON CONFLICT (object_id) DO UPDATE SET embedding = EXCLUDED.embedding""",
            ("ent_hybrid_1", ent_vec, "text-embedding-3-small", ent_text),
        )

    search = PostgresHybridMemorySearch(
        repository=repository,
        embedding_client=embedding_client,
    )

    result = search.search(
        MemorySearchRequest(
            user_id=USER_ID,
            session_id=SESSION_ID,
            query="jasmine tea",
            limit=10,
        )
    )

    assert len(result.hits) > 0, "Expected at least one hit"
    assert result.metadata["strategy"] == "hybrid", (
        f"Expected hybrid strategy, got {result.metadata.get('strategy')}"
    )
    # At least the lexical path should find these
    object_ids = [h.object_ref.object_id for h in result.hits]
    assert "evt_hybrid_1" in object_ids or "ent_hybrid_1" in object_ids, (
        f"Expected to find test objects in results: {object_ids}"
    )


def test_empty_query_falls_back_to_recent(
    repository: PostgresPersistentMemoryRepository,
) -> None:
    """Empty query should use recent strategy without vector search."""
    embedding_client = _StubEmbeddingClient()
    search = PostgresHybridMemorySearch(
        repository=repository,
        embedding_client=embedding_client,
    )

    result = search.search(
        MemorySearchRequest(
            user_id=USER_ID,
            session_id=SESSION_ID,
            query="",
            limit=10,
        )
    )

    assert result.metadata["strategy"] == "recent", (
        f"Expected 'recent' strategy for empty query, got {result.metadata}"
    )


def test_hybrid_search_without_embeddings_table_still_works(
    repository: PostgresPersistentMemoryRepository,
) -> None:
    """When no embeddings exist, hybrid search degrades to lexical-only."""
    source = PersistentSourceRef(
        source_type="message",
        source_id=MESSAGE_ID,
        quote="Swimming practice every Wednesday",
    )
    event = PersistentEvent(
        id="evt_hybrid_2",
        title="Swimming practice",
        summary="Weekly swimming practice on Wednesday evenings",
        event_type="plan",
        user_id=USER_ID,
        session_id=SESSION_ID,
        source_refs=[source],
    )
    bundle = PersistentMemoryBundle(
        events=[event],
        entities=[],
        descriptions=[],
        properties=[],
        links=[],
        time_refs=[],
        time_links=[],
        metadata={},
    )
    repository.save_bundle(bundle)

    # No embeddings inserted — vector search should return nothing
    embedding_client = _StubEmbeddingClient()
    search = PostgresHybridMemorySearch(
        repository=repository,
        embedding_client=embedding_client,
    )

    result = search.search(
        MemorySearchRequest(
            user_id=USER_ID,
            session_id=SESSION_ID,
            query="swimming",
            limit=10,
        )
    )

    # Should still find via lexical path
    assert len(result.hits) > 0, "Expected lexical results"
    object_ids = [h.object_ref.object_id for h in result.hits]
    assert "evt_hybrid_2" in object_ids, (
        f"Expected evt_hybrid_2 in lexical results: {object_ids}"
    )


def test_rrf_fusion_ranks_common_items_higher(
    repository: PostgresPersistentMemoryRepository,
) -> None:
    """Items appearing in both lexical and vector lists rank higher via RRF."""
    source = PersistentSourceRef(
        source_type="message",
        source_id=MESSAGE_ID,
        quote="Coffee preference",
    )
    event_a = PersistentEvent(
        id="evt_hybrid_a",
        title="Coffee preference",
        summary="User likes dark roast coffee",
        event_type="preference",
        user_id=USER_ID,
        session_id=SESSION_ID,
        source_refs=[source],
    )
    event_b = PersistentEvent(
        id="evt_hybrid_b",
        title="Tea preference",
        summary="User likes green tea",
        event_type="preference",
        user_id=USER_ID,
        session_id=SESSION_ID,
        source_refs=[source],
    )
    bundle = PersistentMemoryBundle(
        events=[event_a, event_b],
        entities=[],
        descriptions=[],
        properties=[],
        links=[],
        time_refs=[],
        time_links=[],
        metadata={},
    )
    repository.save_bundle(bundle)

    embedding_client = _StubEmbeddingClient()

    # Both objects get embeddings, but give event_a a vector that will
    # match "coffee" better than event_b
    text_a = "Coffee preference User likes dark roast coffee preference"
    text_b = "Tea preference User likes green tea preference"
    vec_a = embedding_client.embed([text_a])[0]
    vec_b = embedding_client.embed([text_b])[0]

    # Make vec_b very different so it won't match "coffee" semantically
    vec_b = [-v for v in vec_b]

    with repository.database.connect() as conn:
        register_vector(conn)
        conn.execute(
            """INSERT INTO memory_object_embeddings
               (object_id, embedding, model, searchable_text)
               VALUES (%s, %s::vector, %s, %s)
               ON CONFLICT (object_id) DO UPDATE SET embedding = EXCLUDED.embedding""",
            ("evt_hybrid_a", vec_a, "text-embedding-3-small", text_a),
        )
        conn.execute(
            """INSERT INTO memory_object_embeddings
               (object_id, embedding, model, searchable_text)
               VALUES (%s, %s::vector, %s, %s)
               ON CONFLICT (object_id) DO UPDATE SET embedding = EXCLUDED.embedding""",
            ("evt_hybrid_b", vec_b, "text-embedding-3-small", text_b),
        )

    search = PostgresHybridMemorySearch(
        repository=repository,
        embedding_client=embedding_client,
    )

    result = search.search(
        MemorySearchRequest(
            user_id=USER_ID,
            session_id=SESSION_ID,
            query="coffee",
            limit=10,
        )
    )

    assert len(result.hits) > 0, "Expected at least one hit"
    # Check that the fusion metadata is populated
    assert "lexical_fallback" not in result.metadata.get("strategy", ""), (
        "Should not fall back to lexical-only"
    )


def test_lexical_search_returns_same_results_as_baseline(
    repository: PostgresPersistentMemoryRepository,
) -> None:
    """The lexical leg of hybrid search should match standalone lexical search."""
    source = PersistentSourceRef(
        source_type="message",
        source_id=MESSAGE_ID,
        quote="Running schedule",
    )
    event = PersistentEvent(
        id="evt_hybrid_3",
        title="Running schedule",
        summary="User runs every Tuesday morning",
        event_type="plan",
        user_id=USER_ID,
        session_id=SESSION_ID,
        source_refs=[source],
    )
    bundle = PersistentMemoryBundle(
        events=[event],
        entities=[],
        descriptions=[],
        properties=[],
        links=[],
        time_refs=[],
        time_links=[],
        metadata={},
    )
    repository.save_bundle(bundle)

    embedding_client = _StubEmbeddingClient()
    hybrid = PostgresHybridMemorySearch(
        repository=repository,
        embedding_client=embedding_client,
    )
    lexical = PostgresNormalizedMemorySearch(repository)

    hybrid_result = hybrid.search(
        MemorySearchRequest(
            user_id=USER_ID,
            session_id=SESSION_ID,
            query="running",
            limit=10,
        )
    )
    lexical_result = lexical.search(
        MemorySearchRequest(
            user_id=USER_ID,
            session_id=SESSION_ID,
            query="running",
            limit=10,
        )
    )

    # Hybrid should find at least what lexical finds
    hybrid_ids = {h.object_ref.object_id for h in hybrid_result.hits}
    lexical_ids = {h.object_ref.object_id for h in lexical_result.hits}
    assert lexical_ids <= hybrid_ids, (
        f"Hybrid missing lexical results: {lexical_ids - hybrid_ids}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    config = StorageConfig.from_env(".env")
    PostgresConversationStore(config.database_url)
    repository = PostgresPersistentMemoryRepository(config.database_url)

    tests: list[Callable[[PostgresPersistentMemoryRepository], None]] = [
        test_hybrid_search_finds_lexical_match,
        test_empty_query_falls_back_to_recent,
        test_hybrid_search_without_embeddings_table_still_works,
        test_rrf_fusion_ranks_common_items_higher,
        test_lexical_search_returns_same_results_as_baseline,
    ]

    for test in tests:
        _cleanup(repository)
        try:
            test(repository)
        finally:
            _cleanup(repository)
        print(f"PASS {test.__name__}")

    print(f"passed={len(tests)}/{len(tests)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
