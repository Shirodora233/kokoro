"""Memory embedding service for generating and storing embeddings."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any, Sequence

from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from llm.interfaces import EmbeddingClient

from ..persistence.models import (
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentMemoryBundle,
    PersistentProperty,
)

LOGGER = logging.getLogger(__name__)

# Object types that are embeddable (have semantic searchable text)
_EMBEDDABLE_TYPES = {"event", "entity", "description", "property"}


class MemoryEmbeddingService:
    """Generate and store embeddings for normalized memory objects."""

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        database_url: str,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        batch_size: int = 20,
    ) -> None:
        self.embedding_client = embedding_client
        self.database_url = database_url
        self.model = model
        self.dimensions = dimensions
        self.batch_size = max(1, batch_size)

    # ------------------------------------------------------------------
    # Searchable text construction
    # ------------------------------------------------------------------

    @staticmethod
    def build_searchable_text(obj: object) -> str | None:
        """Build the searchable text for a memory object.

        Returns None for structural object types (link, time_ref, time_link)
        that should not be embedded.
        """
        if isinstance(obj, PersistentEvent):
            parts = [obj.title]
            if obj.summary:
                parts.append(obj.summary)
            if obj.event_type:
                parts.append(obj.event_type)
            return " ".join(parts)

        if isinstance(obj, PersistentEntity):
            parts = [obj.name, obj.entity_type]
            if obj.identity_summary:
                parts.append(obj.identity_summary)
            if obj.aliases:
                parts.append(" ".join(obj.aliases))
            return " ".join(parts)

        if isinstance(obj, PersistentDescription):
            parts = [obj.content]
            if obj.description_type:
                parts.append(obj.description_type)
            return " ".join(parts)

        if isinstance(obj, PersistentProperty):
            parts = [obj.content]
            if obj.property_type:
                parts.append(obj.property_type)
            return " ".join(parts)

        return None

    # ------------------------------------------------------------------
    # Embedding generation on write
    # ------------------------------------------------------------------

    def embed_bundle(
        self,
        connection: Any,
        bundle: PersistentMemoryBundle,
    ) -> None:
        """Generate embeddings for every embeddable object in a bundle.

        Failures are logged but do not propagate -- the memory write
        already succeeded.
        """
        objects: list[tuple[str, str]] = []  # (object_id, searchable_text)

        for field_name in ("events", "entities", "descriptions", "properties"):
            for item in getattr(bundle, field_name, ()):
                text = self.build_searchable_text(item)
                if text and item.id:
                    objects.append((item.id, text))

        if not objects:
            return

        self._embed_and_store(connection, objects)

    def _embed_and_store(
        self,
        connection: Any,
        objects: list[tuple[str, str]],
    ) -> None:
        """Batch-embed texts and upsert into memory_object_embeddings."""
        # Register the vector adapter on this connection so psycopg can
        # convert Python lists to PostgreSQL vector parameters.  Wrapped
        # so test stubs (fake connections) don't trip over the type check.
        try:
            register_vector(connection)
        except TypeError:
            pass
        except Exception:
            LOGGER.warning(
                "Failed to register pgvector adapter; skipping embedding storage",
                exc_info=True,
            )
            try:
                connection.rollback()
            except Exception:
                LOGGER.warning(
                    "Failed to roll back after pgvector adapter registration error",
                    exc_info=True,
                )
            return

        for start in range(0, len(objects), self.batch_size):
            chunk = objects[start : start + self.batch_size]
            ids = [obj_id for obj_id, _ in chunk]
            texts = [text for _, text in chunk]

            try:
                vectors = self.embedding_client.embed(texts, model=self.model)
            except Exception:
                LOGGER.warning(
                    "Failed to generate embeddings for %d objects: %s",
                    len(chunk),
                    ids,
                    exc_info=True,
                )
                continue

            for i, obj_id in enumerate(ids):
                embedding = vectors[i] if i < len(vectors) else None
                if embedding is None:
                    continue
                if len(embedding) != self.dimensions:
                    LOGGER.warning(
                        "Embedding dimension mismatch for object %s: "
                        "got %d, expected %d",
                        obj_id,
                        len(embedding),
                        self.dimensions,
                    )
                    continue
                savepoint = (
                    connection.transaction()
                    if hasattr(connection, "transaction")
                    else nullcontext()
                )
                try:
                    with savepoint:
                        connection.execute(
                            """
                            INSERT INTO memory_object_embeddings
                                (object_id, embedding, model, searchable_text)
                            VALUES (%s, %s::vector, %s, %s)
                            ON CONFLICT (object_id, model) DO UPDATE SET
                                embedding = EXCLUDED.embedding,
                                searchable_text = EXCLUDED.searchable_text,
                                generated_at = NOW()
                            """,
                            (obj_id, embedding, self.model, texts[i]),
                        )
                except Exception:
                    LOGGER.warning(
                        "Failed to store embedding for object %s",
                        obj_id,
                        exc_info=True,
                    )

    # ------------------------------------------------------------------
    # Backfill support
    # ------------------------------------------------------------------

    def list_missing(
        self,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return objects that don't yet have embeddings for the current model."""
        import psycopg

        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT o.id, o.object_type
                FROM memory_objects o
                LEFT JOIN memory_object_embeddings e
                       ON e.object_id = o.id AND e.model = %s
                WHERE o.status = 'active'
                  AND o.object_type = ANY(%s)
                  AND e.object_id IS NULL
                ORDER BY o.updated_at DESC
                LIMIT %s
                """,
                (self.model, list(_EMBEDDABLE_TYPES), limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def backfill_batch(
        self,
        limit: int = 100,
    ) -> int:
        """Generate embeddings for up to `limit` objects missing them.

        Uses a single database connection for the entire operation to avoid
        unnecessary connection churn.
        Returns the number of objects processed.
        """
        import psycopg

        # Single connection for the whole backfill batch
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            # Find objects without embeddings for the current model
            rows = conn.execute(
                """
                SELECT o.id, o.object_type
                FROM memory_objects o
                LEFT JOIN memory_object_embeddings e
                       ON e.object_id = o.id AND e.model = %s
                WHERE o.status = 'active'
                  AND o.object_type = ANY(%s)
                  AND e.object_id IS NULL
                ORDER BY o.updated_at DESC
                LIMIT %s
                """,
                (self.model, list(_EMBEDDABLE_TYPES), limit),
            ).fetchall()

            if not rows:
                return 0

            # Build searchable text directly from the source tables
            objects: list[tuple[str, str]] = []
            for row in rows:
                obj_type = row.get("object_type")
                obj_id = row.get("id")
                if not isinstance(obj_id, str):
                    continue
                try:
                    text = self._load_text_for_object(conn, obj_type, obj_id)
                except Exception:
                    LOGGER.warning(
                        "Failed to load object %s", obj_id, exc_info=True,
                    )
                    continue
                if text:
                    objects.append((obj_id, text))

            if not objects:
                return 0

            self._embed_and_store(conn, objects)
            conn.commit()

        return len(objects)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_text_for_object(
        conn: Any,
        obj_type: str,
        obj_id: str,
    ) -> str | None:
        """Load just the searchable text for an object directly from the DB."""
        if obj_type == "event":
            row = conn.execute(
                "SELECT title, summary, event_type "
                "FROM memory_events WHERE id = %s",
                (obj_id,),
            ).fetchone()
            if not row:
                return None
            parts = [row["title"]]
            if row["summary"]:
                parts.append(row["summary"])
            if row["event_type"]:
                parts.append(row["event_type"])
            return " ".join(parts)

        if obj_type == "entity":
            row = conn.execute(
                "SELECT name, entity_type, identity_summary, aliases "
                "FROM memory_entities WHERE id = %s",
                (obj_id,),
            ).fetchone()
            if not row:
                return None
            parts = [row["name"], row["entity_type"]]
            if row["identity_summary"]:
                parts.append(row["identity_summary"])
            if row["aliases"]:
                parts.append(" ".join(row["aliases"]))
            return " ".join(parts)

        if obj_type == "description":
            row = conn.execute(
                "SELECT content, description_type "
                "FROM memory_descriptions WHERE id = %s",
                (obj_id,),
            ).fetchone()
            if not row:
                return None
            parts = [row["content"]]
            if row["description_type"]:
                parts.append(row["description_type"])
            return " ".join(parts)

        if obj_type == "property":
            row = conn.execute(
                "SELECT content, property_type "
                "FROM memory_properties WHERE id = %s",
                (obj_id,),
            ).fetchone()
            if not row:
                return None
            parts = [row["content"]]
            if row["property_type"]:
                parts.append(row["property_type"])
            return " ".join(parts)

        return None
