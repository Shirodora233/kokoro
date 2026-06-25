"""Session persistence operations for PostgreSQL."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from conversation.models import ChatSession

from .connection import PostgresDatabase
from .row_mappers import session_from_row


class PostgresSessionRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def create_session(self, session: ChatSession) -> ChatSession:
        with self.database.connect() as connection:
            user = connection.execute(
                "SELECT id FROM users WHERE id = %s",
                (session.user_id,),
            ).fetchone()
            if not user:
                raise ValueError(f"Unknown user_id for session: {session.user_id}")
            existing = connection.execute(
                "SELECT id FROM sessions WHERE id = %s",
                (session.id,),
            ).fetchone()
            if existing:
                raise ValueError(f"Session id already exists: {session.id}")
            connection.execute(
                """
                INSERT INTO sessions (
                    id, user_id, title, system_prompt, model, temperature,
                    max_context_messages, context_start_index,
                    head_checkpoint_id, root_session_id, parent_session_id,
                    base_checkpoint_id, metadata, created_at, updated_at,
                    archived_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    session.head_checkpoint_id,
                    session.root_session_id,
                    session.parent_session_id,
                    session.base_checkpoint_id,
                    Jsonb(session.metadata),
                    session.created_at,
                    session.updated_at,
                    session.archived_at,
                ),
            )
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = %s",
                (session_id,),
            ).fetchone()
        return session_from_row(row) if row else None

    def update_session(self, session: ChatSession) -> ChatSession:
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE sessions
                SET user_id = %s,
                    title = %s,
                    system_prompt = %s,
                    model = %s,
                    temperature = %s,
                    max_context_messages = %s,
                    context_start_index = %s,
                    head_checkpoint_id = %s,
                    root_session_id = %s,
                    parent_session_id = %s,
                    base_checkpoint_id = %s,
                    metadata = %s,
                    created_at = %s,
                    updated_at = %s,
                    archived_at = %s
                WHERE id = %s
                """,
                (
                    session.user_id,
                    session.title,
                    session.system_prompt,
                    session.model,
                    session.temperature,
                    session.max_context_messages,
                    session.context_start_index,
                    session.head_checkpoint_id,
                    session.root_session_id,
                    session.parent_session_id,
                    session.base_checkpoint_id,
                    Jsonb(session.metadata),
                    session.created_at,
                    session.updated_at,
                    session.archived_at,
                    session.id,
                ),
            )
            if result.rowcount == 0:
                raise ValueError(f"Unknown session_id: {session.id}")
        return session

    def list_sessions(self, user_id: str | None = None) -> list[ChatSession]:
        with self.database.connect() as connection:
            if user_id is None:
                rows = connection.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC, id ASC"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM sessions
                    WHERE user_id = %s
                    ORDER BY updated_at DESC, id ASC
                    """,
                    (user_id,),
                ).fetchall()
        return [session_from_row(row) for row in rows]

    def delete_session(self, session_id: str) -> dict[str, int]:
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM sessions WHERE id = %s",
                (session_id,),
            ).fetchone()
            if not existing:
                raise ValueError(f"Unknown session_id: {session_id}")
            deleted_messages = connection.execute(
                "DELETE FROM messages WHERE session_id = %s",
                (session_id,),
            ).rowcount
            deleted_sessions = connection.execute(
                "DELETE FROM sessions WHERE id = %s",
                (session_id,),
            ).rowcount
        return {"users": 0, "sessions": deleted_sessions, "messages": deleted_messages}
