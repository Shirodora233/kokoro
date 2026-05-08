"""Message persistence operations for PostgreSQL."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from conversation.models import Message, utc_now

from .connection import PostgresDatabase
from .row_mappers import message_from_row


class PostgresMessageRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def append_message(self, message: Message) -> Message:
        with self.database.connect() as connection:
            session = connection.execute(
                "SELECT id FROM sessions WHERE id = %s",
                (message.session_id,),
            ).fetchone()
            if not session:
                raise ValueError(f"Unknown session_id for message: {message.session_id}")
            if message.user_id:
                user = connection.execute(
                    "SELECT id FROM users WHERE id = %s",
                    (message.user_id,),
                ).fetchone()
                if not user:
                    raise ValueError(f"Unknown user_id for message: {message.user_id}")
            existing = connection.execute(
                "SELECT id FROM messages WHERE id = %s",
                (message.id,),
            ).fetchone()
            if existing:
                raise ValueError(f"Message id already exists: {message.id}")

            connection.execute(
                """
                INSERT INTO messages (
                    id, session_id, user_id, role, content, model,
                    token_usage, metadata, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                ),
            )
            connection.execute(
                "UPDATE sessions SET updated_at = %s WHERE id = %s",
                (utc_now(), message.session_id),
            )
        return message

    def list_messages(self, session_id: str) -> list[Message]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM messages
                WHERE session_id = %s
                ORDER BY created_at ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return [message_from_row(row) for row in rows]
