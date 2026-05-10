"""PostgreSQL connection and schema helpers."""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class PostgresDatabase:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        self.database_url = database_url

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with self.connect() as connection:
            connection.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
