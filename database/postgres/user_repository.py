"""User persistence operations for PostgreSQL."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from conversation.models import User

from .connection import PostgresDatabase
from .row_mappers import user_from_row


class PostgresUserRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def create_user(self, user: User) -> User:
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM users WHERE id = %s OR username = %s",
                (user.id, user.username),
            ).fetchone()
            if existing:
                if existing["id"] == user.id:
                    raise ValueError(f"User id already exists: {user.id}")
                raise ValueError(f"Username already exists: {user.username}")
            connection.execute(
                """
                INSERT INTO users (id, username, display_name, metadata, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
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
        return user

    def get_user(self, user_id: str) -> User | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = %s",
                (user_id,),
            ).fetchone()
        return user_from_row(row) if row else None

    def find_user_by_username(self, username: str) -> User | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = %s",
                (username,),
            ).fetchone()
        return user_from_row(row) if row else None

    def list_users(self) -> list[User]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM users ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [user_from_row(row) for row in rows]

    def delete_user(self, user_id: str, cascade: bool = False) -> dict[str, int]:
        with self.database.connect() as connection:
            user = connection.execute(
                "SELECT id FROM users WHERE id = %s",
                (user_id,),
            ).fetchone()
            if not user:
                raise ValueError(f"Unknown user_id: {user_id}")

            session_rows = connection.execute(
                "SELECT id FROM sessions WHERE user_id = %s",
                (user_id,),
            ).fetchall()
            session_ids = [row["id"] for row in session_rows]
            message_count = connection.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE user_id = %s",
                (user_id,),
            ).fetchone()["count"]
            if (session_ids or message_count) and not cascade:
                raise ValueError("User has related sessions/messages; enable cascade to delete them")

            deleted_sessions = 0
            deleted_messages = 0
            if cascade:
                if session_ids:
                    deleted_messages = connection.execute(
                        """
                        DELETE FROM messages
                        WHERE session_id = ANY(%s::text[]) OR user_id = %s
                        """,
                        (session_ids, user_id),
                    ).rowcount
                else:
                    deleted_messages = connection.execute(
                        "DELETE FROM messages WHERE user_id = %s",
                        (user_id,),
                    ).rowcount
                deleted_sessions = connection.execute(
                    "DELETE FROM sessions WHERE user_id = %s",
                    (user_id,),
                ).rowcount

            connection.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return {"users": 1, "sessions": deleted_sessions, "messages": deleted_messages}
