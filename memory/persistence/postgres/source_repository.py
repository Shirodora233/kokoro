"""Source reference persistence for normalized memory objects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Sequence

from psycopg.types.json import Jsonb

from ..models import PersistentSourceRef
from .ids import new_source_id


class PostgresMemorySourceRepository:
    def save_source_refs(
        self,
        connection: Any,
        object_id: str,
        source_refs: Sequence[PersistentSourceRef],
    ) -> None:
        # Merge semantics: dedupe incoming refs by (source_type, source_id),
        # then upsert. Existing refs with different (source_type, source_id)
        # pairs are preserved — only exact matches are updated.
        deduped: dict[tuple[str, str], PersistentSourceRef] = {}
        for source_ref in source_refs:
            key = (source_ref.source_type, source_ref.source_id)
            deduped[key] = source_ref  # last write wins for same key

        for source_ref in deduped.values():
            connection.execute(
                """
                INSERT INTO memory_sources (
                    id, object_id, source_type, source_id,
                    quote, span_start, span_end, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (object_id, source_type, source_id)
                DO UPDATE SET
                    quote = EXCLUDED.quote,
                    span_start = EXCLUDED.span_start,
                    span_end = EXCLUDED.span_end,
                    metadata = EXCLUDED.metadata
                """,
                (
                    new_source_id(),
                    object_id,
                    source_ref.source_type,
                    source_ref.source_id,
                    source_ref.quote,
                    source_ref.span_start,
                    source_ref.span_end,
                    Jsonb(dict(source_ref.metadata)),
                ),
            )

    def load_source_refs(
        self,
        connection: Any,
        object_id: str,
    ) -> list[PersistentSourceRef]:
        rows = connection.execute(
            """
            SELECT * FROM memory_sources
            WHERE object_id = %s
            ORDER BY created_at ASC, id ASC
            """,
            (object_id,),
        ).fetchall()
        return [_source_ref_from_row(row) for row in rows]


def _source_ref_from_row(row: Mapping[str, Any]) -> PersistentSourceRef:
    return PersistentSourceRef(
        source_type=row["source_type"],
        source_id=row["source_id"],
        quote=row["quote"],
        span_start=row["span_start"],
        span_end=row["span_end"],
        metadata=dict(row["metadata"]) if isinstance(row["metadata"], Mapping) else {},
    )
