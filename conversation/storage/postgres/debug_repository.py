"""Persisted debug views for PostgreSQL conversations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from psycopg.types.json import Jsonb

from conversation.models import ConversationMemoryDebugTrace

from .connection import PostgresDatabase
from .row_mappers import memory_debug_trace_from_row


class PostgresConversationDebugRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def save_trace_in_connection(
        self,
        connection: Any,
        trace: ConversationMemoryDebugTrace,
    ) -> ConversationMemoryDebugTrace:
        connection.execute(
            """
            INSERT INTO conversation_memory_debug_traces (
                trace_id, session_id, turn_id, user_message_id,
                assistant_message_id, checkpoint_id, checkpoint_sequence,
                memory_status, summary, trace, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trace_id) DO UPDATE SET
                session_id = EXCLUDED.session_id,
                turn_id = EXCLUDED.turn_id,
                user_message_id = EXCLUDED.user_message_id,
                assistant_message_id = EXCLUDED.assistant_message_id,
                checkpoint_id = EXCLUDED.checkpoint_id,
                checkpoint_sequence = EXCLUDED.checkpoint_sequence,
                memory_status = EXCLUDED.memory_status,
                summary = EXCLUDED.summary,
                trace = EXCLUDED.trace
            """,
            (
                trace.trace_id,
                trace.session_id,
                trace.turn_id,
                trace.user_message_id,
                trace.assistant_message_id,
                trace.checkpoint_id,
                trace.checkpoint_sequence,
                trace.memory_status,
                Jsonb(trace.summary),
                Jsonb(trace.trace),
                trace.created_at,
            ),
        )
        return trace

    def get_trace(self, trace_id: str) -> ConversationMemoryDebugTrace | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM conversation_memory_debug_traces
                WHERE trace_id = %s
                """,
                (trace_id,),
            ).fetchone()
        return memory_debug_trace_from_row(row) if row else None

    def list_visible_turn_debug(
        self,
        scopes: Sequence[Mapping[str, Any]],
        limit: int = 100,
    ) -> list[ConversationMemoryDebugTrace]:
        conditions, params = _session_scope_condition(
            scopes,
            sequence_column="checkpoint_sequence",
        )
        query = """
            SELECT * FROM conversation_memory_debug_traces
            WHERE {where_sql}
            ORDER BY checkpoint_sequence ASC, created_at ASC, trace_id ASC
            LIMIT %s
        """.format(where_sql=conditions)
        with self.database.connect() as connection:
            rows = connection.execute(
                query,
                (*params, max(0, limit)),
            ).fetchall()
        return [memory_debug_trace_from_row(row) for row in rows]

    def checkpoint_memory_snapshot(
        self,
        *,
        user_id: str,
        scopes: Sequence[Mapping[str, Any]],
        limit: int = 100,
    ) -> dict[str, Any]:
        selected_limit = max(0, limit)
        with self.database.connect() as connection:
            checkpoint_ids = self._visible_checkpoint_ids(connection, scopes)
            generic_memories = self._generic_memories(
                connection,
                user_id=user_id,
                scopes=scopes,
                limit=selected_limit,
            )
            normalized_memories = {
                "events": self._session_scoped_rows(
                    connection,
                    table="memory_events",
                    columns=(
                        "id, user_id, session_id, title, summary, event_type, "
                        "status, confidence, importance, created_turn_id, "
                        "created_checkpoint_id, created_checkpoint_sequence, "
                        "metadata, created_at::text AS created_at, "
                        "updated_at::text AS updated_at"
                    ),
                    user_id=user_id,
                    scopes=scopes,
                    limit=selected_limit,
                    status_column="status",
                ),
                "descriptions": self._session_scoped_rows(
                    connection,
                    table="memory_descriptions",
                    columns=(
                        "id, event_id, user_id, session_id, content, "
                        "description_type, status, confidence, importance, "
                        "created_turn_id, created_checkpoint_id, "
                        "created_checkpoint_sequence, metadata, "
                        "created_at::text AS created_at, updated_at::text AS updated_at"
                    ),
                    user_id=user_id,
                    scopes=scopes,
                    limit=selected_limit,
                    status_column="status",
                ),
                "entities": self._session_scoped_rows(
                    connection,
                    table="memory_entities",
                    columns=(
                        "id, user_id, session_id, scope, name, entity_type, "
                        "identity_summary, aliases, confidence, importance, "
                        "created_turn_id, created_checkpoint_id, "
                        "created_checkpoint_sequence, metadata, "
                        "created_at::text AS created_at, updated_at::text AS updated_at"
                    ),
                    user_id=user_id,
                    scopes=scopes,
                    limit=selected_limit,
                ),
                "properties": self._session_scoped_rows(
                    connection,
                    table="memory_properties",
                    columns=(
                        "id, entity_id, user_id, session_id, content, "
                        "property_type, status, confidence, importance, "
                        "created_turn_id, created_checkpoint_id, "
                        "created_checkpoint_sequence, metadata, "
                        "created_at::text AS created_at, updated_at::text AS updated_at"
                    ),
                    user_id=user_id,
                    scopes=scopes,
                    limit=selected_limit,
                    status_column="status",
                ),
                "links": self._checkpoint_scoped_rows(
                    connection,
                    table="memory_links",
                    columns=(
                        "id, user_id, from_type, from_id, to_type, to_id, "
                        "relation_type, reason, status, confidence, "
                        "created_turn_id, created_checkpoint_id, "
                        "created_checkpoint_sequence, metadata, "
                        "created_at::text AS created_at, updated_at::text AS updated_at"
                    ),
                    user_id=user_id,
                    checkpoint_ids=checkpoint_ids,
                    limit=selected_limit,
                    status_column="status",
                ),
                "time_refs": self._checkpoint_scoped_rows(
                    connection,
                    table="memory_time_refs",
                    columns=(
                        "id, raw_text, time_kind, timeline_kind, certainty, "
                        "anchor_timezone, anchor_utc_offset, anchor_message_id, "
                        "resolved_start, resolved_end, granularity, description, "
                        "duration_text, recurrence_text, created_turn_id, "
                        "created_checkpoint_id, created_checkpoint_sequence, "
                        "metadata, created_at::text AS created_at, "
                        "updated_at::text AS updated_at"
                    ),
                    user_id=None,
                    checkpoint_ids=checkpoint_ids,
                    limit=selected_limit,
                ),
                "time_links": self._checkpoint_scoped_rows(
                    connection,
                    table="memory_time_links",
                    columns=(
                        "id, target_type, target_id, time_ref_id, time_role, "
                        "confidence, created_turn_id, created_checkpoint_id, "
                        "created_checkpoint_sequence, metadata, "
                        "created_at::text AS created_at, updated_at::text AS updated_at"
                    ),
                    user_id=None,
                    checkpoint_ids=checkpoint_ids,
                    limit=selected_limit,
                ),
            }
        return {
            "scope": {
                "user_id": user_id,
                "visible_session_scopes": [dict(scope) for scope in scopes],
                "visible_checkpoint_ids": checkpoint_ids,
                "limit": selected_limit,
            },
            "generic_memories": generic_memories,
            "normalized_memories": normalized_memories,
        }

    def _visible_checkpoint_ids(
        self,
        connection: Any,
        scopes: Sequence[Mapping[str, Any]],
    ) -> list[str]:
        where_sql, params = _session_scope_condition(
            scopes,
            sequence_column="sequence",
        )
        rows = connection.execute(
            f"""
            SELECT id FROM conversation_checkpoints
            WHERE {where_sql}
            ORDER BY sequence ASC, created_at ASC, id ASC
            """,
            tuple(params),
        ).fetchall()
        return [row["id"] for row in rows]

    def _generic_memories(
        self,
        connection: Any,
        *,
        user_id: str,
        scopes: Sequence[Mapping[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        scope_sql, scope_params = _memory_record_scope_condition(scopes)
        rows = connection.execute(
            f"""
            SELECT
                id, memory_type, text, user_id, session_id, metadata,
                created_turn_id, created_checkpoint_id,
                created_checkpoint_sequence, created_at::text AS created_at,
                updated_at::text AS updated_at
            FROM memory_records
            WHERE (user_id IS NULL OR user_id = %s)
              AND {scope_sql}
            ORDER BY COALESCE(created_checkpoint_sequence, -1) ASC,
                     created_at ASC, id ASC
            LIMIT %s
            """,
            (user_id, *scope_params, limit),
        ).fetchall()
        source_refs = self._memory_source_refs(
            connection,
            [row["id"] for row in rows],
        )
        return [
            {
                **_json_ready(row),
                "source_refs": source_refs.get(row["id"], []),
            }
            for row in rows
        ]

    def _memory_source_refs(
        self,
        connection: Any,
        memory_record_ids: Sequence[str],
    ) -> dict[str, list[dict[str, Any]]]:
        ids = [record_id for record_id in memory_record_ids if record_id]
        if not ids:
            return {}
        rows = connection.execute(
            f"""
            SELECT
                memory_record_id, position, source_type, source_id, quote,
                span_start, span_end, metadata
            FROM memory_source_refs
            WHERE memory_record_id IN ({_placeholders(ids)})
            ORDER BY memory_record_id ASC, position ASC
            """,
            tuple(ids),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {record_id: [] for record_id in ids}
        for row in rows:
            grouped.setdefault(row["memory_record_id"], []).append(_json_ready(row))
        return grouped

    def _session_scoped_rows(
        self,
        connection: Any,
        *,
        table: str,
        columns: str,
        user_id: str,
        scopes: Sequence[Mapping[str, Any]],
        limit: int,
        status_column: str | None = None,
    ) -> list[dict[str, Any]]:
        scope_sql, scope_params = _memory_record_scope_condition(scopes)
        status_sql = f"AND {status_column} = 'active'" if status_column else ""
        rows = connection.execute(
            f"""
            SELECT {columns}
            FROM {table}
            WHERE (user_id IS NULL OR user_id = %s)
              AND {scope_sql}
              {status_sql}
            ORDER BY COALESCE(created_checkpoint_sequence, -1) ASC,
                     updated_at ASC, id ASC
            LIMIT %s
            """,
            (user_id, *scope_params, limit),
        ).fetchall()
        return [_json_ready(row) for row in rows]

    def _checkpoint_scoped_rows(
        self,
        connection: Any,
        *,
        table: str,
        columns: str,
        user_id: str | None,
        checkpoint_ids: Sequence[str],
        limit: int,
        status_column: str | None = None,
    ) -> list[dict[str, Any]]:
        status_sql = f"AND {status_column} = 'active'" if status_column else ""
        user_sql = "(user_id IS NULL OR user_id = %s) AND" if user_id is not None else ""
        checkpoint_sql = "created_checkpoint_id IS NULL"
        params: list[object] = []
        if user_id is not None:
            params.append(user_id)
        if checkpoint_ids:
            checkpoint_sql = (
                f"(created_checkpoint_id IS NULL OR "
                f"created_checkpoint_id IN ({_placeholders(checkpoint_ids)}))"
            )
            params.extend(checkpoint_ids)
        rows = connection.execute(
            f"""
            SELECT {columns}
            FROM {table}
            WHERE {user_sql} {checkpoint_sql}
              {status_sql}
            ORDER BY COALESCE(created_checkpoint_sequence, -1) ASC,
                     updated_at ASC, id ASC
            LIMIT %s
            """,
            (*params, limit),
        ).fetchall()
        return [_json_ready(row) for row in rows]


def _session_scope_condition(
    scopes: Sequence[Mapping[str, Any]],
    *,
    sequence_column: str,
) -> tuple[str, list[object]]:
    scoped_conditions: list[str] = []
    params: list[object] = []
    for scope in scopes:
        session_id = scope.get("session_id")
        max_sequence = scope.get("max_checkpoint_sequence")
        if not isinstance(session_id, str):
            continue
        if isinstance(max_sequence, int):
            scoped_conditions.append(
                f"(session_id = %s AND {sequence_column} <= %s)"
            )
            params.extend([session_id, max_sequence])
        else:
            scoped_conditions.append("session_id = %s")
            params.append(session_id)
    if not scoped_conditions:
        return "FALSE", []
    return "(" + " OR ".join(scoped_conditions) + ")", params


def _memory_record_scope_condition(
    scopes: Sequence[Mapping[str, Any]],
) -> tuple[str, list[object]]:
    scoped_conditions = ["session_id IS NULL"]
    params: list[object] = []
    for scope in scopes:
        session_id = scope.get("session_id")
        max_sequence = scope.get("max_checkpoint_sequence")
        if not isinstance(session_id, str):
            continue
        if isinstance(max_sequence, int):
            scoped_conditions.append(
                """
                (
                  session_id = %s
                  AND (
                    created_checkpoint_sequence IS NULL
                    OR created_checkpoint_sequence <= %s
                  )
                )
                """
            )
            params.extend([session_id, max_sequence])
        else:
            scoped_conditions.append("session_id = %s")
            params.append(session_id)
    return "(" + " OR ".join(scoped_conditions) + ")", params


def _json_ready(row: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime | date):
            result[key] = value.isoformat()
        elif isinstance(value, Mapping):
            result[key] = dict(value)
        elif isinstance(value, list):
            result[key] = list(value)
        else:
            result[key] = value
    return result


def _placeholders(values: Sequence[object]) -> str:
    return ", ".join(["%s"] * len(values))
