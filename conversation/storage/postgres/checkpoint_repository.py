"""Checkpoint, turn, and branch operations for PostgreSQL conversations."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from conversation.models import (
    ChatSession,
    ConversationCheckpoint,
    ConversationTurn,
    Message,
    SessionBranch,
    utc_now,
)

from .connection import PostgresDatabase
from .row_mappers import (
    branch_from_row,
    checkpoint_from_row,
    message_from_row,
    session_from_row,
    turn_from_row,
)


class PostgresCheckpointRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def begin_turn(
        self,
        turn: ConversationTurn,
    ) -> ConversationTurn:
        with self.database.connect() as connection:
            return self.begin_turn_in_connection(connection, turn)

    def begin_turn_in_connection(
        self,
        connection: Any,
        turn: ConversationTurn,
    ) -> ConversationTurn:
        connection.execute(
            """
            INSERT INTO conversation_turns (
                id, session_id, user_message_id, assistant_message_id,
                checkpoint_id, status, idempotency_key, debug_trace_id,
                memory_status, error, metadata, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                turn.id,
                turn.session_id,
                turn.user_message_id,
                turn.assistant_message_id,
                turn.checkpoint_id,
                turn.status,
                turn.idempotency_key,
                turn.debug_trace_id,
                turn.memory_status,
                turn.error,
                Jsonb(turn.metadata),
                turn.created_at,
                turn.updated_at,
            ),
        )
        return turn

    def get_turn_by_idempotency_key(
        self,
        session_id: str,
        idempotency_key: str,
    ) -> ConversationTurn | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM conversation_turns
                WHERE session_id = %s AND idempotency_key = %s
                """,
                (session_id, idempotency_key),
            ).fetchone()
        return turn_from_row(row) if row else None

    def get_turn(self, turn_id: str) -> ConversationTurn | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_turns WHERE id = %s",
                (turn_id,),
            ).fetchone()
        return turn_from_row(row) if row else None

    def mark_turn_failed(
        self,
        turn_id: str,
        error: str,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE conversation_turns
                SET status = 'failed', error = %s, updated_at = %s
                WHERE id = %s AND status <> 'committed'
                """,
                (error, utc_now(), turn_id),
            )

    def fail_incomplete_turns(self) -> int:
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE conversation_turns
                SET status = 'failed',
                    error = COALESCE(error, 'recovered incomplete turn'),
                    updated_at = %s
                WHERE status IN ('preparing', 'llm_running', 'committing')
                """,
                (utc_now(),),
            )
            return result.rowcount or 0

    def lock_session(
        self,
        connection: Any,
        session_id: str,
    ) -> ChatSession:
        row = connection.execute(
            "SELECT * FROM sessions WHERE id = %s FOR UPDATE",
            (session_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown session_id: {session_id}")
        return session_from_row(row)

    def latest_checkpoint(
        self,
        session_id: str,
    ) -> ConversationCheckpoint | None:
        with self.database.connect() as connection:
            return self.latest_checkpoint_in_connection(connection, session_id)

    def latest_checkpoint_in_connection(
        self,
        connection: Any,
        session_id: str,
    ) -> ConversationCheckpoint | None:
        row = connection.execute(
            """
            SELECT * FROM conversation_checkpoints
            WHERE session_id = %s
            ORDER BY sequence DESC, created_at DESC, id ASC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return checkpoint_from_row(row) if row else None

    def get_checkpoint(self, checkpoint_id: str) -> ConversationCheckpoint | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_checkpoints WHERE id = %s",
                (checkpoint_id,),
            ).fetchone()
        return checkpoint_from_row(row) if row else None

    def list_visible_checkpoints(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[ConversationCheckpoint]:
        with self.database.connect() as connection:
            return self._list_visible_checkpoints(connection, session_id, limit)

    def update_checkpoint_label(
        self,
        checkpoint_id: str,
        label: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationCheckpoint:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                UPDATE conversation_checkpoints
                SET label = %s,
                    metadata = metadata || %s
                WHERE id = %s
                RETURNING *
                """,
                (label, Jsonb(dict(metadata or {})), checkpoint_id),
            ).fetchone()
            if not row:
                raise ValueError(f"Unknown checkpoint_id: {checkpoint_id}")
        return checkpoint_from_row(row)

    def append_message_in_connection(
        self,
        connection: Any,
        message: Message,
        *,
        turn_id: str | None,
        checkpoint_id: str | None,
        sequence: int,
        status: str = "active",
    ) -> Message:
        connection.execute(
            """
            INSERT INTO messages (
                id, session_id, user_id, role, content, model,
                token_usage, metadata, created_at, turn_id, checkpoint_id,
                sequence, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                message.id,
                message.session_id,
                message.user_id,
                message.role,
                message.content,
                message.model,
                Jsonb(message.token_usage),
                Jsonb(message.metadata),
                message.created_at,
                turn_id,
                checkpoint_id,
                sequence,
                status,
            ),
        )
        return message

    def complete_turn_in_connection(
        self,
        connection: Any,
        turn_id: str,
        *,
        user_message_id: str,
        assistant_message_id: str,
        checkpoint_id: str,
        debug_trace_id: str | None,
        memory_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            UPDATE conversation_turns
            SET user_message_id = %s,
                assistant_message_id = %s,
                checkpoint_id = %s,
                status = 'committed',
                debug_trace_id = %s,
                memory_status = %s,
                metadata = metadata || %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                user_message_id,
                assistant_message_id,
                checkpoint_id,
                debug_trace_id,
                memory_status,
                Jsonb(dict(metadata or {})),
                utc_now(),
                turn_id,
            ),
        )

    def create_checkpoint_in_connection(
        self,
        connection: Any,
        checkpoint: ConversationCheckpoint,
    ) -> ConversationCheckpoint:
        connection.execute(
            """
            INSERT INTO conversation_checkpoints (
                id, session_id, turn_id, parent_checkpoint_id,
                assistant_message_id, sequence, label, session_snapshot,
                active_memory_snapshot, metadata, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                checkpoint.id,
                checkpoint.session_id,
                checkpoint.turn_id,
                checkpoint.parent_checkpoint_id,
                checkpoint.assistant_message_id,
                checkpoint.sequence,
                checkpoint.label,
                Jsonb(checkpoint.session_snapshot),
                Jsonb(checkpoint.active_memory_snapshot),
                Jsonb(checkpoint.metadata),
                checkpoint.created_at,
            ),
        )
        return checkpoint

    def create_branch_session(
        self,
        session: ChatSession,
        branch: SessionBranch,
    ) -> ChatSession:
        with self.database.connect() as connection:
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO sessions (
                        id, user_id, title, system_prompt, model, temperature,
                        max_context_messages, context_start_index, metadata,
                        created_at, updated_at, archived_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session.id,
                        session.user_id,
                        session.title,
                        session.system_prompt,
                        session.model,
                        session.temperature,
                        session.max_context_messages,
                        session.context_start_index,
                        Jsonb(session.metadata),
                        session.created_at,
                        session.updated_at,
                        session.archived_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO session_branches (
                        session_id, root_session_id, parent_session_id,
                        base_checkpoint_id, base_sequence, metadata, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        branch.session_id,
                        branch.root_session_id,
                        branch.parent_session_id,
                        branch.base_checkpoint_id,
                        branch.base_sequence,
                        Jsonb(branch.metadata),
                        branch.created_at,
                    ),
                )
        return session

    def get_branch(self, session_id: str) -> SessionBranch | None:
        with self.database.connect() as connection:
            return self.get_branch_in_connection(connection, session_id)

    def get_branch_in_connection(
        self,
        connection: Any,
        session_id: str,
    ) -> SessionBranch | None:
        row = connection.execute(
            "SELECT * FROM session_branches WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        return branch_from_row(row) if row else None

    def visible_messages(
        self,
        session_id: str,
    ) -> list[Message]:
        with self.database.connect() as connection:
            return self._visible_messages(connection, session_id)

    def next_sequence_in_connection(
        self,
        connection: Any,
        session_id: str,
    ) -> int:
        messages = self._visible_messages(connection, session_id)
        sequences = [
            _row_sequence(message)
            for message in messages
            if _row_sequence(message) is not None
        ]
        if sequences:
            return max(sequences) + 1
        return len(messages) + 1

    def branch_memory_scope(self, session_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            return self._branch_memory_scope(connection, session_id)

    def _visible_messages(
        self,
        connection: Any,
        session_id: str,
        cutoff_sequence: int | None = None,
    ) -> list[Message]:
        branch = self.get_branch_in_connection(connection, session_id)
        inherited: list[Message] = []
        if branch is not None:
            inherited = self._visible_messages(
                connection,
                branch.parent_session_id,
                cutoff_sequence=branch.base_sequence,
            )
        rows = connection.execute(
            """
            SELECT * FROM messages
            WHERE session_id = %s
              AND status = 'active'
              AND (%s::integer IS NULL OR sequence IS NULL OR sequence <= %s)
            ORDER BY COALESCE(sequence, 2147483647) ASC, created_at ASC, id ASC
            """,
            (session_id, cutoff_sequence, cutoff_sequence),
        ).fetchall()
        local = [message_from_row(row) for row in rows]
        return [*inherited, *local]

    def _list_visible_checkpoints(
        self,
        connection: Any,
        session_id: str,
        limit: int,
        cutoff_sequence: int | None = None,
    ) -> list[ConversationCheckpoint]:
        branch = self.get_branch_in_connection(connection, session_id)
        inherited: list[ConversationCheckpoint] = []
        if branch is not None:
            inherited = self._list_visible_checkpoints(
                connection,
                branch.parent_session_id,
                limit=limit,
                cutoff_sequence=branch.base_sequence,
            )
        rows = connection.execute(
            """
            SELECT * FROM conversation_checkpoints
            WHERE session_id = %s
              AND (%s::integer IS NULL OR sequence <= %s)
            ORDER BY sequence ASC, created_at ASC, id ASC
            """,
            (session_id, cutoff_sequence, cutoff_sequence),
        ).fetchall()
        checkpoints = [*inherited, *[checkpoint_from_row(row) for row in rows]]
        return checkpoints[-max(0, limit) :]

    def _branch_memory_scope(
        self,
        connection: Any,
        session_id: str,
    ) -> list[dict[str, Any]]:
        branch = self.get_branch_in_connection(connection, session_id)
        if branch is None:
            return [{"session_id": session_id, "max_checkpoint_sequence": None}]
        scopes = self._branch_memory_scope(connection, branch.parent_session_id)
        scoped: list[dict[str, Any]] = []
        for scope in scopes:
            max_sequence = scope["max_checkpoint_sequence"]
            if max_sequence is None or max_sequence > branch.base_sequence:
                max_sequence = branch.base_sequence
            scoped.append(
                {
                    "session_id": scope["session_id"],
                    "max_checkpoint_sequence": max_sequence,
                }
            )
        scoped.append({"session_id": session_id, "max_checkpoint_sequence": None})
        return scoped


def _row_sequence(message: Message) -> int | None:
    value = message.metadata.get("sequence")
    return value if isinstance(value, int) else None
