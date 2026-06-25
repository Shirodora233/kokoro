"""Fast deterministic tests for embedding service (no DB, no real LLM)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from llm.interfaces import EmbeddingClient
from memory.embedding.service import MemoryEmbeddingService
from memory.persistence.models import (
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentProperty,
)


# ---------------------------------------------------------------------------
# Stub embedding client for testing
# ---------------------------------------------------------------------------

class _StubEmbeddingClient:
    """Returns fixed-dimension vectors for testing."""

    def __init__(self, dimension: int = 4) -> None:
        self.dimension = dimension
        self.calls: list[tuple[list[str], str | None]] = []

    def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        self.calls.append((list(texts), model))
        return [[0.1 * (i + 1)] * self.dimension for i in range(len(texts))]


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_event(**kwargs: Any) -> PersistentEvent:
    defaults = {
        "id": "evt_1",
        "title": "Test Event",
        "summary": "A test summary",
        "event_type": "plan",
        "user_id": "u1",
        "session_id": "s1",
        "status": "active",
        "source_refs": [],
        "confidence": "medium",
        "importance": "medium",
        "created_turn_id": None,
        "created_checkpoint_id": None,
        "created_checkpoint_sequence": None,
        "metadata": {},
    }
    defaults.update(kwargs)
    return PersistentEvent(**defaults)


def _make_entity(**kwargs: Any) -> PersistentEntity:
    defaults = {
        "id": "ent_1",
        "name": "Test Entity",
        "entity_type": "person",
        "identity_summary": "A test person",
        "aliases": ["alias1", "alias2"],
        "user_id": "u1",
        "session_id": "s1",
        "scope": "session",
        "source_refs": [],
        "confidence": "medium",
        "importance": "medium",
        "created_turn_id": None,
        "created_checkpoint_id": None,
        "created_checkpoint_sequence": None,
        "metadata": {},
    }
    defaults.update(kwargs)
    return PersistentEntity(**defaults)


def _make_description(**kwargs: Any) -> PersistentDescription:
    defaults = {
        "id": "desc_1",
        "event_id": "evt_1",
        "content": "Test description content",
        "description_type": "detail",
        "user_id": "u1",
        "session_id": "s1",
        "source_refs": [],
        "confidence": "medium",
        "importance": "medium",
        "created_turn_id": None,
        "created_checkpoint_id": None,
        "created_checkpoint_sequence": None,
        "metadata": {},
    }
    defaults.update(kwargs)
    return PersistentDescription(**defaults)


def _make_property(**kwargs: Any) -> PersistentProperty:
    defaults = {
        "id": "prop_1",
        "entity_id": "ent_1",
        "content": "Test property content",
        "property_type": "preference",
        "user_id": "u1",
        "session_id": "s1",
        "source_refs": [],
        "confidence": "medium",
        "importance": "medium",
        "created_turn_id": None,
        "created_checkpoint_id": None,
        "created_checkpoint_sequence": None,
        "metadata": {},
    }
    defaults.update(kwargs)
    return PersistentProperty(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_build_searchable_text_event() -> None:
    event = _make_event(
        title="Swimming practice",
        summary="Every Wednesday evening",
        event_type="plan",
    )
    text = MemoryEmbeddingService.build_searchable_text(event)
    assert text == "Swimming practice Every Wednesday evening plan", f"Got: {text!r}"


def test_build_searchable_text_event_no_summary() -> None:
    event = _make_event(title="Simple event", summary=None, event_type=None)
    text = MemoryEmbeddingService.build_searchable_text(event)
    assert text == "Simple event", f"Got: {text!r}"


def test_build_searchable_text_entity() -> None:
    entity = _make_entity(
        name="Alice",
        entity_type="person",
        identity_summary="Software engineer",
        aliases=["alice_w", "awoo"],
    )
    text = MemoryEmbeddingService.build_searchable_text(entity)
    assert "Alice" in text
    assert "person" in text
    assert "Software engineer" in text
    assert "alice_w" in text
    assert "awoo" in text


def test_build_searchable_text_entity_no_extras() -> None:
    entity = _make_entity(
        name="Bob",
        entity_type="unknown",
        identity_summary=None,
        aliases=[],
    )
    text = MemoryEmbeddingService.build_searchable_text(entity)
    assert text == "Bob unknown", f"Got: {text!r}"


def test_build_searchable_text_description() -> None:
    desc = _make_description(
        content="The user went to the gym",
        description_type="detail",
    )
    text = MemoryEmbeddingService.build_searchable_text(desc)
    assert text == "The user went to the gym detail", f"Got: {text!r}"


def test_build_searchable_text_property() -> None:
    prop = _make_property(
        content="prefers less sugar",
        property_type="preference",
    )
    text = MemoryEmbeddingService.build_searchable_text(prop)
    assert text == "prefers less sugar preference", f"Got: {text!r}"


def test_build_searchable_text_none_for_unsupported_types() -> None:
    text = MemoryEmbeddingService.build_searchable_text(object())
    assert text is None


def test_embed_bundle_calls_client() -> None:
    stub = _StubEmbeddingClient(dimension=4)
    service = MemoryEmbeddingService(
        embedding_client=stub,
        database_url="postgresql://test:test@localhost/test",
        model="test-model",
        dimensions=4,
    )

    # Build a minimal bundle
    from memory.persistence.models import PersistentMemoryBundle

    event = _make_event(id="evt_1", title="Event one")
    entity = _make_entity(id="ent_1", name="Entity one", aliases=[])
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

    # embed_bundle uses a connection; test the text+id extraction by
    # checking that _embed_and_store is called via the stub
    # We'll test via _embed_and_store directly with a fake connection
    class _FakeConnection:
        def __init__(self) -> None:
            self.executed: list[tuple[str, tuple[object, ...]]] = []

        def execute(
            self,
            sql: str,
            params: tuple[object, ...] = (),
        ) -> None:
            self.executed.append((sql, params))

    conn = _FakeConnection()
    service._embed_and_store(
        conn,
        [("evt_1", "Event one"), ("ent_1", "Entity one")],
    )

    # Stub client should have been called
    assert len(stub.calls) == 1, f"Expected 1 call, got {len(stub.calls)}"
    assert stub.calls[0][0] == ["Event one", "Entity one"]
    assert stub.calls[0][1] == "test-model"

    # Connection should have received INSERTs
    assert len(conn.executed) == 2, f"Expected 2 INSERTs, got {len(conn.executed)}"


def test_embed_bundle_skips_empty() -> None:
    stub = _StubEmbeddingClient()
    service = MemoryEmbeddingService(
        embedding_client=stub,
        database_url="postgresql://test:test@localhost/test",
        dimensions=4,
    )

    from memory.persistence.models import PersistentMemoryBundle

    bundle = PersistentMemoryBundle(
        events=[], entities=[], descriptions=[], properties=[],
        links=[], time_refs=[], time_links=[], metadata={},
    )

    class _FakeConnection:
        pass

    # Should not raise and should not call the embedding client
    service.embed_bundle(_FakeConnection(), bundle)
    assert len(stub.calls) == 0


def main() -> int:
    tests: list[Callable[[], None]] = [
        test_build_searchable_text_event,
        test_build_searchable_text_event_no_summary,
        test_build_searchable_text_entity,
        test_build_searchable_text_entity_no_extras,
        test_build_searchable_text_description,
        test_build_searchable_text_property,
        test_build_searchable_text_none_for_unsupported_types,
        test_embed_bundle_calls_client,
        test_embed_bundle_skips_empty,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"passed={len(tests)}/{len(tests)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
