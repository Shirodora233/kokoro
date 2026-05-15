"""PostgreSQL-backed memory record store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Sequence, cast

from psycopg.types.json import Jsonb

from ...models import MemoryRecord, MemoryRecordType, MemorySourceRef
from ..ids import new_memory_id
from .connection import PostgresMemoryDatabase


class PostgresMemoryStore:
    """Durable `MemoryStore` implementation backed by PostgreSQL.

    This store persists the current generic `MemoryRecord` envelope. The
    normalized event/entity/property/time tables remain a later repository layer.
    """

    def __init__(
        self,
        database_url: str | None = None,
        database: PostgresMemoryDatabase | None = None,
        ensure_schema: bool = True,
    ) -> None:
        if database is None:
            if database_url is None:
                raise ValueError("database_url is required")
            database = PostgresMemoryDatabase(database_url)
        self.database = database
        if ensure_schema:
            self.ensure_schema()

    def ensure_schema(self) -> None:
        self.database.ensure_schema()

    def save_records(self, records: Sequence[MemoryRecord]) -> Sequence[MemoryRecord]:
        stored_records: list[MemoryRecord] = []
        with self.database.connect() as connection:
            for record in records:
                stored_record = self._record_with_id(record)
                metadata = dict(stored_record.metadata)
                connection.execute(
                    """
                    INSERT INTO memory_records (
                        id, memory_type, text, user_id, session_id, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        memory_type = EXCLUDED.memory_type,
                        text = EXCLUDED.text,
                        user_id = EXCLUDED.user_id,
                        session_id = EXCLUDED.session_id,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """,
                    (
                        stored_record.id,
                        stored_record.memory_type,
                        stored_record.text,
                        _metadata_string(metadata, "user_id"),
                        _metadata_string(metadata, "session_id"),
                        Jsonb(metadata),
                    ),
                )
                connection.execute(
                    "DELETE FROM memory_source_refs WHERE memory_record_id = %s",
                    (stored_record.id,),
                )
                for position, source_ref in enumerate(stored_record.source_refs):
                    connection.execute(
                        """
                        INSERT INTO memory_source_refs (
                            memory_record_id, position, source_type, source_id,
                            quote, span_start, span_end, metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            stored_record.id,
                            position,
                            source_ref.source_type,
                            source_ref.source_id,
                            source_ref.quote,
                            source_ref.span_start,
                            source_ref.span_end,
                            Jsonb(dict(source_ref.metadata)),
                        ),
                    )
                stored_records.append(stored_record)
        return stored_records

    def get_records(self, record_ids: Sequence[str]) -> Sequence[MemoryRecord]:
        ids = [record_id for record_id in record_ids if record_id]
        if not ids:
            return []
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM memory_records
                WHERE id IN ({_placeholders(ids)})
                """,
                tuple(ids),
            ).fetchall()
            source_refs = self._load_source_refs(connection, ids)
        records_by_id = {
            row["id"]: _record_from_row(row, source_refs.get(row["id"], []))
            for row in rows
        }
        return [
            records_by_id[record_id]
            for record_id in ids
            if record_id in records_by_id
        ]

    def list_records(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        memory_type: MemoryRecordType | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        conditions: list[str] = []
        params: list[object] = []

        if memory_type is not None:
            conditions.append("memory_type = %s")
            params.append(memory_type)

        if user_id is not None or session_id is not None:
            conditions.append("(user_id IS NULL OR user_id = %s)")
            params.append(user_id)
            conditions.append("(session_id IS NULL OR session_id = %s)")
            params.append(session_id)

        query = "SELECT * FROM memory_records"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at ASC, id ASC"
        if limit is not None:
            query += " LIMIT %s"
            params.append(max(0, limit))

        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            source_refs = self._load_source_refs(
                connection,
                [row["id"] for row in rows],
            )
        return [
            _record_from_row(row, source_refs.get(row["id"], []))
            for row in rows
        ]

    def clear(self) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM memory_records")

    def _record_with_id(self, record: MemoryRecord) -> MemoryRecord:
        if record.id:
            return record
        return replace(record, id=new_memory_id(record.memory_type))

    def _load_source_refs(
        self,
        connection: Any,
        record_ids: Sequence[str],
    ) -> dict[str, list[MemorySourceRef]]:
        ids = [record_id for record_id in record_ids if record_id]
        if not ids:
            return {}
        rows = connection.execute(
            f"""
            SELECT * FROM memory_source_refs
            WHERE memory_record_id IN ({_placeholders(ids)})
            ORDER BY memory_record_id ASC, position ASC
            """,
            tuple(ids),
        ).fetchall()
        grouped: dict[str, list[MemorySourceRef]] = {
            record_id: [] for record_id in ids
        }
        for row in rows:
            grouped.setdefault(row["memory_record_id"], []).append(
                MemorySourceRef(
                    source_type=row["source_type"],
                    source_id=row["source_id"],
                    quote=row["quote"],
                    span_start=row["span_start"],
                    span_end=row["span_end"],
                    metadata=_metadata_dict(row["metadata"]),
                )
            )
        return grouped


def _record_from_row(
    row: Mapping[str, Any],
    source_refs: list[MemorySourceRef],
) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        memory_type=cast(MemoryRecordType, row["memory_type"]),
        text=row["text"],
        source_refs=source_refs,
        metadata=_metadata_dict(row["metadata"]),
    )


def _metadata_string(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _metadata_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _placeholders(values: Sequence[object]) -> str:
    return ", ".join(["%s"] * len(values))
