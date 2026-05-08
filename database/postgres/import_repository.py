"""Bulk import helpers for PostgreSQL conversation data."""

from __future__ import annotations

from typing import Iterable

import psycopg
from psycopg.types.json import Jsonb

from conversation.models import ChatSession, Message, User

from .connection import PostgresDatabase


class PostgresImportRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def import_records(
        self,
        users: Iterable[User],
        sessions: Iterable[ChatSession],
        messages: Iterable[Message],
        replace: bool = False,
    ) -> dict[str, int]:
        user_list = list(users)
        session_list = list(sessions)
        message_list = list(messages)
        with self.database.connect() as connection:
            if replace:
                connection.execute("DELETE FROM messages")
                connection.execute("DELETE FROM sessions")
                connection.execute("DELETE FROM users")
            for user in user_list:
                self._upsert_user(connection, user)
            for session in session_list:
                self._upsert_session(connection, session)
            for message in message_list:
                self._upsert_message(connection, message)
        return {
            "users": len(user_list),
            "sessions": len(session_list),
            "messages": len(message_list),
        }

    def _upsert_user(self, connection: psycopg.Connection, user: User) -> None:
        connection.execute(
            """
            INSERT INTO users (id, username, display_name, metadata, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET username = EXCLUDED.username,
                display_name = EXCLUDED.display_name,
                metadata = EXCLUDED.metadata,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at
            """,
            (
                user.id,
                user.username,
                user.display_name,
                Jsonb(user.metadata),
                user.created_at,
                user.updated_at,
            ),
        )

    def _upsert_session(self, connection: psycopg.Connection, session: ChatSession) -> None:
        connection.execute(
            """
            INSERT INTO sessions (
                id, user_id, title, system_prompt, model, temperature,
                max_context_messages, context_start_index, metadata,
                created_at, updated_at, archived_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET user_id = EXCLUDED.user_id,
                title = EXCLUDED.title,
                system_prompt = EXCLUDED.system_prompt,
                model = EXCLUDED.model,
                temperature = EXCLUDED.temperature,
                max_context_messages = EXCLUDED.max_context_messages,
                context_start_index = EXCLUDED.context_start_index,
                metadata = EXCLUDED.metadata,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at,
                archived_at = EXCLUDED.archived_at
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

    def _upsert_message(self, connection: psycopg.Connection, message: Message) -> None:
        connection.execute(
            """
            INSERT INTO messages (
                id, session_id, user_id, role, content, model,
                token_usage, metadata, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET session_id = EXCLUDED.session_id,
                user_id = EXCLUDED.user_id,
                role = EXCLUDED.role,
                content = EXCLUDED.content,
                model = EXCLUDED.model,
                token_usage = EXCLUDED.token_usage,
                metadata = EXCLUDED.metadata,
                created_at = EXCLUDED.created_at
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
