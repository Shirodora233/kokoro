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
        memory_type: str,
        memory_id: str,
        source_refs: Sequence[PersistentSourceRef],
    ) -> None:
        connection.execute(
            """
            DELETE FROM memory_sources
            WHERE memory_type = %s AND memory_id = %s
            """,
            (memory_type, memory_id),
        )
        for source_ref in source_refs:
            connection.execute(
                """
                INSERT INTO memory_sources (
                    id, memory_type, memory_id, source_type, source_id,
                    quote, span_start, span_end, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    new_source_id(),
                    memory_type,
                    memory_id,
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
        memory_type: str,
        memory_id: str,
    ) -> list[PersistentSourceRef]:
        rows = connection.execute(
            """
            SELECT * FROM memory_sources
            WHERE memory_type = %s AND memory_id = %s
            ORDER BY created_at ASC, id ASC
            """,
            (memory_type, memory_id),
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
