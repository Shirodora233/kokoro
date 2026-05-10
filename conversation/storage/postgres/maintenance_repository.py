"""Cross-table PostgreSQL maintenance operations."""

from __future__ import annotations

from .connection import PostgresDatabase


class PostgresMaintenanceRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def delete_all(self) -> dict[str, int]:
        with self.database.connect() as connection:
            messages = connection.execute("DELETE FROM messages").rowcount
            sessions = connection.execute("DELETE FROM sessions").rowcount
            users = connection.execute("DELETE FROM users").rowcount
        return {"messages": messages, "sessions": sessions, "users": users}
