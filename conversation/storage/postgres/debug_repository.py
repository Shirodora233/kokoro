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
            normalized_memories = {
                "events": self._object_scoped_rows(
                    connection,
                    select_sql=(
                        "SELECT e.id, e.title, e.summary, e.event_type, "
                        "o.user_id, o.session_id, o.scope, o.status, "
                        "o.confidence, o.importance, o.created_turn_id, "
                        "o.created_checkpoint_id, cp.sequence AS created_checkpoint_sequence, "
                        "o.metadata, o.created_at::text AS created_at, "
                        "o.updated_at::text AS updated_at "
                        "FROM memory_events e "
                        "JOIN memory_objects o ON o.id = e.id "
                        "LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id"
                    ),
                    user_id=user_id,
                    scopes=scopes,
                    limit=selected_limit,
                ),
                "descriptions": self._object_scoped_rows(
                    connection,
                    select_sql=(
                        "SELECT d.id, d.event_id, d.content, d.description_type, "
                        "o.user_id, o.session_id, o.scope, o.status, "
                        "o.confidence, o.importance, o.created_turn_id, "
                        "o.created_checkpoint_id, cp.sequence AS created_checkpoint_sequence, "
                        "o.metadata, o.created_at::text AS created_at, "
                        "o.updated_at::text AS updated_at "
                        "FROM memory_descriptions d "
                        "JOIN memory_objects o ON o.id = d.id "
                        "LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id"
                    ),
                    user_id=user_id,
                    scopes=scopes,
                    limit=selected_limit,
                ),
                "entities": self._object_scoped_rows(
                    connection,
                    select_sql=(
                        "SELECT ent.id, ent.name, ent.entity_type, ent.identity_summary, "
                        "COALESCE(alias_rows.aliases, '[]'::jsonb) AS aliases, "
                        "o.user_id, o.session_id, o.scope, o.status, "
                        "o.confidence, o.importance, o.created_turn_id, "
                        "o.created_checkpoint_id, cp.sequence AS created_checkpoint_sequence, "
                        "o.metadata, o.created_at::text AS created_at, "
                        "o.updated_at::text AS updated_at "
                        "FROM memory_entities ent "
                        "JOIN memory_objects o ON o.id = ent.id "
                        "LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id "
                        "LEFT JOIN ("
                        "SELECT entity_id, jsonb_agg(alias ORDER BY position) AS aliases "
                        "FROM memory_entity_aliases GROUP BY entity_id"
                        ") alias_rows ON alias_rows.entity_id = ent.id"
                    ),
                    user_id=user_id,
                    scopes=scopes,
                    limit=selected_limit,
                ),
                "properties": self._object_scoped_rows(
                    connection,
                    select_sql=(
                        "SELECT p.id, p.entity_id, p.content, p.property_type, "
                        "o.user_id, o.session_id, o.scope, o.status, "
                        "o.confidence, o.importance, o.created_turn_id, "
                        "o.created_checkpoint_id, cp.sequence AS created_checkpoint_sequence, "
                        "o.metadata, o.created_at::text AS created_at, "
                        "o.updated_at::text AS updated_at "
                        "FROM memory_properties p "
                        "JOIN memory_objects o ON o.id = p.id "
                        "LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id"
                    ),
                    user_id=user_id,
                    scopes=scopes,
                    limit=selected_limit,
                ),
                "links": self._object_scoped_rows(
                    connection,
                    select_sql=(
                        "SELECT r.id, from_object.object_type AS from_type, "
                        "r.from_object_id AS from_id, to_object.object_type AS to_type, "
                        "r.to_object_id AS to_id, r.relation_type, r.reason, "
                        "o.user_id, o.session_id, o.scope, o.status, "
                        "o.confidence, o.importance, o.created_turn_id, "
                        "o.created_checkpoint_id, cp.sequence AS created_checkpoint_sequence, "
                        "o.metadata, o.created_at::text AS created_at, "
                        "o.updated_at::text AS updated_at "
                        "FROM memory_relations r "
                        "JOIN memory_objects o ON o.id = r.id "
                        "JOIN memory_objects from_object ON from_object.id = r.from_object_id "
                        "JOIN memory_objects to_object ON to_object.id = r.to_object_id "
                        "LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id"
                    ),
                    user_id=user_id,
                    scopes=scopes,
                    limit=selected_limit,
                ),
                "time_refs": self._object_scoped_rows(
                    connection,
                    select_sql=(
                        "SELECT tr.id, tr.raw_text, tr.time_kind, tr.timeline_kind, "
                        "tr.certainty, tr.anchor_timezone, tr.anchor_utc_offset, "
                        "tr.anchor_message_id, tr.resolved_start, tr.resolved_end, "
                        "tr.granularity, tr.description, tr.duration_text, "
                        "tr.recurrence_text, o.user_id, o.session_id, o.scope, "
                        "o.status, o.confidence, o.importance, o.created_turn_id, "
                        "o.created_checkpoint_id, cp.sequence AS created_checkpoint_sequence, "
                        "o.metadata, o.created_at::text AS created_at, "
                        "o.updated_at::text AS updated_at "
                        "FROM memory_time_refs tr "
                        "JOIN memory_objects o ON o.id = tr.id "
                        "LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id"
                    ),
                    user_id=user_id,
                    scopes=scopes,
                    limit=selected_limit,
                ),
                "time_links": self._object_scoped_rows(
                    connection,
                    select_sql=(
                        "SELECT tl.id, target_object.object_type AS target_type, "
                        "tl.target_object_id AS target_id, "
                        "tl.time_ref_object_id AS time_ref_id, tl.time_role, "
                        "o.user_id, o.session_id, o.scope, o.status, "
                        "o.confidence, o.importance, o.created_turn_id, "
                        "o.created_checkpoint_id, cp.sequence AS created_checkpoint_sequence, "
                        "o.metadata, o.created_at::text AS created_at, "
                        "o.updated_at::text AS updated_at "
                        "FROM memory_time_links tl "
                        "JOIN memory_objects o ON o.id = tl.id "
                        "JOIN memory_objects target_object ON target_object.id = tl.target_object_id "
                        "LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id"
                    ),
                    user_id=user_id,
                    scopes=scopes,
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

    def _object_scoped_rows(
        self,
        connection: Any,
        *,
        select_sql: str,
        user_id: str,
        scopes: Sequence[Mapping[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        scope_sql, scope_params = _memory_object_scope_condition(scopes)
        rows = connection.execute(
            f"""
            {select_sql}
            WHERE (o.user_id IS NULL OR o.user_id = %s)
              AND o.status = 'active'
              AND {scope_sql}
            ORDER BY COALESCE(cp.sequence, -1) ASC,
                     o.updated_at ASC, id ASC
            LIMIT %s
            """,
            (user_id, *scope_params, limit),
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


def _memory_object_scope_condition(
    scopes: Sequence[Mapping[str, Any]],
) -> tuple[str, list[object]]:
    scoped_conditions = ["o.session_id IS NULL"]
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
                  o.session_id = %s
                  AND (
                    o.created_checkpoint_id IS NULL
                    OR cp.sequence <= %s
                  )
                )
                """
            )
            params.extend([session_id, max_sequence])
        else:
            scoped_conditions.append("o.session_id = %s")
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


    def delete_traces_by_session_id(self, session_id: str) -> int:
        with self.database.connect() as connection:
            result = connection.execute(
                """
                DELETE FROM conversation_memory_debug_traces
                WHERE session_id = %s
                """,
                (session_id,),
            )
            return result.rowcount

    def delete_traces_by_user_id(self, user_id: str) -> int:
        with self.database.connect() as connection:
            result = connection.execute(
                """
                DELETE FROM conversation_memory_debug_traces
                WHERE session_id IN (
                    SELECT id FROM sessions WHERE user_id = %s
                )
                """,
                (user_id,),
            )
            return result.rowcount

    def delete_all_traces(self) -> int:
        with self.database.connect() as connection:
            result = connection.execute(
                "DELETE FROM conversation_memory_debug_traces"
            )
            return result.rowcount


def _placeholders(values: Sequence[object]) -> str:
    return ", ".join(["%s"] * len(values))
